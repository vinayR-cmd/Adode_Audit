---
name: content-extractability
description: Check whether a page's facts are actually extractable and quotable by an AI assistant — content depth on key pages, concrete statistics instead of vague claims, outbound citations to independent sources, whether the page opens with a direct quotable answer, and facts locked inside images without alt text or inside PDFs instead of HTML text. Use this when auditing why an AI assistant reaches a site but still won't quote or cite it, when reviewing content for AI answer-engine visibility (GEO/AEO), or when key facts seem invisible to LLMs despite the pages being crawlable. Read-only; never modifies the site.
license: MIT
compatibility: ">=1.0"
allowed-tools: Read, Bash, WebFetch
metadata:
  version: "1.0.0"
  category: audit
  funnel_stage: extract
---

# Content extractability

Stage 3 of the funnel: **extract**. The fetcher got the HTML. Is there anything
in it worth lifting into an answer?

## When to use

Use this when the site is demonstrably reachable — the crawler gets a 200 and
real HTML — but assistants still won't quote it. Concretely:

- "AI assistants can reach our pages but never cite them."
- Content review for AI answer-engine visibility (GEO / AEO): is this page
  shaped like something an assistant can lift a passage from?
- "Our key facts seem invisible to LLMs even though the pages are crawlable."
- Suspicion that facts are locked in images, charts or PDFs rather than text.
- "We rank fine but the assistant quotes a competitor's page instead."
- As stage 3 of a full audit driven by `audit-orchestrator`.

Use `crawl-render-audit` instead when the fetcher cannot get the HTML in the
first place — thin-looking content caused by blocking or client-side rendering
is a reach/read problem, not an extractability one, and this skill will say so
rather than guess.

## Inputs

Either of:

- **A crawl bundle** (preferred) — `--bundle bundle.json`, the shared crawl
  produced once by the orchestrator, so findings here refer to exactly the same
  pages the other concern skills saw.
- **A URL** — `--url https://example.com` for standalone use; the script runs
  its own small bounded crawl.

```bash
python scripts/analyze.py --bundle bundle.json      # shared crawl (preferred)
python scripts/analyze.py --url https://example.com # standalone
```

From each sampled page this skill reads: visible text (script/style/nav chrome
excluded), headings, links with their resolved targets, `<img>` attributes, and
the page's own URL. Pages that were blocked, errored or login-walled are
excluded from the analyzable sample by the bundle itself — they are `not_verified`,
not thin.

Rubric and thresholds: `references/checks.md`.

## Procedure

### 1. Depth on the pages that matter

Count visible text words per sampled page (exclude script/style/nav chrome).
Under ~200 words a page rarely contains a self-contained answer to anything.

Judge the *sample shape*, not a single page: a thin contact page is normal; a
site where most pages are thin is a finding. Report it as **one** finding
listing the affected pages — never one finding per thin page.

Note explicitly which pages *should* be citable (product, pricing, service,
"how it works", documentation) and whether those specifically are thin. That
distinction is more useful to the owner than a sitewide average.

### 2. Concrete figures vs. adjectives

Scan for percentages, currency amounts, magnitudes, durations, counts, dates.
A claim with a number is quotable and checkable; "industry-leading" is neither.

**Exclude navigation-style pages** (high link-to-word ratio, index/browse
pages) before concluding "no concrete facts" — a directory page is not supposed
to make claims. The bundled script uses a link-density guard for this; if you
are judging manually, apply the same rule.

### 3. Outbound citations

Count external links that point to independent, checkable sources — research,
standards bodies, government, press, review platforms. Social profiles do not
count as sourcing.

Zero across the sample is a medium finding: every claim rests on the brand's
own assertion, so it is easier to drop than to corroborate. One or two is fine;
do not manufacture a finding out of "could have more".

### 4. Answer-first structure

- Does each page have exactly one `h1` naming its subject in plain words?
- Do the opening lines state the answer, or do they open with a slogan?
- Are sections headed with the question a reader would actually ask?

Missing `h1` across most of the sample is a medium finding (structural cue for
what a passage answers). A page whose opening block has almost no text is a low
finding — real, but weaker than depth or sourcing.

### 5. Facts locked in media

- Images with no `alt` (ignore obvious icons/logos/spacers and
  `role="presentation"`): if pricing, specs or comparison tables live in an
  image, that fact does not exist for a text fetcher.
- PDF-heavy pages with thin HTML: the substance is in a format that gets
  fetched less, parsed less reliably, and cited less precisely.

Report the *fact loss*, not the accessibility violation — alt text matters here
because of what it makes extractable. (It matters for accessibility too; that's
a different audit.)

### 6. Judgement rules — apply to every check above

- Never conclude "no content" from a page you could not fetch, that was
  bot-blocked, or that sat behind a login. Those are `not_verified`.
- Do not penalise a language you cannot read. Word counts, digits, link
  structure and headings are language-independent — use those, and lower your
  confidence rather than inventing a defect from an English-only regex.
- Length is not quality. Do not recommend padding; recommend specificity.
- Every finding names the pages and the counts behind it.

## Output

Returns one JSON object to the orchestrator:

```json
{
  "skill": "content-extractability",
  "findings": [ ... ],
  "not_verified": [ ... ],
  "opportunities": [ ... ],
  "observations": { ... }
}
```

- `findings[]` — detected defects. Each carries `title`, `severity`,
  `confidence`, `category`, `mechanism`, `evidence` (page URLs plus the counts
  behind the claim), `affected_pages[]`, `root_cause`, `check`, and
  `suggested_action`.
- `opportunities[]` — proactive suggestions such as question-and-answer framing
  on high-intent headings. This is the field the marketplace template calls
  *proactive actions*; it is kept separate from `findings` so detected defects
  stay credible.
- `not_verified[]` — checks that could not be completed, with reasons.
- `observations{}` — supporting context: pages analyzed, median word count,
  per-page stat/source/image counts, thin pages that did not reach the
  finding threshold.

The orchestrator merges this into the final report. Every finding must carry
concrete evidence; drop any you cannot state that way.
