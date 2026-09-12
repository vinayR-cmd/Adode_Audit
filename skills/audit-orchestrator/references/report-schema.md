# Report schema

One JSON object per audit. Required keys are marked **required**; everything
else is additive and recommended — the additive fields are what let a reader
check the work rather than trust it.

```jsonc
{
  "site": "https://example.com",            // required — normalized input URL
  "audited_at": "2026-09-10T11:02:45Z",     // required — ISO-8601 UTC
  "auditor": "brand-ai-readiness-audit/1.0",

  "summary": {                               // required
    "total_findings": 7,
    "critical": 1, "high": 2, "medium": 3, "low": 1,
    "pages_audited": 9,
    "checks_not_verified": 4
  },

  "findings": [                              // required (may be empty)
    {
      "id": "F-001",                         // required — stable within a report
      "title": "robots.txt blocks named AI crawlers from the whole site",  // required
      "severity": "critical",                // required — critical|high|medium|low
      "confidence": "high",                  // high|medium|low
      "category": "discoverability",         // discoverability|engagement
      "check": "robots_ai_bots",             // machine-readable check id
      "source_skill": "crawl-render-audit",
      "mechanism": "Stage 1 (reach): a compliant crawler named with Disallow: / never fetches any page.",
      "evidence": "https://example.com/robots.txt returned HTTP 200 and contains Disallow: / for: GPTBot, PerplexityBot",  // required — URL + status/count/snippet
      "affected_pages": ["https://example.com/robots.txt"],
      "suggested_action": {                  // required
        "summary": "Decide deliberately which AI crawlers may read the site.",  // required
        "priority": "critical",
        "how": "Edit /robots.txt; training crawlers and answer-time fetchers have different consequences."
      }
    }
  ],

  "opportunities": [                         // improvements, never disguised as defects
    {
      "title": "Anchor the brand name against same-name entities",
      "type": "opportunity",
      "category": "discoverability",
      "rationale": "Why this would help, and what is NOT established.",
      "suggested_action": {"summary": "...", "effort": "low|medium|high"},
      "source_skill": "entity-trust-audit"
    }
  ],

  "not_verified": [                          // unknowns — never silently dropped
    {
      "check": "rendered_dom_diff",
      "target": "https://example.com/pricing",
      "reason": "no JavaScript rendering tool available; static-only conclusion is heuristic",
      "source_skill": "crawl-render-audit"
    }
  ],

  "skills_run": ["audit-orchestrator", "crawl-render-audit", "..."],

  "pages_audited": [
    {"url": "https://example.com/", "status": 200, "content_type": "text/html",
     "bytes": 84213, "words": 940, "note": null}
  ],

  "crawl": {
    "robots_txt": {"status": 200, "exists": true, "crawl_delay": null, "sitemaps": ["..."]},
    "sitemap_urls": 122,
    "notes": ["robots.txt declares crawl-delay 2 — honoring 2.0s between requests"],
    "crawl_elapsed_s": 18.4,
    "analysis_elapsed_s": 1.2
  },

  "limitations": [
    "Bounded sample of 9 pages; findings describe that sample.",
    "No JavaScript executed; static-render conclusions are heuristic.",
    "One network vantage point, one moment in time."
  ]
}
```

## Rules

- **Emit exactly one JSON object.** Not one per skill, not JSON wrapped in
  prose commentary.
- **No score.** No `overall_score`, no grade, no percentage of "AI readiness".
  See `decision-principles.md` §5.
- **Every finding has evidence.** If the `evidence` string does not contain a
  URL and a concrete observation, the finding does not ship.
- **Findings are defects; opportunities are ideas.** Keep them in separate
  arrays.
- **`not_verified` is a first-class result.** A report with four honest
  unknowns is more useful than one with four invented findings.
- **IDs** are `F-001`, `F-002`, … assigned after sorting by severity, so `F-001`
  is always the most important thing found.
- **Stable field names.** Additive fields are welcome; renaming the required
  ones breaks consumers.
