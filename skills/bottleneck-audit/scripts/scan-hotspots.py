#!/usr/bin/env python3
"""Bounded static bottleneck triage and stack/profiler probe (Python 3 stdlib)."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import _rules  # noqa: E402


def is_test_path(rel_path: Path) -> bool:
    for part in rel_path.parts[:-1]:
        if part.lower() in _rules.TEST_DIR_NAMES:
            return True
    name = rel_path.name.lower()
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    return False


def is_asset_path(rel_path: Path) -> bool:
    return any(part.lower() in _rules.ASSET_DIR_NAMES for part in rel_path.parts[:-1])


def is_binary_bytes(sample: bytes) -> bool:
    return b"\x00" in sample


def strip_py_comment_and_bracket_delta(line: str) -> tuple[str, int]:
    """Strip unquoted `#` comments and count net `([{}])` delta in one pass."""
    in_single = False
    in_double = False
    escaped = False
    delta = 0

    for i, ch in enumerate(line):
        if in_double:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
        elif in_single:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_single = False
        else:
            if ch == '"':
                in_double = True
            elif ch == "'":
                in_single = True
            elif ch == "#":
                return line[:i], delta
            elif ch in "([{":
                delta += 1
            elif ch in ")]}":
                delta -= 1

    return line, delta


def _strip_hash_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for i, ch in enumerate(line):
        if in_double:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_double = False
        elif in_single:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "'":
                in_single = False
        else:
            if ch == '"':
                in_double = True
            elif ch == "'":
                in_single = True
            elif ch == "#":
                return line[:i]
    return line


def strip_c_comment_and_braces(
    line: str, ext: str, in_block_comment: bool, count_braces: bool
) -> tuple[str, int, int, bool]:
    """Strip comments outside string literals and optionally count `{`/`}` in one pass."""
    if ext in _rules.HASH_COMMENT_EXTS:
        return _strip_hash_comment(line), 0, 0, False

    out: list[str] = []
    i = 0
    n = len(line)
    in_single = False
    in_double = False
    in_backtick = False
    escaped = False
    sql_mode = ext in _rules.SQL_EXTS
    opens = 0
    closes = 0

    while i < n:
        ch = line[i]
        nxt = line[i + 1] if i + 1 < n else ""

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue

        if in_double or in_single or in_backtick:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\" and not (in_single and sql_mode):
                escaped = True
            elif (
                (in_double and ch == '"')
                or (in_single and ch == "'")
                or (in_backtick and ch == "`")
            ):
                in_double = in_single = in_backtick = False
            i += 1
            continue

        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if not sql_mode and ch == "/" and nxt == "/" and (i == 0 or line[i - 1] != ":"):
            break
        if sql_mode and ch == "-" and nxt == "-":
            break

        if ch == '"':
            in_double = True
        elif ch == "'":
            in_single = True
        elif ch == "`" and not sql_mode:
            in_backtick = True
        elif count_braces:
            if ch == "{":
                opens += 1
            elif ch == "}":
                closes += 1

        out.append(ch)
        i += 1

    return "".join(out), opens, closes, in_block_comment


def detect_stacks(root: Path) -> list[str]:
    found: set[str] = set()
    roots = [root]
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name not in _rules.SKIP_DIRS and not child.name.startswith("."):
                roots.append(child)
    except OSError:
        pass
    for base in roots:
        for marker, label in _rules.STACK_MARKERS.items():
            if (base / marker).exists():
                found.add(label)
    return sorted(found)


def detect_profilers() -> list[str]:
    return [b for b in _rules.PROFILER_BINS if shutil.which(b)]


def evaluate_line(
    rel_path: str,
    line_no: int,
    code: str,
    raw_line: str,
    *,
    file_rules: tuple[_rules.Rule, ...],
    check_nested: bool,
    in_loop: bool,
    in_enclosing_loop: bool,
    in_async_py: bool,
    in_async_brace: bool,
    in_reduce: bool,
    opened_nested_loop: bool,
) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None

    for rule in file_rules:
        if rule.require_loop and not in_loop:
            continue
        if (
            rule.rule_id == "cpu-linear-lookup-in-loop"
            and not in_enclosing_loop
            and _rules.SORTED_CALL_RE.search(code)
        ):
            continue
        if rule.require_async_py and not in_async_py:
            continue
        if rule.require_reduce and not in_reduce:
            continue
        if rule.exclude_pattern and rule.exclude_pattern.search(code):
            continue
        if not rule.pattern.search(code):
            continue

        score = rule.score
        if rule.boost_in_async_or_loop and (in_loop or in_async_brace):
            score += rule.boost_in_async_or_loop

        cand = {
            "score": score,
            "domain": rule.domain,
            "rule": rule.rule_id,
            "file": rel_path,
            "line": line_no,
            "evidence": raw_line.strip()[:120],
            "why": rule.why,
        }
        if best is None or score > best[0]:
            best = (score, cand)

    if opened_nested_loop and check_nested:
        info = _rules.NESTED_LOOP_INFO
        cand = {
            "score": info.score,
            "domain": info.domain,
            "rule": info.rule_id,
            "file": rel_path,
            "line": line_no,
            "evidence": raw_line.strip()[:120],
            "why": info.why,
        }
        if best is None or info.score > best[0]:
            best = (info.score, cand)

    return best[1] if best else None


def scan_python_file(
    rel_path: str,
    lines: list[str],
    file_rules: tuple[_rules.Rule, ...],
    check_nested: bool,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    # Stack of (indent, kind) where kind in {"loop", "async_def"}
    scope_stack: list[tuple[int, str]] = []
    loop_count = 0
    async_count = 0
    bracket_depth = 0
    in_triple: str | None = None

    for line_no, raw_line in enumerate(lines, 1):
        stripped_raw = raw_line.strip()
        if in_triple:
            if in_triple in stripped_raw:
                in_triple = None
            continue
        if stripped_raw.startswith(('"""', "'''")):
            delim = stripped_raw[:3]
            if stripped_raw.count(delim) == 1:
                in_triple = delim
            continue

        code, line_delta = strip_py_comment_and_bracket_delta(raw_line)
        code_stripped = code.strip()
        if not code_stripped:
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" \t"))
        if bracket_depth == 0:
            while scope_stack and scope_stack[-1][0] >= indent:
                _, popped_kind = scope_stack.pop()
                if popped_kind == "loop":
                    loop_count -= 1
                else:
                    async_count -= 1

        is_loop_opener = bool(_rules.PY_LOOP_RE.match(code_stripped))
        is_async_def = bool(_rules.PY_ASYNC_DEF_RE.match(code_stripped))
        same_line_comp = (
            bool(_rules.PY_COMPREHENSION_RE.search(code_stripped)) and not is_loop_opener
        )

        prior_loops = loop_count
        in_loop = prior_loops > 0 or same_line_comp
        in_async_py = async_count > 0
        opened_nested = (is_loop_opener or same_line_comp) and prior_loops >= 1

        hit = evaluate_line(
            rel_path,
            line_no,
            code,
            raw_line,
            file_rules=file_rules,
            check_nested=check_nested,
            in_loop=in_loop,
            in_enclosing_loop=prior_loops > 0,
            in_async_py=in_async_py,
            in_async_brace=False,
            in_reduce=False,
            opened_nested_loop=opened_nested,
        )
        if hit:
            hits.append(hit)

        if bracket_depth == 0:
            if is_loop_opener:
                scope_stack.append((indent, "loop"))
                loop_count += 1
            elif is_async_def:
                scope_stack.append((indent, "async_def"))
                async_count += 1

        bracket_depth = max(0, bracket_depth + line_delta)

    return hits


def scan_brace_or_generic_file(
    rel_path: str,
    ext: str,
    lines: list[str],
    file_rules: tuple[_rules.Rule, ...],
    check_nested: bool,
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    # Stack of (target_brace_depth, kind, is_parallel_map)
    scope_stack: list[tuple[int, str, bool]] = []
    seq_loop_count = 0
    any_loop_count = 0
    reduce_count = 0
    async_count = 0

    pending_kind: str | None = None
    pending_parallel = False
    pending_ttl = 0
    brace_depth = 0
    in_block_comment = False
    is_brace_lang = ext in _rules.BRACE_EXTS

    for line_no, raw_line in enumerate(lines, 1):
        code, opens, closes, in_block_comment = strip_c_comment_and_braces(
            raw_line, ext, in_block_comment, count_braces=is_brace_lang
        )
        code_stripped = code.strip()
        if not code_stripped:
            if pending_ttl > 0:
                pending_ttl -= 1
                if pending_ttl == 0:
                    pending_kind = None
                    pending_parallel = False
            continue

        is_loop_opener = is_brace_lang and bool(_rules.BRACE_LOOP_RE.search(code_stripped))
        is_reduce_line = is_brace_lang and bool(_rules.BRACE_REDUCE_RE.search(code_stripped))
        is_async_opener = is_brace_lang and bool(_rules.BRACE_ASYNC_RE.search(code_stripped))
        is_parallel_map = is_brace_lang and bool(_rules.PROMISE_ALL_MAP_RE.search(code_stripped))

        prior_seq_loops = seq_loop_count
        prior_any_loops = any_loop_count
        in_loop_seq = prior_seq_loops > 0 or (is_loop_opener and opens == 0 and not is_parallel_map)
        in_reduce = reduce_count > 0 or is_reduce_line
        in_async_brace = async_count > 0 or is_async_opener
        opened_nested = is_loop_opener and prior_any_loops >= 1 and not is_parallel_map

        hit = evaluate_line(
            rel_path,
            line_no,
            code,
            raw_line,
            file_rules=file_rules,
            check_nested=check_nested,
            in_loop=in_loop_seq,
            in_enclosing_loop=prior_seq_loops > 0,
            in_async_py=False,
            in_async_brace=in_async_brace,
            in_reduce=in_reduce,
            opened_nested_loop=opened_nested,
        )
        if hit:
            hits.append(hit)

        if is_brace_lang:
            if is_reduce_line:
                pending_kind = "reduce"
                pending_parallel = False
                pending_ttl = 3
            elif is_loop_opener:
                pending_kind = "loop"
                pending_parallel = is_parallel_map
                pending_ttl = 3
            elif is_async_opener and pending_kind is None:
                pending_kind = "async"
                pending_parallel = False
                pending_ttl = 3

            for _ in range(opens):
                brace_depth += 1
                if pending_kind is not None:
                    scope_stack.append((brace_depth, pending_kind, pending_parallel))
                    if pending_kind in ("loop", "reduce"):
                        any_loop_count += 1
                        if not pending_parallel:
                            seq_loop_count += 1
                        if pending_kind == "reduce":
                            reduce_count += 1
                    elif pending_kind == "async":
                        async_count += 1
                    pending_kind = None
                    pending_parallel = False
                    pending_ttl = 0

            for _ in range(closes):
                brace_depth = max(0, brace_depth - 1)
                while scope_stack and scope_stack[-1][0] > brace_depth:
                    _, popped_kind, popped_parallel = scope_stack.pop()
                    if popped_kind in ("loop", "reduce"):
                        any_loop_count -= 1
                        if not popped_parallel:
                            seq_loop_count -= 1
                        if popped_kind == "reduce":
                            reduce_count -= 1
                    elif popped_kind == "async":
                        async_count -= 1

            if pending_ttl > 0:
                pending_ttl -= 1
                if pending_ttl == 0:
                    pending_kind = None
                    pending_parallel = False

    return hits


def scan_target(
    target: Path,
    active_domains: set[str],
    limit: int,
    top_files: int,
    max_file_kb: int,
    include_tests: bool,
) -> dict[str, Any]:
    root = target if target.is_dir() else target.parent
    stacks = detect_stacks(root)
    profilers = detect_profilers()

    max_bytes = max_file_kb * 1024
    files_scanned = 0
    files_skipped = 0
    all_hits: list[dict[str, Any]] = []
    source_sizes: list[tuple[int, int, str]] = []
    large_assets: list[tuple[int, str]] = []
    rules_by_ext: dict[str, tuple[_rules.Rule, ...]] = {}
    check_nested = "cpu" in active_domains

    if target.is_file():
        candidates = [target]
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in _rules.SKIP_DIRS
                and (include_tests or d.lower() not in _rules.TEST_DIR_NAMES)
            )
            for fname in sorted(filenames):
                candidates.append(Path(dirpath) / fname)

    for path in candidates:
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = Path(path.name)
        rel_str = rel.as_posix()
        name = path.name
        ext = path.suffix.lower()

        try:
            size = path.stat().st_size
        except OSError:
            files_skipped += 1
            continue

        if (
            is_asset_path(rel)
            and size >= _rules.ASSET_THRESHOLD_BYTES
            and ext not in _rules.SCAN_EXTS
        ):
            large_assets.append((size, rel_str))
            continue

        if (
            name in _rules.SKIP_FILENAMES
            or name.endswith(".map")
            or name.endswith(".min.js")
            or name.endswith(".min.css")
            or ext not in _rules.SCAN_EXTS
            or (not include_tests and is_test_path(rel))
            or size > max_bytes
        ):
            files_skipped += 1
            continue

        try:
            with path.open("rb") as fh:
                head = fh.read(1024)
                if is_binary_bytes(head):
                    files_skipped += 1
                    continue
                raw_bytes = head + fh.read()
            text = raw_bytes.decode("utf-8", errors="replace")
        except OSError:
            files_skipped += 1
            continue

        files_scanned += 1
        lines = text.splitlines()
        source_sizes.append((size, len(lines), rel_str))

        file_rules = rules_by_ext.get(ext)
        if file_rules is None:
            file_rules = _rules.filter_rules(active_domains, ext)
            rules_by_ext[ext] = file_rules

        if ext in _rules.PY_EXTS:
            all_hits.extend(scan_python_file(rel_str, lines, file_rules, check_nested))
        else:
            all_hits.extend(
                scan_brace_or_generic_file(rel_str, ext, lines, file_rules, check_nested)
            )

    all_hits.sort(key=lambda h: (-h["score"], h["file"], h["line"]))
    per_file_rule: dict[tuple[str, str], int] = defaultdict(int)
    capped_hits: list[dict[str, Any]] = []
    suppressed = 0
    for hit in all_hits:
        key = (hit["file"], hit["rule"])
        per_file_rule[key] += 1
        if per_file_rule[key] <= 3:
            capped_hits.append(hit)
        else:
            suppressed += 1

    shown_hits = capped_hits[:limit]
    source_sizes.sort(reverse=True)
    large_assets.sort(reverse=True)

    return {
        "target": str(target),
        "stacks": stacks,
        "available_profilers": profilers,
        "files_scanned": files_scanned,
        "files_skipped": files_skipped,
        "total_suspects": len(all_hits),
        "suppressed_duplicates": suppressed,
        "shown_suspects": len(shown_hits),
        "suspects": shown_hits,
        "largest_sources": [
            {"file": f, "lines": ln, "kb": round(sz / 1024, 1)}
            for sz, ln, f in source_sizes[:top_files]
        ],
        "large_assets": [
            {"file": f, "kb": round(sz / 1024, 1)}
            for sz, f in large_assets[:top_files]
        ],
    }


def _md_cell(text: str, max_len: int = 80) -> str:
    cleaned = " ".join(text.replace("|", "\\|").split())
    if len(cleaned) > max_len:
        return cleaned[: max_len - 3] + "..."
    return cleaned


def print_markdown(report: dict[str, Any]) -> None:
    stacks = ", ".join(report["stacks"]) or "none detected"
    profilers = ", ".join(report["available_profilers"]) or "none"
    print(f"# Hotspot Triage: `{report['target']}`")
    print(
        f"- **Stacks:** {stacks} | **Profilers:** {profilers}\n"
        f"- **Files:** {report['files_scanned']} scanned ({report['files_skipped']} skipped) | "
        f"**Suspects:** {report['shown_suspects']} shown / {report['total_suspects']} total"
        + (
            f" ({report['suppressed_duplicates']} repeated hits suppressed)"
            if report["suppressed_duplicates"]
            else ""
        )
    )

    suspects = report["suspects"]
    if suspects:
        print("\n| Score | Domain | Rule | Location | Evidence | Why |")
        print("| ---: | --- | --- | --- | --- | --- |")
        for s in suspects:
            loc = f"`{s['file']}:{s['line']}`"
            ev = f"`{_md_cell(s['evidence'], 68)}`"
            why = _md_cell(s["why"], 72)
            print(f"| {s['score']} | {s['domain']} | `{s['rule']}` | {loc} | {ev} | {why} |")
    else:
        print("\n_No static bottleneck patterns matched in scanned files._")

    if report["largest_sources"]:
        items = ", ".join(
            f"`{f['file']}` ({f['lines']}L / {f['kb']} KB)" for f in report["largest_sources"]
        )
        print(f"\n- **Largest source files:** {items}")
    if report["large_assets"]:
        assets = ", ".join(f"`{a['file']}` ({a['kb']} KB)" for a in report["large_assets"])
        print(f"- **Large static assets (>=500 KB):** {assets}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bounded static bottleneck triage and stack/profiler reconnaissance."
    )
    parser.add_argument("target", nargs="?", default=".", help="Directory or file to scan (default: .)")
    parser.add_argument(
        "--domain",
        default="all",
        help=f"Comma-separated domains from {', '.join(_rules.ALL_DOMAINS)} or 'all' (default: all).",
    )
    parser.add_argument("--limit", type=int, default=25, help="Max suspects to output (default: 25).")
    parser.add_argument("--top-files", type=int, default=5, help="Max largest files/assets (default: 5).")
    parser.add_argument(
        "--max-file-kb", type=int, default=512, help="Skip source files larger than N KB (default: 512)."
    )
    parser.add_argument("--include-tests", action="store_true", help="Include test directories and files.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    args = parser.parse_args()

    target = Path(args.target).expanduser().resolve()
    if not target.exists():
        print(f"Error: target not found: {target}", file=sys.stderr)
        return 1

    if args.domain.strip().lower() == "all":
        active_domains = set(_rules.ALL_DOMAINS)
    else:
        requested = [d.strip().lower() for d in args.domain.split(",") if d.strip()]
        invalid = [d for d in requested if d not in _rules.ALL_DOMAINS]
        if invalid:
            print(
                f"Error: unknown domain(s): {', '.join(invalid)}. Valid: {', '.join(_rules.ALL_DOMAINS)}",
                file=sys.stderr,
            )
            return 2
        active_domains = set(requested)

    report = scan_target(
        target,
        active_domains=active_domains,
        limit=max(1, args.limit),
        top_files=max(0, args.top_files),
        max_file_kb=max(1, args.max_file_kb),
        include_tests=args.include_tests,
    )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print_markdown(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
