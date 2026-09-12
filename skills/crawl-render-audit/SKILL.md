---
name: crawl-render-audit
description: Check whether an AI crawler can reach and read a site at all — robots.txt rules naming AI bots (GPTBot, OAI-SearchBot, PerplexityBot, ClaudeBot, Google-Extended, CCBot and others), sitemap presence and coverage, HTTP status and redirect chains on sampled pages, noindex and canonical directives, and whether the facts exist in the initial HTML or only after JavaScript renders. Use this when auditing why AI assistants can't find or fetch a site, when diagnosing crawlability, indexing hygiene, bot blocking, WAF/anti-bot interference, or suspected client-side-rendering invisibility. Read-only GET requests; never modifies the site.
license: MIT
compatibility: ">=1.0"
allowed-tools: Read, Bash, WebFetch
metadata:
  version: "1.0.0"
  category: audit
  funnel_stage: reach-and-read
---

# Crawl & render audit

Stage 1–2 of the funnel: **let in → read**. If a fetcher is blocked or gets a
shell with no content, nothing downstream can compensate. Findings here are the
ones that outrank everything else.

## When to use

Use this whenever the question is whether an AI crawler can get in and get
anything back. Concretely:

- "Is robots.txt blocking GPTBot / PerplexityBot / ClaudeBot?"
- "AI assistants don't seem to see our site at all" — the reach diagnosis.
- Crawlability or indexing-hygiene review: HTTP errors, redirect chains,
  `noindex` left in production, canonicals pointing off-domain.
- Suspected WAF / anti-bot interference — Cloudflare challenges, empty 403s.
- Suspected client-side-rendering invisibility: "our content is there in the
  browser, so why can't a fetcher read it?"
- As stage 1–2 of a full audit driven by `audit-orchestrator`.

Reach for a different skill when the site is demonstrably fetchable and the
question is about the *quality* of what comes back — that is
`content-extractability` (is it quotable) or `entity-trust-audit` (whose is it).

## Inputs

Either of:

- **A crawl bundle** (preferred) — the shared JSON produced by the
  orchestrator's one polite crawl, passed as `--bundle bundle.json`. Using the
  bundle means every concern skill reasons about the *same* observed pages, and
  the site is fetched once rather than five times.
- **A URL** — `--url https://example.com`, for standalone use. The script does
  its own small bounded crawl in that case.

```bash
python scripts/analyze.py --url https://example.com      # standalone
python scripts/analyze.py --bundle bundle.json           # shared crawl (preferred)
```

The bundle carries: the parsed robots.txt model, the sitemap inventory, and the
sampled pages with their raw bytes, final status, headers, redirect chain,
content-type and byte size. Everything this skill judges comes from there.

See `references/checks.md` for the per-check rubric and severity anchors.

## Procedure

Run the helper for the mechanical parts, then judge the ambiguous ones yourself.

### 1. robots.txt — who is allowed in

Fetch `/robots.txt`. Parse groups properly (most specific matching user-agent
wins; `Allow` overrides a shorter `Disallow`).

Report separately:

- **Named AI bots with `Disallow: /`** — critical. Say *which* bots. The
  distinction matters to the owner: training crawlers (`GPTBot`, `CCBot`,
  `Google-Extended`, `Applebot-Extended`, `Bytespider`, `anthropic-ai`) versus
  answer-time fetchers (`OAI-SearchBot`, `ChatGPT-User`, `PerplexityBot`,
  `Perplexity-User`, `Claude-SearchBot`, `ClaudeBot`). Blocking the second group
  removes the brand from live answers today; blocking the first is a licensing
  decision that may be deliberate. Report the fact and the consequence — do not
  assume it was a mistake.
- **`User-agent: * / Disallow: /`** — critical, blocks everything compliant.
- **Path-level rules** hiding substantive sections — note them with the paths.
- **No robots.txt at all** — this is *not* a defect. Nothing is blocked.

If robots.txt disallows *your* fetch: respect it, don't work around it, and
report the block as a finding with the rule that caused it.

### 2. Sitemap

Check `Sitemap:` directives, then `/sitemap.xml`. Follow a sitemap index one
level, capped. Absence alone is an **opportunity, not a defect** — sites are
crawled by links too. It becomes a finding when sampled, internally-linked
pages are systematically missing from a sitemap that does exist.

### 3. Page sample hygiene

For each sampled page record: final status, redirect chain (break loops at 5
hops), content-type, byte size.

- 5xx on linked pages → high. 4xx → medium. Both are findings about those
  pages; the audit continues past them.
- Redirect loop → high. Chains of 3+ hops → low.
- Cross-domain redirect → record it, and do **not** count the destination as
  same-site for link analysis.
- Non-HTML at the entry URL (PDF/JSON/image) → high, with the content-type in
  evidence; do not attempt to parse it as HTML.

### 4. Indexing directives

- `noindex` via meta robots or `X-Robots-Tag` → critical on the entry page,
  high elsewhere. Mechanism: search indexes are the retrieval layer several
  assistants query before citing.
- Canonical pointing to another domain → high (credit and citation go there).
- Canonical pointing to a different same-site URL is normal; only flag it when
  it contradicts the site's own linking (e.g. every page canonicalises to the
  homepage).

### 5. Static vs rendered — the false-positive trap

**A framework marker is not a defect.** Most modern sites are React/Next/Nuxt
and ship perfectly good HTML.

Flag "content missing from the initial HTML" on either of two shapes.

**Shape A — recognised framework shell.** All of:

1. static visible text under ~120 words, **and**
2. an app-shell marker in the initial HTML, **and**
3. at least three corroborating signals total (few/no headings, very few links,
   many external scripts, embedded-state blob), **and**
4. you have not confirmed the opposite with a renderer.

**Shape B — large empty shell, no recognised marker.** A marker whitelist only
recognises frameworks it has heard of. All of:

1. document larger than ~20 KB, **and**
2. zero internal links, **and**
3. near-zero visible text (≤10 words), **and**
4. several `<script src>` tags (≥3, counting relative paths — a client-rendered
   site usually loads its bundle from its own origin).

`class="nojs"` and `<noscript>` blocks corroborate Shape B but are **not
required**: a site can client-render without either. A large document that
renders nothing is client-side rendering, not an empty site — this shape exists
so such a site is never reported as parked or under construction.

If you have a rendering/browser tool: diff initial HTML against the rendered
DOM and report the *specific facts* present only after rendering. That evidence
replaces the heuristic and raises confidence. If you have no renderer, mark the
finding `confidence: medium` and add a `not_verified` note saying so.

### 6. Distinguish blocking from breakage

A bot challenge, CAPTCHA page, or a 403 with a near-empty body is **not**
evidence of a rendering defect and **not** evidence the site is empty. Report:
"could not verify — likely blocked by anti-bot protection", plus a medium
finding that AI fetchers arriving as non-browser clients may hit the same wall.
Phrase it as risk: your generic user-agent is not proof about named AI agents.

### 7. Negligible content

If the entry page returns 200 with almost no text and almost no links, **and it
is genuinely small** (not the large-empty-shell shape in step 5), and the JS
heuristic did not fire, report it plainly: the site is parked, empty or under
construction. Don't redistribute that into unrelated categories.

### 8. Robustness — catch, record, continue

Catch every failure, record it, continue: DNS failure, timeout (retry once,
then `not_verified` for that check only), 429 (back off, honour `Retry-After`),
malformed HTML (parse defensively, never raise), oversized pages (cap bytes
read), unknown encodings (charset from header, then `<meta charset>`, then
utf-8 with replacement), login walls (`not_verified`, never a penalty).

## Output

Returns one JSON object to the orchestrator:

```json
{
  "skill": "crawl-render-audit",
  "findings": [ ... ],
  "not_verified": [ ... ],
  "opportunities": [ ... ],
  "observations": { ... }
}
```

- `findings[]` — detected defects. Each carries `title`, `severity`,
  `confidence`, `category`, `mechanism`, `evidence` (URL + status/count/
  snippet), `affected_pages[]`, `root_cause` (the orchestrator's dedupe key),
  `check`, and `suggested_action`.
- `opportunities[]` — proactive suggestions, never dressed as defects. This is
  the field the marketplace template calls *proactive actions*.
- `not_verified[]` — checks that could not be completed, each with a reason.
- `observations{}` — context that is not a finding (e.g. "no robots.txt —
  nothing blocked, which is fine", per-bot path rules, cross-domain redirects).

The orchestrator merges this into the final report, capping severity by
confidence and deduplicating on `root_cause`. Emit no finding without evidence.
