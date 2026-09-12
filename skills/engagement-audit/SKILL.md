---
name: engagement-audit
description: Check whether a visitor who arrives from an AI answer — deep, cold, with no session history — can orient and act, or bounces. Covers deep-linkability (do topics have their own stable URLs or does everything funnel to the homepage), whether the sought fact is visible in the landing view, navigation and on-site search availability, mobile viewport, and page payload weight. Use this when auditing on-site engagement, high bounce from AI or search referrals, "visitors arrive but don't stay", or landing-page effectiveness for assistant-referred traffic. Read-only; never submits forms, logs in, or modifies the site.
license: MIT
compatibility: ">=1.0"
allowed-tools: Read, Bash, WebFetch
metadata:
  version: "1.0.0"
  category: audit
  funnel_stage: engagement
---

# Engagement audit

The other half of the problem. Being cited is worth nothing if the click
bounces. The visitor an assistant sends is unlike a search visitor: they arrive
**mid-site, cold, with a specific question already formed**, and they have a
frictionless alternative — going back to the assistant.

## When to use

Use this when the traffic arrives but doesn't convert into attention.
Concretely:

- "We get referrals from AI answers but nobody stays."
- High bounce rate specifically from AI-assistant or search referrals.
- "Can an assistant even link to the right part of our site?" — the
  deep-linkability question.
- Landing-page effectiveness for cold, deep-arriving visitors.
- "Everything on our site is one long homepage with anchors — does that matter?"
- Mobile readability and page-weight questions for assistant-referred traffic.
- As the engagement stage of a full audit driven by `audit-orchestrator`.

Use the discoverability skills instead when the problem is upstream — nobody is
arriving at all. This skill assumes arrival and asks what happens next.

## Inputs

Either of:

- **A crawl bundle** (preferred) — `--bundle bundle.json`, the shared crawl, so
  engagement findings refer to the same pages as the discoverability ones.
- **A URL** — `--url https://example.com` for standalone use.

```bash
python scripts/analyze.py --bundle bundle.json
python scripts/analyze.py --url https://example.com
```

From each sampled page this skill reads: all links with their resolved targets
and path depths, headings, the opening text block, navigation markup
(`<nav>`, `<header>`, `role="navigation"`, nav-classed wrappers), search
inputs, the viewport meta tag, document byte size, and `<script src>` counts.
It also reads the sitemap URL count from the bundle to judge whether site size
warrants search.

**This skill never interacts with the site.** No forms, no logins, no carts —
see step 5 and the closing judgement rules.

Rubric: `references/checks.md`.

## Procedure

### 1. Deep-linkability

An assistant can only send someone to a URL. Check whether significant topics,
products and services have their own stable URLs, or whether the site is one
long homepage with `#anchor` sections.

Count **distinct internal destinations at path depth ≥ 1** — deduplicated, with
fragments and trailing slashes normalised away. Three or more is a pass.

- Mostly same-page anchors and almost no distinct internal URLs → high finding.
  Consequence: the assistant links the homepage, the visitor lands above what
  they asked about, and no section can be cited or ranked on its own.
- Few distinct internal destinations without the anchor pattern → medium.

**Depth ≥ 2 is recorded, not required.** A flat information architecture
(`/about`, `/services`, `/pricing` with no nesting) is a URL convention, not a
defect — those pages are perfectly deep-linkable. Report nesting as a
confidence flag (`nested` / `flat` / `no_internal_destinations`) alongside the
verdict, never as the gate. A nine-page law firm must not score the same as a
one-page brochure.

### 2. Does the landing view confirm the promise?

For each sampled page: is there an `h1`, and does the opening block contain
real text? A cold visitor is checking, in seconds, "is this the thing the
assistant told me about?" A page opening with a slogan and a hero image does
not answer that.

Report pages with no `h1` **and** a near-empty opening block. One or the other
alone is weaker — say so rather than inflating it.

### 3. Wayfinding: navigation and search

Count links inside navigation markup — and do not assume `<nav>`/`<header>`
are the only valid markers: `role="navigation"` and class-named wrappers
(`div class="site-header"`, `ul class="menu"`) are extremely common. Check for
a search input too (matching `type=search`, and search-ish `name`/`id`/
`placeholder`/`aria-label` values, in more languages than English).

Only report "no usable navigation" when the sparse nav markup is **corroborated
by a genuinely small set of distinct internal destinations**. A site with a
plain menu in an unconventional wrapper has navigation; flagging it is a false
positive.

On a large site (many sitemap URLs) with no search, raise search as an
opportunity, not a defect.

### 4. Mobile and weight

- No `<meta name="viewport">` on most sampled pages → medium. Mobile browsers
  fall back to desktop width and zoom out; most assistant referrals are mobile.
- HTML document of several MB, or one that hits the reader's byte cap → medium.
  The document is on the critical path; nothing renders until it lands.
- An unusually high count of blocking `<script src>` tags → low.

Do not claim a performance score you did not measure. You measured document
bytes and request counts; say that.

### 5. Context continuity — recommendation only

Whether the page picks up the intent the visitor arrived with (restating the
question it answers, offering the adjacent questions, letting them act without
returning to the homepage) is **runtime behaviour a static audit cannot
observe**.

Emit it as an `opportunity` with a `not_verified` entry. Never assert it as a
detected defect. If you have a browser tool and actually walked the flow, then
you have evidence and may report what you observed — cite what you did.

### 6. Judgement rules — apply to every check above

- Engagement findings are about the *cold deep-landing* visitor, not general UX
  taste. Don't drift into design critique.
- Never submit a form, log in, or trigger a purchase flow to test anything.
- Anything you infer rather than observe gets `confidence: low` and says why.

## Output

Returns one JSON object to the orchestrator:

```json
{
  "skill": "engagement-audit",
  "findings": [ ... ],
  "not_verified": [ ... ],
  "opportunities": [ ... ],
  "observations": { ... }
}
```

- `findings[]` — detected defects. Each carries `title`, `severity`,
  `confidence`, `category` (`engagement`), `mechanism` written from the cold
  deep-landing visitor's point of view, `evidence` (link and destination counts,
  byte sizes, script counts, the specific pages), `affected_pages[]`,
  `root_cause`, `check`, and `suggested_action`.
- `opportunities[]` — proactive suggestions, including **context continuity,
  which always lands here and never in `findings`**, and on-site search for
  large sites. This is the field the marketplace template calls *proactive
  actions*.
- `not_verified[]` — checks that could not be completed; always includes
  `context_continuity`, because static HTML cannot show runtime behaviour.
- `observations{}` — pages analyzed, distinct internal URLs from the entry page,
  anchor-only link count, navigation link count, whether site search was found.

The orchestrator merges this into the final report. Never report a runtime
behaviour you did not observe.
