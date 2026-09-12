"""
run_audit.py — deterministic fast-path for the audit-orchestrator skill.

One crawl, five analyzers, one JSON report. This is the mechanical spine the
agent running SKILL.md can lean on; the agent still adds what a script cannot
do (live web search, JS rendering, judgement on ambiguous cases) and may edit,
add to, or overrule any finding here before emitting the final report.

Usage:
    python run_audit.py --url https://example.com
    python run_audit.py --url https://example.com --max-pages 12 --out report.json
    python run_audit.py --bundle bundle.json          # re-analyze a saved crawl
"""

import argparse
import importlib.util
import json
import os
import sys

import common
import crawl
from common import Budget, utcnow

SKILL_ORDER = [
    "crawl-render-audit",
    "content-extractability",
    "entity-trust-audit",
    "freshness-corroboration",
    "engagement-audit",
]

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
# A low-confidence finding never outranks a mid-severity one (evidence before severity).
CONFIDENCE_CAP = {"low": "medium", "medium": "high", "high": "critical"}


def _skills_dir():
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "..", ".."))


def load_analyzers(only=None):
    """Import each concern skill's scripts/analyze.py by path."""
    loaded, missing = [], []
    for name in SKILL_ORDER:
        if only and name not in only:
            continue
        path = os.path.join(_skills_dir(), name, "scripts", "analyze.py")
        if not os.path.exists(path):
            missing.append((name, "analyze.py not found at %s" % path))
            continue
        try:
            spec = importlib.util.spec_from_file_location("analyzer_%s"
                                                          % name.replace("-", "_"), path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            loaded.append((name, mod))
        except Exception as e:
            missing.append((name, "import failed: %s" % e))
    return loaded, missing


def cap_severity(sev, confidence):
    """Evidence before severity: weak evidence cannot produce a top severity."""
    ceiling = CONFIDENCE_CAP.get(confidence, "critical")
    if SEVERITY_RANK[sev] < SEVERITY_RANK[ceiling]:
        return ceiling
    return sev


def dedupe(findings):
    """Merge findings sharing a root cause; keep the strongest, union the pages."""
    by_cause, order, standalone = {}, [], []
    for f in findings:
        cause = f.get("root_cause")
        if not cause:
            standalone.append(f)
            continue
        if cause not in by_cause:
            by_cause[cause] = f
            order.append(cause)
            continue
        keep = by_cause[cause]
        merged_pages = list(dict.fromkeys((keep.get("affected_pages") or []) +
                                          (f.get("affected_pages") or [])))
        if SEVERITY_RANK[f["severity"]] < SEVERITY_RANK[keep["severity"]]:
            f["affected_pages"] = merged_pages
            f["evidence"] = "%s | also: %s" % (f["evidence"], keep["evidence"])
            f.setdefault("merged_from", []).append(keep.get("check"))
            by_cause[cause] = f
        else:
            keep["affected_pages"] = merged_pages
            keep["evidence"] = "%s | also: %s" % (keep["evidence"], f["evidence"])
            keep.setdefault("merged_from", []).append(f.get("check"))
    return [by_cause[c] for c in order] + standalone


def build_report(bundle, results, missing, budget, notes=None):
    findings, nv, opps = [], [], []
    skills_run = []
    for name, res in results:
        skills_run.append(name)
        for f in res.get("findings", []):
            f["source_skill"] = name
            f["severity"] = cap_severity(f["severity"], f.get("confidence", "high"))
            findings.append(f)
        for item in res.get("not_verified", []):
            item["source_skill"] = name
            nv.append(item)
        for o in res.get("opportunities", []):
            o["source_skill"] = name
            opps.append(o)

    findings = dedupe(findings)
    findings.sort(key=lambda f: (SEVERITY_RANK[f["severity"]],
                                 {"high": 0, "medium": 1, "low": 2}.get(
                                     f.get("confidence", "high"), 3)))
    for i, f in enumerate(findings, 1):
        f["id"] = "F-%03d" % i
        f["affected_pages"] = (f.get("affected_pages") or [])[:12]

    for name, why in missing:
        nv.append({"check": name, "target": "", "reason": why,
                   "source_skill": "audit-orchestrator"})

    nv.extend(bundle.get("not_verified", []))

    counts = {s: sum(1 for f in findings if f["severity"] == s)
              for s in ("critical", "high", "medium", "low")}
    pages = [{"url": p.get("final_url") or p.get("url"), "status": p.get("status"),
              "content_type": p.get("content_type"),
              "bytes": p.get("bytes"), "words": p.get("word_count"),
              "note": p.get("blocked_reason") or p.get("login_wall") or p.get("error")}
             for p in bundle.get("pages", [])]

    return {
        "site": bundle.get("start_url"),
        "audited_at": utcnow(),
        "auditor": "brand-ai-readiness-audit/1.0 (script fast-path)",
        "summary": {
            "total_findings": len(findings),
            "critical": counts["critical"], "high": counts["high"],
            "medium": counts["medium"], "low": counts["low"],
            "pages_audited": len(pages),
            "checks_not_verified": len(nv),
        },
        "findings": [_public(f) for f in findings],
        "opportunities": opps,
        "not_verified": nv,
        "skills_run": ["audit-orchestrator"] + skills_run,
        "pages_audited": pages,
        "crawl": {
            "robots_txt": {k: bundle.get("robots", {}).get(k)
                           for k in ("status", "exists", "crawl_delay", "sitemaps")},
            "sitemap_urls": len(bundle.get("sitemap", {}).get("urls", [])),
            "notes": bundle.get("notes", []) + (notes or []),
            "crawl_elapsed_s": (bundle.get("timing") or {}).get("elapsed_s"),
            "total_elapsed_s": round(budget.elapsed(), 1),
        },
        "limitations": [
            "Read-only static audit: no JavaScript was executed by this script, so "
            "any 'not in the initial HTML' conclusion is heuristic unless confirmed "
            "with a rendering tool.",
            "A bounded sample of %d pages was analyzed; findings describe that sample, "
            "not every page on the site." % len(pages),
            "No third-party or search-engine data was consulted by the script; "
            "corroboration and name-ambiguity checks need live web search.",
            "Findings state risk to AI discoverability and engagement by mechanism. "
            "They are not proof that any specific assistant does or does not cite "
            "this brand.",
        ],
    }


def _public(f):
    return {
        "id": f["id"], "title": f["title"], "severity": f["severity"],
        "confidence": f.get("confidence"), "category": f.get("category"),
        "check": f.get("check"), "source_skill": f.get("source_skill"),
        "mechanism": f.get("mechanism"),
        "evidence": f["evidence"],
        "affected_pages": f.get("affected_pages", []),
        "suggested_action": f["suggested_action"],
    }


def run(url=None, bundle_path=None, max_pages=crawl.DEFAULT_MAX_PAGES,
        timeout=common.DEFAULT_TIMEOUT, budget_s=crawl.DEFAULT_BUDGET,
        verbose=False, only=None):
    budget = Budget(budget_s)
    notes = []
    if bundle_path:
        with open(bundle_path, "r", encoding="utf-8") as fh:
            bundle = json.load(fh)
        notes.append("analyzed a previously saved crawl bundle (%s)" % bundle_path)
    else:
        try:
            url = common.normalize_url(url)
        except ValueError as e:
            return {"site": url, "audited_at": utcnow(),
                    "summary": {"total_findings": 0, "critical": 0, "high": 0,
                                "medium": 0, "low": 0},
                    "findings": [],
                    "not_verified": [{"check": "input", "reason": "invalid URL: %s" % e}],
                    "limitations": ["audit did not run"]}
        bundle = crawl.crawl(url, max_pages=max_pages, timeout=timeout,
                             budget=budget, verbose=verbose)

    analyzers, missing = load_analyzers(only=only)
    results = []
    for name, mod in analyzers:
        if budget.exhausted(reserve=5):
            missing.append((name, "skipped: audit time budget exhausted"))
            continue
        try:
            results.append((name, mod.analyze(bundle)))
        except Exception as e:  # one broken analyzer must not sink the audit
            missing.append((name, "analyzer raised %s: %s" % (type(e).__name__, e)))
        if verbose:
            print("  [orchestrator] %s done (%.1fs elapsed)"
                  % (name, budget.elapsed()), file=sys.stderr)
    return build_report(bundle, results, missing, budget, notes)


def main(argv):
    ap = argparse.ArgumentParser(description="Brand AI-readiness audit (fast path)")
    ap.add_argument("--url")
    ap.add_argument("--bundle", help="re-analyze a saved crawl bundle")
    ap.add_argument("--max-pages", type=int, default=crawl.DEFAULT_MAX_PAGES)
    ap.add_argument("--timeout", type=int, default=common.DEFAULT_TIMEOUT)
    ap.add_argument("--budget", type=int, default=crawl.DEFAULT_BUDGET,
                    help="wall-clock seconds for the whole audit")
    ap.add_argument("--out")
    ap.add_argument("--save-bundle")
    ap.add_argument("--only", nargs="*", help="run only these concern skills")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)
    if not args.url and not args.bundle:
        ap.error("provide --url or --bundle")

    if args.save_bundle and args.url:
        budget = Budget(args.budget)
        bundle = crawl.crawl(common.normalize_url(args.url), max_pages=args.max_pages,
                             timeout=args.timeout, budget=budget, verbose=args.verbose)
        for p in bundle["pages"]:
            p.pop("_parsed", None)
        with open(args.save_bundle, "w", encoding="utf-8") as fh:
            json.dump(bundle, fh, indent=2, ensure_ascii=False)
        report = run(bundle_path=args.save_bundle, budget_s=args.budget,
                     verbose=args.verbose, only=args.only)
    else:
        report = run(url=args.url, bundle_path=args.bundle, max_pages=args.max_pages,
                     timeout=args.timeout, budget_s=args.budget,
                     verbose=args.verbose, only=args.only)

    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("report written to %s" % args.out, file=sys.stderr)
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
