---
name: freshness-corroboration
description: Check whether an AI assistant can date a site's claims and corroborate them anywhere it doesn't control — visible "last updated" text, schema dateModified/datePublished, Last-Modified headers, stale copyright years with no fresher counter-signal, and links to independent platforms (Wikipedia, Wikidata, LinkedIn, G2, Capterra, Trustpilot, BBB) that could confirm the brand's facts. Use this when auditing why an assistant prefers a competitor's newer page, describes a brand with outdated or conflicting facts, or treats its claims as unverified. Read-only; never modifies the site.
license: MIT
compatibility: ">=1.0"
allowed-tools: Read, Bash, WebFetch, WebSearch
metadata:
  version: "1.0.0"
  category: audit
  funnel_stage: trust
---

# Freshness & corroboration

Two questions an assistant asks before repeating a claim: **when was this
true?** and **does anyone else say so?**

## When to use

Use this when the content is reachable, readable and attributable, but the
assistant still won't repeat its claims — or repeats stale ones. Concretely:

- "The assistant prefers a competitor's page that says the same thing but newer."
- "It describes us with outdated facts" — old pricing, an old product name, a
  headcount from three years ago.
- "It hedges on our claims instead of stating them" — the corroboration gap.
- "It states something about us that contradicts our own site."
- Questions about `dateModified` / `Last-Modified` / visible "last updated"
  dates and whether they matter.
- "Which review platforms or registries should we be on?" — sector-appropriate
  corroboration.
- As stage 4 (trust) of a full audit driven by `audit-orchestrator`.

Use `entity-trust-audit` instead when the problem is *who* the claim belongs to
rather than *when* it was true or whether anyone else confirms it.

## Inputs

Either of:

- **A crawl bundle** (preferred) — `--bundle bundle.json`, the shared crawl, so
  date signals are read from the same pages the other skills analyzed.
- **A URL** — `--url https://example.com` for standalone use.

```bash
python scripts/analyze.py --bundle bundle.json
python scripts/analyze.py --url https://example.com
```

From each sampled page this skill reads: JSON-LD date properties, `<time
datetime>` elements, the `Last-Modified` response header, visible date phrases,
copyright years, the `html lang` attribute, and all outbound links plus `sameAs`
values (for corroboration platforms).

**Optional but decisive: a web search tool.** The conflict check in step 4
cannot be done from the site alone. Without search it stays in `not_verified`.

Rubric: `references/checks.md`.

## Procedure

### 1. Freshness — structural signals first

Collect, in this order of reliability:

1. `dateModified` / `datePublished` / `dateCreated` in JSON-LD.
2. `<time datetime="...">` elements.
3. The `Last-Modified` HTTP response header.
4. Visible "last updated"-style text.

**1–3 are language-independent. 4 is not.** Match the visible phrase in several
languages, but never conclude "this site has no date" from an English-only
regex — if the page is not in English and structural signals are absent, mark
the check low confidence and say why.

**This check is empirically calibrated**, not only mechanism-motivated: across
51 real cited/omitted site pairs, cited sites carried a freshness signal 59% of
the time vs 32% for omitted sites (+27 pooled, +30 sector-average, positive in
4 of 5 sectors — negative in B2B sales). It is the only signal in the suite with
field evidence behind its severity. See `references/checks.md` for the method,
the sample, and the counter-example.

Findings:

- No signal of any kind anywhere → **high**. Mechanism: undated content is
  treated as unknown age and loses recency arbitration to a dated competitor.
  Severity reflects measured evidence (above), not just the mechanism. On a
  **B2B** site, note the sector counter-example in the finding rather than
  asserting the general result.
- Dates visible to humans but never machine-readable → low.
- Undated content specifically on article/news/blog/press URLs → medium, even
  when other pages are dated: that is where age decides citability.

### 2. Stale-year detection

Find the newest year that appears anywhere (visible text, schema dates, ISO
dates) and compare with the footer copyright.

- Copyright two or more years old **and** no fresher date anywhere → medium
  finding: the site reads as abandoned.
- Copyright old **but** fresh dates elsewhere → **not** a finding. Say so in
  the observations. This is the most common false positive in this area.
- Never recommend simply bumping the year. Recommend a review that produces a
  real date; a fake freshness signal is worse than an honest stale one.

### 3. Corroboration

Count links (page HTML and `sameAs`) to platforms the brand does not control:
Wikipedia, Wikidata, LinkedIn, Crunchbase, G2, Capterra, Trustpilot, BBB, Yelp,
Clutch, OpenCorporates, SEC/Companies House, GitHub.

- None at all → medium. Every claim rests on self-assertion, so it is easier to
  drop than to repeat.
- Lower this to low for institutional-authority domains (`.gov`, `.edu`,
  `.mil`, `.ac.uk` and similar): the domain itself already carries the trust
  this check measures.
- Exactly one → not a finding; an opportunity to broaden.

Recommend sector-appropriate platforms only: G2/Capterra for software,
BBB/Yelp/Google Business for local trades, registries for regulated fields.
Generic advice to "get on review sites" is noise.

### 4. Conflict checking — use search if you have it

Spend **1–2 web searches**, no more, on the brand's key facts (legal name,
headline claim, headquarters, founding year, pricing model).

- If an independent page states something that contradicts the site, that is a
  **high-value finding with direct evidence** — quote both sources and both
  URLs. Conflicting facts are a leading cause of an assistant describing a
  brand wrongly or hedging instead of citing.
- If sources agree, record it as a verified strength.
- If you have no search tool, put the conflict check in `not_verified` and say
  it needs search. Do not guess.

### 5. Judgement rules — apply to every check above

- A page with no date is not automatically stale — it is undated. Say the
  accurate thing.
- Do not infer abandonment from design or from a lack of a blog.
- Recency matters differently by content type: pricing, security posture and
  product capability decay fast; a founding story does not. Weight severity by
  what the page claims.

## Output

Returns one JSON object to the orchestrator:

```json
{
  "skill": "freshness-corroboration",
  "findings": [ ... ],
  "not_verified": [ ... ],
  "opportunities": [ ... ],
  "observations": { ... }
}
```

- `findings[]` — detected defects. Each carries `title`, `severity`,
  `confidence`, `category`, `mechanism`, `evidence` (which date signals were
  looked for and on which pages, the years found, the platforms checked),
  `affected_pages[]`, `root_cause`, `check`, and `suggested_action`.
- `opportunities[]` — proactive suggestions such as broadening corroboration
  beyond a single platform. This is the field the marketplace template calls
  *proactive actions*.
- `not_verified[]` — checks that could not be completed; always includes
  `claim_conflict_check` when no web search was performed.
- `observations{}` — pages analyzed, which date-signal kinds were found, the
  newest year seen, the copyright year, a stale-copyright note when fresher
  dates exist elsewhere, the corroboration platforms found, and a language note
  when non-English pages made text matching low confidence.

The orchestrator merges this into the final report. Report undated content as
undated, never as stale.
