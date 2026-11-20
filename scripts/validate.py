#!/usr/bin/env python3
"""Validate skill directories in this repository using Python stdlib (or PyYAML if available)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None

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


class FrontmatterParseError(ValueError):
    """Raised when YAML frontmatter cannot be parsed cleanly."""


def _strip_inline_comment(text: str) -> str:
    """Strip an unquoted `# comment` suffix from a YAML line."""
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(text):
        if in_double:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
        elif in_single:
            if ch == "'":
                in_single = False
        else:
            if ch == '"':
                in_double = True
            elif ch == "'":
                in_single = True
            elif ch == "#" and (idx == 0 or text[idx - 1].isspace()):
                return text[:idx].rstrip()
    return text.rstrip()


def _parse_double_quoted(raw: str) -> str:
    if len(raw) < 2 or not raw.endswith('"'):
        raise FrontmatterParseError(f"Unterminated double-quoted string: {raw}")
    inner = raw[1:-1]
    out: list[str] = []
    i = 0
    escapes = {
        "\\": "\\",
        '"': '"',
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "/": "/",
        "b": "\b",
        "f": "\f",
        "0": "\0",
    }
    while i < len(inner):
        ch = inner[i]
        if ch == "\\":
            i += 1
            if i >= len(inner):
                raise FrontmatterParseError(f"Trailing backslash in double-quoted string: {raw}")
            esc = inner[i]
            if esc in escapes:
                out.append(escapes[esc])
            elif esc == "x" and i + 2 < len(inner):
                out.append(chr(int(inner[i + 1 : i + 3], 16)))
                i += 2
            elif esc == "u" and i + 4 < len(inner):
                out.append(chr(int(inner[i + 1 : i + 5], 16)))
                i += 4
            else:
                raise FrontmatterParseError(f"Unsupported escape '\\{esc}' in double-quoted string")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _parse_single_quoted(raw: str) -> str:
    if len(raw) < 2 or not raw.endswith("'"):
        raise FrontmatterParseError(f"Unterminated single-quoted string: {raw}")
    inner = raw[1:-1]
    # Single-quoted strings in YAML only escape '' -> '
    i = 0
    out: list[str] = []
    while i < len(inner):
        if inner[i] == "'":
            if i + 1 < len(inner) and inner[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            raise FrontmatterParseError(f"Unescaped single quote inside single-quoted string: {raw}")
        out.append(inner[i])
        i += 1
    return "".join(out)


def _split_flow_items(inner: str) -> list[str]:
    items: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    escaped = False
    depth = 0
    for ch in inner:
        if in_double:
            buf.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
            continue
        if in_single:
            buf.append(ch)
            if ch == "'":
                in_single = False
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
        elif ch == "'":
            in_single = True
            buf.append(ch)
        elif ch in "[{":
            depth += 1
            buf.append(ch)
        elif ch in "]}":
            depth -= 1
            if depth < 0:
                raise FrontmatterParseError(f"Unbalanced brackets in flow sequence: [{inner}]")
            buf.append(ch)
        elif ch == "," and depth == 0:
            token = "".join(buf).strip()
            if not token:
                raise FrontmatterParseError(f"Empty item in flow sequence: [{inner}]")
            items.append(token)
            buf = []
        else:
            buf.append(ch)
    if in_single or in_double or depth != 0:
        raise FrontmatterParseError(f"Malformed flow sequence: [{inner}]")
    tail = "".join(buf).strip()
    if tail:
        items.append(tail)
    return items


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith('"'):
        return _parse_double_quoted(text)
    if text.startswith("'"):
        return _parse_single_quoted(text)
    if text.startswith("["):
        if not text.endswith("]"):
            raise FrontmatterParseError(f"Unterminated inline list: {text}")
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(item) for item in _split_flow_items(inner)]
    if text in ("null", "Null", "NULL", "~"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if re.fullmatch(r"[+-]?[0-9]+", text):
        return int(text)
    if re.fullmatch(r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)", text):
        return float(text)
    return text


def _line_indent(line: str) -> int:
    if "\t" in line[: len(line) - len(line.lstrip(" \t"))]:
        raise FrontmatterParseError("Tabs are not allowed in YAML indentation")
    return len(line) - len(line.lstrip(" "))


def _is_blank_or_comment(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def _parse_block_scalar(lines: list[str], start_idx: int, parent_indent: int, header: str) -> tuple[str, int]:
    match = BLOCK_HEADER_RE.match(header.strip())
    if not match:
        raise FrontmatterParseError(f"Invalid block scalar header: {header}")
    style, chomp, explicit_indent = match.group(1), match.group(2) or "", match.group(3)

    idx = start_idx
    block_indent: int | None = None
    if explicit_indent is not None:
        exp = int(explicit_indent)
        if exp <= 0:
            raise FrontmatterParseError(f"Invalid block scalar indent indicator: {header}")
        block_indent = parent_indent + exp

    raw_block_lines: list[str] = []
    while idx < len(lines):
        line = lines[idx]
        if not line.strip():
            raw_block_lines.append("")
            idx += 1
            continue
        indent = _line_indent(line)
        if indent <= parent_indent:
            break
        if block_indent is None:
            block_indent = indent
        elif indent < block_indent:
            raise FrontmatterParseError(
                f"Inconsistent indentation inside block scalar at line {idx + 1}"
            )
        raw_block_lines.append(line[block_indent:])
        idx += 1

    # Count trailing empty lines for chomping
    trailing_empty = 0
    while raw_block_lines and raw_block_lines[-1] == "":
        raw_block_lines.pop()
        trailing_empty += 1

    if not raw_block_lines:
        return ("", idx)

    if style == "|":
        text = "\n".join(raw_block_lines)
    else:
        # Folded scalar (>)
        paragraphs: list[str] = []
        current: list[str] = []
        prev_indented = False
        for blk_line in raw_block_lines:
            if blk_line == "":
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                else:
                    paragraphs.append("")
                prev_indented = False
            elif blk_line.startswith((" ", "\t")):
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                paragraphs.append(blk_line)
                prev_indented = True
            else:
                if prev_indented:
                    paragraphs.append(blk_line)
                    prev_indented = False
                else:
                    current.append(blk_line)
        if current:
            paragraphs.append(" ".join(current))
        text = "\n".join(paragraphs)

    if chomp == "-":
        pass
    elif chomp == "+":
        text += "\n" * (1 + trailing_empty)
    else:
        text += "\n"

    return text, idx


def _next_significant_line(lines: list[str], idx: int) -> int | None:
    while idx < len(lines):
        if not _is_blank_or_comment(lines[idx]):
            return idx
        idx += 1
    return None


def _parse_block(lines: list[str], start_idx: int, min_indent: int) -> tuple[Any, int]:
    first = _next_significant_line(lines, start_idx)
    if first is None:
        return {}, len(lines)
    indent = _line_indent(lines[first])
    if indent < min_indent:
        return {}, first
    stripped = lines[first].lstrip(" ")
    if stripped.startswith("- ") or stripped == "-":
        return _parse_sequence(lines, first, indent)
    return _parse_mapping(lines, first, indent)


def _parse_sequence(lines: list[str], start_idx: int, seq_indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    idx = start_idx
    while idx < len(lines):
        nxt = _next_significant_line(lines, idx)
        if nxt is None:
            idx = len(lines)
            break
        idx = nxt
        line = lines[idx]
        indent = _line_indent(line)
        if indent < seq_indent:
            break
        if indent > seq_indent:
            raise FrontmatterParseError(f"Unexpected indentation in sequence at line {idx + 1}: {line}")
        stripped = line[indent:]
        if not (stripped == "-" or stripped.startswith("- ")):
            break

        rest = stripped[1:].strip() if len(stripped) > 1 else ""
        if not rest or rest.startswith("#"):
            child_idx = _next_significant_line(lines, idx + 1)
            if child_idx is not None and _line_indent(lines[child_idx]) > seq_indent:
                val, idx = _parse_block(lines, child_idx, seq_indent + 1)
            else:
                val = None
                idx += 1
            items.append(val)
            continue

        if BLOCK_HEADER_RE.match(rest):
            val, idx = _parse_block_scalar(lines, idx + 1, seq_indent, rest)
            items.append(val)
            continue

        rest_clean = _strip_inline_comment(rest)
        kv_match = KEY_VALUE_RE.match(rest_clean)
        if kv_match and not rest_clean.startswith(("'", '"', "[")):
            # Inline mapping inside sequence item
            key = kv_match.group(1)
            raw_val = (kv_match.group(2) or "").strip()
            item_map: dict[str, Any] = {}
            if raw_val:
                item_map[key] = _parse_scalar(raw_val)
                idx += 1
            else:
                child_idx = _next_significant_line(lines, idx + 1)
                if child_idx is not None and _line_indent(lines[child_idx]) > seq_indent + 2:
                    item_map[key], idx = _parse_block(lines, child_idx, seq_indent + 3)
                else:
                    item_map[key] = None
                    idx += 1
            child_idx = _next_significant_line(lines, idx)
            if child_idx is not None and _line_indent(lines[child_idx]) >= seq_indent + 2:
                extra, idx = _parse_mapping(lines, child_idx, _line_indent(lines[child_idx]))
                item_map.update(extra)
            items.append(item_map)
            continue

        items.append(_parse_scalar(rest_clean))
        idx += 1

    return items, idx


def _parse_mapping(lines: list[str], start_idx: int, map_indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    idx = start_idx
    while idx < len(lines):
        nxt = _next_significant_line(lines, idx)
        if nxt is None:
            idx = len(lines)
            break
        idx = nxt
        line = lines[idx]
        indent = _line_indent(line)
        if indent < map_indent:
            break
        if indent > map_indent:
            raise FrontmatterParseError(f"Unexpected indentation at line {idx + 1}: {line}")

        stripped = _strip_inline_comment(line[indent:])
        kv_match = KEY_VALUE_RE.match(stripped)
        if not kv_match:
            raise FrontmatterParseError(f"Expected 'key: value' at line {idx + 1}: {line}")

        key = kv_match.group(1)
        if key in result:
            raise FrontmatterParseError(f"Duplicate key '{key}' in frontmatter")
        raw_val = (kv_match.group(2) or "").strip()

        if raw_val and BLOCK_HEADER_RE.match(raw_val):
            val, idx = _parse_block_scalar(lines, idx + 1, map_indent, raw_val)
            result[key] = val
            continue

        if raw_val:
            # Handle plain multiline continuation if subsequent lines are more indented
            if not raw_val.startswith(("'", '"', "[")):
                cont_parts = [raw_val]
                look = idx + 1
                while look < len(lines):
                    next_line = lines[look]
                    if not next_line.strip():
                        break
                    if next_line.lstrip().startswith("#"):
                        break
                    next_indent = _line_indent(next_line)
                    if next_indent <= map_indent:
                        break
                    cont_text = _strip_inline_comment(next_line.strip())
                    if cont_text.startswith("- ") or KEY_VALUE_RE.match(cont_text):
                        raise FrontmatterParseError(
                            f"Invalid continuation line {look + 1}: {next_line}"
                        )
                    cont_parts.append(cont_text)
                    look += 1
                if len(cont_parts) > 1:
                    result[key] = " ".join(cont_parts)
                    idx = look
                    continue
            result[key] = _parse_scalar(raw_val)
            idx += 1
            continue

        # Empty value after ':' -> inspect nested block or None
        child_idx = _next_significant_line(lines, idx + 1)
        if child_idx is None:
            result[key] = None
            idx += 1
            continue
        child_indent = _line_indent(lines[child_idx])
        child_stripped = lines[child_idx].lstrip(" ")
        if child_indent > map_indent:
            val, idx = _parse_block(lines, child_idx, child_indent)
            result[key] = val
        elif child_indent == map_indent and (child_stripped.startswith("- ") or child_stripped == "-"):
            val, idx = _parse_sequence(lines, child_idx, child_indent)
            result[key] = val
        else:
            result[key] = None
            idx += 1

    return result, idx


def parse_frontmatter_stdlib(frontmatter_text: str) -> dict[str, Any]:
    lines = frontmatter_text.split("\n")
    first = _next_significant_line(lines, 0)
    if first is None:
        return {}
    if _line_indent(lines[first]) != 0:
        raise FrontmatterParseError("Top-level frontmatter keys must not be indented")
    parsed, next_idx = _parse_mapping(lines, first, 0)
    rem = _next_significant_line(lines, next_idx)
    if rem is not None:
        raise FrontmatterParseError(f"Unexpected content at line {rem + 1}: {lines[rem]}")
    return parsed


def extract_frontmatter(content: str) -> tuple[dict[str, Any], int]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    if not lines or lines[0].strip() != "---":
        raise FrontmatterParseError("No YAML frontmatter found (file must start with '---')")

    end_idx: int | None = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise FrontmatterParseError("Invalid frontmatter format (missing closing '---')")

    fm_text = "\n".join(lines[1:end_idx])
    if yaml is not None:
        try:
            loaded = yaml.safe_load(fm_text)
        except Exception as exc:  # pragma: no cover
            raise FrontmatterParseError(f"Invalid YAML in frontmatter: {exc}") from exc
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise FrontmatterParseError("Frontmatter must be a YAML dictionary")
        return loaded, len(lines)

    loaded = parse_frontmatter_stdlib(fm_text)
    if not isinstance(loaded, dict):
        raise FrontmatterParseError("Frontmatter must be a YAML dictionary")
    return loaded, len(lines)


def validate_skill_dir(skill_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    if not skill_dir.exists():
        return [f"Directory does not exist: {skill_dir}"], warnings
    if not skill_dir.is_dir():
        return [f"Path is not a directory: {skill_dir}"], warnings

    if (skill_dir / ".git").exists():
        errors.append("Nested '.git' directory inside skill folder is not allowed")

    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        errors.append("SKILL.md not found")
        return errors, warnings

    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"Unable to read SKILL.md: {exc}")
        return errors, warnings

    if not content.strip():
        errors.append("SKILL.md is empty")
        return errors, warnings

    try:
        frontmatter, line_count = extract_frontmatter(content)
    except FrontmatterParseError as exc:
        errors.append(str(exc))
        return errors, warnings

    unexpected = set(frontmatter.keys()) - ALLOWED_PROPERTIES
    if unexpected:
        errors.append(
            f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected))}. "
            f"Allowed properties: {', '.join(sorted(ALLOWED_PROPERTIES))}"
        )

    if "name" not in frontmatter:
        errors.append("Missing 'name' in frontmatter")
    else:
        name = frontmatter["name"]
        if not isinstance(name, str):
            errors.append(f"'name' must be a string, got {type(name).__name__}")
        else:
            name = name.strip()
            if not name:
                errors.append("'name' cannot be empty")
            else:
                if not NAME_RE.match(name):
                    errors.append(
                        f"Name '{name}' must be kebab-case (lowercase letters, digits, single hyphens)"
                    )
                if len(name) > 64:
                    errors.append(f"Name '{name}' is too long ({len(name)} chars; max 64)")
                if name != skill_dir.name:
                    errors.append(
                        f"Frontmatter name '{name}' does not match directory name '{skill_dir.name}'"
                    )

    if "description" not in frontmatter:
        errors.append("Missing 'description' in frontmatter")
    else:
        description = frontmatter["description"]
        if not isinstance(description, str):
            errors.append(f"'description' must be a string, got {type(description).__name__}")
        else:
            description = description.strip()
            if not description:
                errors.append("'description' cannot be empty")
            else:
                if "<" in description or ">" in description:
                    errors.append("'description' cannot contain angle brackets (< or >)")
                if len(description) > 1024:
                    errors.append(
                        f"'description' is too long ({len(description)} chars; max 1024)"
                    )
                if "TODO:" in description:
                    warnings.append("'description' still contains a TODO: placeholder")

    if "compatibility" in frontmatter and frontmatter["compatibility"] is not None:
        compat = frontmatter["compatibility"]
        if not isinstance(compat, str):
            errors.append(f"'compatibility' must be a string, got {type(compat).__name__}")
        elif len(compat) > 500:
            errors.append(f"'compatibility' is too long ({len(compat)} chars; max 500)")

    if line_count > 500:
        warnings.append(f"SKILL.md has {line_count} lines (recommended <= 500 lines)")

    return errors, warnings


def resolve_targets(args: list[str], repo_root: Path) -> tuple[list[Path], list[str]]:
    skills_root = repo_root / "skills"
    if not args:
        if not skills_root.is_dir():
            return [], []
        dirs = sorted(
            p for p in skills_root.iterdir() if p.is_dir() and not p.name.startswith(".")
        )
        return dirs, []

    targets: list[Path] = []
    missing: list[str] = []
    for raw in args:
        candidate = Path(raw).expanduser()
        if candidate.exists():
            targets.append(candidate.resolve())
            continue
        if "/" not in raw and not raw.startswith("."):
            repo_candidate = skills_root / raw
            if repo_candidate.exists():
                targets.append(repo_candidate.resolve())
                continue
        missing.append(raw)
    return targets, missing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate custom agent skills in this repository."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings (TODO placeholders, >500 lines) as errors.",
    )
    parser.add_argument(
        "skills",
        nargs="*",
        help="Skill name(s) under skills/ or path(s) to skill directories. Defaults to all skills under skills/.",
    )
    parsed = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    targets, missing = resolve_targets(parsed.skills, repo_root)

    if missing:
        for item in missing:
            print(f"[ERROR] {item}: skill directory not found", file=sys.stderr)
        return 1

    if not targets:
        print(f"No skills found in {repo_root / 'skills'} — nothing to validate.")
        return 0

    total_errors = 0
    total_warnings = 0

    for target in targets:
        errors, warnings = validate_skill_dir(target)
        total_errors += len(errors)
        total_warnings += len(warnings)

        if errors:
            print(f"[ERROR] {target.name} ({target})")
            for err in errors:
                print(f"  - ERROR: {err}")
            for warn in warnings:
                print(f"  - WARN:  {warn}")
        elif warnings:
            label = "ERROR" if parsed.strict else "WARN"
            print(f"[{label}] {target.name} ({target})")
            for warn in warnings:
                print(f"  - WARN:  {warn}")
        else:
            print(f"[OK] {target.name} ({target})")

    print(
        f"\nValidated {len(targets)} skill(s): "
        f"{total_errors} error(s), {total_warnings} warning(s)."
    )

    if total_errors > 0:
        return 1
    if parsed.strict and total_warnings > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
