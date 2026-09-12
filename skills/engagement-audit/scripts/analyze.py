"""
analyze.py — deterministic fast-path helper for the engagement-audit skill.

Answers the second half of the problem: a visitor who DID arrive — often from an
AI answer, landing deep and cold, with no session history — finds what?

Checks deep-linkability, above-the-fold orientation, navigation/search presence,
mobile viewport, and payload weight. Context continuity is deliberately NOT
checked: a static read cannot observe it, so it is emitted as a low-confidence
opportunity, never as a detected defect.

Usage:
    python analyze.py --bundle bundle.json
    python analyze.py --url https://example.com
"""

import re
import sys
from urllib.parse import urljoin, urldefrag, urlparse

import common
from common import finding, not_verified, opportunity

SKILL = "engagement-audit"

HEAVY_BYTES = 2_500_000       # HTML document alone, before assets
MANY_SCRIPTS = 25
NAV_MIN = 4


def analyze(bundle):
    findings, nv, opps = [], [], []
    obs = {}
    sample = common.html_pages(bundle)
    if not sample:
        nv.append(not_verified("engagement", "no analyzable HTML page in the sample",
                               bundle.get("start_url")))
        return _wrap(findings, nv, opps, obs)

    home = sample[0]
    home_parsed = common.get_parsed(home)
    n = len(sample)
    obs["pages_analyzed"] = n

    # ------------------------------------------------------- deep-linkability
    internal_deep = set()
    hash_only = 0
    total_links = 0
    for href, _t in home_parsed["links"]:
        total_links += 1
        if href.startswith("#"):
            hash_only += 1
            continue
        if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        full = urldefrag(urljoin(home["final_url"], href))[0]
        if common.same_site(home["final_url"], full) and common.path_depth(full) >= 1:
            internal_deep.add(full)
    obs["distinct_internal_urls_from_home"] = len(internal_deep)
    obs["home_anchor_only_links"] = hash_only

    if len(internal_deep) < 5 and total_links >= 5 and hash_only >= max(3, total_links * 0.4):
        findings.append(finding(
            title="Everything lives on the homepage: topics have no URLs of their own",
            severity="high", category="engagement",
            mechanism="An assistant can only send a visitor to a URL. When sections "
                      "exist as #anchors on one page, the assistant links the "
                      "homepage; the visitor lands above the thing they asked about "
                      "and has to re-find it, which is where the bounce happens. It "
                      "also means no section can be cited or ranked independently.",
            evidence="Homepage %s exposes %d distinct internal URLs against %d "
                     "same-page anchor links out of %d total links."
                     % (home["final_url"], len(internal_deep), hash_only, total_links),
            action_summary="Give each significant topic, product or service its own "
                           "stable, linkable URL.",
            confidence="high", root_cause="no-deep-links", check="deep_linkability",
            pages=[home["final_url"]]))
    elif len(internal_deep) < 5 and total_links >= 5:
        findings.append(finding(
            title="Very few distinct internal destinations from the entry page",
            severity="medium", category="engagement",
            mechanism="A visitor arriving from an AI answer needs an onward path to "
                      "the specific thing they asked about. Few destinations means "
                      "few landing targets and a shallow, dead-ending site.",
            evidence="Homepage %s links to only %d distinct internal URLs (of %d "
                     "links total)." % (home["final_url"], len(internal_deep),
                                        total_links),
            action_summary="Publish and link dedicated pages for the questions people "
                           "actually arrive with.",
            confidence="medium", root_cause="shallow-site", check="deep_linkability",
            pages=[home["final_url"]]))

    # --------------------------------------------------- above-the-fold clarity
    thin_open = []
    for p in sample:
        parsed = common.get_parsed(p)
        h1 = [t for tag, t in parsed["headings"] if tag == "h1"]
        early = len(parsed["early_text"].split())
        if not h1 and early < 30:
            thin_open.append((p["final_url"], early))
    if thin_open:
        findings.append(finding(
            title="Landing view states nothing concrete",
            severity="medium", category="engagement",
            mechanism="A cold visitor sent by an assistant decides in seconds whether "
                      "this page is the thing they were promised. With no heading and "
                      "almost no text in the opening block, that confirmation is "
                      "missing and the visitor returns to the assistant instead.",
            evidence="; ".join("%s: no h1, %d words in the opening block"
                               % (u, w) for u, w in thin_open[:4]),
            action_summary="Lead each page with a heading and one sentence naming what "
                           "the page delivers.",
            confidence="medium", root_cause="weak-above-fold", check="above_fold",
            pages=[u for u, _ in thin_open]))

    # ------------------------------------------------------- navigation/search
    nav_count = len({h for h in home_parsed["nav_links"]
                     if not h.startswith(("#", "mailto:", "tel:", "javascript:"))})
    has_search = any(common.get_parsed(p)["has_search_input"] for p in sample)
    obs["nav_links_on_home"] = nav_count
    obs["has_site_search"] = has_search
    if nav_count < NAV_MIN and not has_search and len(internal_deep) < 10:
        findings.append(finding(
            title="No usable navigation or on-site search",
            severity="medium", category="engagement",
            mechanism="A visitor who lands deep and needs one adjacent fact has two "
                      "ways to get it: navigate or search. With neither, the only "
                      "remaining move is leaving.",
            evidence="Entry page exposes %d links inside navigation markup "
                     "(<nav>/<header>/role=navigation/nav-classed containers) and only "
                     "%d distinct internal destinations in total; no search input was "
                     "found on any of the %d sampled pages."
                     % (nav_count, len(internal_deep), n),
            action_summary="Add a persistent primary navigation, and site search once "
                           "the site is more than a few pages.",
            confidence="medium", root_cause="no-wayfinding", check="navigation",
            pages=[home["final_url"]]))
    elif not has_search and len(bundle.get("sitemap", {}).get("urls", [])) > 50:
        opps.append(opportunity(
            title="Add on-site search",
            category="engagement",
            rationale="The sitemap lists %d URLs but no search input was found; on a "
                      "site that size, browsing alone is a slow path to one fact."
                      % len(bundle["sitemap"]["urls"]),
            action="Add a site search box to the header.", effort="medium"))

    # -------------------------------------------------------------- mobile
    no_viewport = [p["final_url"] for p in sample
                   if not common.get_parsed(p)["has_viewport"]]
    if len(no_viewport) >= max(1, round(n * 0.5)):
        findings.append(finding(
            title="No mobile viewport meta tag",
            severity="medium", category="engagement",
            mechanism="Without a viewport declaration, mobile browsers render at "
                      "desktop width and zoom out, so text arrives unreadable. Most "
                      "AI-assistant referrals are mobile, and this is the first thing "
                      "they see.",
            evidence="%d of %d sampled pages have no <meta name=\"viewport\">: %s"
                     % (len(no_viewport), n, "; ".join(no_viewport[:4])),
            action_summary="Add <meta name=\"viewport\" content=\"width=device-width, "
                           "initial-scale=1\"> to the base template.",
            confidence="high", root_cause="no-viewport", check="viewport",
            pages=no_viewport))

    # ------------------------------------------------------------- payload
    heavy = [p for p in sample if p.get("bytes", 0) >= HEAVY_BYTES or p.get("truncated")]
    script_heavy = [p for p in sample
                    if common.get_parsed(p)["script_src_count"] >= MANY_SCRIPTS]
    if heavy:
        findings.append(finding(
            title="Very large HTML documents",
            severity="medium", category="engagement",
            mechanism="The HTML document is on the critical path: nothing renders "
                      "until it arrives. A multi-megabyte document delays first paint "
                      "on mobile networks past the point most cold visitors wait.",
            evidence="; ".join("%s: %.1f MB of HTML%s"
                               % (p["final_url"], p.get("bytes", 0) / 1e6,
                                  " (hit the reader's cap)" if p.get("truncated") else "")
                               for p in heavy[:4]),
            action_summary="Trim inlined data/markup from the document and load it "
                           "asynchronously.",
            confidence="high", root_cause="heavy-payload", check="payload",
            pages=[p["final_url"] for p in heavy]))
    if script_heavy:
        findings.append(finding(
            title="Unusually many blocking script requests",
            severity="low", category="engagement",
            mechanism="Each additional script is another request competing with "
                      "content rendering; at this count the page is usually "
                      "interactive well after the visitor has decided.",
            evidence="; ".join("%s: %d <script src> tags"
                               % (p["final_url"],
                                  common.get_parsed(p)["script_src_count"])
                               for p in script_heavy[:4]),
            action_summary="Audit third-party tags; defer or remove what isn't needed "
                           "for the first view.",
            confidence="medium", root_cause="script-bloat", check="script_count",
            pages=[p["final_url"] for p in script_heavy]))

    # ---------------------------------------------- context continuity (never a defect)
    opps.append(opportunity(
        title="Design for cold, deep-landing visitors (context continuity)",
        category="engagement",
        rationale="A visitor arriving from an AI answer carries a question the site "
                  "never saw and lands mid-site with no session history. Whether the "
                  "page picks that context up is runtime behaviour this static audit "
                  "cannot observe — this is a recommendation, not a detected defect.",
        action="On each deep page, restate the question the page answers in its "
               "opening lines, link the 2-3 adjacent questions people ask next, and "
               "make the primary next action reachable without returning to the "
               "homepage.", effort="medium"))
    nv.append(not_verified(
        "context_continuity",
        "runtime behaviour (does the page pick up an arriving visitor's intent) cannot "
        "be observed from static HTML; reported as an opportunity only",
        bundle.get("site")))

    return _wrap(findings, nv, opps, obs)


def _wrap(findings, nv, opps, obs):
    return {"skill": SKILL, "findings": findings, "not_verified": nv,
            "opportunities": opps, "observations": obs}


if __name__ == "__main__":
    common.emit(analyze(common.load_bundle_from_args(sys.argv[1:])))
