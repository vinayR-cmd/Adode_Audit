# freshness-corroboration — check rubric

| Check id | Signal | Fires when | Base severity | Confidence |
|---|---|---|---|---|
| `freshness_signal` | No date anywhere | No schema date, `<time datetime>`, `Last-Modified`, or visible date phrase on any sampled page | **high** (field-calibrated, see below) | high |
| `freshness_signal_dated_pages` | Time-sensitive pages undated | Article/news/blog/press URLs with no date, while other pages have them | medium | high |
| `date_machine_readable` | Human-only dates | Visible date phrases but no structural date anywhere (English-language sites only) | low | medium |
| `stale_year` | Reads as abandoned | Newest copyright ≤ current year − 2 **and** no fresher date anywhere | medium | medium |
| `corroboration` | No independent platform linked | No outbound link or `sameAs` to any corroboration platform | medium (low on authority domains) | medium |
| `claim_conflict_check` | Third-party statements disagree | Requires web search — always `not_verified` for the script | high when confirmed | high (direct evidence) |

## Field calibration: why `freshness_signal` is high

Raised from medium to **high** on measured evidence, not on theory.

**Method.** 51 real sites with usable data (29 cited, 22 omitted), drawn from
pairs where an AI assistant's answer was observed to cite one site and not the
other. Covers 5 of 6 sectors — Ecommerce and part of Education were lost to
network/TLS failures in that run and are excluded rather than counted as
failures.

**Result.** Sites the assistant cited carried some freshness signal **59% of the
time (17/29)**; sites it omitted, **32% (7/22)**. That is **+27 points pooled**
(sample-weighted) and **+30 points averaged per sector**, positive in **4 of 5
usable sectors** (Education, Financial Services, Health Info, Local Services).

It is the only one of six calibrated checks to clear all three bars: >15 points
pooled, >15 points sector-average, and majority-positive sectors.

**Counter-example, stated plainly.** It went **negative in B2B sales (−17%)** —
cited B2B sites carried dates *less* often than omitted ones. So the honest
claim is: *freshness signals showed the strongest evidence of any signal checked
in this round's field calibration, with one sector counter-example.* Not:
*freshness determines citation.* When auditing a B2B site, say so — this
evidence does not support treating a missing date there as decisive.

**What the severity does and does not mean.** High severity reflects the
strength of the association measured here, on a sample of 51 sites, in one
round, from one network. It is not proof of causation, and a single round on a
sample this size can move. Re-check it as the calibration set grows.

This is the same evidence-before-severity treatment applied in the opposite
direction to the entity-ambiguity check, which was demoted from a finding to an
opportunity after it false-positived on well-known brands during testing.

## Not yet calibrated — do not re-weight these on this round

The other five checks did **not** show a confirmed separation in this sample and
their severities stay where they are:

| Check | Home skill | This round |
|---|---|---|
| `schema_valid` | entity-trust-audit | round 1: −7 pooled / −0 sector-avg — no separation. Round 2 (all 6 sectors): +3 pooled / +8 sector-avg — **weak**, 4/6 sectors positive, still short of the KEEP bar. See that skill's rubric for the full note. |
| `has_entity_links` (`sameas`) | entity-trust-audit | −19 pooled / −21 sector-avg — negative |
| `deep_linkable` | engagement-audit | +1 pooled / +4 sector-avg — no separation |
| `robots_allows_ai` | crawl-render-audit | +14 pooled / +9 sector-avg — weak, driven entirely by Health Info |
| `raw_html_readable` | crawl-render-audit | +0 — no site in the sample failed it, so it had no range to separate on |

A null result here is **not** evidence a check is wrong: `raw_html_readable`
separated nothing because every sampled site passed it, which is a property of
the sample, not of the mechanism. These remain justified by mechanism; they are
simply not yet supported by field evidence.

**Data needed before revisiting:**

- **Education** — needs more `omitted` sites; the bucket was 1 site, and the
  cited side lost 2 more to anti-bot 403s.
- **Ecommerce** — needs a full re-run after the SSL/timeout fix in the
  calibration harness; the entire sector was lost to transport failures in the
  round that produced these numbers.
- **Local Services** — 5:2 cited:omitted, the most lopsided remaining sector.
- Any sector where a check has **no failing sites at all** (currently
  `raw_html_readable`) needs sites that actually fail it before the check can
  be evaluated.

## Signal reliability order

1. `dateModified` / `datePublished` / `dateCreated` in JSON-LD — explicit,
   language-independent.
2. `<time datetime="…">` — explicit, language-independent.
3. `Last-Modified` HTTP header — often template-generated, but real.
4. Visible "last updated" text — human-facing, **language-dependent**.

The script matches the visible phrase in ~12 languages (English, French,
German, Spanish, Italian, Portuguese, Japanese, Chinese, Korean, Russian,
Arabic, Hindi). That list is not exhaustive: on a non-English site with no
structural signal, mark the check low confidence rather than reporting "no
date" as fact.

## Stale-year logic

- Copyright year old **and** nothing fresher → finding.
- Copyright year old **but** fresher dates elsewhere → **not** a finding;
  record it as an observation. This is the most common false positive here.
- Never recommend bumping the footer year on its own. A fake freshness signal
  is worse than an honest stale one; recommend a review that produces a real
  date.

## Corroboration platforms

Wikipedia, Wikidata, LinkedIn, Crunchbase, G2, Capterra, Trustpilot, BBB,
Yelp, Clutch, Product Hunt, OpenCorporates, SEC, Companies House, GitHub.

Recommend only what fits the sector: G2/Capterra for software, BBB/Yelp/Google
Business for local trades, registries for regulated fields, GitHub for
developer tools. "Get on review sites" is noise.

Institutional-authority domains (`.gov`, `.edu`, `.mil`, `.ac.uk`, `.gov.au`,
`.gc.ca` …) already carry most of the trust this check measures — drop the
severity one level and say why.

## Conflict checking (agent, with search)

Budget: 1–2 searches. Compare the brand's key facts — legal name, headline
claim, headquarters, founding year, pricing model — against independent pages.

- Contradiction found → high-value finding with direct evidence. Quote both
  statements and both URLs. Conflicting facts are a leading cause of an
  assistant hedging or describing a brand wrongly.
- Agreement → record as a verified strength.
- No search available → `not_verified`. Do not guess.

## Not defects

- A page with no date is *undated*, not *stale*. Say the accurate thing.
- No blog, no "news" section, no press page.
- A design that looks dated.
- An old founding-story page — recency weight follows what the page claims.
