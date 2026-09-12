# brand-ai-readiness-audit

An Agent Skill Marketplace that audits a website, **read-only**, for two
coupled questions:

1. **AI-discoverability** — why do AI assistants (ChatGPT, Gemini, Perplexity,
   Claude) fail to find, cite, or correctly represent this brand?
2. **On-site engagement** — the visitor those assistants *do* send arrives
   deep, cold and impatient. Why don't they stay?

Output: **one structured JSON report** with evidence-backed findings, honest
unknowns, and separate improvement opportunities. No score, no grade.

---

## The model behind it

Every check maps to a stage in one funnel. Earlier stages dominate later ones —
a blocked crawler makes content quality irrelevant.

```
   reach  ──▶  read  ──▶  extract  ──▶  attribute/trust  ──▶  engage
     │           │           │                │                  │
crawl-render-audit      content-        entity-trust-      engagement-
                        extractability   audit +            audit
                                         freshness-
                                         corroboration
```

## The six skills

| Skill | Stage | What it establishes |
|---|---|---|
| **audit-orchestrator** *(entrypoint)* | — | Normalizes the URL, sets the crawl boundary, runs the other five over one shared page sample, dedupes by root cause, applies the severity rubric, emits the report |
| **crawl-render-audit** | reach / read | robots.txt rules naming AI crawlers, sitemap coverage, HTTP status and redirect chains, `noindex`/canonical directives, anti-bot interference, static-vs-rendered content |
| **content-extractability** | extract | Depth on key pages, concrete figures vs. adjectives, outbound sourcing, answer-first structure, facts locked in images or PDFs |
| **entity-trust-audit** | attribute | JSON-LD presence/validity/coverage, `Organization` identity markup, `sameAs` anchoring, brand-name ambiguity |
| **freshness-corroboration** | trust | Machine-readable and visible dates, stale-year detection, independent corroboration, claim conflicts |
| **engagement-audit** | engage | Deep-linkability, landing-view clarity, navigation and search, mobile viewport, payload weight |

Each folder is independently valid per the agentskills.io SKILL.md spec — YAML
frontmatter with `name` and a trigger-shaped `description`, plus
`scripts/` and `references/`.

## How the entrypoint composes the others

`audit-orchestrator` performs **one polite crawl** and hands every concern
skill the *same bundle* — the same fetched bytes for the same URLs. That is
what makes cross-skill findings refer to the same observed pages, and what
makes root-cause deduplication possible (one template missing schema on ten
pages is one finding, not ten).

```
URL ─▶ normalize ─▶ robots.txt + sitemap ─▶ bounded sample (8–12 pages)
        │
        └─▶ bundle ─┬─▶ crawl-render-audit      ─┐
                    ├─▶ content-extractability   │
                    ├─▶ entity-trust-audit       ├─▶ cap severity by confidence
                    ├─▶ freshness-corroboration  │   dedupe by root cause
                    └─▶ engagement-audit        ─┘   sort, assign F-001…
                                                        │
                                                        ▼
                                                  one JSON report
```

## Running it

The skills are written to be executed **by an agent** — SKILL.md is a procedure
for the agent, which can use its own fetch, search and rendering tools. The
bundled Python scripts are an optional deterministic fast path for the
mechanical parts.

```bash
cd skills/audit-orchestrator/scripts

# full audit
python run_audit.py --url https://example.com --max-pages 10 --out report.json

# keep the raw crawl so you can re-analyze without re-fetching
python run_audit.py --url https://example.com --save-bundle bundle.json --out report.json
python run_audit.py --bundle bundle.json

# one concern skill on its own
cd ../../content-extractability/scripts
python analyze.py --url https://example.com
```

Python 3.8+, **standard library only** — no `pip install`, no model weights,
no third-party services.

## Report shape

See `skills/audit-orchestrator/references/report-schema.md`. Minimum:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-09-10T11:02:45Z",
  "summary": {"total_findings": 5, "critical": 0, "high": 1, "medium": 4},
  "findings": [
    {"id": "F-001", "title": "...", "severity": "high",
     "evidence": "URL + status/count/snippet",
     "suggested_action": {"summary": "...", "priority": "high"}}
  ]
}
```

Plus `confidence`, `category`, `mechanism`, `not_verified`, `opportunities`,
`limitations`, `skills_run`, `pages_audited`, `crawl`.

## What keeps it from producing garbage

The full rules are in
`skills/audit-orchestrator/references/decision-principles.md`:

- **Mechanism before convention** — a missing meta description is not a defect;
  a blocked crawler is. Every finding names the causal path.
- **Evidence before severity** — every finding carries a URL plus a concrete
  observation, and confidence caps severity (low confidence can never be
  `critical`).
- **Root cause before symptom** — sitewide template issues merge into one
  finding.
- **No causal overclaim** — findings state risk ("materially lowers the odds
  of being quoted for …"), never "this is why ChatGPT ignores you", unless an
  assistant's actual output was observed.
- **No universal score** — severity-bucketed counts and ranked findings only.
- **Unknowns stay unknown** — blocked, timed out, login-walled or ambiguous
  checks land in `not_verified`, never in `findings`.

## Calibration evidence

Four of the six skills carry field-calibration evidence in their rubrics, and
two remain mechanism-only. **`freshness-corroboration`** is the only skill
where evidence actually changed a severity: its `freshness_signal` check was
raised medium → high after clearing all three bars across three consecutive
rounds (+27 to +31% pooled, +30 to +33% sector-average, positive in 4–5 of 5–6
sectors, with the B2B sales counter-example recorded honestly alongside it).
**`entity-trust-audit`** carries two notes and no severity change:
`schema_valid` moved from no-separation to weak (+5% pooled, 4/6 sectors,
short of the bar), and `sameas` accumulated four rounds of consistently
negative evidence plus a 20-site redesign pilot that failed in three variants —
with the diagnosis recorded that mention-counting saturates and a
fundamentally different mechanism is needed. **`crawl-render-audit`** carries
ground-truth accuracy for two checks (`robots_ai_bots` 3/4, with the
woodenstreet case proving it separates scraper-blocking from
AI-crawler-blocking; `raw_html_readable` 3/3) plus the note that its 0%
citation delta is population saturation, not a defect. **`engagement-audit`**
documents a real false positive found and fixed in `deep_linkable` — flat
multi-page sites scoring identically to zero-page sites — with ground-truth
accuracy improving 67% → 89%, framed explicitly as a correctness win rather
than a discrimination win, no severity change. The two skills that remain
**mechanism-only, with no field evidence either way, are
`content-extractability` and `audit-orchestrator`** — the former's checks
(depth, concrete figures, sourcing, answer position, media-locked facts) were
never put through the calibration harness, and the latter owns composition and
severity rules rather than site-level checks, so there is nothing in it to
calibrate against cited/omitted pairs.

**Caveat on all of the above:** every number comes from a single 68-site sample
across six sectors, with 14 rows lost to anti-bot blocking (403/402/challenge
pages), and no sector has more than 7 usable sites per side. The two skills
without evidence are not thereby weaker — they are simply untested.

The per-check notes live in each skill's `references/checks.md`, under a
"Field calibration log" heading. The calibration harness itself is a separate
research aid and is not part of this marketplace.

## Robustness

Every one of these is handled explicitly, recorded honestly, and never aborts
the run: DNS failure, connection refused, timeouts (one retry, then
`not_verified` for that check only), 4xx/5xx pages, redirect loops and long
chains, robots.txt blocking the auditor itself, Cloudflare/Akamai bot
challenges and suspicious empty error responses, non-HTML responses, malformed
HTML, oversized pages (3 MB read cap), cross-domain redirects, unknown or mixed
encodings, HTTP 429 and `Crawl-delay`, non-English sites, legitimate SPAs,
login walls, the 5-minute time budget, and empty or parked domains.

## Safety

Read-only HTTP GET only. Never modifies a live site, submits a form, logs in,
creates an account, or performs any authenticated or destructive action.
robots.txt is respected for the auditor's own fetches — and a block is reported
as evidence rather than worked around.

## Validation

```bash
# if the agentskills reference CLI is installed
skills-ref validate skills/audit-orchestrator
skills-ref validate skills/crawl-render-audit
skills-ref validate skills/content-extractability
skills-ref validate skills/entity-trust-audit
skills-ref validate skills/freshness-corroboration
skills-ref validate skills/engagement-audit

# always available: manifest + frontmatter + script sanity
python validate.py
```

`validate.py` checks the manifest is well-formed with exactly one entrypoint,
every listed skill folder exists with a SKILL.md whose `name` matches its
folder, required frontmatter is present, and every bundled script compiles.

## Layout

```
brand-ai-readiness-audit/
  marketplace.json
  README.md
  validate.py
  skills/
    audit-orchestrator/        SKILL.md  scripts/{common,crawl,run_audit}.py  references/{checks,report-schema,severity,decision-principles}.md
    crawl-render-audit/        SKILL.md  scripts/{analyze,common}.py          references/checks.md
    content-extractability/    SKILL.md  scripts/{analyze,common}.py          references/checks.md
    entity-trust-audit/        SKILL.md  scripts/{analyze,common}.py          references/checks.md
    freshness-corroboration/   SKILL.md  scripts/{analyze,common}.py          references/checks.md
    engagement-audit/          SKILL.md  scripts/{analyze,common}.py          references/checks.md
```

`common.py` is vendored identically into each skill so every folder runs
standalone. In the four calibrated skills, `references/checks.md` also carries a **Field calibration log** section (see *Calibration evidence* above).
