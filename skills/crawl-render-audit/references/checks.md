# crawl-render-audit — check rubric

| Check id | Signal | Fires when | Base severity | Confidence |
|---|---|---|---|---|
| `robots_ai_bots` | Named AI crawler group with `Disallow: /` | Any of GPTBot, OAI-SearchBot, ChatGPT-User, PerplexityBot, Perplexity-User, Google-Extended, ClaudeBot, Claude-SearchBot, anthropic-ai, CCBot, Applebot-Extended, Bytespider, Amazonbot, meta-externalagent blocked sitewide | critical | high |
| `robots_wildcard` | `User-agent: *` + `Disallow: /` | Wildcard group blocks the root and no `Allow` overrides it | critical | high |
| `robots_self_block` | Auditor's own fetch disallowed | Entry path disallowed for a generic UA | critical | high |
| `entry_reachable` | DNS / connection failure | No response after one retry | critical → capped **high** | medium |
| `entry_status` | Entry URL 4xx/5xx | Status ≥ 400 and not an anti-bot deflection | critical | high |
| `bot_protection` | Challenge page, suspicious empty 4xx/5xx, edge-server deflection | Challenge markers, or <200-byte error body, or Cloudflare/Akamai edge signature | medium | medium |
| `entry_content_type` | Entry URL is not HTML | 2xx with a non-HTML content-type | high | high |
| `http_status` | Linked pages error | 5xx → high, 4xx → medium (entry page excluded; it has its own check) | high / medium | high |
| `redirect_loop` | Cycle detected | Same URL seen twice in a chain | high | high |
| `redirect_chain` | ≥3 hops | Multi-hop internal links | low | high |
| `meta_robots` | `noindex` | meta robots or `X-Robots-Tag` | critical on entry, else high | high |
| `canonical` | Off-domain canonical | Canonical resolves to a different registrable domain | high | high |
| `sitemap_coverage` | Sitemap omits sampled pages | Sitemap fully read **and** ≥60% of sampled pages absent | low | medium |
| `static_render` | Facts only after JS | See the four-condition bar below | high | medium (high with a renderer) |
| `content_presence` | Negligible content | 2xx entry with <50 words and <5 links, JS heuristic did not fire | critical | high |

## Field calibration log — `robots_ai_bots` and `static_render`

**No severity changes.** These record what testing has shown, so a later round
can see the trend instead of re-deriving it.

### `robots_ai_bots` — ground truth 3/4 scored, 1 errored

Tested against 4 real sites with human-assigned expected results:

| Site | Expected | Actual | |
|---|---|---|---|
| foodviva.com | fail | fail | correct |
| textileinfomedia.com | fail | fail | correct |
| scotusblog.com | fail | fail | correct |
| woodenstreet.com | fail | **pass** | **check was right, label was wrong** |
| trailfinders.com | fail | — | errored (anti-bot challenge page) |

The woodenstreet row is the valuable one. Its robots.txt carries **39 bare
`Disallow: /` lines**, which is what produced the human "All disallow" label.
Every one of them sits under a named *scraper* user-agent — `Scrapy`,
`HTTrack`, `WebZIP`, `WebReaper`, `EmailSiphon`, `Python-urllib` and 33 more.
There is no `Disallow: /` under `*`, and **no AI crawler is named anywhere in
the file**. GPTBot, PerplexityBot, ClaudeBot et al. are all free to crawl.

That is direct proof the check distinguishes **"blocks scrapers"** from
**"blocks AI crawlers"** — a naive count of `Disallow: /` lines would have
agreed with the label and been wrong. Keep that distinction when hand-reading
a robots.txt: only a wildcard block or a block under a named AI agent counts.

**Citation signal: weak.** Across the 68-site calibration set the equivalent
signal ran **+8% pooled / +6% sector-average, positive in 1 of 6 sectors** —
driven entirely by Health Info (+33%), where several omitted health sites block
AI crawlers and the cited ones do not. It does not clear the KEEP bar. The
mechanism is not in doubt (a blocked crawler fetches nothing); it simply is not
the thing separating cited from omitted sites in this population, because
almost nobody in it blocks AI crawlers at all.

### `static_render` / `raw_html_readable` — ground truth 3/3

Google Scholar, Wikipedia and a small catering site all scored `pass`
correctly (100%). Its citation-separation delta across the 68-site set is
**+0%, in every sector** — but that is **saturation, not a flaw in the check**:
every scoreable site in the population ships readable static HTML, so the
signal has no range to separate on. A check can only discriminate if both
groups contain sites that fail it. To evaluate this one properly the sample
needs sites that actually fail it.

## The static-render bar

All four must hold:

1. static visible text < ~120 words;
2. an app-shell marker present (`__NEXT_DATA__`, `__NUXT__`, `data-reactroot`,
   `id="root"`, `__remixContext`, `astro-island`, …);
3. ≥3 corroborating signals total (few/no headings, <5 links, ≥5 external
   scripts, embedded-state blob);
4. no renderer available to prove otherwise.

A framework marker alone means nothing — most well-built sites ship one and
serve complete HTML. When a renderer *is* available, diff initial HTML against
the rendered DOM and report the specific facts that appear only after
rendering; that is direct evidence and outranks the heuristic.

## Not defects

- No robots.txt (nothing is blocked).
- No sitemap (opportunity — crawling follows links too).
- A 404 on a URL you constructed rather than one the site linked.
- Same-site canonicals, `Disallow` on `/cart`, `/admin`, `/search`.
- Framework/SPA usage per se.

## Distinctions that must not blur

| Observed | Not the same as |
|---|---|
| Anti-bot challenge | JS-rendering defect |
| Login wall | Thin content |
| DNS failure | Site has no content |
| Deliberate AI-crawler block | Accidental misconfiguration (report the consequence, not the intent) |
| Cross-domain redirect | Same-site page |
