# content-extractability — check rubric

| Check id | Signal | Fires when | Base severity | Confidence |
|---|---|---|---|---|
| `word_depth` | Thin pages | ≥50% of sampled pages under 200 words (high at ≥75%) | medium / high | high |
| `statistics` | No concrete figures | ≥60% of **prose** pages contain no %, currency, quantity, or date | medium | medium |
| `outbound_citations` | No independent sourcing | Zero external links to reference domains across the sample | medium | medium |
| `answer_structure` | No `h1` | ≥50% of sampled pages lack an `h1` | medium | high |
| `answer_position` | Answer buried | Substantive page whose opening block has <25 words | low | medium |
| `image_alt` | Facts locked in images | ≥50% of ≥5 content images lack `alt` (icons/logos/`role=presentation` excluded) | medium | medium |
| `pdf_content` | Facts locked in PDFs | ≥3 PDF links on a page with <450 words of HTML | low | medium |

## Thresholds

- **200 words** — below this a page rarely contains a self-contained,
  quotable answer.
- **450 words** — a page that can actually answer a question in depth. Used as
  advice, never as a target to pad toward.
- **Prose page** — ≥150 words *and* link-to-word ratio < 0.12. Navigation,
  index and browse pages are excluded from the "no figures" check: a directory
  page is not supposed to make claims.

## What counts as a concrete figure

Percentages, currency amounts, magnitudes (`2.4M`, `12k`), measured quantities
with units, counts of users/customers/countries/employees, and years. The point
is checkability, not the presence of digits — a phone number is not a claim.

## What counts as an independent source

Research and standards (`doi.org`, `arxiv.org`, IEEE, ACM, `nature.com`),
government and institutional (`.gov`, `.edu`, WHO, OECD, World Bank),
reference (Wikipedia, Wikidata), reputable press, and sector review platforms
(G2, Capterra). **Social profiles are not sourcing.** A brand's own subdomains
are not sourcing.

## Language handling

Word counts, digit patterns, link structure and heading structure are
language-independent — prefer them. Never conclude a defect from an
English-only text pattern; where a check depends on reading the prose, lower
the confidence and say so rather than reporting a false negative as a finding.

## Not defects

- A short contact or legal page.
- One thin page among substantive ones (that is an observation).
- A long page without statistics when the topic has none to give.
- Missing meta descriptions.
- Absence of a blog.

## Framing

Report the *fact loss*, not the checklist item: "the price table exists only
inside an image with no alt text, so a text fetcher cannot read it" — not
"images are missing alt attributes".
