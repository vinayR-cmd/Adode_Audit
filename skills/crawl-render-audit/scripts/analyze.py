"""
analyze.py — deterministic fast-path helper for the crawl-render-audit skill.

Covers the mechanical half of the "let in -> read -> extract" funnel: robots
rules, sitemap presence, HTTP status, redirect chains, indexing directives, and
a deliberately conservative static-vs-rendered heuristic.

It is an aid, not the skill. The agent running SKILL.md still judges ambiguous
cases (anti-bot vs. JS-only, intentional noindex vs. accidental) and may use a
real rendering tool, which beats this heuristic every time.

Usage:
    python analyze.py --bundle bundle.json
    python analyze.py --url https://example.com
"""

import sys
from urllib.parse import urldefrag, urljoin, urlparse

import common
from common import finding, not_verified, opportunity

SKILL = "crawl-render-audit"

# App-shell markers: presence alone means nothing (every React site has one).
SHELL_MARKERS = [
    "__NEXT_DATA__", "__NUXT__", "window.__INITIAL_STATE__", "ng-version",
    "data-reactroot", "data-react-helmet", 'id="root"', "id='root'",
    'id="app"', "id='app'", "data-server-rendered", "__remixContext",
    "__sveltekit", "astro-island",
]

# A marker whitelist only recognises frameworks it has heard of. jetbrains.com
# ships a 44 KB document with zero links, zero headings and zero text and none
# of the markers above — a custom client-rendered build. Without the shape test
# below it fell through to content_presence and was reported as a parked or
# under-construction domain, at critical. A large document that renders nothing
# is client-side rendering, not an empty site.
LARGE_SHELL_BYTES = 20_000     # a genuinely empty page is small; a shell is not
SHELL_TEXT_WORDS = 10          # "near-zero visible text"
SHELL_MIN_SCRIPTS = 3          # several external scripts


def _internal_link_count(page, parsed):
    """Distinct same-site destinations linked from this page's static HTML."""
    base = page.get("final_url") or page.get("url") or ""
    out = set()
    for href, _t in parsed["links"]:
        h = (href or "").strip()
        if not h or h.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        full = urldefrag(urljoin(base, h))[0]
        if full.startswith(("http://", "https://")) and common.same_site(base, full):
            out.add(full.rstrip("/"))
    return len(out)


def _large_empty_shell(page, parsed, internal_links):
    """
    True for the 'big document, nothing in it' shape — client-side rendering
    with no recognisable framework marker.

    class="nojs" and <noscript> blocks corroborate but are NOT required: a site
    can client-render without either.
    """
    if page.get("bytes", 0) <= LARGE_SHELL_BYTES:
        return None
    if internal_links != 0 or parsed["word_count"] > SHELL_TEXT_WORDS:
        return None
    # Count ALL <script src> tags, not just absolute-URL ones: a client-rendered
    # site usually loads its bundle from a relative path on its own origin.
    if parsed["script_src_count"] < SHELL_MIN_SCRIPTS:
        return None
    html = page.get("html", "") or ""
    sigs = ["%.0f KB of HTML containing 0 internal links and %d words of visible "
            "text" % (page.get("bytes", 0) / 1000.0, parsed["word_count"]),
            "%d script src tags" % parsed["script_src_count"],
            "no app-shell marker recognised — custom client-side build"]
    low = html[:4000].lower()
    if "nojs" in low:
        sigs.append('body carries a "nojs" class (corroborating)')
    if "<noscript" in html.lower():
        sigs.append("<noscript> fallback present (corroborating)")
    return sigs


def _shell_signals(page, parsed):
    html = page.get("html", "")
    sigs = []
    if parsed["word_count"] < 120:
        sigs.append("static text is only %d words" % parsed["word_count"])
    hit = [m for m in SHELL_MARKERS if m in html]
    if hit:
        sigs.append("app-shell marker %s in initial HTML" % hit[0])
    if parsed["external_script_count"] >= 5:
        sigs.append("%d external scripts" % parsed["external_script_count"])
    if not parsed["headings"]:
        sigs.append("no h1-h3 headings in initial HTML")
    if len(parsed["links"]) < 5:
        sigs.append("only %d links in initial HTML" % len(parsed["links"]))
    return sigs, hit


def analyze(bundle):
    findings, nv, opps = [], [], []
    obs = {}
    pages = bundle.get("pages", [])
    sample = common.html_pages(bundle)
    origin = bundle.get("origin", "")
    robots = bundle.get("robots", {})

    # ---------------------------------------------------------------- robots
    ai = robots.get("ai_bots") or {}
    blocked_bots = sorted(b for b, v in ai.items() if v.get("blocked_all"))
    explicit_blocked = sorted(b for b in blocked_bots if ai[b].get("explicit"))
    if explicit_blocked:
        findings.append(finding(
            title="robots.txt blocks named AI crawlers from the whole site",
            severity="critical", category="discoverability",
            mechanism="Stage 1 (reach): a compliant AI crawler that is named with "
                      "Disallow: / never fetches any page, so no downstream signal "
                      "quality can compensate.",
            evidence="%s returned HTTP %s and contains Disallow: / for: %s"
                     % (robots.get("url"), robots.get("status"),
                        ", ".join(explicit_blocked)),
            action_summary="Decide deliberately which AI crawlers may read the site; "
                           "remove the blanket Disallow for any you want citing you.",
            how="Edit /robots.txt. Keep blocks only where licensing/legal reasons "
                "apply; note training crawlers (GPTBot, CCBot, Google-Extended) and "
                "answer-time fetchers (OAI-SearchBot, ChatGPT-User, PerplexityBot, "
                "Claude-SearchBot) have different consequences — blocking the latter "
                "removes you from live answers.",
            confidence="high", root_cause="robots-ai-block", check="robots_ai_bots",
            pages=[robots.get("url")]))
    elif blocked_bots:
        findings.append(finding(
            title="robots.txt blocks all crawlers site-wide (AI crawlers included)",
            severity="critical", category="discoverability",
            mechanism="Stage 1 (reach): a `User-agent: *` + `Disallow: /` group "
                      "applies to every compliant crawler, including AI fetchers.",
            evidence="%s (HTTP %s) has a wildcard group disallowing '/': %s"
                     % (robots.get("url"), robots.get("status"),
                        (robots.get("text_excerpt") or "")[:300].replace("\n", " | ")),
            action_summary="Narrow the wildcard Disallow to the paths that genuinely "
                           "must stay private.",
            confidence="high", root_cause="robots-wildcard-block",
            check="robots_wildcard", pages=[robots.get("url")]))
    elif not robots.get("exists"):
        if robots.get("error"):
            nv.append(not_verified("robots_ai_bots",
                                   "robots.txt unreadable: %s" % robots.get("error"),
                                   robots.get("url")))
        else:
            obs["robots"] = "no robots.txt (HTTP %s) — nothing blocked, which is fine" \
                            % robots.get("status")

    partial = {b: v for b, v in ai.items()
               if not v.get("blocked_all") and v.get("explicit") and v.get("rules")}
    if partial:
        obs["ai_bot_path_rules"] = {b: v["rules"] for b, v in partial.items()}

    # -------------------------------------------------------------- sitemap
    sm = bundle.get("sitemap", {})
    entry = pages[0] if pages else None
    entry_reachable = bool(entry and isinstance(entry.get("status"), int)
                           and entry["status"] < 400 and not entry.get("blocked_reason"))
    if not sm.get("found") and not entry_reachable:
        nv.append(not_verified(
            "sitemap", "site was unreachable/blocked, so the absence of a sitemap "
            "proves nothing", urljoin(origin, "/sitemap.xml")))
    elif not sm.get("found"):
        opps.append(opportunity(
            title="No XML sitemap found",
            category="discoverability",
            rationale="Checked %s and robots.txt Sitemap: directives — none returned a "
                      "parseable sitemap (%s). A sitemap is not required for crawling "
                      "and its absence alone is not a defect, but it is the cheapest "
                      "way to make deep pages discoverable without relying on link "
                      "depth." % (urljoin(origin, "/sitemap.xml"),
                                  "; ".join(sm.get("errors", [])) or "no <loc> entries"),
            action="Publish /sitemap.xml with lastmod dates and reference it from "
                   "robots.txt.", effort="low"))
    else:
        obs["sitemap"] = {"urls": len(sm.get("urls", [])),
                          "declared_in_robots": sm.get("declared_in_robots")}
        sampled = {p["final_url"].rstrip("/") for p in pages
                   if not sm.get("capped")}
        missing = [p for p in sampled
                   if p not in {u.rstrip("/") for u in sm.get("urls", [])}]
        if sm.get("capped"):
            nv.append(not_verified(
                "sitemap_coverage",
                "only the first %d sitemap URLs were read (large or nested sitemap), "
                "so coverage of the sampled pages could not be judged"
                % len(sm.get("urls", [])), urljoin(origin, "/sitemap.xml")))
        elif sm.get("urls") and len(missing) >= max(3, len(sampled) * 0.6):
            findings.append(finding(
                title="Sitemap omits most linked pages",
                severity="low", category="discoverability",
                mechanism="Stage 1 (reach): pages absent from the sitemap depend "
                          "entirely on being reachable by link-following, which "
                          "answer-time fetchers do far less of than search crawlers.",
                evidence="%d of %d sampled, internally-linked pages are absent from "
                         "the sitemap (%d URLs total). Examples: %s"
                         % (len(missing), len(sampled), len(sm.get("urls", [])),
                            ", ".join(sorted(missing)[:3])),
                action_summary="Regenerate the sitemap from the live route list.",
                confidence="medium", root_cause="sitemap-coverage",
                check="sitemap_coverage"))

    # --------------------------------------------------- entry reachability
    home = pages[0] if pages else None
    if home is None:
        nv.append(not_verified("all_checks", "no pages were fetched", bundle.get("start_url")))
        return _wrap(findings, nv, opps, obs)

    if home.get("robots_allowed") is False:
        findings.append(finding(
            title="robots.txt blocks the auditor from the entry URL",
            severity="critical", category="discoverability",
            mechanism="Stage 1 (reach): the path rules that stopped this read apply "
                      "to any compliant crawler using a generic user-agent.",
            evidence="Not fetched — %s disallows %s for a generic user-agent."
                     % (robots.get("url"), bundle.get("start_url")),
            action_summary="Review the Disallow rules covering the entry path.",
            confidence="high", root_cause="robots-ai-block", check="robots_self_block",
            pages=[bundle.get("start_url")]))
        nv.append(not_verified("page_content", "entry URL not fetched (robots.txt "
                               "disallow respected)", bundle.get("start_url")))
        return _wrap(findings, nv, opps, obs)

    if home.get("error") and home.get("status") is None:
        findings.append(finding(
            title="Entry URL was unreachable during the audit",
            severity="critical", category="discoverability",
            mechanism="Stage 1 (reach): if the host does not answer, no crawler — "
                      "AI or search — can retrieve anything. Note this is what the "
                      "auditor observed from one network at one time; it is not proof "
                      "the site is permanently down.",
            evidence="GET %s -> %s (after one retry, %ss timeout)"
                     % (bundle.get("start_url"), home.get("error"),
                        common.DEFAULT_TIMEOUT),
            action_summary="Verify DNS, TLS and host availability from outside your "
                           "network before drawing any other conclusion.",
            confidence="medium", root_cause="unreachable", check="entry_reachable",
            pages=[bundle.get("start_url")]))
        nv.append(not_verified("all_content_checks",
                               "host unreachable: %s" % home.get("error"),
                               bundle.get("start_url")))
        return _wrap(findings, nv, opps, obs)

    if home.get("blocked_reason"):
        findings.append(finding(
            title="Entry URL is served behind bot protection",
            severity="medium", category="discoverability",
            mechanism="Stage 1 (reach): AI fetchers arrive as non-browser clients and "
                      "commonly trip the same protection. This is a RISK observed "
                      "against one generic user-agent, not proof that named AI "
                      "crawlers are blocked.",
            evidence="GET %s -> %s. Detected: %s"
                     % (home.get("url"), home.get("status"), home["blocked_reason"]),
            action_summary="Allow-list the AI user-agents you want to be cited by in "
                           "your WAF/bot rules, and verify with a fetch as those agents.",
            confidence="medium", root_cause="bot-protection", check="bot_protection",
            pages=[home.get("url")]))
        nv.append(not_verified("content_checks", "entry page body was a bot challenge, "
                               "not site content", home.get("url")))

    entry_status = home.get("status")
    if isinstance(entry_status, int) and entry_status >= 400 and not home.get("blocked_reason"):
        findings.append(finding(
            title="Entry URL returns HTTP %s" % entry_status,
            severity="critical", category="discoverability",
            mechanism="Stage 1 (reach): the audited URL itself does not serve content, "
                      "so there is nothing for any crawler or visitor to read there.",
            evidence="GET %s -> HTTP %s, Content-Type: %s, %d bytes of body"
                     % (home.get("url"), entry_status,
                        home.get("content_type") or "none", home.get("bytes", 0)),
            action_summary="Confirm the correct public URL and that it serves a 200 "
                           "response to non-browser clients.",
            confidence="high", root_cause="entry-status", check="entry_status",
            pages=[home.get("url")]))

    if not home.get("is_html") and entry_status and 200 <= entry_status < 300:
        findings.append(finding(
            title="Entry URL does not return HTML",
            severity="high", category="discoverability",
            mechanism="Stage 2 (read): a non-HTML entry point gives crawlers no "
                      "headings, links or text to extract or follow.",
            evidence="GET %s -> HTTP %s, Content-Type: %s, %d bytes"
                     % (home.get("url"), home.get("status"),
                        home.get("content_type") or "unknown", home.get("bytes", 0)),
            action_summary="Serve an HTML landing page at the audited URL.",
            confidence="high", check="entry_content_type", pages=[home.get("url")]))

    # ---------------------------------------------------- per-page HTTP hygiene
    bad = [p for p in pages[1:]
           if isinstance(p.get("status"), int) and p["status"] >= 400]
    server_err = [p for p in bad if p["status"] >= 500]
    client_err = [p for p in bad if 400 <= p["status"] < 500 and not p.get("blocked_reason")]
    for group, sev, label in ((server_err, "high", "5xx server errors"),
                              (client_err, "medium", "4xx errors")):
        if group:
            findings.append(finding(
                title="Internally linked pages return %s" % label,
                severity=sev, category="discoverability",
                mechanism="Stage 1 (reach): a linked URL that errors wastes the "
                          "crawler's budget and drops that content from any answer.",
                evidence="; ".join("%s -> HTTP %s" % (p["url"], p["status"])
                                   for p in group[:5]),
                action_summary="Fix or remove the broken links / restore the pages.",
                confidence="high", root_cause="http-errors-%s" % sev,
                check="http_status", pages=[p["url"] for p in group]))

    loops = [p for p in pages if p.get("redirect_loop")]
    if loops:
        findings.append(finding(
            title="Redirect loop detected",
            severity="high", category="discoverability",
            mechanism="Stage 1 (reach): a loop terminates the fetch with no content.",
            evidence="; ".join("%s: %s" % (p["url"], " -> ".join(
                str(h["to"]) for h in p.get("redirect_chain", [])[:4])) for p in loops[:3]),
            action_summary="Break the redirect cycle; each URL must resolve in one hop.",
            confidence="high", root_cause="redirect-loop", check="redirect_loop",
            pages=[p["url"] for p in loops]))

    long_chains = [p for p in pages if len(p.get("redirect_chain", [])) >= 3]
    if long_chains:
        findings.append(finding(
            title="Multi-hop redirect chains on internal URLs",
            severity="low", category="discoverability",
            mechanism="Stage 1 (reach): every hop is another request some fetchers "
                      "abandon, and hop-limited clients may never reach the content.",
            evidence="; ".join("%s: %d hops (%s)" % (
                p["url"], len(p["redirect_chain"]),
                " -> ".join(str(h["status"]) for h in p["redirect_chain"]))
                for p in long_chains[:3]),
            action_summary="Point internal links at the final URL.",
            confidence="high", root_cause="redirect-chain", check="redirect_chain"))

    xdomain = [p for p in pages if p.get("cross_domain_redirect")]
    if xdomain:
        obs["cross_domain_redirects"] = [
            {"from": p["url"], "to": p["final_url"]} for p in xdomain[:5]]

    # ------------------------------------------------------ indexing directives
    noindex = []
    for p in sample:
        parsed = common.get_parsed(p)
        mr = common.meta_robots(parsed["metas"])
        xr = (p.get("headers", {}).get("x-robots-tag", "") or "").lower()
        if "noindex" in mr or "noindex" in xr:
            noindex.append((p["url"], "meta robots=%r" % mr if "noindex" in mr
                            else "X-Robots-Tag: %s" % xr))
    if noindex:
        sev = "critical" if any(u.rstrip("/") == home["final_url"].rstrip("/")
                                for u, _ in noindex) else "high"
        findings.append(finding(
            title="Pages carry a noindex directive",
            severity=sev, category="discoverability",
            mechanism="Stage 1 (reach): noindex removes the page from search indexes, "
                      "which are the retrieval layer several AI assistants query "
                      "before citing anything.",
            evidence="; ".join("%s (%s)" % (u, why) for u, why in noindex[:5]),
            action_summary="Remove noindex from pages meant to be publicly citable "
                           "(a staging directive left in production is the usual cause).",
            confidence="high", root_cause="noindex", check="meta_robots",
            pages=[u for u, _ in noindex]))

    off_canon = []
    for p in sample:
        c = common.get_parsed(p).get("rel_canonical")
        if not c:
            continue
        full = urljoin(p["final_url"], c)
        if not common.same_site(p["final_url"], full):
            off_canon.append((p["url"], full))
    if off_canon:
        findings.append(finding(
            title="Canonical tags point to a different domain",
            severity="high", category="discoverability",
            mechanism="Stage 1 (reach): an off-site canonical tells indexers to credit "
                      "and cite the other domain instead of this one.",
            evidence="; ".join("%s -> canonical %s" % (u, c) for u, c in off_canon[:5]),
            action_summary="Point canonicals at the page's own URL unless the content "
                           "is deliberately syndicated.",
            confidence="high", root_cause="canonical-offsite", check="canonical",
            pages=[u for u, _ in off_canon]))

    # ------------------------------------------------- static vs rendered content
    # Conservative: requires several corroborating signals before flagging, so a
    # normal framework-built site that ships real HTML is never called broken.
    js_flagged = []
    for p in sample:
        parsed = common.get_parsed(p)
        sigs, shell_hits = _shell_signals(p, parsed)
        internal_links = _internal_link_count(p, parsed)
        if parsed["word_count"] < 120 and shell_hits and len(sigs) >= 3:
            js_flagged.append((p["url"], sigs))
            continue
        shell_sigs = _large_empty_shell(p, parsed, internal_links)
        if shell_sigs:
            js_flagged.append((p["url"], shell_sigs))
    if js_flagged:
        findings.append(finding(
            title="Core content appears to be absent from the initial HTML response",
            severity="high", category="discoverability",
            mechanism="Stage 2 (read): fetchers that do not execute JavaScript see "
                      "only the shell. Where the visible facts arrive only after "
                      "client-side rendering, those fetchers have nothing to quote.",
            evidence="; ".join("%s: %s" % (u, "; ".join(s)) for u, s in js_flagged[:4]),
            action_summary="Server-render (or statically pre-render) the primary "
                           "content of key pages.",
            how="Verify first: fetch the URL with JavaScript disabled, or use a "
                "rendering tool to diff initial HTML against the rendered DOM. If the "
                "facts are present in the initial HTML, this finding does not apply.",
            confidence="medium", root_cause="js-only-content", check="static_render",
            pages=[u for u, _ in js_flagged]))
        nv.append(not_verified(
            "rendered_dom_diff",
            "no JavaScript rendering tool was used by this script; the static-only "
            "conclusion above is heuristic and should be confirmed with a renderer",
            ", ".join(u for u, _ in js_flagged[:3])))

    # ------------------------------------------------------- negligible content
    entry_2xx = isinstance(home.get("status"), int) and 200 <= home["status"] < 300
    if home.get("is_html") and not home.get("blocked_reason") and entry_2xx:
        hp = common.get_parsed(home)
        # Only a genuinely SMALL, thin page is a parked/under-construction
        # candidate. A large document with nothing in it is a rendering
        # problem, already reported by static_render above.
        genuinely_small = home.get("bytes", 0) <= LARGE_SHELL_BYTES
        if (hp["word_count"] < 50 and len(hp["links"]) < 5
                and not js_flagged and genuinely_small):
            findings.append(finding(
                title="Site has negligible content at the entry URL",
                severity="critical", category="discoverability",
                mechanism="Stage 2/3 (read/extract): with almost no text and almost no "
                          "links, there is nothing for an assistant to retrieve, quote "
                          "or attribute — this pattern matches parked or "
                          "under-construction domains.",
                evidence="%s -> HTTP %s, %d words of visible text, %d links, title %r"
                         % (home["final_url"], home["status"], hp["word_count"],
                            len(hp["links"]), hp["title"][:80]),
                action_summary="Publish real content before any other optimisation is "
                               "worth doing.",
                confidence="high", root_cause="empty-site", check="content_presence",
                pages=[home["final_url"]]))

    # ------------------------------------------------------------- not-verified
    for p in pages:
        if p.get("blocked_reason") and p is not home:
            nv.append(not_verified("page_analysis", "bot protection: %s"
                                   % p["blocked_reason"], p["url"]))
        if p.get("login_wall"):
            nv.append(not_verified("page_analysis", "authenticated area: %s"
                                   % p["login_wall"], p["url"]))
        if p.get("truncated"):
            nv.append(not_verified("full_page_read", "page exceeded the %d-byte read "
                                   "cap; analysis used the first part only"
                                   % common.MAX_BYTES, p["url"]))
        if p.get("is_html") and common.get_parsed(p).get("parse_error"):
            nv.append(not_verified("html_parse", common.get_parsed(p)["parse_error"],
                                   p["url"]))

    obs["pages_fetched"] = len(pages)
    obs["pages_analyzable"] = len(sample)
    return _wrap(findings, nv, opps, obs)


def _wrap(findings, nv, opps, obs):
    return {"skill": SKILL, "findings": findings, "not_verified": nv,
            "opportunities": opps, "observations": obs}


if __name__ == "__main__":
    common.emit(analyze(common.load_bundle_from_args(sys.argv[1:])))
