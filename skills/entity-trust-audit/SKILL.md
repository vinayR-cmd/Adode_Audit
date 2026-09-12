---
name: entity-trust-audit
description: Check whether an AI assistant can tell WHO a site belongs to and distinguish that brand from other entities with the same name — schema.org JSON-LD presence, validity and sitewide coverage, Organization/LocalBusiness/WebSite identity markup, sameAs anchoring to Wikidata, LinkedIn, Crunchbase or industry registries, and signs that the brand name is contested. Use this when auditing why an AI assistant describes a brand vaguely, confuses it with a different company of the same name, attributes its work to someone else, or cites the site without naming the brand. Read-only; never modifies the site.
license: MIT
compatibility: ">=1.0"
allowed-tools: Read, Bash, WebFetch, WebSearch
metadata:
  version: "1.0.0"
  category: audit
  funnel_stage: attribute
---

# Entity & trust audit

Stage 4 of the funnel: **attribute**. Retrieval found the text. Does the
assistant know whose text it is, and which "Atlas" / "Delta" / "Arc" this is?

## When to use

Use this when content is reaching assistants and being read, but the *identity*
attached to it is wrong, vague or missing. Concretely:

- "The assistant describes us vaguely — it clearly doesn't know who we are."
- "It confuses us with a different company that has the same name."
- "It attributes our research / product / claim to someone else."
- "It cites our page but never names the brand."
- A schema.org / structured-data review aimed at AI citability rather than
  search rich results.
- "Should we claim a Wikidata item?" — the disambiguation question.
- As stage 4 of a full audit driven by `audit-orchestrator`.

Use `freshness-corroboration` instead when the question is whether claims can be
*dated* or corroborated on third-party sites; use `content-extractability` when
the text itself isn't quotable. This skill is specifically about identity
resolution: who published this, and is that identity unambiguous.

## Inputs

Either of:

- **A crawl bundle** (preferred) — `--bundle bundle.json`, the shared crawl, so
  schema coverage is measured across the same pages the other skills analyzed.
- **A URL** — `--url https://example.com` for standalone use.

```bash
python scripts/analyze.py --bundle bundle.json
python scripts/analyze.py --url https://example.com
```

From each sampled page this skill reads: every
`<script type="application/ld+json">` block, microdata `itemtype` attributes,
`og:site_name` and `<title>`, and all outbound links (to spot identity profiles
linked in the footer but missing from `sameAs`).

**Optional but decisive: a web search tool.** Name ambiguity cannot be settled
from the site alone — see step 4. Without search, that check is emitted as an
opportunity plus a `not_verified` entry, never as a finding.

Rubric: `references/checks.md`.

## Procedure

### 1. Structured data: present, valid, covering

- **Present?** Collect every `<script type="application/ld+json">` block, plus
  microdata `itemtype` as a fallback. None anywhere in the sample → high.
- **Valid?** Parse each block. Present-but-broken is *worse* than absent: the
  site pays the authoring cost and gets nothing, silently. Quote the parser
  error and the page.
- **Covering?** Compute the share of sampled pages carrying markup. Partial
  coverage is usually one template missing the include — that is **one**
  finding naming the affected pages, not one per page.

Handle `@graph` and arrays. A site using microdata rather than JSON-LD is not
defective; note the format and judge the content.

### 2. Identity, not just page types

`Article`, `Product`, `FAQPage`, `WebPage` describe *content*. None of them says
who published it. Look specifically for an identity node — `Organization`,
`Corporation`, `LocalBusiness`, `NGO`, `EducationalOrganization`,
`GovernmentOrganization`, `Person` — with `name`, `url`, `logo`, `description`,
and referenced as `publisher`/`provider` from the page-level schema.

Recognise **subtypes**, not just the bare type names: `NewsMediaOrganization`,
`Dentist`, `AutoRepair` and dozens of others are Organization- or
LocalBusiness-class identity nodes. Anything ending in `Organization` or
`Business` counts. `GovernmentService` and similar do **not** — a service a body
offers is not the body itself.

Its absence is a high finding: there is no entity for reputation, citations or
corroboration to attach to.

### 3. sameAs — the join to the identity graph

`sameAs` is the explicit statement "this site is that entity". Check what it
points at:

- **Identity graphs and registries** (Wikidata, Wikipedia, LinkedIn company,
  Crunchbase, OpenCorporates, SEC/Companies House, ORCID/ISNI, G2/Capterra/BBB
  where the sector fits) — these resolve a name to an entity.
- **Social profiles only** (X, Instagram, Facebook, TikTok) — self-asserted and
  weakly linked; better than nothing, worth a low finding suggesting stronger
  anchors.
- **Nothing** on an existing Organization node — medium finding. Check the page
  HTML first: many sites link their LinkedIn in the footer but omit it from
  `sameAs`, which is a five-minute fix worth naming precisely.

### 4. Name ambiguity — do not assert this from the site alone

A short or dictionary-word brand name is a *risk indicator*, never a finding on
its own. A script cannot tell whether "Linear" or "GOV.UK" is actually
contested, and guessing produces exactly the kind of false positive that makes
a report untrustworthy.

Procedure:

1. Derive the brand name (identity schema `name` → `og:site_name` → title
   segment → domain).
2. If you have **web search**: search the bare name. If the brand dominates the
   first page of results, there is no ambiguity problem — say so and move on.
   If other entities dominate, *now* you have evidence: cite the competing
   entities in the finding and set severity by how thoroughly they crowd it out.
3. If you have **no web search**: emit it as an *opportunity* plus a
   `not_verified` entry saying the collision was not confirmed. The bundled
   script does exactly this — never upgrade it to a finding without evidence.

Disambiguation that already exists (sameAs to Wikidata/LinkedIn, a consistent
qualified name in prose) cancels this concern; check for it before raising it.

### 5. What not to flag

- A missing *specific* schema type (no `FAQPage`, no `Review`) is not a defect.
  Schema is a means; the mechanism is identity resolution.
- Rich-result eligibility is a search-feature question, not an AI-citation one.
  Don't smuggle SEO checklist items in here.
- A brand with no Wikipedia article is not defective. Wikidata is claimable;
  Wikipedia has notability requirements you cannot promise.

## Output

Returns one JSON object to the orchestrator:

```json
{
  "skill": "entity-trust-audit",
  "findings": [ ... ],
  "not_verified": [ ... ],
  "opportunities": [ ... ],
  "observations": { ... }
}
```

- `findings[]` — detected defects. Each carries `title`, `severity`,
  `confidence`, `category`, `mechanism`, `evidence` (the parsed `@type` values
  found, the coverage fraction, the parser error, the pages), `affected_pages[]`,
  `root_cause`, `check`, and `suggested_action`.
- `opportunities[]` — proactive suggestions: completing an Organization node,
  anchoring a collision-prone name. This is the field the marketplace template
  calls *proactive actions*. **The name-ambiguity check lands here, not in
  `findings`, unless a web search confirmed the collision.**
- `not_verified[]` — checks that could not be completed, with reasons; always
  includes `name_ambiguity` when search was unavailable.
- `observations{}` — the JSON-LD `@type` values found, pages with JSON-LD vs
  microdata, identity types found, `sameAs` values, authority profile links
  spotted in page HTML, brand-name candidates.

The orchestrator merges this into the final report. Never emit an ambiguity
finding on heuristics alone.
