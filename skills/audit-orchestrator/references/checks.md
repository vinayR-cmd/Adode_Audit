# Orchestration checklist

What the entrypoint owns, in order. Per-check rubrics live in each concern
skill's `references/checks.md`.

## Crawl boundary (owned here, not by the concern skills)

| Setting | Value | Why |
|---|---|---|
| Sample size | 8–12 pages | Enough for template-level conclusions inside the time budget |
| Scope | same registrable domain | A cross-domain redirect destination is *not* same-site |
| Per-request timeout | 8–12 s | One slow page must not consume the run |
| Retries | 1, with backoff | Then `not_verified` for that check only |
| Redirects | max 5, loops detected | Record the chain as evidence |
| Bytes per page | ~3 MB cap | One bloated page can't blow the budget |
| Politeness | ≥0.4 s between requests; honour `Crawl-delay` (capped ~5 s); back off on 429 `Retry-After` | Read-only auditing must not look like an attack |
| Total budget | 5 minutes | Stop sampling, still emit a report |

Page selection: nav links first, then other internal links, then sitemap
entries; spread across distinct top-level path prefixes; skip assets and
account/cart/login paths.

## Composition

All five concern skills receive **the same bundle** — the same fetched bytes
for the same URLs. This is what lets findings from different skills refer to
the same observed pages, and what makes root-cause dedupe possible.

| Skill | Stage | Owns |
|---|---|---|
| crawl-render-audit | reach / read | robots, sitemap, status, redirects, indexing directives, static-vs-rendered, blocking vs breakage |
| content-extractability | extract | depth, concrete facts, sourcing, answer position, media-locked facts |
| entity-trust-audit | attribute | schema validity/coverage, identity entity, sameAs, name ambiguity |
| freshness-corroboration | trust | dates (structural first), stale years, independent corroboration, claim conflicts |
| engagement-audit | engage | deep-linkability, landing clarity, wayfinding, mobile, payload, context continuity (opportunity only) |

## Merge rules

1. **Cap severity by confidence** (`severity.md`) before anything else.
2. **Dedupe by `root_cause`** — strongest severity wins, affected pages are
   unioned, evidence is concatenated.
3. **Sort** by severity, then confidence. Assign `F-001…` after sorting.
4. **Collect `not_verified`** from every skill plus the crawl itself. Never
   discard one because the report looks cleaner without it.
5. **Keep opportunities separate** from findings.

## Failure containment

- A concern skill that raises is recorded in `not_verified` with the exception
  text; the other four still run and the report still ships.
- If the time budget runs out mid-run, the remaining skills are recorded as
  skipped and the report is emitted from what was gathered.
- An invalid input URL produces a report with an empty `findings` array and a
  `not_verified` entry — never a stack trace.

## Self-check before emitting

- [ ] Exactly one JSON object, conforming to `report-schema.md`.
- [ ] Every finding has a URL plus a concrete observation in `evidence`.
- [ ] No finding restates another finding's root cause.
- [ ] No severity exceeds its confidence cap.
- [ ] No causal overclaim ("this is why ChatGPT ignores you").
- [ ] No overall score.
- [ ] Opportunities are in `opportunities`, unknowns in `not_verified`.
- [ ] `limitations` states the sample size, the lack of JS execution (if
      applicable), and the single vantage point.
