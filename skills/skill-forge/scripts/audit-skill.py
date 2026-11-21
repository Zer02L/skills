#!/usr/bin/env python3
"""Audit agent skill structure, hook portability, and token budgets (stdlib only)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ALLOWED_PROPERTIES = {
    "name",
    "description",
    "license",
    "allowed-tools",
    "metadata",
    "compatibility",
}
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
KEY_VALUE_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s*:(?:\s+(.*)|\s*)$")
BLOCK_HEADER_RE = re.compile(r"^([|>])([+-])?(\d+)?(?:\s+#.*)?$")
INLINE_RE_FLAG = re.compile(r"\(\?(?:[aiLmsux]+(?:-[imsx]+)?|-[imsx]+)[):]")
CYRILLIC_WORD_BOUNDARY = re.compile(r"(?:\\b[а-яёА-ЯЁ]|[а-яёА-ЯЁ]\\b)")

IDLE_WARN_TOKENS = 250
ACTIVE_WARN_TOKENS = 2000
REF_WARN_TOKENS = 3500


class FrontmatterError(ValueError):
    """Raised when YAML frontmatter cannot be parsed."""


def _est_tokens(byte_count: int) -> int:
    return round(byte_count / 4)


def _extract_frontmatter(content: str) -> tuple[dict[str, Any], str, int]:
    norm = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("Missing opening '---' YAML frontmatter delimiter")
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise FrontmatterError("Missing closing '---' YAML frontmatter delimiter")

    fm_raw = "\n".join(lines[: end_idx + 1])
    fm_lines = lines[1:end_idx]

    # Try PyYAML if available; otherwise parse cleanly with stdlib.
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load("\n".join(fm_lines)) or {}
        if not isinstance(loaded, dict):
            raise FrontmatterError("Frontmatter must be a YAML mapping")
        return loaded, fm_raw, len(lines)
    except ImportError:
        pass

    parsed: dict[str, Any] = {}
    i = 0
    while i < len(fm_lines):
        raw_line = fm_lines[i]
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if raw_line.startswith((" ", "\t")):
            raise FrontmatterError(f"Unexpected indentation at frontmatter line {i + 2}")
        m = KEY_VALUE_RE.match(stripped)
        if not m:
            raise FrontmatterError(f"Malformed frontmatter line {i + 2}: {raw_line}")
        key = m.group(1)
        val = (m.group(2) or "").strip()

        if BLOCK_HEADER_RE.match(val):
            style = val[0]
            block_lines: list[str] = []
            i += 1
            base_ind: int | None = None
            while i < len(fm_lines):
                ln = fm_lines[i]
                if not ln.strip():
                    block_lines.append("")
                    i += 1
                    continue
                ind = len(ln) - len(ln.lstrip(" "))
                if ind == 0:
                    break
                if base_ind is None:
                    base_ind = ind
                block_lines.append(ln[base_ind:])
                i += 1
            parsed[key] = ("\n" if style == "|" else " ").join(
                ln for ln in block_lines
            ).strip()
            continue

        if val:
            if (val.startswith('"') and val.endswith('"')) or (
                val.startswith("'") and val.endswith("'")
            ):
                val = val[1:-1]
                parsed[key] = val
                i += 1
                continue
            parts = [val]
            i += 1
            while i < len(fm_lines):
                nxt = fm_lines[i]
                if not nxt.strip() or nxt.lstrip().startswith("#"):
                    break
                if len(nxt) - len(nxt.lstrip(" ")) == 0:
                    break
                parts.append(nxt.strip())
                i += 1
            parsed[key] = " ".join(parts)
            continue

        # Nested mapping or list (collect raw presence)
        children: list[str] = []
        i += 1
        while i < len(fm_lines):
            nxt = fm_lines[i]
            if not nxt.strip() or nxt.lstrip().startswith("#"):
                i += 1
                continue
            if len(nxt) - len(nxt.lstrip(" ")) == 0:
                break
            children.append(nxt.strip())
            i += 1
        parsed[key] = children if children else None

    return parsed, fm_raw, len(lines)


def audit_skill(skill_dir: Path) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "name": skill_dir.name,
        "path": str(skill_dir),
        "idle_bytes": 0,
        "idle_tokens": 0,
        "active_bytes": 0,
        "active_tokens": 0,
        "active_lines": 0,
        "references_count": 0,
        "references_bytes": 0,
        "references_tokens": 0,
        "scripts_count": 0,
        "hook_status": "none",
    }

    if not skill_dir.is_dir():
        errors.append(f"Not a directory: {skill_dir}")
        return {"metrics": metrics, "errors": errors, "warnings": warnings}

    if (skill_dir / ".git").exists():
        errors.append("Nested '.git' directory is not allowed inside a skill folder")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append("SKILL.md not found")
        return {"metrics": metrics, "errors": errors, "warnings": warnings}

    raw = skill_md.read_text(encoding="utf-8")
    active_bytes = len(raw.encode("utf-8"))
    metrics["active_bytes"] = active_bytes
    metrics["active_tokens"] = _est_tokens(active_bytes)

    try:
        fm, fm_raw, line_count = _extract_frontmatter(raw)
        metrics["active_lines"] = line_count
        idle_bytes = len(fm_raw.encode("utf-8"))
        metrics["idle_bytes"] = idle_bytes
        metrics["idle_tokens"] = _est_tokens(idle_bytes)
    except FrontmatterError as exc:
        errors.append(str(exc))
        return {"metrics": metrics, "errors": errors, "warnings": warnings}

    unexpected = set(fm.keys()) - ALLOWED_PROPERTIES
    if unexpected:
        errors.append(f"Unexpected frontmatter keys: {', '.join(sorted(unexpected))}")

    name = fm.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append("Missing or invalid 'name' in frontmatter")
    else:
        name = name.strip()
        if not NAME_RE.match(name) or len(name) > 64:
            errors.append(f"Invalid kebab-case name '{name}' (max 64 chars)")
        if name != skill_dir.name:
            errors.append(f"Frontmatter name '{name}' != directory '{skill_dir.name}'")

    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        errors.append("Missing or invalid 'description' in frontmatter")
    else:
        desc = desc.strip()
        if "<" in desc or ">" in desc:
            errors.append("'description' cannot contain '<' or '>'")
        if len(desc) > 1024:
            errors.append(f"'description' exceeds 1024 chars ({len(desc)})")
        if "TODO:" in desc:
            warnings.append("'description' still contains a TODO: placeholder")

    compat = fm.get("compatibility")
    if compat is not None:
        if not isinstance(compat, str) or len(compat) > 500:
            errors.append("'compatibility' must be a string <= 500 chars")

    if metrics["idle_tokens"] > IDLE_WARN_TOKENS:
        warnings.append(
            f"Idle frontmatter is {metrics['idle_tokens']} tokens (target <= {IDLE_WARN_TOKENS})"
        )
    if line_count > 500:
        warnings.append(f"SKILL.md has {line_count} lines (recommended <= 500)")
    elif metrics["active_tokens"] > ACTIVE_WARN_TOKENS:
        warnings.append(
            f"Active SKILL.md is ~{metrics['active_tokens']} tokens (target <= {ACTIVE_WARN_TOKENS})"
        )

    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        ref_files = sorted(p for p in refs_dir.rglob("*") if p.is_file())
        metrics["references_count"] = len(ref_files)
        total_ref_b = 0
        for rf in ref_files:
            rb = rf.stat().st_size
            total_ref_b += rb
            rt = _est_tokens(rb)
            if rt > REF_WARN_TOKENS:
                warnings.append(
                    f"Reference {rf.relative_to(skill_dir)} is ~{rt} tokens (consider splitting; target <= {REF_WARN_TOKENS})"
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
                first_line = sf.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
                if first_line and first_line[0].startswith("#!") and not (sf.stat().st_mode & 0o111):
                    warnings.append(f"Script {sf.name} has shebang but is not executable (chmod +x)")

    hook_file = skill_dir / "hook-triggers.json"
    if hook_file.exists():
        try:
            hd = json.loads(hook_file.read_text(encoding="utf-8"))
            if not isinstance(hd, dict):
                errors.append("hook-triggers.json must be a JSON object")
            else:
                enabled = hd.get("enabled")
                metrics["hook_status"] = "enabled" if enabled is True else "disabled"
                if hd.get("schema_version") != 1:
                    errors.append("hook-triggers.json: 'schema_version' must be 1")
                if not isinstance(enabled, bool):
                    errors.append("hook-triggers.json: 'enabled' must be boolean")
                if hd.get("skill") != skill_dir.name:
                    errors.append(f"hook-triggers.json: 'skill' must match '{skill_dir.name}'")
                patterns: list[tuple[str, str]] = []
                if isinstance(hd.get("prompt_regex"), str):
                    patterns.append(("prompt_regex", hd["prompt_regex"]))
                for idx, entry in enumerate(hd.get("deny_shell") or []):
                    if isinstance(entry, dict):
                        if isinstance(entry.get("regex"), str):
                            patterns.append((f"deny_shell[{idx}].regex", entry["regex"]))
                        if isinstance(entry.get("allow_if_regex"), str):
                            patterns.append((f"deny_shell[{idx}].allow_if_regex", entry["allow_if_regex"]))
                for pname, pat in patterns:
                    if INLINE_RE_FLAG.search(pat):
                        errors.append(f"hook-triggers.json {pname}: inline (?i) flags break JS RegExp")
                    if CYRILLIC_WORD_BOUNDARY.search(pat):
                        warnings.append(
                            f"hook-triggers.json {pname}: '\\b' adjacent to Cyrillic fails in JS RegExp"
                        )
                    try:
                        re.compile(pat)
                    except re.error as exc:
                        errors.append(f"hook-triggers.json {pname}: invalid regex ({exc})")
                if enabled is True and isinstance(hd.get("hint"), str) and "TODO:" in hd["hint"]:
                    warnings.append("hook-triggers.json: 'hint' still contains TODO: while enabled")
        except Exception as exc:
            errors.append(f"Invalid hook-triggers.json: {exc}")

    return {"metrics": metrics, "errors": errors, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit skill structure, hook portability, and token budgets."
    )
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    parser.add_argument("skills", nargs="+", help="Path(s) to skill directories.")
    args = parser.parse_args()

    results = [audit_skill(Path(p).expanduser().resolve()) for p in args.skills]

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
