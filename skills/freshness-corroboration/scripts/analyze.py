"""
analyze.py — deterministic fast-path helper for the freshness-corroboration skill.

Answers: can an assistant tell HOW OLD a claim is, and can it find the same
claim stated anywhere it doesn't control?

Freshness is checked structurally first (schema dates, <time datetime>,
Last-Modified header) because those are language-independent; visible-text date
phrases are matched in several languages and only ever used to ADD confidence,
never to conclude "no date" for a non-English site.

Usage:
    python analyze.py --bundle bundle.json
    python analyze.py --url https://example.com
"""

import datetime
import re
import sys
from urllib.parse import urlparse

import common
from common import finding, not_verified, opportunity

SKILL = "freshness-corroboration"

THIS_YEAR = datetime.datetime.now(datetime.timezone.utc).year

# "last updated"-style phrases across common web languages (extend freely).
UPDATED_PHRASE_RE = re.compile(
    r"(?i)(last\s+updated|updated\s+on|last\s+modified|reviewed\s+on|published\s+on"
    r"|dernière\s+mise\s+à\s+jour|mis\s+à\s+jour|zuletzt\s+aktualisiert"
    r"|última\s+actualización|actualizado\s+el|ultimo\s+aggiornamento"
    r"|última\s+atualização|最終更新|更新日|최종\s*업데이트|обновлено"
    r"|آخر\s*تحديث|अंतिम\s*अपडेट)")
TIME_ATTR_RE = re.compile(r"<time[^>]+datetime\s*=\s*[\"']([^\"']+)[\"']", re.I)
ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
COPYRIGHT_RE = re.compile(r"(?:©|&copy;|\(c\)|copyright)[^0-9]{0,20}((?:19|20)\d{2})"
                          r"(?:\s*[-–—]\s*((?:19|20)\d{2}))?", re.I)
ANY_YEAR_RE = re.compile(r"\b(20[0-4]\d)\b")

CORROBORATION_ANCHORS = {
    "wikipedia.org": "Wikipedia", "wikidata.org": "Wikidata",
    "linkedin.com": "LinkedIn", "crunchbase.com": "Crunchbase",
    "g2.com": "G2", "capterra.com": "Capterra", "trustpilot.com": "Trustpilot",
    "bbb.org": "BBB", "glassdoor.com": "Glassdoor", "yelp.com": "Yelp",
    "clutch.co": "Clutch", "producthunt.com": "Product Hunt",
    "opencorporates.com": "OpenCorporates", "sec.gov": "SEC",
    "companieshouse.gov.uk": "Companies House", "github.com": "GitHub",
}

DATED_CONTENT_HINT = re.compile(
    r"/(?:blog|news|press|articles?|insights?|resources?|updates?|posts?|"
    r"stories|newsroom|research|reports?)(?:/|$)", re.I)


def _page_dates(page, parsed):
    """Collect every freshness signal on one page, tagged by strength."""
    signals = []
    lm = page.get("headers", {}).get("last-modified")
    if lm:
        signals.append(("http_last_modified", lm))
    objs, _ = common.parse_jsonld(parsed["jsonld_raw"])
    for o in objs:
        for key in ("dateModified", "datePublished", "dateCreated", "uploadDate"):
            v = o.get(key)
            if isinstance(v, str) and v.strip():
                signals.append(("schema_%s" % key, v.strip()[:40]))
    for m in TIME_ATTR_RE.findall(page.get("html", "")[:400000])[:5]:
        signals.append(("time_element", m[:40]))
    text = parsed["visible_text"]
    m = UPDATED_PHRASE_RE.search(text)
    if m:
        window = text[m.start():m.start() + 120]
        signals.append(("visible_phrase", window.strip()[:100]))
    return signals


def _years_in(text):
    return [int(y) for y in ANY_YEAR_RE.findall(text)]


def analyze(bundle):
    findings, nv, opps = [], [], []
    obs = {}
    sample = common.html_pages(bundle)
    if not sample:
        nv.append(not_verified("freshness", "no analyzable HTML page in the sample",
                               bundle.get("start_url")))
        return _wrap(findings, nv, opps, obs)

    n = len(sample)
    per_page = []
    for p in sample:
        parsed = common.get_parsed(p)
        sigs = _page_dates(p, parsed)
        text_years = _years_in(parsed["visible_text"])
        cm = COPYRIGHT_RE.search(parsed["visible_text"])
        copyright_year = None
        if cm:
            copyright_year = int(cm.group(2) or cm.group(1))
        iso_years = [int(y) for y, _, _ in ISO_DATE_RE.findall(
            " ".join(v for _, v in sigs))]
        per_page.append({
            "url": p["final_url"],
            "signals": sigs,
            "signal_kinds": sorted({k for k, _ in sigs}),
            "max_year": max(text_years + iso_years) if (text_years or iso_years) else None,
            "copyright_year": copyright_year,
            "dated_type": bool(DATED_CONTENT_HINT.search(urlparse(p["final_url"]).path)),
            "lang": parsed.get("html_lang"),
        })

    obs["pages_analyzed"] = n
    obs["pages_with_any_date_signal"] = sum(1 for x in per_page if x["signals"])
    obs["date_signal_kinds"] = sorted({k for x in per_page for k in x["signal_kinds"]})

    non_english = any((x["lang"] or "en").lower()[:2] != "en" for x in per_page)
    if non_english:
        obs["language"] = "non-English html lang detected (%s) — text-phrase date " \
                          "matching treated as low confidence" % \
                          ", ".join(sorted({x["lang"] for x in per_page if x["lang"]}))

    # ------------------------------------------------------- no date signals
    dateless = [x for x in per_page if not x["signals"]]
    structural = [x for x in per_page
                  if any(k.startswith(("schema_", "http_", "time_"))
                         for k in x["signal_kinds"])]
    if len(dateless) == n:
        # High, not medium, on field-calibration evidence: across 51 real
        # cited/omitted pairs this was the only signal of six to separate the
        # two groups on every measure (59% vs 32% pooled, +30 sector-average,
        # 4 of 5 sectors positive). See references/checks.md — including the
        # B2B sales counter-example, which the agent should surface for B2B
        # sites rather than restating the general result.
        findings.append(finding(
            title="No freshness signal of any kind on the sampled pages",
            severity="high", category="discoverability",
            mechanism="Recency arbitration: when two sources make competing claims, "
                      "an assistant prefers the one it can date. Content with no "
                      "machine-readable date is treated as of unknown age and loses "
                      "to a dated competitor page — especially for 'current', "
                      "'latest' or pricing questions.",
            evidence="Across %d pages, none carried a Last-Modified header, a schema "
                     "dateModified/datePublished, a <time datetime> element, or a "
                     "visible 'last updated' phrase (checked in %d languages). "
                     "Pages: %s" % (n, 12, "; ".join(x["url"] for x in per_page[:5])),
            action_summary="Emit dateModified/datePublished in page schema and show a "
                           "human-visible 'last reviewed' date on substantive pages.",
            how="Structural signals matter most: schema dates and a correct "
                "Last-Modified header are language-independent.",
            confidence="high", root_cause="no-date-signal", check="freshness_signal",
            pages=[x["url"] for x in per_page]))
    elif not structural and not non_english:
        findings.append(finding(
            title="Dates are only human-visible, never machine-readable",
            severity="low", category="discoverability",
            mechanism="Recency arbitration: a date rendered as prose has to be parsed "
                      "out of the text and is often missed or mis-attributed; schema "
                      "dates and <time datetime> are unambiguous.",
            evidence="Date phrases found on %d/%d pages but no schema date, <time "
                     "datetime> or Last-Modified header anywhere. Example: %r"
                     % (n - len(dateless), n,
                        next((v for x in per_page for k, v in x["signals"]
                              if k == "visible_phrase"), "")[:90]),
            action_summary="Add dateModified/datePublished to the page schema.",
            confidence="medium", root_cause="dates-not-machine-readable",
            check="date_machine_readable"))
    elif dateless:
        dated_dateless = [x for x in dateless if x["dated_type"]]
        if dated_dateless:
            findings.append(finding(
                title="Time-sensitive content pages carry no date",
                severity="medium", category="discoverability",
                mechanism="Recency arbitration: article/news/blog URLs are exactly "
                          "where age decides whether a claim is quoted; undated ones "
                          "are treated as unknown-age.",
                evidence="; ".join(x["url"] for x in dated_dateless[:5]),
                action_summary="Add datePublished and dateModified to the article "
                               "template.",
                confidence="high", root_cause="no-date-signal",
                check="freshness_signal_dated_pages",
                pages=[x["url"] for x in dated_dateless]))
        else:
            obs["pages_without_dates"] = [x["url"] for x in dateless][:8]

    # ------------------------------------------------------------ stale years
    fresh_years = [x["max_year"] for x in per_page if x["max_year"]]
    newest = max(fresh_years) if fresh_years else None
    copyright_years = [x["copyright_year"] for x in per_page if x["copyright_year"]]
    obs["newest_year_seen"] = newest
    obs["copyright_year"] = max(copyright_years) if copyright_years else None

    if copyright_years and max(copyright_years) <= THIS_YEAR - 2 and (
            newest is None or newest <= THIS_YEAR - 2):
        findings.append(finding(
            title="Site reads as abandoned: newest date on it is %d" % max(
                copyright_years),
            severity="medium", category="discoverability",
            mechanism="Recency arbitration and trust: a stale copyright with no fresher "
                      "counter-signal is read as an unmaintained source, which lowers "
                      "the odds of being cited for anything time-sensitive.",
            evidence="Latest copyright year found: %d (current year %d). No date signal "
                     "newer than %s anywhere in the %d-page sample."
                     % (max(copyright_years), THIS_YEAR, newest or "none found", n),
            action_summary="Update the footer year and publish/refresh dates on key "
                           "pages — but only alongside a real content review.",
            confidence="medium", root_cause="stale-dates", check="stale_year"))
    elif copyright_years and newest and max(copyright_years) <= THIS_YEAR - 2 < newest:
        obs["stale_copyright_note"] = (
            "footer copyright says %d but fresher dates (%d) exist elsewhere — not "
            "flagged as stale" % (max(copyright_years), newest))

    # --------------------------------------------------------- corroboration
    hits = {}
    for p in sample:
        parsed = common.get_parsed(p)
        for href, _t in parsed["links"]:
            low = href.lower()
            for anchor, label in CORROBORATION_ANCHORS.items():
                if anchor in low:
                    hits.setdefault(label, href)
        objs, _ = common.parse_jsonld(parsed["jsonld_raw"])
        for o in objs:
            sa = o.get("sameAs")
            for v in (sa if isinstance(sa, list) else ([sa] if sa else [])):
                for anchor, label in CORROBORATION_ANCHORS.items():
                    if anchor in str(v).lower():
                        hits.setdefault(label, str(v))
    obs["corroboration_platforms"] = hits

    host = urlparse(bundle.get("start_url", "")).netloc.lower()
    authority_tld = host.endswith((".gov", ".edu", ".mil", ".int", ".gov.uk",
                                   ".ac.uk", ".edu.au", ".gov.au", ".gc.ca"))
    if not hits:
        findings.append(finding(
            title="No link to any independent platform that could corroborate the brand",
            severity="low" if authority_tld else "medium",
            category="discoverability",
            mechanism="Corroboration: assistants prefer claims that appear on sources "
                      "the brand does not control. With no path from this site to an "
                      "independent profile (encyclopaedia, registry, review platform), "
                      "every claim rests on self-assertion alone.",
            evidence="Across %d sampled pages, no outbound link or sameAs value "
                     "pointed to any of: %s.%s"
                     % (n, ", ".join(sorted(set(CORROBORATION_ANCHORS.values()))[:10]),
                        " Note: %s is itself an institutional-authority domain, which "
                        "already carries most of the trust this check measures — "
                        "severity lowered accordingly." % host if authority_tld else ""),
            action_summary="Establish and link at least two independent profiles "
                           "appropriate to the sector (Wikidata/LinkedIn for any "
                           "business; G2/Capterra for software; BBB/Yelp for local).",
            how="This measures links FROM the site. Confirm with a web search whether "
                "independent profiles exist but simply aren't linked — the fix differs "
                "(link them vs. create them).",
            confidence="medium", root_cause="no-corroboration", check="corroboration"))
        nv.append(not_verified(
            "third_party_corroboration",
            "whether independent sources state the brand's facts consistently was not "
            "checked by this script — it requires web search",
            bundle.get("site")))
    elif len(hits) == 1:
        opps.append(opportunity(
            title="Broaden independent corroboration",
            category="discoverability",
            rationale="Only one independent platform (%s) is linked. A second and third "
                      "independent source materially raises the odds that a claim "
                      "survives corroboration checks." % list(hits)[0],
            action="Create/claim and link one more sector-appropriate profile.",
            effort="medium"))

    nv.append(not_verified(
        "claim_conflict_check",
        "this script does not compare on-site claims against third-party statements; "
        "the agent should spend 1-2 web searches on the brand's key claim and flag "
        "conflicts", bundle.get("site")))

    obs["per_page"] = [{"url": x["url"], "signals": x["signal_kinds"],
                        "max_year": x["max_year"]} for x in per_page]
    return _wrap(findings, nv, opps, obs)


def _wrap(findings, nv, opps, obs):
    return {"skill": SKILL, "findings": findings, "not_verified": nv,
            "opportunities": opps, "observations": obs}


if __name__ == "__main__":
    common.emit(analyze(common.load_bundle_from_args(sys.argv[1:])))
