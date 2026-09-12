# Decision principles

These five rules govern every judgement in this marketplace. When a check and a
principle disagree, the principle wins.

---

## 1. Mechanism before convention

A missing conventional element is not a defect. A broken *mechanism* is.

Before reporting anything, name the causal path: **how does this stop an AI
assistant from reaching, reading, extracting, attributing or trusting the
content — or stop a visitor from orienting and acting?** If you cannot state
that path in one sentence with the observed evidence in it, you do not have a
finding.

Not defects by themselves: a missing meta description, no blog, no FAQ schema,
no sitemap, a short homepage, a React build, no Wikipedia article.

Defects when the mechanism holds: `Disallow: /` for a named AI crawler
(blocks reach), `noindex` on a page meant to be citable (blocks retrieval),
JSON-LD that does not parse (identity silently discarded), a fact that exists
only inside an un-alt-texted image (unreadable to a text fetcher).

## 2. Evidence before severity

Severity is capped by evidence strength, never by how alarming the issue
sounds.

- Every finding carries a URL plus a status, count, or extracted snippet.
- A check you could not complete is `not_verified` with the reason — never a
  defect. Blocked, timed out, login-walled, non-HTML and ambiguous are all
  *unknowns*, and an unknown reported as a defect is a fabrication.
- A low-confidence finding cannot be `critical`; a medium-confidence one cannot
  exceed `high`. The tooling enforces this; you should too.
- Where a live tool would settle it (a renderer for static-vs-rendered, a web
  search for name ambiguity or claim conflicts), use it, or say plainly that
  the check is unverified.

## 3. Root cause before symptom

One template that omits schema on forty pages is **one** finding listing the
affected pages — not forty findings.

Merge on the shared cause, keep the strongest severity, union the affected
pages. A long list of symptom-level duplicates reads as padding and buries the
two things that actually matter.

## 4. No causal overclaim

You are measuring *risk*, not observed outcomes.

Say: "this materially lowers the odds of being quoted for questions of this
type, because …". Do not say: "this is why ChatGPT never mentions you."

The only time a direct causal claim is allowed is when you have direct
evidence — you actually observed an assistant's output getting the brand wrong
or omitting it — and then you quote what you observed and where.

Assistants differ, change often, and weigh signals you cannot see from the
outside. Honest probability language is what makes the rest of the report
believable.

## 5. No universal score

Do not emit a single "AI-readiness score" out of 100. There is no validated
scale behind such a number, and a score invites optimising the number instead
of the mechanism. Report severity-bucketed counts and ranked findings.

Related: never hardcode logic to a specific brand, domain or sector. Every
check must be mechanism-level so it generalises to a site nobody has seen yet.
If a check needs sector context (which review platforms matter, how fast this
content decays), take it as input to judgement — don't bake a site into the
code.

---

## Applying them, in order

1. Did I observe it? → else `not_verified`.
2. Can I state the mechanism? → else drop it.
3. Is it the cause or a symptom? → merge upward.
4. Is my language proportional to my evidence? → downgrade until it is.
5. Is this a defect or an improvement idea? → improvements go in
   `opportunities`.
