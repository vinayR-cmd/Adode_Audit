---
name: audit-orchestrator
description: Audit a website end-to-end for why AI assistants (ChatGPT, Gemini, Perplexity, Claude) fail to find, cite or correctly represent the brand, and why arriving visitors don't stay — then emit one structured JSON report. Use this when given a website URL and asked for an AI-readiness, AI-visibility, AI-discoverability, GEO/AEO, LLM-citability or on-site engagement audit, or when asked "why don't AI assistants mention this brand". This is the entrypoint skill: it runs the crawl boundary, composes crawl-render-audit, content-extractability, entity-trust-audit, freshness-corroboration and engagement-audit over one shared page sample, deduplicates by root cause, and produces the final report. Read-only — it never modifies, submits to, or logs into the audited site.
license: MIT
compatibility: ">=1.0"
allowed-tools: Read, Bash, WebFetch, WebSearch
metadata:
  version: "1.0.0"
  entrypoint: true
  category: audit
  emits: json-report
---

# Audit orchestrator

You are auditing one website, read-only, for two coupled questions:

1. **AI-discoverability** — can an AI assistant reach, read, extract, attribute
   and trust this site well enough to cite it?
2. **On-site engagement** — a visitor who did arrive (often deep, cold, sent by
   an assistant) — can they orient, find the fact, and act?

You produce **one JSON report**. Not a score, not a grade — evidenced findings
with mechanisms and actions.

## When to use

This is the entrypoint. Use it whenever someone hands you a website and asks
why AI assistants aren't representing it properly, or wants the engagement side
of that same problem examined. Concretely, invoke it when the request is any of:

- "Run an AI-readiness / AI-visibility / AI-discoverability audit on this site."
- "Why doesn't ChatGPT / Gemini / Perplexity / Claude mention us?"
- "Why does the assistant describe us wrongly, or cite a competitor instead?"
- A GEO (generative engine optimization) or AEO (answer engine optimization)
  review, or an "LLM-citability" assessment.
- "We get traffic from AI answers but nobody stays" — the engagement half.
- Any request for a structured, evidenced report across all five concerns
  rather than one narrow check.

Use a **concern skill directly instead** when the question is already scoped to
one stage — for example "is robots.txt blocking GPTBot?" (`crawl-render-audit`)
or "is our schema.org markup any good?" (`entity-trust-audit`). Come here when
the answer needs all five, composed and deduplicated.

Do **not** use this to modify a site, to test a login or checkout flow, or to
produce a single numeric score — none of those are things this skill does.

## Inputs

**Required: one website URL or bare domain.** All of these are accepted and
normalized to the same thing:

- `example.com`
- `www.example.com`
- `https://example.com`
- `https://example.com/some/deep/page` — a deep URL is a legitimate audit
  target, not an error. Keep the path; audit what you were pointed at.

Optional inputs you may accept or set yourself:

| Input | Default | Meaning |
|---|---|---|
| page sample size | 10 | How many same-site pages to fetch (8–12 is the sane band) |
| per-request timeout | 8–12 s | One retry with backoff, then give up on that page |
| total time budget | 5 minutes | Whole audit, including all five concern skills |
| saved crawl bundle | none | A previously saved `bundle.json` to re-analyze without re-fetching |

Via the bundled helper these map to `--url`, `--max-pages`, `--timeout`,
`--budget`, and `--bundle` / `--save-bundle` respectively.

**Not accepted:** non-http(s) schemes (`ftp://`, `file://`) — reject them with a
plain message rather than guessing. Credentials, cookies or session tokens —
this skill never authenticates.

## Procedure

Read `references/decision-principles.md` before you judge anything. It is short
and it governs every call you make below.

### Step 1 — Normalize the input

- Accept `example.com`, `https://example.com/path`, with or without `www`.
- Add `https://` if no scheme; strip the fragment; keep the path if given (a
  deep URL is a legitimate audit target, not an error).
- Reject non-http(s) schemes with a plain message; do not guess.
- Record the normalized URL as `site` in the report.

### Step 2 — Establish crawl boundaries before fetching anything

- Fetch `/robots.txt` first. Parse it for: wildcard rules, rules naming AI
  crawlers, `Crawl-delay`, and `Sitemap:` directives.
- **Respect it for your own fetches.** If a path is disallowed for a generic
  user-agent, do not fetch it. Record the block as evidence — an AI-crawler
  block is itself one of the most important findings this audit can make.
- Fetch the sitemap(s) if declared, else try `/sitemap.xml`. A sitemap index is
  followed one level deep, capped.
- Set the sample: **8–12 pages, same-site only**, chosen for diversity (nav
  links first, then other internal links, then sitemap entries; spread across
  distinct top-level path prefixes so you don't sample eight blog posts).
- Set the budget: per-request timeout 8–12s, one retry with backoff, whole
  audit inside **5 minutes**. Track elapsed time; if the budget runs short,
  stop sampling and report from what you have — never return nothing.
- **Honor a declared `Crawl-delay` in full — never truncate it.** A site that
  asks for 30 seconds between requests gets 30 seconds, not a faster,
  undisclosed rate. Above a **10-second planning ceiling**, protect the time
  budget by fetching **fewer pages instead of waiting less** — reduce the
  sample size so `(sample size × delay)` still fits inside the 5-minute
  budget, and disclose the exact reduction (declared delay, honored delay,
  original vs. reduced sample size) in `crawl.notes`. At or below the ceiling
  the default sample size already fits, so no reduction is needed. This
  reduction is proactive, decided before sampling starts — never a device for
  quietly fetching faster than requested.

### Step 3 — Fast path, then judgement

Run the bundled helper to do the mechanical work in one polite crawl:

```bash
python scripts/run_audit.py --url <URL> --max-pages 10 --out report.json
# or, to keep the raw crawl for re-analysis without re-fetching:
python scripts/run_audit.py --url <URL> --save-bundle bundle.json --out report.json
```

`scripts/run_audit.py` crawls once and calls each concern skill's
`scripts/analyze.py` on the same bundle, so all five reason about the same
observed pages. Stdlib only, no installs.

**The script is a helper, not the audit.** After it runs you must:

- Confirm or overturn anything it marked `confidence: medium` or `low`.
- Do what it structurally cannot: if you have a **rendering/browser tool**, diff
  the initial HTML against the rendered DOM for the flagged pages and correct
  the static-render finding accordingly. If you have **web search**, spend 1–2
  searches on brand-name ambiguity and third-party corroboration (see
  `freshness-corroboration` and `entity-trust-audit`).
- Drop any finding whose evidence you cannot state concretely.

If the script cannot run in your environment, execute each concern skill's
SKILL.md manually with your own fetch tool — they are written to be run by an
agent, not only by the script.

### Step 4 — Collect findings with evidence only

Every finding carries a URL plus a status, count, or extracted snippet. A check
you could not complete goes in `not_verified` with the reason — blocked, timed
out, non-HTML, login-walled, ambiguous. **An unknown is never a defect.** The
distinctions that matter most:

| Observed | Correct conclusion |
|---|---|
| DNS/connection failure | `not_verified` + reachability finding — **not** "no content" |
| Bot challenge / suspicious empty 403 | "could not verify — likely anti-bot" — **not** a JS-rendering defect |
| Login wall | `not_verified` — never penalise content you shouldn't see |
| 4xx/5xx on one page | a finding about *that page*; the run continues |
| Non-HTML content-type | note the type in evidence; don't parse it as HTML |
| Framework/SPA markers alone | nothing — see `crawl-render-audit` for the multi-signal bar |

### Step 5 — Deduplicate by root cause

Ten pages missing schema because one template omits it is **one** finding
listing ten affected pages — not ten findings. Merge on the shared cause, keep
the strongest severity, union the affected pages. Symptom-level duplicates make
a report look thorough and read as noise.

### Step 6 — Assign severity by rubric

Use `references/severity.md`. Severity is a function of **where the mechanism
sits in the funnel** (reach → read → extract → attribute/trust) and **how
strong your evidence is** — never of how commonly the issue is discussed. Weak
evidence caps severity: a low-confidence finding cannot be `critical`.

### Step 7 — Separate opportunities from defects

Proactive suggestions ("add FAQ-shaped headings", "claim a Wikidata item") go
in `opportunities` with a rationale and effort estimate. Never dress an
improvement idea as a detected defect; the distinction is what makes the
defects credible.

### Step 8 — Emit one JSON report

See **Output** below for the contract. State limitations plainly in the report:
bounded sample, no JS execution (if you had no renderer), one network vantage
point, one moment in time.

### Safety constraints — apply throughout every step

Read-only HTTP GET only. Never submit a form, log in, create an account, or
send anything that changes state on the audited site. Respect robots.txt, keep
the sample small, honour `Crawl-delay`, back off on 429.

## Output

**One JSON object**, conforming to `references/report-schema.md`. That file is
the authority on the full shape; the minimum contract is:

```json
{
  "site": "https://example.com",
  "audited_at": "2026-09-11T19:32:36Z",
  "summary": {"total_findings": 4, "critical": 0, "high": 2, "medium": 1, "low": 1},
  "findings": [
    {
      "id": "F-001",
      "title": "...",
      "severity": "critical|high|medium|low",
      "evidence": "concrete: URL, status, counts, extracted snippet",
      "suggested_action": {"summary": "...", "priority": "..."}
    }
  ]
}
```

Also emit these additive fields — they are what make the report auditable by
the person receiving it rather than merely believable:

- `confidence`, `category`, `mechanism`, `check`, `source_skill` on each finding
- `opportunities[]` — improvement ideas, kept separate from detected defects
- `not_verified[]` — every check you could not complete, with the reason
- `limitations[]`, `skills_run[]`, `pages_audited[]`, `crawl`

`id` values are assigned **after** sorting by severity, so `F-001` is always the
most important thing found. Emit exactly one JSON object — not one per skill,
and not JSON wrapped in prose commentary. Never emit an overall score or grade.
