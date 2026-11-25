"""Static hotspot rule catalog, stack markers, and file extension filters (Python 3 stdlib)."""

from __future__ import annotations

import re
from dataclasses import dataclass

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
HASH_COMMENT_EXTS = PY_EXTS | OTHER_CODE_EXTS
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
SORTED_CALL_RE = re.compile(r"\bsorted\s*\(")


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


@dataclass(frozen=True)
class NestedLoopInfo:
    rule_id: str
    domain: str
    score: int
    why: str


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

NESTED_LOOP_INFO = NestedLoopInfo(
    rule_id="cpu-nested-loop",
    domain="cpu",
    score=72,
    why="Nested loop creates quadratic O(N*M) scaling as collection sizes grow",
)


def filter_rules(active_domains: set[str], ext: str) -> tuple[Rule, ...]:
    """Return rules applicable to both active_domains and file extension ext."""
    return tuple(
        rule
        for rule in RULES
        if rule.domain in active_domains and (rule.exts is None or ext in rule.exts)
    )
