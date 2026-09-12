# engagement-audit — check rubric

The visitor this skill models: **arrives deep, cold, from an AI answer, with a
question already formed, and one click from going back to the assistant.**

| Check id | Signal | Fires when | Base severity | Confidence |
|---|---|---|---|---|
| `deep_linkability` (anchors) | Homepage-only site | <5 distinct internal URLs and same-page anchors are ≥40% of links | high | high |
| `deep_linkability` (shallow) | Few destinations | <5 distinct internal URLs without the anchor pattern | medium | medium |
| `above_fold` | Landing view says nothing | No `h1` **and** <30 words in the opening block | medium | medium |
| `navigation` | No wayfinding | <4 links in navigation markup **and** no search input **and** <10 distinct internal destinations | medium | medium |
| `viewport` | No mobile viewport | ≥50% of sampled pages lack `<meta name="viewport">` | medium | high |
| `payload` | Very heavy document | HTML document ≥2.5 MB, or it hit the reader's byte cap | medium | high |
| `script_count` | Script bloat | ≥25 `<script src>` tags on a page | low | medium |
| context continuity | Runtime intent pickup | **Never a finding** — always an `opportunity` + `not_verified` | — | — |

## Field calibration log — `deep_linkable`

**No severity change.** This records a real false positive that was found and
fixed, and what the fix did and did not buy.

### The false positive

The original rule gated on **3+ distinct same-site links at path depth ≥ 2**.
That measures URL *shape*, not linkability. Ground-truth testing on verified
sites showed it scoring a flat multi-page site identically to a site with no
pages at all:

| Site | Reality | Old rule |
|---|---|---|
| strouplegal.com | 9 real pages (`/about`, `/services`, `/contact`, `/scheduling`, …), no nesting | **fail** |
| addsup.co.uk | 5 real pages, and `sitemap.xml` confirms no nesting exists anywhere | **fail** |
| lepetitbleucafe.com | zero separate pages, 100% `#anchor` navigation | fail |
| obliques.co | zero separate pages, 100% `#anchor` navigation | fail |

A nine-page law firm scoring the same as a one-page brochure is a false
finding, and an assistant can deep-link to `addsup.co.uk/pricing` perfectly
well. Flat information architecture is a URL convention, not a defect.

### The fix

The gate is now **3+ distinct internal destinations at depth ≥ 1**. Nesting is
still measured but no longer gates: it is recorded as
`deep_linkable_confidence` — `nested` (3+ destinations also reach depth ≥ 2),
`flat` (real pages, none nested), or `no_internal_destinations`.

Both flat sites now pass with confidence `flat`; both single-page sites still
fail. **Ground-truth accuracy on this check improved from 67% to 89%** (2/3 to
8/9 scored).

### What the fix was worth

**Correctness, not discrimination.** Re-scored across all 68 calibration sites,
the citation-separation delta barely moved: **+1% → +4% pooled**, positive in
1 of 6 sectors, still **DROP**. Only one row changed verdict, because the
population saturates — **53 of 54 scoreable sites already pass** (25 because
the audited URL was itself a deep page, 27 genuinely nested, 1 flat).

So the fix stops the audit emitting false findings in real reports, which is
worth having on its own terms. It does **not** make the check better at telling
cited sites from omitted ones, and it is not evidence for raising its severity.
The single remaining failure in the whole set is a site with zero internal
destinations — exactly what the check should catch.

## Navigation detection

Count links inside: `<nav>`, `<header>`, any element with
`role="navigation"`, and `div`/`ul`/`section`/`aside`/`footer` whose class
contains `nav`, `menu` or `header`.

Then require corroboration: sparse navigation markup alone is **not** proof of
missing navigation — plenty of sites ship a perfectly usable menu in an
unconventional wrapper. The finding only fires when the page also exposes very
few distinct internal destinations.

Search detection: `type="search"`, plus search-ish `name`/`id`/`placeholder`/
`aria-label` values in more than one language.

## Why deep-linkability is the flagship check here

An assistant can only hand over a URL. If the answer lives in a `#section` of a
one-page site, the assistant links the homepage; the visitor lands above the
thing they asked about, has to re-find it, and often doesn't. The same
structure also means no section can be cited or ranked independently — which is
why this check straddles engagement and discoverability.

## Weight and performance

Report only what was measured: HTML document bytes and `<script src>` counts.
Do not claim a Core Web Vitals or Lighthouse score you did not run. If you have
a browser tool and measured real timings, report those instead, and say how.

## Not defects

- Design taste, colour, copywriting style.
- A long homepage that *also* has real deep pages.
- Heavy imagery on a portfolio or brand site where imagery is the product.
- Missing chat widget, popup, or newsletter capture.
- No search on a small site.

## Safety

Read-only. Never submit a form, log in, add to a cart, or trigger a purchase or
donation flow to test a path. If a flow cannot be observed without acting on
it, it is `not_verified`.
