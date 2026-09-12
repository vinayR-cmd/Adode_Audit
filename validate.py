"""
validate.py — structural self-check for the marketplace.

Verifies, with the standard library only:
  * marketplace.json is well-formed and lists exactly one entrypoint;
  * every listed skill folder exists with SKILL.md, scripts/ and references/;
  * SKILL.md frontmatter has a `name` matching the folder (lowercase-hyphenated)
    and a non-trivial `description`;
  * the vendored common.py copies are identical to the canonical one;
  * every bundled Python script compiles.

    python validate.py
"""

import hashlib
import json
import os
import py_compile
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

errors, warnings, checks = [], [], 0


def check(cond, msg):
    global checks
    checks += 1
    if not cond:
        errors.append(msg)
    return cond


def read_frontmatter(path):
    """Minimal YAML frontmatter reader — top-level scalar keys only."""
    text = open(path, encoding="utf-8").read()
    if not text.startswith("---"):
        return None, "no YAML frontmatter"
    end = text.find("\n---", 3)
    if end < 0:
        return None, "unterminated frontmatter"
    fm = {}
    for line in text[3:end].splitlines():
        if not line.strip() or line.startswith("#") or line[:1] in (" ", "\t"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, None


def main():
    manifest_path = os.path.join(ROOT, "marketplace.json")
    if not check(os.path.exists(manifest_path), "marketplace.json is missing"):
        return report()
    try:
        manifest = json.load(open(manifest_path, encoding="utf-8"))
    except ValueError as e:
        errors.append("marketplace.json does not parse: %s" % e)
        return report()

    skills = manifest.get("skills", [])
    check(bool(skills), "marketplace.json lists no skills")
    entries = [s for s in skills if s.get("entrypoint")]
    check(len(entries) == 1,
          "expected exactly one entrypoint:true, found %d" % len(entries))

    canonical = os.path.join(ROOT, "skills", "audit-orchestrator", "scripts", "common.py")
    canon_hash = None
    if os.path.exists(canonical):
        canon_hash = hashlib.sha256(open(canonical, "rb").read()).hexdigest()

    for entry in skills:
        name = entry.get("id", "")
        folder = os.path.join(ROOT, entry.get("path", ""))
        if not check(os.path.isdir(folder), "%s: folder missing (%s)" % (name, folder)):
            continue
        check(NAME_RE.match(name), "%s: id is not lowercase-hyphenated" % name)
        check(os.path.basename(folder.rstrip("/\\")) == name,
              "%s: folder name does not match skill id" % name)

        skill_md = os.path.join(folder, "SKILL.md")
        if not check(os.path.exists(skill_md), "%s: SKILL.md missing" % name):
            continue
        fm, err = read_frontmatter(skill_md)
        if not check(fm is not None, "%s: %s" % (name, err)):
            continue
        check(fm.get("name") == name,
              "%s: frontmatter name %r does not match folder" % (name, fm.get("name")))
        desc = fm.get("description", "")
        check(len(desc) >= 80,
              "%s: description too short to act as a trigger signal (%d chars)"
              % (name, len(desc)))
        if "use this" not in desc.lower() and "use it" not in desc.lower():
            warnings.append("%s: description does not say WHEN to use the skill" % name)

        for sub in ("scripts", "references"):
            check(os.path.isdir(os.path.join(folder, sub)),
                  "%s: %s/ missing" % (name, sub))
        refs = os.listdir(os.path.join(folder, "references")) \
            if os.path.isdir(os.path.join(folder, "references")) else []
        check(any(r.endswith(".md") for r in refs),
              "%s: references/ has no markdown doc" % name)

        if name == "audit-orchestrator":
            for required in ("report-schema.md", "severity.md", "decision-principles.md"):
                check(required in refs,
                      "audit-orchestrator: references/%s missing" % required)

        scripts_dir = os.path.join(folder, "scripts")
        for fn in sorted(os.listdir(scripts_dir)) if os.path.isdir(scripts_dir) else []:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(scripts_dir, fn)
            try:
                py_compile.compile(path, cfile=os.path.join(tempfile.gettempdir(),
                                                            "%s_%s.pyc" % (name, fn)),
                                   doraise=True)
                globals()["checks"] = globals()["checks"] + 1
            except py_compile.PyCompileError as e:
                errors.append("%s/%s: does not compile: %s" % (name, fn, e))
            if fn == "common.py" and canon_hash:
                h = hashlib.sha256(open(path, "rb").read()).hexdigest()
                check(h == canon_hash,
                      "%s/common.py differs from the canonical copy — re-vendor it" % name)

    return report()


def report():
    for w in warnings:
        print("WARN  %s" % w)
    for e in errors:
        print("FAIL  %s" % e)
    print("\n%d checks run, %d failures, %d warnings" % (checks, len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
