#!/usr/bin/env python3
"""Audit agent skill structure, hook portability, and token budgets (stdlib only)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import _spec  # noqa: E402

IDLE_TARGET_TOKENS = 150
IDLE_WARN_TOKENS = 250
ACTIVE_TARGET_TOKENS = 1500
ACTIVE_WARN_TOKENS = 2000
ACTIVE_TARGET_LINES = 150
REF_TARGET_TOKENS = 2500
REF_WARN_TOKENS = 3500

BUNDLED_REF_RE = re.compile(r"(?<![./\w])((?:scripts|references|assets)/[A-Za-z0-9._/*<>-]+)")
HARDCODED_HOME_RE = re.compile(
    r"(?:/home/[A-Za-z0-9._-]+/|/Users/[A-Za-z0-9._-]+/|[A-Za-z]:\\Users\\[A-Za-z0-9._-]+\\)"
)
REPO_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(?:scripts\.)?lib(?:\.|\s+import)|import\s+(?:scripts\.)?lib\b)",
    re.MULTILINE,
)


def _est_tokens(byte_count: int) -> int:
    return round(byte_count / 4)


def _skill_md_body(raw: str) -> str:
    norm = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    if lines and lines[0].strip() == "---":
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                return "\n".join(lines[idx + 1 :])
    return norm


def _check_skill_md_refs(skill_dir: Path, raw_skill_md: str, warnings: list[str]) -> None:
    body = _skill_md_body(raw_skill_md)
    candidates: set[str] = set()
    for match in BUNDLED_REF_RE.finditer(body):
        rel = match.group(1).rstrip(".,:;)\"'`")
        if not rel or rel.endswith("/") or any(ch in rel for ch in "*<>{}"):
            continue
        candidates.add(rel)
    for rel in sorted(candidates):
        if not (skill_dir / rel).exists():
            warnings.append(f"SKILL.md references missing bundled path '{rel}'")


def _check_portability(skill_dir: Path, raw_skill_md: str, warnings: list[str]) -> None:
    if HARDCODED_HOME_RE.search(raw_skill_md):
        warnings.append("SKILL.md contains a hardcoded user home path")

    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return
    for sf in sorted(scripts_dir.rglob("*")):
        if not sf.is_file() or "__pycache__" in sf.parts or sf.suffix not in (".py", ".sh"):
            continue
        rel = sf.relative_to(skill_dir).as_posix()
        try:
            text = sf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if HARDCODED_HOME_RE.search(text):
            warnings.append(f"{rel} contains a hardcoded user home path")
        if sf.suffix == ".py" and REPO_IMPORT_RE.search(text):
            warnings.append(f"{rel} imports from repo-root scripts/lib (breaks standalone portability)")


def audit_skill(skill_dir: Path, *, target_strict: bool = False) -> dict[str, Any]:
    info, errors, warnings = _spec.validate_skill_structure(skill_dir)
    active_bytes = info["active_bytes"]
    idle_bytes = info["idle_bytes"]
    line_count = info["line_count"]

    metrics: dict[str, Any] = {
        "name": skill_dir.name,
        "path": str(skill_dir),
        "idle_bytes": idle_bytes,
        "idle_tokens": _est_tokens(idle_bytes),
        "active_bytes": active_bytes,
        "active_tokens": _est_tokens(active_bytes),
        "active_lines": line_count,
        "references_count": 0,
        "references_bytes": 0,
        "references_tokens": 0,
        "scripts_count": 0,
        "hook_status": "none",
    }

    if not skill_dir.is_dir() or info["frontmatter"] is None:
        return {"metrics": metrics, "errors": errors, "warnings": warnings}

    idle_limit = IDLE_TARGET_TOKENS if target_strict else IDLE_WARN_TOKENS
    active_limit = ACTIVE_TARGET_TOKENS if target_strict else ACTIVE_WARN_TOKENS
    ref_limit = REF_TARGET_TOKENS if target_strict else REF_WARN_TOKENS

    if metrics["idle_tokens"] > idle_limit:
        warnings.append(
            f"Idle frontmatter is {metrics['idle_tokens']} tokens (target <= {idle_limit})"
        )
    if target_strict and ACTIVE_TARGET_LINES < line_count <= 500:
        warnings.append(
            f"SKILL.md has {line_count} lines (target <= {ACTIVE_TARGET_LINES} lines)"
        )
    if metrics["active_tokens"] > active_limit:
        warnings.append(
            f"Active SKILL.md is ~{metrics['active_tokens']} tokens (target <= {active_limit})"
        )

    raw_skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    _check_skill_md_refs(skill_dir, raw_skill_md, warnings)
    _check_portability(skill_dir, raw_skill_md, warnings)

    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        ref_files = sorted(p for p in refs_dir.rglob("*") if p.is_file())
        metrics["references_count"] = len(ref_files)
        total_ref_b = 0
        for rf in ref_files:
            rb = rf.stat().st_size
            total_ref_b += rb
            rt = _est_tokens(rb)
            if rt > ref_limit:
                warnings.append(
                    f"Reference {rf.relative_to(skill_dir)} is ~{rt} tokens (consider splitting; target <= {ref_limit})"
                )
        metrics["references_bytes"] = total_ref_b
        metrics["references_tokens"] = _est_tokens(total_ref_b)

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        script_files = sorted(
            p for p in scripts_dir.iterdir()
            if p.is_file() and not p.name.startswith("_")
        )
        metrics["scripts_count"] = len(script_files)
        for sf in script_files:
            if sf.suffix in (".sh", ".py"):
                with sf.open("r", encoding="utf-8", errors="replace") as fh:
                    first_line = fh.readline()
                if first_line.startswith("#!") and not (sf.stat().st_mode & 0o111):
                    warnings.append(f"Script {sf.name} has shebang but is not executable (chmod +x)")

    hook_data = info["hook_data"]
    if isinstance(hook_data, dict):
        enabled = hook_data.get("enabled") is True
        metrics["hook_status"] = "enabled" if enabled else "disabled"
        if enabled and not (skill_dir / "evals" / "trigger-tests.json").is_file():
            warnings.append("hook-triggers.json is enabled but evals/trigger-tests.json is missing")

    return {"metrics": metrics, "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit skill structure, hook portability, and token budgets."
    )
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")
    parser.add_argument(
        "--target-strict",
        action="store_true",
        help="Enforce target budgets (150 idle tok, 1500 active tok / 150 lines, 2500 ref tok).",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("skills", nargs="+", help="Path(s) to skill directories.")
    args = parser.parse_args()

    results = [
        audit_skill(Path(p).expanduser().resolve(), target_strict=args.target_strict)
        for p in args.skills
    ]

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print("| Skill | Idle (tok) | Active SKILL.md | Lines | Refs (tok) | Scripts | Hook | Status |")
        print("| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |")
        for res in results:
            m = res["metrics"]
            status = "ERR" if res["errors"] else ("WARN" if res["warnings"] else "OK")
            print(
                f"| {m['name']} | ~{m['idle_tokens']} ({m['idle_bytes']} B) "
                f"| ~{m['active_tokens']} ({m['active_bytes']} B) | {m['active_lines']} "
                f"| ~{m['references_tokens']} ({m['references_count']}) "
                f"| {m['scripts_count']} | {m['hook_status']} | {status} |"
            )
        for res in results:
            m = res["metrics"]
            for err in res["errors"]:
                print(f"[ERROR] {m['name']}: {err}", file=sys.stderr)
            for warn in res["warnings"]:
                print(f"[WARN]  {m['name']}: {warn}", file=sys.stderr)

    has_err = any(r["errors"] for r in results)
    has_warn = any(r["warnings"] for r in results)
    if has_err or (args.strict and has_warn):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
