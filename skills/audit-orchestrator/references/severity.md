# Severity rubric

Severity = **where the mechanism sits in the funnel** × **how strong the
evidence is**. Nothing else. Not how commonly the issue is discussed, not how
easy the fix is, not how bad it sounds.

## The funnel

| Stage | Question | Failure means |
|---|---|---|
| 1. Reach | Can a fetcher get the bytes? | Nothing downstream can compensate |
| 2. Read | Are the facts in the response? | The fetch succeeded and returned nothing usable |
| 3. Extract | Is there a quotable, self-contained answer? | Retrieved but not quoted |
| 4. Attribute / trust | Whose claim is it, how old, corroborated? | Quoted but unattributed, or dropped as unverifiable |
| 5. Engage | Does the arriving visitor stay? | The citation converts to nothing |

Earlier stages dominate: a stage-1 block makes stage-3 quality irrelevant.

## Base severity by stage

| Base | When |
|---|---|
| **critical** | Stage 1 total blocker: named AI crawlers disallowed sitewide; `Disallow: /` for `*`; entry URL unreachable, erroring, or `noindex`; site has effectively no content |
| **high** | Stage 1–2 partial blocker or stage 4 identity gap: 5xx on linked pages, redirect loops, off-domain canonicals, core facts absent from the initial HTML, no identity entity anywhere, JSON-LD present but invalid, most key pages too thin to quote |
| **medium** | Stage 3–5 degradation: no concrete figures on prose pages, no outbound sourcing, no freshness signal, no corroboration links, missing `h1` sitewide, facts locked in un-alt-texted images, no viewport, no wayfinding, multi-megabyte documents |
| **low** | Marginal or easily-compensated: multi-hop redirect chains, sitemap gaps, dates human-visible but not machine-readable, `sameAs` limited to social profiles, script bloat, answer buried below the opening block |

## Evidence cap

Confidence caps severity, always:

| Confidence | Max severity | Meaning |
|---|---|---|
| high | critical | Directly observed, unambiguous (status codes, parsed markup, counts) |
| medium | high | Observed but interpretation-dependent (heuristics, single vantage point) |
| low | medium | Inferred, or dependent on a check that could not be completed |

So: a static-vs-rendered finding with no renderer to confirm is medium
confidence → at most `high`. A name-ambiguity concern with no search to confirm
is low confidence → at most `medium`, and is better emitted as an
`opportunity`.

## Modifiers

- **Scope**: entry page / sitewide template → keep base. One peripheral page →
  drop one level.
- **Compensation**: a signal that is missing in one form but present in another
  (visible date but no schema date; social `sameAs` but no Wikidata) → drop one
  level, and say what compensates.
- **Content type**: recency matters far more for pricing, availability,
  security posture and product capability than for a founding story. Weight the
  freshness findings by what the page claims.
- **Authority context**: an institutional domain (`.gov`, `.edu`, `.ac.uk`)
  already carries most of the trust the corroboration check measures → drop
  corroboration findings one level.
- **Deliberate choices**: a robots.txt AI block may be a licensing decision.
  Report the consequence at full severity, but never assume it was a mistake —
  the fix column says "decide deliberately", not "remove this".

## Sorting

Order the report by severity, then by confidence within a severity band. The
first three findings should be the three things worth doing first.
