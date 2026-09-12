# entity-trust-audit — check rubric

| Check id | Signal | Fires when | Base severity | Confidence |
|---|---|---|---|---|
| `jsonld_presence` | No structured data at all | No JSON-LD block and no microdata `itemtype` anywhere in the sample | high | high |
| `jsonld_valid` | Markup present but broken | Any JSON-LD block fails to parse | high | high |
| `jsonld_coverage` | Uneven coverage | <50% of sampled pages carry markup (and >0) | medium | high |
| `identity_markup` | No publisher entity | Markup exists but contains no `Organization`-class or `Person` node | high | high |
| `sameas` | Identity node with no `sameAs` | Organization node present, `sameAs` absent | medium | high |
| `sameas_quality` | Social-only anchoring | `sameAs` present but only social profiles | low | medium |
| `ambiguity` | Collision-prone name | **Opportunity only** unless a web search confirms the collision | — | low |

## Field calibration log — structured data (`jsonld_presence` / `jsonld_valid`)

**No severity change.** These entries record what field calibration has shown so
far, so a later round can see the trend instead of re-deriving it. The
calibration harness scores one combined `schema_valid` signal (JSON-LD present
and parsing) which maps onto both checks above.

**Round 1** (65 rows, 51 usable, 5 of 6 sectors — Ecommerce lost to transport
failures): `schema_valid` showed no separation — −7% pooled, −0% sector-average.

**Round 2** (71 rows, 54 usable, all 6 sectors): `schema_valid` moved from
no-separation to weak — positive in 4/6 sectors (Education +50%, B2B +33%,
Financial Services +20%, Health Info +14%; negative in Ecommerce −20% and Local
Services −50%). Sector-average (+8%) and pooled (+3%) disagree significantly —
the sector-average is carried by Education's small usable sample (6 cited vs 3
omitted), which is exactly the kind of thin-sector distortion the pooled metric
exists to catch. Does not clear the KEEP bar. Revisit if Ecommerce/Local
Services grow enough to confirm whether their negative pull is real or also a
small-sample artifact.

## Field calibration log — `sameas` / entity corroboration

**No severity change.**

**4 rounds of evidence, consistently negative on the on-page-link version.**
The calibration harness's `has_entity_links` signal — does the page link OUT to
Wikipedia / LinkedIn / G2 / a registry — ran negative in every round
(pooled −19% to −29%, positive in at most 1 of 6 sectors). The diagnosis is
that it measures outbound-linking *habits*, not corroboration: an established
brand has no reason to link to its own encyclopedia entry from its homepage,
so the sites most strongly corroborated elsewhere score worst on it.

A redesigned signal was piloted on 20 hand-researched sites (10 cited / 10
omitted across Financial Services, B2B sales, Health Info), replacing on-page
links with what the wider web actually says:

| Variant | Rule | Pooled | Sector-avg | Sectors + | Verdict |
|---|---|---|---|---|---|
| Permissive | Wikipedia OR review platform OR ≥2 independent domains | +0% | +0% | 0/3 | **no variance** — 20/20 passed |
| A: strict | dedicated Wikipedia article for the brand itself | +10% | +14% | 2/3 | below bar |
| B: graded | 0–3 (Wikipedia + real review platform + ≥2 recognizable domains), compared by mean | −0.20 of 3.00 | — | 1/3 | below bar |

**A stricter dedicated-Wikipedia variant shows a weak positive signal too small
to act on (n=10).** Variant A is the only one pointing the right way (cited
70% vs omitted 60%), and it inverts in Financial Services (−25%), where the
cited budgeting apps mostly lack their own article while the omitted ones have
one. Variant B goes slightly negative once thin affiliate domains are excluded.

**Recommendation: leave the current severity unchanged and mark this check as
needing either a larger sample or a fundamentally different mechanism** — e.g.
checking whether an independent source states the brand's *specific key fact*,
not merely that the brand is mentioned somewhere. Mention-counting appears to
saturate: nearly every real company clears it, so it cannot discriminate.

Evidence file: `entity_corroboration.csv`; re-analysis:
`analyze_corroboration_variants.py` (both in the calibration harness, not
shipped with the marketplace).

Severity therefore stays where the mechanism put it (`jsonld_presence` high,
`jsonld_valid` high, `jsonld_coverage` medium, `sameas` medium,
`sameas_quality` low). Contrast with
`freshness-corroboration`'s `freshness_signal`, which *did* clear all three
bars and was raised on that evidence — see that skill's `references/checks.md`
for the bar and the method.

## Identity types accepted

`Organization`, `Corporation`, `LocalBusiness` (and subtypes such as `Store`,
`Restaurant`, `Hotel`), `NGO`, `EducationalOrganization`,
`GovernmentOrganization`, `MedicalOrganization`, `SportsOrganization`,
`OnlineBusiness`, `Person`.

Page-level types (`Article`, `Product`, `FAQPage`, `WebPage`,
`BreadcrumbList`, `GovernmentService`) describe content, not the publisher.
A site with rich page schema and no identity node still fails
`identity_markup` — and the evidence should list the types that *were* found,
so the owner can see the gap precisely.

## sameAs tiers

| Tier | Examples | Weight |
|---|---|---|
| Identity graph | Wikidata, Wikipedia, LinkedIn company, Crunchbase | Strongest — these resolve a name to an entity |
| Registry | OpenCorporates, SEC, Companies House, ORCID, ISNI | Strong, sector-dependent |
| Review platform | G2, Capterra, Trustpilot, BBB, Glassdoor | Useful where the sector fits |
| Social | X, Instagram, Facebook, TikTok, YouTube | Weak — self-asserted |

Check the page HTML as well as `sameAs`: a footer LinkedIn link that is missing
from `sameAs` is a five-minute fix worth naming exactly.

## Name ambiguity procedure

1. Derive the name: identity schema `name` → `og:site_name` → first title
   segment → domain label.
2. Flagging heuristics (a short single token, or a common dictionary/sector
   word) indicate **risk only**.
3. With web search: search the bare name. Brand dominates → no problem, record
   it. Others dominate → finding, citing the competing entities.
4. Without web search: `opportunity` + `not_verified`. Never a finding.
5. Existing disambiguation (`sameAs` to Wikidata/LinkedIn, a consistently
   qualified name in prose) cancels the concern.

## Not defects

- Missing a specific schema type (`FAQPage`, `Review`, `HowTo`).
- Using microdata or RDFa instead of JSON-LD.
- No Wikipedia article (notability is not something you can promise; Wikidata
  is the claimable one).
- Rich-result eligibility — that is a search-feature question, not an
  AI-citation one.
