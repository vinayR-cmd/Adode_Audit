"""
crawl.py — the one polite, bounded crawl that every concern skill analyzes.

Called once by the orchestrator. Produces a "bundle": robots.txt model, sitemap
inventory, and a small representative page sample with raw bytes captured, so
all five concern skills reason about the SAME observed pages.

Guarantees (see references/ in audit-orchestrator):
  * read-only GET only, never a POST/form/login;
  * robots.txt is respected for our own fetches, and a block is recorded as
    evidence rather than worked around;
  * bounded page count, bounded bytes, bounded time, short timeouts;
  * every failure becomes recorded evidence, never an exception.
"""

import html as html_module
import re
import sys
import time
from urllib.parse import urljoin, urldefrag, urlparse

import common
from common import (Budget, Robots, fetch, fetch_robots, is_html, normalize_url,
                    origin_of, path_depth, registrable, same_site, utcnow)

DEFAULT_MAX_PAGES = 10
DEFAULT_BUDGET = 240          # seconds for the whole audit (rule 15)
MIN_DELAY = 0.4               # politeness floor between requests
MAX_DELAY = 5.0               # cap on a site's declared crawl-delay
SITEMAP_URL_CAP = 300

_ASSET_RE = re.compile(
    r"\.(?:png|jpe?g|gif|svg|webp|avif|ico|css|js|mjs|woff2?|ttf|eot|zip|gz|"
    r"mp4|webm|mp3|wav|dmg|exe|pkg|rss|atom)(?:$|\?)", re.I)
_SKIP_PATH_RE = re.compile(
    r"/(?:wp-admin|wp-login|cart|checkout|basket|signin|sign-in|login|log-in|"
    r"logout|account|my-account|register|signup|sign-up|admin|cdn-cgi)(?:/|$)", re.I)


# --------------------------------------------------------------------------- #
# Sitemaps                                                                     #
# --------------------------------------------------------------------------- #
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def collect_sitemap(origin, robots, timeout, budget, notes):
    """Fetch sitemap(s) — from robots.txt if declared, else /sitemap.xml.

    Follows a sitemap index one level deep, capped. Returns a dict.
    """
    out = {"found": False, "sources": [], "urls": [], "errors": [], "capped": False,
           "declared_in_robots": bool(robots.sitemaps)}
    candidates = list(dict.fromkeys(robots.sitemaps or [])) or [urljoin(origin, "/sitemap.xml")]
    seen_docs = set()
    queue = candidates[:3]
    index_expansions = 0

    while queue and len(out["urls"]) < SITEMAP_URL_CAP and not budget.exhausted(reserve=25):
        sm_url = queue.pop(0)
        if sm_url in seen_docs:
            continue
        seen_docs.add(sm_url)
        res = fetch(sm_url, timeout=timeout)
        out["sources"].append({"url": sm_url, "status": res["status"],
                               "error": res["error"]})
        if res["error"] or res["status"] != 200 or not res["text"]:
            out["errors"].append("%s -> %s" % (sm_url, res["error"] or res["status"]))
            continue
        body = res["text"]
        locs = _LOC_RE.findall(body[:2_000_000])
        if not locs and sm_url.endswith(".gz"):
            out["errors"].append("%s -> gzipped sitemap not decoded" % sm_url)
            continue
        out["found"] = True
        if "<sitemapindex" in body[:5000].lower() and index_expansions < 3:
            index_expansions += 1
            queue.extend(html_module.unescape(u) for u in locs[:3])
            notes.append("sitemap index at %s expanded (%d children, first 3 read)"
                         % (sm_url, len(locs)))
            continue
        for u in locs:
            # <loc> values are XML: "&amp;" is the correct encoding of "&", so a
            # query string with two parameters arrives escaped and must be
            # decoded before the URL is fetched or reported.
            u = urldefrag(html_module.unescape(u.strip()))[0]
            if u and u not in out["urls"]:
                out["urls"].append(u)
            if len(out["urls"]) >= SITEMAP_URL_CAP:
                break
    if len(out["urls"]) >= SITEMAP_URL_CAP or queue or index_expansions:
        out["capped"] = True
        notes.append("sitemap read was partial (%d URLs, cap %d%s) — sitemap coverage "
                     "was not evaluated" % (len(out["urls"]), SITEMAP_URL_CAP,
                                            ", index expanded" if index_expansions else ""))
    return out


# --------------------------------------------------------------------------- #
# Candidate selection                                                          #
# --------------------------------------------------------------------------- #
def candidate_urls(start_url, parsed, sitemap_urls, want):
    """
    Build a diverse, bounded list of same-site URLs to sample.

    Priority: navigation links (what a visitor/crawler meets first), then other
    on-page internal links, then sitemap entries — de-duplicated and spread
    across distinct top-level path prefixes so the sample isn't 8 blog posts.
    """
    origin = origin_of(start_url)
    ordered = []

    def add(href):
        if not href:
            return
        href = href.strip()
        if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            return
        full = urldefrag(urljoin(start_url, href))[0]
        if not full.startswith(("http://", "https://")):
            return
        if not same_site(start_url, full):
            return
        if _ASSET_RE.search(full) or _SKIP_PATH_RE.search(urlparse(full).path):
            return
        if full.rstrip("/") == start_url.rstrip("/"):
            return
        if full not in ordered:
            ordered.append(full)

    for href in parsed.get("nav_links", []):
        add(href)
    for href, _text in parsed.get("links", []):
        add(href)
    for u in sitemap_urls:
        if same_site(start_url, u):
            add(u)

    # Spread across distinct first path segments, preferring shallow pages.
    buckets = {}
    for u in ordered:
        segs = [s for s in urlparse(u).path.strip("/").split("/") if s]
        key = segs[0].lower() if segs else ""
        buckets.setdefault(key, []).append(u)
    for key in buckets:
        buckets[key].sort(key=lambda u: (path_depth(u), len(u)))

    picked, keys = [], list(buckets.keys())
    round_i = 0
    while len(picked) < want * 3 and keys:
        progressed = False
        for k in list(keys):
            if round_i < len(buckets[k]):
                picked.append(buckets[k][round_i])
                progressed = True
            if len(picked) >= want * 3:
                break
        if not progressed:
            break
        round_i += 1
    return picked


# --------------------------------------------------------------------------- #
# Page fetching                                                                #
# --------------------------------------------------------------------------- #
def fetch_page(url, robots, timeout, delay, notes):
    """Fetch one page into bundle-page shape. Never raises."""
    page = {
        "url": url, "final_url": url, "status": None, "headers": {}, "html": "",
        "content_type": "", "bytes": 0, "error": None, "robots_allowed": True,
        "is_html": False, "redirect_chain": [], "cross_domain_redirect": False,
        "blocked_reason": None, "login_wall": None, "truncated": False,
        "encoding": None, "elapsed": 0.0,
    }
    if not robots.allowed(url):
        page["robots_allowed"] = False
        page["error"] = "not fetched: disallowed by robots.txt for our user-agent"
        return page

    res = fetch(url, timeout=timeout)
    if res["status"] == 429:
        wait = res["headers"].get("retry-after")
        try:
            wait = min(float(wait), 10.0)
        except (TypeError, ValueError):
            wait = 5.0
        notes.append("HTTP 429 at %s — backed off %.1fs and retried once" % (url, wait))
        time.sleep(wait)
        res = fetch(url, timeout=timeout, retry=False)

    page.update({
        "final_url": res["final_url"], "status": res["status"],
        "headers": res["headers"], "content_type": res["content_type"],
        "bytes": res["raw_len"], "error": res["error"],
        "redirect_chain": res["redirect_chain"],
        "cross_domain_redirect": res["cross_domain_redirect"],
        "redirect_loop": res["redirect_loop"], "truncated": res["truncated"],
        "encoding": res["encoding"], "elapsed": res["elapsed"],
    })
    page["blocked_reason"] = common.detect_bot_block(res)
    page["is_html"] = is_html(res)
    if page["is_html"] and not page["blocked_reason"]:
        page["html"] = res["text"]
        parsed = common.get_parsed(page)
        page["login_wall"] = common.detect_login_wall(parsed, res)
        page["word_count"] = parsed["word_count"]
    time.sleep(delay)
    return page


# --------------------------------------------------------------------------- #
# Crawl                                                                        #
# --------------------------------------------------------------------------- #
def crawl(start_url, max_pages=DEFAULT_MAX_PAGES, timeout=common.DEFAULT_TIMEOUT,
          budget=None, verbose=False):
    budget = budget or Budget(DEFAULT_BUDGET)
    notes, nv = [], []
    start_url = normalize_url(start_url)
    origin = origin_of(start_url)

    bundle = {
        "site": registrable(urlparse(start_url).netloc),
        "start_url": start_url,
        "origin": origin,
        "fetched_at": utcnow(),
        "max_pages": max_pages,
        "robots": {},
        "sitemap": {},
        "pages": [],
        "notes": notes,
        "not_verified": nv,
        "timing": {},
    }

    def log(msg):
        if verbose:
            print("  [crawl] %s" % msg, file=sys.stderr)

    # -- robots.txt ---------------------------------------------------------
    robots, robots_res = fetch_robots(origin, timeout=timeout)
    bundle["robots"] = {
        "url": urljoin(origin, "/robots.txt"),
        "status": robots_res["status"],
        "exists": robots.exists,
        "error": robots_res["error"],
        "sitemaps": robots.sitemaps,
        "crawl_delay": robots.crawl_delay(),
        "ai_bots": robots.ai_bot_status() if robots.exists else {},
        "text_excerpt": (robots.text or "")[:2000],
        "group_count": len(robots.groups),
    }
    if not robots.exists and robots_res["error"]:
        nv.append(common.not_verified(
            "robots.txt", "could not fetch robots.txt: %s" % robots_res["error"],
            bundle["robots"]["url"]))
    log("robots.txt: %s" % ("present" if robots.exists else "absent/unreadable"))

    delay = MIN_DELAY
    cd = robots.crawl_delay()
    if cd:
        delay = max(MIN_DELAY, min(float(cd), MAX_DELAY))
        notes.append("robots.txt declares crawl-delay %s — honoring %.1fs between "
                     "requests (capped at %.0fs)" % (cd, delay, MAX_DELAY))

    # -- sitemap ------------------------------------------------------------
    bundle["sitemap"] = collect_sitemap(origin, robots, timeout, budget, notes)
    log("sitemap urls: %d" % len(bundle["sitemap"]["urls"]))

    # -- start page ---------------------------------------------------------
    home = fetch_page(start_url, robots, timeout, delay, notes)
    bundle["pages"].append(home)
    log("%s -> %s" % (start_url, home["status"] or home["error"]))

    if not home["robots_allowed"]:
        nv.append(common.not_verified(
            "page sample", "robots.txt disallows our user-agent on the entry URL; "
            "no pages fetched (this block is itself reported as a finding)",
            start_url))
        bundle["timing"] = {"elapsed_s": round(budget.elapsed(), 1)}
        return bundle

    # -- sample -------------------------------------------------------------
    if home["is_html"] and home["html"]:
        parsed = common.get_parsed(home)
        cands = candidate_urls(start_url, parsed, bundle["sitemap"]["urls"], max_pages)
    else:
        cands = [u for u in bundle["sitemap"]["urls"] if same_site(start_url, u)]
        if not home["is_html"]:
            notes.append("entry URL returned %s (not HTML) — link discovery fell back "
                         "to the sitemap" % (home["content_type"] or "unknown type"))

    fetched = {start_url.rstrip("/"), home["final_url"].rstrip("/")}
    for url in cands:
        if len(bundle["pages"]) >= max_pages:
            break
        if budget.exhausted(reserve=45):
            nv.append(common.not_verified(
                "page sample", "time budget reached after %d pages; remaining "
                "candidates were not fetched" % len(bundle["pages"])))
            notes.append("stopped sampling early to stay inside the time budget")
            break
        if url.rstrip("/") in fetched:
            continue
        fetched.add(url.rstrip("/"))
        page = fetch_page(url, robots, timeout, delay, notes)
        bundle["pages"].append(page)
        log("%s -> %s" % (url, page["status"] or page["error"]))

    bundle["timing"] = {
        "elapsed_s": round(budget.elapsed(), 1),
        "pages_fetched": len(bundle["pages"]),
        "budget_s": budget.seconds,
    }
    return bundle


def main(argv):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Polite bounded crawl -> bundle JSON")
    ap.add_argument("--url", required=True)
    ap.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES)
    ap.add_argument("--timeout", type=int, default=common.DEFAULT_TIMEOUT)
    ap.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    ap.add_argument("--out")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    bundle = crawl(args.url, max_pages=args.max_pages, timeout=args.timeout,
                   budget=Budget(args.budget), verbose=args.verbose)
    for p in bundle["pages"]:
        p.pop("_parsed", None)
    text = json.dumps(bundle, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("bundle written to %s (%d pages)" % (args.out, len(bundle["pages"])),
              file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
