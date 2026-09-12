"""
analyze.py — deterministic fast-path helper for the content-extractability skill.

Answers: once a fetcher has the HTML, is there anything in it worth quoting?
Measures depth, concrete facts, sourcing, answer position, and facts locked in
images/PDFs. Every check is language-agnostic where it can be (counts, digits,
structure) and marked lower confidence where it cannot.

Usage:
    python analyze.py --bundle bundle.json
    python analyze.py --url https://example.com
"""

import re
import sys
from urllib.parse import urljoin, urlparse

import common
from common import finding, not_verified, opportunity

SKILL = "content-extractability"

THIN_WORDS = 200          # below this a page rarely carries a quotable fact
DEEP_WORDS = 450          # a page that can actually answer a question

# Concrete facts: percentages, currency, magnitudes, years, measured quantities.
STAT_RE = re.compile(
    r"(?<![\w/])(?:"
    r"\d{1,3}(?:[.,]\d+)?\s?%"                       # 42%, 3,5 %
    r"|[$€£¥₹]\s?\d[\d.,]*\s?(?:[kKmMbB]|billion|million|crore|lakh)?"
    r"|\d[\d.,]*\s?(?:[kKmMbB]n?|billion|million|thousand)\b"
    r"|\d[\d.,]*\s?(?:kg|km|mm|cm|ms|GB|MB|TB|hrs?|hours?|days?|years?|users?|"
    r"customers?|countries|employees|clients?)\b"
    r"|\b(?:19|20)\d{2}\b"
    r")", re.I)

SOCIAL_HOSTS = ("facebook.", "twitter.", "x.com", "instagram.", "linkedin.",
                "youtube.", "youtu.be", "tiktok.", "pinterest.", "reddit.",
                "t.me", "whatsapp.", "threads.net", "discord.")
# Independent, checkable sources — the kind an assistant will corroborate against.
SOURCE_HINTS = (".gov", ".edu", ".org", "wikipedia.org", "wikidata.org", "doi.org",
                "arxiv.org", "nih.gov", "who.int", "oecd.org", "worldbank.org",
                "statista.com", "gartner.com", "forrester.com", "nature.com",
                "ieee.org", "acm.org", "reuters.com", "bloomberg.com", "ft.com",
                "nytimes.com", "bbc.co", "techcrunch.com", "g2.com", "capterra.com")

DECORATIVE_HINT = re.compile(r"(icon|logo|sprite|spacer|pixel|bg[-_]|background|"
                             r"arrow|chevron|divider|avatar|placeholder)", re.I)


def _external_links(parsed, base):
    out = []
    for href, text in parsed["links"]:
        if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
            continue
        full = urljoin(base, href)
        if not full.startswith(("http://", "https://")):
            continue
        if not common.same_site(base, full):
            out.append((full, text))
    return out


def analyze(bundle):
    findings, nv, opps = [], [], []
    obs = {}
    sample = common.html_pages(bundle)
    if not sample:
        nv.append(not_verified("content_extractability",
                               "no analyzable HTML page in the sample",
                               bundle.get("start_url")))
        return _wrap(findings, nv, opps, obs)

    per_page = []
    for p in sample:
        parsed = common.get_parsed(p)
        text = parsed["visible_text"]
        ext = _external_links(parsed, p["final_url"])
        stats = STAT_RE.findall(text)
        sources = [u for u, _ in ext
                   if any(h in urlparse(u).netloc.lower() for h in SOURCE_HINTS)
                   and not any(s in urlparse(u).netloc.lower() for s in SOCIAL_HOSTS)]
        imgs = parsed["images"]
        no_alt = [i for i in imgs
                  if not (i.get("alt") or "").strip()
                  and not DECORATIVE_HINT.search(i.get("src", ""))
                  and (i.get("role", "") or "").lower() != "presentation"]
        pdfs = [u for u, _ in parsed["links"] if u.lower().split("?")[0].endswith(".pdf")]
        h1 = [t for tag, t in parsed["headings"] if tag == "h1"]
        early_words = len(parsed["early_text"].split())
        link_density = (len(parsed["links"]) / float(parsed["word_count"])
                        if parsed["word_count"] else 1.0)
        per_page.append({
            "url": p["final_url"], "words": parsed["word_count"],
            "link_density": round(link_density, 3),
            "is_prose": parsed["word_count"] >= 150 and link_density < 0.12,
            "stats": len(stats), "stat_samples": stats[:3],
            "ext_links": len(ext), "sources": sources, "images": len(imgs),
            "images_no_alt": len(no_alt), "pdfs": len(pdfs), "h1": h1[:1],
            "early_words": early_words, "title": parsed["title"],
        })

    n = len(per_page)
    obs["pages_analyzed"] = n
    obs["median_word_count"] = sorted(x["words"] for x in per_page)[n // 2]

    # ------------------------------------------------------------- thin content
    thin = [x for x in per_page if x["words"] < THIN_WORDS]
    if len(thin) >= max(2, round(n * 0.5)):
        findings.append(finding(
            title="Most sampled pages are too thin to be quoted",
            severity="high" if len(thin) >= round(n * 0.75) else "medium",
            category="discoverability",
            mechanism="Stage 3 (extract): assistants quote self-contained passages. "
                      "A page with a headline and a few marketing lines offers no "
                      "span that answers a question, so it loses to a competitor page "
                      "that has one — even when both rank equally well.",
            evidence="%d of %d sampled pages have under %d words of visible text "
                     "(median %d). Examples: %s"
                     % (len(thin), n, THIN_WORDS, obs["median_word_count"],
                        "; ".join("%s (%dw)" % (x["url"], x["words"]) for x in thin[:4])),
            action_summary="Give the pages that should be citable a substantive, "
                           "self-contained explanation of their topic.",
            how="Target the pages a customer would ask an assistant about. ~%d+ words "
                "of specific, answer-shaped prose beats a longer page of adjectives."
                % DEEP_WORDS,
            confidence="high", root_cause="thin-content", check="word_depth",
            pages=[x["url"] for x in thin]))
    elif thin:
        obs["thin_pages"] = ["%s (%dw)" % (x["url"], x["words"]) for x in thin]

    # ---------------------------------------------------------- concrete facts
    prose = [x for x in per_page if x["is_prose"]]
    no_stats = [x for x in prose if x["stats"] == 0]
    if prose and no_stats and len(no_stats) >= max(2, round(len(prose) * 0.6)):
        findings.append(finding(
            title="Claims are qualitative with no concrete figures",
            severity="medium", category="discoverability",
            mechanism="Stage 3 (extract): a specific number ('cuts onboarding from 6 "
                      "weeks to 4 days') is quotable and checkable; 'industry-leading' "
                      "is neither, so it is skipped in favour of a competitor's "
                      "specific claim.",
            evidence="%d of %d prose pages (navigation-style pages excluded) contain "
                     "no percentage, currency amount, quantity or date in their "
                     "visible text. Examples: %s"
                     % (len(no_stats), len(prose),
                        "; ".join("%s (%dw, 0 figures)" % (x["url"], x["words"])
                                  for x in no_stats[:4])),
            action_summary="Attach at least one verifiable figure to each key claim.",
            confidence="medium", root_cause="no-concrete-facts", check="statistics",
            pages=[x["url"] for x in no_stats]))

    # -------------------------------------------------------------- sourcing
    total_sources = sum(len(x["sources"]) for x in per_page)
    if total_sources == 0:
        findings.append(finding(
            title="No outbound citations to independent sources",
            severity="medium", category="discoverability",
            mechanism="Stage 3 (extract) plus trust: an assistant weighs whether a "
                      "claim can be corroborated. A page whose assertions link to "
                      "nothing external is a single unsupported source, so its claims "
                      "are more likely to be dropped than repeated.",
            evidence="Across %d sampled pages, %d external links were found and none "
                     "pointed to an independent reference domain (research, standards, "
                     "government, press or review platforms)." % (
                         n, sum(x["ext_links"] for x in per_page)),
            action_summary="Cite the sources behind your data claims, and link the "
                           "standards/research you build on.",
            confidence="medium", root_cause="no-citations",
            check="outbound_citations",
            pages=[x["url"] for x in per_page[:6]]))
    else:
        obs["outbound_source_links"] = total_sources

    # -------------------------------------------------- answer-first structure
    no_h1 = [x for x in per_page if not x["h1"]]
    buried = [x for x in per_page if x["early_words"] < 25 and x["words"] >= THIN_WORDS]
    if len(no_h1) >= max(2, round(n * 0.5)):
        findings.append(finding(
            title="Pages lack a top-level heading stating what they are about",
            severity="medium", category="discoverability",
            mechanism="Stage 3 (extract): the h1 is the strongest structural cue for "
                      "what a passage answers. Without it, extraction has to guess the "
                      "topic from body prose and often attributes the passage wrongly "
                      "or not at all.",
            evidence="%d of %d sampled pages have no <h1>. Examples: %s"
                     % (len(no_h1), n, "; ".join("%s (title %r)"
                        % (x["url"], (x["title"] or "")[:50]) for x in no_h1[:4])),
            action_summary="Give every page one h1 that names its subject in plain "
                           "words.",
            confidence="high", root_cause="missing-h1", check="answer_structure",
            pages=[x["url"] for x in no_h1]))
    if buried:
        findings.append(finding(
            title="Key pages open with no readable text near the top",
            severity="low", category="discoverability",
            mechanism="Stage 3 (extract): a direct answer in the opening lines is what "
                      "gets lifted into a response. Pages that open with navigation, "
                      "hero imagery or a slogan push the answer past where extraction "
                      "usually looks.",
            evidence="; ".join("%s: %d words in the opening block of %d total"
                               % (x["url"], x["early_words"], x["words"])
                               for x in buried[:4]),
            action_summary="Open each key page with 2-3 sentences that answer its "
                           "core question directly.",
            confidence="medium", root_cause="answer-not-first", check="answer_position",
            pages=[x["url"] for x in buried]))

    # --------------------------------------------------- facts locked in media
    alt_missing = sum(x["images_no_alt"] for x in per_page)
    img_total = sum(x["images"] for x in per_page)
    if img_total >= 5 and alt_missing >= max(5, round(img_total * 0.5)):
        worst = sorted(per_page, key=lambda x: -x["images_no_alt"])[:4]
        findings.append(finding(
            title="Content-bearing images carry no alt text",
            severity="medium", category="discoverability",
            mechanism="Stage 3 (extract): a text fetcher reads alt text, not pixels. "
                      "Where pricing, specs or comparisons live inside an image with "
                      "no alt text, that fact is invisible to the assistant.",
            evidence="%d of %d images across %d pages have no alt attribute (obvious "
                     "icons/logos excluded). Worst pages: %s"
                     % (alt_missing, img_total, n,
                        "; ".join("%s (%d/%d)" % (x["url"], x["images_no_alt"],
                                                  x["images"]) for x in worst)),
            action_summary="Write alt text that states the fact the image conveys, and "
                           "put any critical numbers in HTML text as well.",
            confidence="medium", root_cause="images-no-alt", check="image_alt",
            pages=[x["url"] for x in worst]))

    pdf_heavy = [x for x in per_page if x["pdfs"] >= 3 and x["words"] < DEEP_WORDS]
    if pdf_heavy:
        findings.append(finding(
            title="Substantive material is published as PDFs on thin HTML pages",
            severity="low", category="discoverability",
            mechanism="Stage 2/3: PDFs are fetched less often, parsed less reliably, "
                      "and cited with less precision than HTML. When the HTML page is "
                      "only a link list, the actual content is effectively offline.",
            evidence="; ".join("%s: %d PDF links, %d words of HTML text"
                               % (x["url"], x["pdfs"], x["words"]) for x in pdf_heavy[:4]),
            action_summary="Publish an HTML summary (key findings, figures, "
                           "conclusions) alongside each PDF.",
            confidence="medium", root_cause="pdf-locked", check="pdf_content",
            pages=[x["url"] for x in pdf_heavy]))

    # ------------------------------------------------------------ opportunity
    if not any(f["check"] == "answer_structure" for f in findings):
        opps.append(opportunity(
            title="Add explicit question-and-answer framing to key pages",
            category="discoverability",
            rationale="Pages already carry headings; phrasing key sections as the "
                      "question a buyer actually asks makes the following paragraph "
                      "directly liftable as an answer.",
            action="Convert 3-5 high-intent headings into question form with a "
                   "self-contained 2-3 sentence answer underneath.", effort="low"))

    obs["per_page"] = per_page
    return _wrap(findings, nv, opps, obs)


def _wrap(findings, nv, opps, obs):
    return {"skill": SKILL, "findings": findings, "not_verified": nv,
            "opportunities": opps, "observations": obs}


if __name__ == "__main__":
    common.emit(analyze(common.load_bundle_from_args(sys.argv[1:])))
