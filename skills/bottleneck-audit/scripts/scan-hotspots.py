#!/usr/bin/env python3
"""Bounded static bottleneck triage and stack/profiler probe (Python 3 stdlib)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ALL_DOMAINS = ("db", "io", "cpu", "memory", "concurrency", "frontend")

SKIP_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "out",
    ".next",
    ".nuxt",
    "target",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    ".cache",
    "coverage",
    ".turbo",
}

TEST_DIR_NAMES = {
    "test",
    "tests",
    "__tests__",
    "__mocks__",
    "fixtures",
    "spec",
    "e2e",
    "testdata",
}

ASSET_DIR_NAMES = {"public", "static", "assets", "images", "media"}
ASSET_THRESHOLD_BYTES = 500 * 1024

SKIP_FILENAMES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "bun.lock",
    "bun.lockb",
    "poetry.lock",
    "uv.lock",
    "Cargo.lock",
    "go.sum",
    "composer.lock",
    "Gemfile.lock",
}

PY_EXTS = {".py"}
BRACE_EXTS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".vue",
    ".svelte",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".php",
    ".cs",
}
JS_EXTS = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
FRONTEND_EXTS = JS_EXTS | {".vue", ".svelte"}
SQL_EXTS = {".sql"}
OTHER_CODE_EXTS = {".rb", ".sh", ".bash", ".yaml", ".yml"}
SCAN_EXTS = PY_EXTS | BRACE_EXTS | SQL_EXTS | OTHER_CODE_EXTS

STACK_MARKERS = {
    "package.json": "Node.js",
    "tsconfig.json": "TypeScript",
    "pyproject.toml": "Python",
    "requirements.txt": "Python",
    "go.mod": "Go",
    "Cargo.toml": "Rust",
    "pom.xml": "Java (Maven)",
    "build.gradle": "Java/Kotlin (Gradle)",
    "Dockerfile": "Docker",
    "docker-compose.yml": "Docker Compose",
    ".github/workflows": "GitHub Actions",
    "prisma/schema.prisma": "Prisma",
    "alembic.ini": "Alembic",
}

PROFILER_BINS = (
    "perf",
    "py-spy",
    "hyperfine",
    "node",
    "bun",
    "go",
    "cargo",
    "psql",
    "sqlite3",
    "strace",
    "wrk",
    "oha",
    "curl",
)

PY_LOOP_RE = re.compile(r"^(?:async\s+for|for|while)\b")
PY_ASYNC_DEF_RE = re.compile(r"^async\s+def\b")
PY_COMPREHENSION_RE = re.compile(r"\bfor\s+[A-Za-z_][\w,\s()]*\s+in\b")

BRACE_LOOP_RE = re.compile(
    r"(?:\b(?:for|while)\s*(?:\(|\b)|\.(?:forEach|map|flatMap|reduce)\s*\()"
)
BRACE_REDUCE_RE = re.compile(r"\.reduce\s*\(")
BRACE_ASYNC_RE = re.compile(
    r"(?:\basync\s+function\b|\basync\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>|\basync\s+[A-Za-z_$][\w$]*\s*\()"
)
PROMISE_ALL_MAP_RE = re.compile(
    r"\bPromise\.(?:all|allSettled|race|any)\s*\(\s*[^\n]*\.map\s*\("
)


@dataclass(frozen=True)
class Rule:
    rule_id: str
    domain: str
    score: int
    why: str
    pattern: re.Pattern[str]
    require_loop: bool = False
    require_async_py: bool = False
    require_reduce: bool = False
    exts: frozenset[str] | None = None
    exclude_pattern: re.Pattern[str] | None = None
    boost_in_async_or_loop: int = 0


RULES: tuple[Rule, ...] = (
    Rule(
        rule_id="db-n-plus-one",
        domain="db",
        score=95,
        why="DB/ORM query inside loop causes 1+N network round-trips and connection hold time",
        require_loop=True,
        pattern=re.compile(
            r"(?:\b(?:cursor|conn|connection|db|pool|tx|session|prisma|knex|sequelize|mongoose|drizzle|repo|repository|client)\b[^\n;]*\.(?:execute|executemany|query|raw|exec|find|findOne|findFirst|findUnique|findMany|findAll|findByPk|findById|select|insert|update|delete|upsert|save|create|get|first|scalar|scalars|all|one|count|aggregate)\s*\(|\.(?:objects\.(?:get|filter|all|create|update|delete|exclude)|query\.(?:get|filter|filter_by|all|first)|createQueryBuilder|getRepository|QueryRow|Query|Exec)\s*\(|\b(?:SELECT\s+.+\s+FROM|INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM)\b)",
            re.IGNORECASE,
        ),
    ),
    Rule(
        rule_id="io-sequential-await",
        domain="io",
        score=90,
        why="Sequential await inside loop serializes independent I/O latencies (sum of RTTs)",
        require_loop=True,
        pattern=re.compile(r"\bawait\b"),
        exclude_pattern=re.compile(
            r"(?:^\s*async\s+for\b|\bPromise\.(?:all|allSettled|race|any)\b|\basyncio\.gather\b|\bTaskGroup\b)"
        ),
    ),
    Rule(
        rule_id="io-blocking-in-async-py",
        domain="io",
        score=90,
        why="Blocking call inside Python async def stalls the entire event loop thread",
        require_async_py=True,
        exts=frozenset(PY_EXTS),
        pattern=re.compile(
            r"\b(?:time\.sleep|requests\.(?:get|post|put|patch|delete|head|request)|urllib\.request\.urlopen|subprocess\.(?:run|call|check_output|check_call|Popen)|os\.system)\s*\("
        ),
    ),
    Rule(
        rule_id="memory-reduce-spread",
        domain="memory",
        score=86,
        why="Spreading accumulator inside .reduce() allocates and copies O(N^2) objects/elements",
        require_reduce=True,
        exts=frozenset(FRONTEND_EXTS),
        pattern=re.compile(r"\{\s*\.\.\.[A-Za-z_$][\w$]*|\[\s*\.\.\.[A-Za-z_$][\w$]*"),
    ),
    Rule(
        rule_id="io-sync-in-js",
        domain="io",
        score=85,
        boost_in_async_or_loop=10,
        why="Synchronous JS/Node call blocks the single-threaded event loop for all concurrent requests",
        exts=frozenset(JS_EXTS),
        pattern=re.compile(
            r"\b(?:readFileSync|writeFileSync|appendFileSync|readdirSync|statSync|lstatSync|existsSync|mkdirSync|rmSync|copyFileSync|execSync|execFileSync|spawnSync|pbkdf2Sync|scryptSync|deflateSync|inflateSync|gzipSync|gunzipSync)\s*\("
        ),
    ),
    Rule(
        rule_id="io-http-in-loop",
        domain="io",
        score=82,
        why="HTTP client call inside loop multiplies network RTTs and socket/TLS setup overhead",
        require_loop=True,
        pattern=re.compile(
            r"\b(?:fetch|axios(?:\.(?:get|post|put|patch|delete|request))?|got(?:\.(?:get|post|put|patch|delete))?|requests\.(?:get|post|put|patch|delete)|httpx\.(?:get|post|put|patch|delete)|http\.(?:Get|Post|Do)|reqwest::[A-Za-z_]\w*)\s*\("
        ),
    ),
    Rule(
        rule_id="frontend-layout-thrash",
        domain="frontend",
        score=82,
        why="Reading DOM geometry inside loop can trigger forced synchronous layout reflows",
        require_loop=True,
        exts=frozenset(FRONTEND_EXTS),
        pattern=re.compile(
            r"(?:\.(?:getBoundingClientRect|getClientRects|offsetHeight|offsetWidth|offsetTop|offsetLeft|clientHeight|clientWidth|scrollHeight|scrollWidth|scrollTop|scrollLeft)\b|\bgetComputedStyle\s*\()"
        ),
    ),
    Rule(
        rule_id="cpu-linear-lookup-in-loop",
        domain="cpu",
        score=80,
        why="Linear array scan, head-removal, or sort inside loop degrades runtime to O(N^2) or O(N^2 log N)",
        require_loop=True,
        pattern=re.compile(
            r"(?:\.(?:includes|indexOf|lastIndexOf|find|findIndex|some|shift|unshift|sort|sorted)\s*\(|\.pop\s*\(\s*0\s*\)|\bsorted\s*\()"
        ),
    ),
    Rule(
        rule_id="concurrency-subprocess-in-loop",
        domain="concurrency",
        score=80,
        why="Spawning OS processes inside a loop adds high fork/exec and cold-start overhead per item",
        require_loop=True,
        pattern=re.compile(
            r"\b(?:subprocess\.(?:run|Popen|call|check_output|check_call)|execSync|spawnSync|execFileSync|child_process\.(?:exec|spawn|execFile)|exec\.Command|Command::new)\s*\("
        ),
    ),
    Rule(
        rule_id="memory-full-read-in-loop",
        domain="memory",
        score=78,
        why="Reading entire files into memory inside loop causes peak RSS spikes and GC pressure",
        require_loop=True,
        pattern=re.compile(
            r"(?:\.(?:readFile|readFileSync|read_text|read_bytes|readlines)\s*\(|\bfs\.promises\.readFile\s*\(|\bos\.ReadFile\s*\(|\bioutil\.ReadFile\s*\()"
        ),
    ),
    Rule(
        rule_id="cpu-regex-or-clone-in-loop",
        domain="cpu",
        score=76,
        why="Re-compiling regexes or deep-cloning inside loop wastes CPU and triggers allocation churn",
        require_loop=True,
        pattern=re.compile(
            r"(?:\bre\.compile\s*\(|\bnew\s+RegExp\s*\(|JSON\.parse\s*\(\s*JSON\.stringify\s*\(|\bcopy\.deepcopy\s*\()"
        ),
    ),
    Rule(
        rule_id="concurrency-unbounded-promise-all",
        domain="concurrency",
        score=75,
        why="Unbounded Promise.all(items.map(...)) can exhaust connection pools, FDs, or downstream limits",
        exts=frozenset(FRONTEND_EXTS),
        pattern=re.compile(r"\bPromise\.(?:all|allSettled)\s*\(\s*[A-Za-z_$][\w$.]*\.map\s*\("),
    ),
    Rule(
        rule_id="db-select-star-or-leading-wildcard",
        domain="db",
        score=74,
        why="SELECT * blocks covering index-only scans; leading '%...' breaks B-tree index lookups",
        pattern=re.compile(r"(?:\bSELECT\s+\*\s+FROM\b|\bI?LIKE\s+['\"]%)", re.IGNORECASE),
    ),
    Rule(
        rule_id="frontend-full-lib-import",
        domain="frontend",
        score=74,
        why="Root/namespace import of heavy utility or icon pack inflates bundle size and parse CPU",
        exts=frozenset(FRONTEND_EXTS),
        pattern=re.compile(
            r"(?:import\s+(?:\*\s+as\s+\w+|[A-Za-z_$][\w$]*)\s+from\s+['\"](?:lodash|moment|@mui/icons-material|lucide-react|date-fns|rxjs)['\"]|require\s*\(\s*['\"](?:lodash|moment)['\"]\s*\))"
        ),
    ),
    Rule(
        rule_id="db-unbounded-query",
        domain="db",
        score=70,
        why="Unbounded ORM fetch without limit/pagination loads entire table into DB I/O and app RAM",
        pattern=re.compile(
            r"(?:\.(?:findAll|findMany)\s*\(\s*(?:\{\s*\})?\s*\)|\.objects\.all\s*\(\s*\))"
        ),
    ),
)

NESTED_LOOP_RULE = Rule(
    rule_id="cpu-nested-loop",
    domain="cpu",
    score=72,
    why="Nested loop creates quadratic O(N*M) scaling as collection sizes grow",
    pattern=re.compile(r""),
)


def is_test_path(rel_path: Path) -> bool:
    for part in rel_path.parts[:-1]:
        if part.lower() in TEST_DIR_NAMES:
            return True
    name = rel_path.name.lower()
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.go"):
        return True
    if ".test." in name or ".spec." in name:
        return True
    return False


def is_asset_path(rel_path: Path) -> bool:
    return any(part.lower() in ASSET_DIR_NAMES for part in rel_path.parts[:-1])


def is_binary_bytes(sample: bytes) -> bool:
    return b"\x00" in sample


def _iter_unquoted(
    code: str, *, allow_backtick: bool = True, escape_in_single: bool = True
):
    """Yield (index, char) pairs outside single, double, and optional backtick strings."""
    in_single = False
    in_double = False
    in_backtick = False
    escaped = False
    for i, ch in enumerate(code):
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
            elif ch == "\\" and escape_in_single:
                escaped = True
            elif ch == "'":
                in_single = False
        elif in_backtick:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == "`":
                in_backtick = False
        else:
            if ch == '"':
                in_double = True
            elif ch == "'":
                in_single = True
            elif ch == "`" and allow_backtick:
                in_backtick = True
            else:
                yield i, ch


def strip_line_comment(line: str, ext: str, in_block_comment: bool) -> tuple[str, bool]:
    """Strip comments outside string literals; also track /* ... */ block state for brace/SQL files."""
    if ext in PY_EXTS or ext in {".rb", ".sh", ".bash", ".yaml", ".yml"}:
        for i, ch in _iter_unquoted(line, allow_backtick=False):
            if ch == "#":
                return line[:i], False
        return line, False

    out: list[str] = []
    i = 0
    n = len(line)
    in_single = False
    in_double = False
    in_backtick = False
    escaped = False
    sql_mode = ext in SQL_EXTS

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
            elif (in_double and ch == '"') or (in_single and ch == "'") or (in_backtick and ch == "`"):
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

        out.append(ch)
        i += 1

    return "".join(out), in_block_comment


def count_braces_outside_strings(code: str) -> tuple[int, int]:
    opens = 0
    closes = 0
    for _, ch in _iter_unquoted(code, allow_backtick=True):
        if ch == "{":
            opens += 1
        elif ch == "}":
            closes += 1
    return opens, closes


def count_all_brackets(code: str) -> int:
    """Net paren/bracket/brace delta outside strings for Python multiline grouping."""
    delta = 0
    for _, ch in _iter_unquoted(code, allow_backtick=False):
        if ch in "([{":
            delta += 1
        elif ch in ")]}":
            delta -= 1
    return delta


def detect_stacks(root: Path) -> list[str]:
    found: set[str] = set()
    roots = [root]
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name not in SKIP_DIRS and not child.name.startswith("."):
                roots.append(child)
    except OSError:
        pass
    for base in roots:
        for marker, label in STACK_MARKERS.items():
            if (base / marker).exists():
                found.add(label)
    return sorted(found)


def detect_profilers() -> list[str]:
    return [b for b in PROFILER_BINS if shutil.which(b)]


def evaluate_line(
    rel_path: str,
    ext: str,
    line_no: int,
    code: str,
    raw_line: str,
    *,
    in_loop: bool,
    in_enclosing_loop: bool,
    in_async_py: bool,
    in_async_brace: bool,
    in_reduce: bool,
    opened_nested_loop: bool,
    active_domains: set[str],
) -> dict[str, Any] | None:
    best: tuple[int, dict[str, Any]] | None = None

    for rule in RULES:
        if rule.domain not in active_domains:
            continue
        if rule.exts is not None and ext not in rule.exts:
            continue
        if rule.require_loop and not in_loop:
            continue
        if rule.rule_id == "cpu-linear-lookup-in-loop" and not in_enclosing_loop and re.search(r"\bsorted\s*\(", code):
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

    if opened_nested_loop and "cpu" in active_domains:
        cand = {
            "score": NESTED_LOOP_RULE.score,
            "domain": NESTED_LOOP_RULE.domain,
            "rule": NESTED_LOOP_RULE.rule_id,
            "file": rel_path,
            "line": line_no,
            "evidence": raw_line.strip()[:120],
            "why": NESTED_LOOP_RULE.why,
        }
        if best is None or NESTED_LOOP_RULE.score > best[0]:
            best = (NESTED_LOOP_RULE.score, cand)

    return best[1] if best else None


def scan_python_file(
    rel_path: str,
    lines: list[str],
    active_domains: set[str],
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    # Stack of (indent, kind) where kind in {"loop", "async_def"}
    scope_stack: list[tuple[int, str]] = []
    bracket_depth = 0
    in_triple: str | None = None

    for line_no, raw_line in enumerate(lines, 1):
        stripped_raw = raw_line.strip()
        # Lightweight multiline docstring skip
        if in_triple:
            if in_triple in stripped_raw:
                in_triple = None
            continue
        if stripped_raw.startswith(('"""', "'''")):
            delim = stripped_raw[:3]
            if stripped_raw.count(delim) == 1:
                in_triple = delim
            continue

        code, _ = strip_line_comment(raw_line, ".py", False)
        code_stripped = code.strip()
        if not code_stripped:
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" \t"))
        if bracket_depth == 0:
            while scope_stack and scope_stack[-1][0] >= indent:
                scope_stack.pop()

        is_loop_opener = bool(PY_LOOP_RE.match(code_stripped))
        is_async_def = bool(PY_ASYNC_DEF_RE.match(code_stripped))
        same_line_comp = bool(PY_COMPREHENSION_RE.search(code_stripped)) and not is_loop_opener

        prior_loops = sum(1 for _, k in scope_stack if k == "loop")
        in_loop = prior_loops > 0 or same_line_comp
        in_async_py = any(k == "async_def" for _, k in scope_stack)
        opened_nested = (is_loop_opener or same_line_comp) and prior_loops >= 1

        hit = evaluate_line(
            rel_path,
            ".py",
            line_no,
            code,
            raw_line,
            in_loop=in_loop,
            in_enclosing_loop=prior_loops > 0,
            in_async_py=in_async_py,
            in_async_brace=False,
            in_reduce=False,
            opened_nested_loop=opened_nested,
            active_domains=active_domains,
        )
        if hit:
            hits.append(hit)

        if bracket_depth == 0:
            if is_loop_opener:
                scope_stack.append((indent, "loop"))
            elif is_async_def:
                scope_stack.append((indent, "async_def"))

        bracket_depth = max(0, bracket_depth + count_all_brackets(code))

    return hits


def scan_brace_or_generic_file(
    rel_path: str,
    ext: str,
    lines: list[str],
    active_domains: set[str],
) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    # Stack of (target_brace_depth, kind, is_parallel_map)
    scope_stack: list[tuple[int, str, bool]] = []
    pending_kind: str | None = None
    pending_parallel = False
    pending_ttl = 0
    brace_depth = 0
    in_block_comment = False
    is_brace_lang = ext in BRACE_EXTS

    for line_no, raw_line in enumerate(lines, 1):
        code, in_block_comment = strip_line_comment(raw_line, ext, in_block_comment)
        code_stripped = code.strip()
        if not code_stripped:
            if pending_ttl > 0:
                pending_ttl -= 1
                if pending_ttl == 0:
                    pending_kind = None
                    pending_parallel = False
            continue

        opens, closes = count_braces_outside_strings(code) if is_brace_lang else (0, 0)
        is_loop_opener = is_brace_lang and bool(BRACE_LOOP_RE.search(code_stripped))
        is_reduce_line = is_brace_lang and bool(BRACE_REDUCE_RE.search(code_stripped))
        is_async_opener = is_brace_lang and bool(BRACE_ASYNC_RE.search(code_stripped))
        is_parallel_map = is_brace_lang and bool(PROMISE_ALL_MAP_RE.search(code_stripped))

        prior_seq_loops = sum(
            1 for _, kind, parallel in scope_stack if kind in ("loop", "reduce") and not parallel
        )
        prior_any_loops = sum(1 for _, kind, _ in scope_stack if kind in ("loop", "reduce"))
        in_loop_seq = prior_seq_loops > 0 or (is_loop_opener and opens == 0 and not is_parallel_map)
        in_reduce = any(kind == "reduce" for _, kind, _ in scope_stack) or is_reduce_line
        in_async_brace = any(kind == "async" for _, kind, _ in scope_stack) or is_async_opener
        opened_nested = is_loop_opener and prior_any_loops >= 1 and not is_parallel_map

        hit = evaluate_line(
            rel_path,
            ext,
            line_no,
            code,
            raw_line,
            in_loop=in_loop_seq,
            in_enclosing_loop=prior_seq_loops > 0,
            in_async_py=False,
            in_async_brace=in_async_brace,
            in_reduce=in_reduce,
            opened_nested_loop=opened_nested,
            active_domains=active_domains,
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
                    pending_kind = None
                    pending_parallel = False
                    pending_ttl = 0

            for _ in range(closes):
                brace_depth = max(0, brace_depth - 1)
                while scope_stack and scope_stack[-1][0] > brace_depth:
                    scope_stack.pop()

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

    if target.is_file():
        candidates = [target]
    else:
        candidates = []
        for dirpath, dirnames, filenames in os.walk(target):
            dirnames[:] = sorted(
                d
                for d in dirnames
                if d not in SKIP_DIRS
                and (include_tests or d.lower() not in TEST_DIR_NAMES)
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

        if is_asset_path(rel) and size >= ASSET_THRESHOLD_BYTES and ext not in SCAN_EXTS:
            large_assets.append((size, rel_str))
            continue

        if (
            name in SKIP_FILENAMES
            or name.endswith(".map")
            or name.endswith(".min.js")
            or name.endswith(".min.css")
            or ext not in SCAN_EXTS
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

        if ext in PY_EXTS:
            all_hits.extend(scan_python_file(rel_str, lines, active_domains))
        else:
            all_hits.extend(scan_brace_or_generic_file(rel_str, ext, lines, active_domains))

    # Cap per (file, rule) to 3 occurrences and sort by severity
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
        help=f"Comma-separated domains from {', '.join(ALL_DOMAINS)} or 'all' (default: all).",
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
        active_domains = set(ALL_DOMAINS)
    else:
        requested = [d.strip().lower() for d in args.domain.split(",") if d.strip()]
        invalid = [d for d in requested if d not in ALL_DOMAINS]
        if invalid:
            print(
                f"Error: unknown domain(s): {', '.join(invalid)}. Valid: {', '.join(ALL_DOMAINS)}",
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
