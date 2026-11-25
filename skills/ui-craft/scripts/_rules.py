"""Rule engine, comment masking, waiver parsing, and redesign snapshot contract for ui-craft."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

SUPPORTED_EXTS = {
    ".html",
    ".htm",
    ".css",
    ".templ",
    ".jsx",
    ".tsx",
    ".vue",
    ".svelte",
    ".astro",
}
MARKUP_EXTS = SUPPORTED_EXTS - {".css"}
SKIP_DIRS = {
    ".git",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".astro",
    ".ui-craft",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    "__pycache__",
    "target",
}
MAX_FILE_BYTES = 512 * 1024
MAX_CSS_LINE_LEN = 2000

PROFILES = ("commercial", "editorial", "app")
SCOPES = ("page", "component", "app")
TIERS = ("floor", "reflex", "all")

WAIVER_RE = re.compile(r"ui-craft-waive:\s*([A-Za-z0-9-]+)\s*\(([^)\n]*)\)", re.IGNORECASE)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

CLASS_ATTR_RE = re.compile(
    r"""\bclass(?:Name)?\s*=\s*(?:"([^"]*)"|'([^']*)'|\{([^}\n]*)\})"""
)
STYLE_ATTR_RE = re.compile(r"""\bstyle\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
INLINE_COLOR_PROP_RE = re.compile(
    r"""(?:^|;)\s*(?:color|background(?:-color)?|border(?:-color)?)\s*:\s*(?:#[0-9a-fA-F]{3,8}\b|rgba?\()""",
    re.IGNORECASE,
)

FOCUS_NONE_RE = re.compile(r"(?<![-\w])(?:focus:)?outline-(?:none|0)(?![-\w])")
FOCUS_RING_RE = re.compile(r"(?:focus-visible:ring|focus-visible:outline)")
CSS_OUTLINE_NONE_RE = re.compile(r"\boutline\s*:\s*(?:none|0)\b", re.IGNORECASE)

BUTTON_BLOCK_RE = re.compile(r"<button\b([^>]*)>(.*?)</button>", re.DOTALL | re.IGNORECASE)
SVG_BLOCK_RE = re.compile(r"<svg\b.*?</svg>", re.DOTALL | re.IGNORECASE)
BTN_A11Y_ATTR_RE = re.compile(r"\b(?:aria-label|aria-labelledby|title)\s*=", re.IGNORECASE)
SR_ONLY_RE = re.compile(r"\bsr-only\b")

IMG_TAG_RE = re.compile(r"""<img\b((?:[^>"']|"[^"]*"|'[^']*')*)/?>""", re.IGNORECASE | re.DOTALL)
ALT_ATTR_RE = re.compile(r"\balt\s*=", re.IGNORECASE)
IMG_LOADING_RE = re.compile(r"\bloading\s*=", re.IGNORECASE)
IMG_DECODING_RE = re.compile(r"\bdecoding\s*=", re.IGNORECASE)
IMG_EAGER_RE = re.compile(r"""(?:fetchpriority\s*=\s*["']high["']|loading\s*=\s*["']eager["'])""", re.IGNORECASE)
HERO_SECTION_RE = re.compile(r"<(?:section|header)\b[^>]*\bhero\b", re.IGNORECASE)

RIGID_WIDTH_RE = re.compile(r"(?<![-:\w])w-\[(?:3[7-9]\d|[4-9]\d{2}|\d{4,})px\]")
MAX_W_RE = re.compile(r"\bmax-w-")
W_SCREEN_RE = re.compile(r"(?<![-:\w])w-screen(?![-\w])")
CSS_100VW_RE = re.compile(r"\bwidth\s*:\s*100vw\b", re.IGNORECASE)

CSS_TRANSITION_ALL_RE = re.compile(r"\btransition(?:-property)?\s*:\s*[^;]*\ball\b", re.IGNORECASE)
CLASS_TRANSITION_ALL_RE = re.compile(r"(?<![-\w])(?:[a-z0-9-]+:)*transition-all(?![-\w])")
CSS_LAYOUT_PROP_RE = re.compile(
    r"(?<![-\w])(?:width|height|top|left|margin(?:-(?:top|right|bottom|left))?|padding(?:-(?:top|right|bottom|left))?)\b",
    re.IGNORECASE,
)
CSS_TRANSITION_DECL_RE = re.compile(r"\btransition(?:-property)?\s*:\s*([^;{}]+)", re.IGNORECASE)
CSS_KEYFRAME_PROP_RE = re.compile(
    r"(?<![-\w])(?:width|height|top|left|margin(?:-(?:top|right|bottom|left))?|padding(?:-(?:top|right|bottom|left))?)\s*:",
    re.IGNORECASE,
)

OPACITY_ZERO_RE = re.compile(r"\bopacity-0\b")
TRANSLATE_Y_HIDE_RE = re.compile(r"\btranslate-y-(?:[4-9]|1\d+)\b")
NOJS_GUARD_RE = re.compile(r"(?:\bno-js\b|\bdata-js\b|\bjs:|x-cloak\b|x-transition\b)")

SLOP_FROM_RE = re.compile(r"\bfrom-(?:indigo|purple|violet)-\d{2,3}\b")
SLOP_TO_VIA_RE = re.compile(r"\b(?:to-(?:purple|indigo|violet|pink|cyan|blue)-\d{2,3}|via-(?:purple|indigo|violet)-\d{2,3})\b")
BG_CLIP_TEXT_RE = re.compile(r"\bbg-clip-text\b")
TEXT_TRANSPARENT_RE = re.compile(r"\btext-transparent\b")

TW_HEX_RE = re.compile(r"\b(?:bg|text|border|fill|stroke|ring|from|to|via)-\[#[0-9a-fA-F]{3,8}\]")
CSS_COLOR_DECL_RE = re.compile(
    r"(?:^|[;{]\s*)(color|background(?:-color)?|border(?:-color)?|fill|stroke|outline-color)\s*:\s*([^;{}]+)",
    re.IGNORECASE,
)
VAR_EXPR_RE = re.compile(r"var\([^)]*\)")
HEX_OR_RGB_RE = re.compile(r"(?:#[0-9a-fA-F]{3,8}\b|\brgba?\()", re.IGNORECASE)

CLICHE_RE = re.compile(
    r"(?:"
    r"инновационные\s+решения|лидеры\s+рынка|революционный\s+подход|раскройте\s+потенциал|"
    r"в\s+современном\s+(?:быстро\s+меняющемся\s+)?мире|индивидуальный\s+подход\s+к\s+каждому|"
    r"высококачественн\w+\s+услуг\w*|экосистема\s+будущего|"
    r"supercharge\s+your|unleash\s+the\s+power\s+of|seamlessly\s+integrat\w+|"
    r"elevate\s+your|next-generation\s+platform|all-in-one\s+solution|"
    r"in\s+today['’]s\s+fast-paced\s+world"
    r")",
    re.IGNORECASE,
)
FAKE_PROOF_RE = re.compile(
    r"(?:lorem\s+ipsum|acme\s+corp|\bjohn\s+doe\b|\bjane\s+doe\b|10[,\s]?000\+\s+(?:happy|satisfied)\s+customers)",
    re.IGNORECASE,
)

BLUR_ORB_RE = re.compile(r"\bblur-(?:2xl|3xl)\b")
CSS_BLUR_ORB_RE = re.compile(r"\bblur\(\s*(?:4\d|[5-9]\d|\d{3,})px\s*\)", re.IGNORECASE)
BACKDROP_BLUR_RE = re.compile(r"\bbackdrop-blur-(?:sm|md|lg|xl|2xl)\b")
GLASS_BG_RE = re.compile(r"\bbg-(?:white|black|neutral-\d+)/\d+\b")
RAW_GRAY_RE = re.compile(r"\b(?:bg|text|border|divide|ring)-(?:gray|slate|zinc|neutral|stone)-\d{2,3}\b")
TW_SLOW_RE = re.compile(r"\bduration-(?:500|700|1000)\b")
CSS_SLOW_RE = re.compile(
    r"\btransition(?:-duration)?\s*:[^;]*\b(?:0\.[5-9]|[1-9](?:\.\d+)?)s\b|\b(?:500|6\d\d|7\d\d|8\d\d|9\d\d|\d{4,})ms\b",
    re.IGNORECASE,
)
ROUNDED_LARGE_RE = re.compile(r"\brounded-(?:2xl|3xl)\b")
CRAMPED_PAD_RE = re.compile(r"\bp-(?:1|2|2\.5|3)\b")
ITALIC_HEADING_RE = re.compile(r"<h[1-3]\b[^>]*>.*?<(?:em|i)\b", re.IGNORECASE | re.DOTALL)
UI_EMOJI_CONTAINER_RE = re.compile(r"<(h[1-6]|button|a|nav)\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)
EMOJI_CHARS_RE = re.compile(r"[🚀✨🔥💡⚡🎯✅💎]")

EYEBROW_LINE_RE = re.compile(
    r"(?:\bsection-badge\b|\beyebrow\b|<(?:span|p|div)\b[^>]*class=[\"'][^\"']*(?:(?:rounded-full|rounded-badge)[^\"']*\btext-xs\b|\btext-xs\b[^\"']*(?:rounded-full|rounded-badge))[^\"']*[\"'])",
    re.IGNORECASE,
)
HEADING_1_3_RE = re.compile(r"<h[1-3]\b", re.IGNORECASE)
UPPERCASE_RE = re.compile(r"\buppercase\b")
TRACKING_WIDE_RE = re.compile(r"\btracking-(?:wide|wider|widest)\b")
APP_CAPS_TAG_RE = re.compile(r"<(?:th|label)\b", re.IGNORECASE)
ARROW_BTN_LINK_RE = re.compile(r"<(?:button|a)\b[^>]*>.*?(?:→|->|&rarr;).*?</(?:button|a)>", re.IGNORECASE | re.DOTALL)
STATUS_DOT_PING_RE = re.compile(r"\banimate-(?:ping|pulse)\b")
STATUS_DOT_SIZE_RE = re.compile(r"\b(?:w|h)-[1-3]\b")
ROUNDED_FULL_RE = re.compile(r"\brounded-full\b")
MID_DOT_CHAIN_RE = re.compile(r">[^<\n]*(?:·[^<\n]{1,40}·|•[^<\n]{1,40}•)[^<\n]*<")

CARD_TAG_OPEN_RE = re.compile(
    r"""<(/)?(div|article|section|li|aside)\b((?:[^>"']|"[^"]*"|'[^']*')*)(/?)>""",
    re.IGNORECASE | re.DOTALL,
)
CARD_BASE_RE = re.compile(r"\bcard-(?:base|interactive|sm)\b")
BORDER_TOKEN_RE = re.compile(r"\bborder(?:-[a-z0-9/]+)?\b")
ROUNDED_CARD_RE = re.compile(r"\brounded-(?:md|lg|xl|2xl|3xl|card(?:-sm)?)\b")
BG_SURFACE_RE = re.compile(r"\bbg-surface(?:-muted)?\b")

REDUCED_MOTION_RE = re.compile(r"@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)", re.IGNORECASE)
CSS_HAS_MOTION_RE = re.compile(r"(?:@keyframes\b|\btransition(?:-duration|-property)?\s*:)", re.IGNORECASE)
TABULAR_TRIGGER_RE = re.compile(r"(?:<table\b|\b(?:kpi|stat-value|metric-value|price|invoice-total)\b)", re.IGNORECASE)
TABULAR_VALUE_RE = re.compile(r"(?:\btabular-nums\b|font-variant-numeric\s*:\s*tabular-nums)", re.IGNORECASE)
APP_DYNAMIC_DATA_RE = re.compile(r"(?:<table\b|\.map\s*\(|\bfor\b[^<\n]*:=|\bv-for=|\{#each\b)", re.IGNORECASE)
APP_STATES_OK_RE = re.compile(
    r"(?:\bempty\b|\bloading\b|\bskeleton\b|\berror\b|no\s+results|нет\s+данных|пусто|загрузка|ошибка)",
    re.IGNORECASE,
)

# Snapshot extractors
HREF_RE = re.compile(r"""\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
FORM_TAG_RE = re.compile(r"<form\b([^>]*)>", re.IGNORECASE | re.DOTALL)
ACTION_ATTR_RE = re.compile(r"""\baction\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
METHOD_ATTR_RE = re.compile(r"""\bmethod\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
HTMX_EP_RE = re.compile(r"""\b(hx-(?:get|post|put|patch|delete))\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.IGNORECASE)
INPUT_NAME_RE = re.compile(
    r"""<(?:input|select|textarea)\b[^>]*\bname\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.IGNORECASE | re.DOTALL,
)
TEST_HOOK_RE = re.compile(
    r"""\b(data-(?:testid|component|source|field|block))\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.IGNORECASE,
)
HANDLER_RE = re.compile(
    r"""\b(hx-trigger|x-model|x-on:[a-z0-9.-]+|@[a-z0-9.-]+|onClick|onSubmit)\s*=\s*(?:"([^"]*)"|'([^']*)'|\{([^}\n]*)\})""",
    re.IGNORECASE,
)
HEADING_12_RE = re.compile(r"<h([12])\b[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
STRIP_TAGS_RE = re.compile(r"<[^>]+>")


def _keep_newlines(match: re.Match[str]) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def is_minified_css(path: Path, text: str | None = None) -> bool:
    """Return True if a file is a minified, oversized, or compiled CSS bundle."""
    name = path.name.lower()
    if name.endswith(".min.css"):
        return True
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return True
    except OSError:
        return False
    if path.suffix.lower() == ".css":
        if text is None:
            text = path.read_text(encoding="utf-8", errors="replace")
        head = text[:400].lower()
        if "/*! tailwindcss" in head:
            return True
        for line in text.splitlines():
            if len(line) > MAX_CSS_LINE_LEN:
                return True
    return False


def collect_files(paths: list[str | Path]) -> tuple[list[Path], list[str]]:
    """Collect supported UI/style files, skipping build dirs and minified CSS bundles."""
    found: list[Path] = []
    skipped_minified: list[str] = []
    seen: set[Path] = set()

    for raw in paths:
        p = Path(raw)
        if not p.exists():
            raise FileNotFoundError(f"Path not found: {raw}")
        if p.is_file():
            resolved = p.resolve()
            if resolved in seen or resolved.suffix.lower() not in SUPPORTED_EXTS:
                continue
            seen.add(resolved)
            if is_minified_css(resolved):
                skipped_minified.append(str(resolved))
            else:
                found.append(resolved)
            continue

        for root, dirs, files in os.walk(p):
            dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
            for fname in sorted(files):
                fp = (Path(root) / fname).resolve()
                if fp in seen or fp.suffix.lower() not in SUPPORTED_EXTS:
                    continue
                seen.add(fp)
                if is_minified_css(fp):
                    skipped_minified.append(str(fp))
                else:
                    found.append(fp)

    return sorted(found), skipped_minified


def _mask_block_comments(text: str, ext: str) -> str:
    """Mask `/* ... */` comments outside quoted strings while preserving newlines."""
    out: list[str] = []
    i = 0
    n = len(text)
    in_double = False
    in_single = False
    track_single = ext == ".css"

    while i < n:
        ch = text[i]
        if ch == "\n":
            in_double = False
            in_single = False
            out.append(ch)
            i += 1
            continue
        if in_double:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue
        if in_single:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue
        if ch == '"':
            in_double = True
            out.append(ch)
            i += 1
            continue
        if track_single and ch == "'":
            in_single = True
            out.append(ch)
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end = text.find("*/", i + 2)
            stop = n if end == -1 else end + 2
            out.append(re.sub(r"[^\n]", " ", text[i:stop]))
            i = stop
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _mask_line_slash_comments(text: str) -> str:
    """Mask `// ...` comments only when preceded by SOL or whitespace and outside double quotes."""
    masked_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        in_double = False
        cut_at: int | None = None
        i = 0
        n = len(line)
        while i < n:
            ch = line[i]
            if in_double:
                if ch == "\\" and i + 1 < n:
                    i += 2
                    continue
                if ch == '"':
                    in_double = False
                i += 1
                continue
            if ch == '"':
                in_double = True
                i += 1
                continue
            if ch == "/" and i + 1 < n and line[i + 1] == "/":
                if i == 0 or line[i - 1] in " \t":
                    cut_at = i
                    break
            i += 1
        if cut_at is None:
            masked_lines.append(line)
        else:
            tail = line[cut_at:]
            nl = "\n" if tail.endswith("\n") else ""
            core_len = len(tail) - len(nl)
            masked_lines.append(line[:cut_at] + (" " * core_len) + nl)
    return "".join(masked_lines)


def mask_comments(text: str, ext: str) -> str:
    """Replace comments with spaces while preserving line numbers and URL literals."""
    ext_l = ext.lower()
    masked = text
    if ext_l != ".css":
        masked = HTML_COMMENT_RE.sub(_keep_newlines, masked)
    masked = _mask_block_comments(masked, ext_l)
    if ext_l != ".css":
        masked = _mask_line_slash_comments(masked)
    return masked


def parse_waivers(raw_text: str, masked_text: str) -> dict[str, Any]:
    """Extract file-level and line-level waivers from raw comment lines."""
    raw_lines = raw_text.splitlines()
    masked_lines = masked_text.splitlines()
    while len(masked_lines) < len(raw_lines):
        masked_lines.append("")

    comment_only = [ml.strip(" \t{}") == "" for ml in masked_lines]
    file_waivers: dict[str, str] = {}
    line_waivers: dict[int, dict[str, str]] = {}

    for idx, raw_line in enumerate(raw_lines, start=1):
        matches = list(WAIVER_RE.finditer(raw_line))
        if not matches:
            continue
        is_c_only = comment_only[idx - 1]
        for m in matches:
            rid = m.group(1).upper()
            reason = m.group(2).strip()
            if idx <= 50 and is_c_only:
                file_waivers[rid] = reason
            else:
                line_waivers.setdefault(idx, {})[rid] = reason

    return {
        "file_waivers": file_waivers,
        "line_waivers": line_waivers,
        "comment_only": comment_only,
    }


def _find_waiver_for_line(
    rule_id: str,
    line_no: int,
    waiver_info: dict[str, Any],
) -> tuple[bool, str | None]:
    line_waivers: dict[int, dict[str, str]] = waiver_info["line_waivers"]
    comment_only: list[bool] = waiver_info["comment_only"]
    file_waivers: dict[str, str] = waiver_info["file_waivers"]

    if rule_id in line_waivers.get(line_no, {}):
        return True, line_waivers[line_no][rule_id]

    cur = line_no - 1
    while cur >= 1 and comment_only[cur - 1]:
        if rule_id in line_waivers.get(cur, {}):
            return True, line_waivers[cur][rule_id]
        cur -= 1

    if rule_id in file_waivers:
        return True, file_waivers[rule_id]
    return False, None


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _snippet(lines: list[str], line_no: int) -> str:
    if 1 <= line_no <= len(lines):
        return lines[line_no - 1].strip()[:110]
    return ""


def _iter_class_attrs(masked_text: str) -> list[tuple[int, str, str]]:
    """Return list of (line_no, class_value, line_text) for each class attribute."""
    lines = masked_text.splitlines()
    results: list[tuple[int, str, str]] = []
    for m in CLASS_ATTR_RE.finditer(masked_text):
        cls_val = next((g for g in m.groups() if g is not None), "")
        line_no = _line_of_offset(masked_text, m.start())
        line_txt = lines[line_no - 1] if 1 <= line_no <= len(lines) else ""
        results.append((line_no, cls_val, line_txt))
    return results


def _iter_css_blocks(masked_text: str) -> list[tuple[str, int, str]]:
    """Extract top-level and nested CSS selector/at-rule headers with body and start line."""
    blocks: list[tuple[str, int, str]] = []
    brace_re = re.compile(r"([^{};]+)\{")
    n = len(masked_text)
    for m in brace_re.finditer(masked_text):
        selector = " ".join(m.group(1).split())
        start = m.end()
        depth = 1
        i = start
        while i < n and depth > 0:
            if masked_text[i] == "{":
                depth += 1
            elif masked_text[i] == "}":
                depth -= 1
            i += 1
        body = masked_text[start : i - 1]
        blocks.append((selector, _line_of_offset(masked_text, m.start()), body))
    return blocks


def _css_token_context_lines(masked_text: str) -> set[int]:
    """Return 1-based line numbers inside `:root`, `@theme`, or `[data-theme` blocks."""
    token_lines: set[int] = set()
    for selector, start_line, body in _iter_css_blocks(masked_text):
        sel_low = selector.lower()
        if ":root" in sel_low or "@theme" in sel_low or "[data-theme" in sel_low:
            end_line = start_line + body.count("\n")
            token_lines.update(range(start_line, end_line + 1))
    return token_lines


def _add_finding(
    findings: list[dict[str, Any]],
    *,
    rule_id: str,
    tier: str,
    category: str,
    file_path: Path,
    line: int,
    message: str,
    snippet: str,
    fix: str,
    waiver_info: dict[str, Any],
) -> None:
    has_waiver, reason = _find_waiver_for_line(rule_id, line, waiver_info)
    waived = False
    waiver_reason: str | None = None
    rejected: str | None = None

    if has_waiver:
        if tier == "FLOOR":
            rejected = "FLOOR rules cannot be waived"
        elif tier == "REFLEX":
            if reason is not None and len(reason.strip()) >= 4:
                waived = True
                waiver_reason = reason.strip()
            else:
                rejected = "Waiver requires a concrete reason (>= 4 chars)"

    item: dict[str, Any] = {
        "id": rule_id,
        "tier": tier,
        "category": category,
        "file": str(file_path),
        "line": line,
        "message": message,
        "snippet": snippet,
        "fix": fix,
        "waived": waived,
        "waiver_reason": waiver_reason,
    }
    if rejected:
        item["waiver_rejected"] = rejected
    findings.append(item)


def _check_markup_file(
    file_path: Path,
    masked: str,
    raw_lines: list[str],
    waiver_info: dict[str, Any],
    profile: str,
    findings: list[dict[str, Any]],
) -> None:
    masked_lines = masked.splitlines()
    cls_attrs = _iter_class_attrs(masked)

    def emit(rid: str, tier: str, cat: str, line: int, msg: str, fix: str) -> None:
        _add_finding(
            findings,
            rule_id=rid,
            tier=tier,
            category=cat,
            file_path=file_path,
            line=line,
            message=msg,
            snippet=_snippet(raw_lines, line),
            fix=fix,
            waiver_info=waiver_info,
        )

    # Class-attribute rules
    for line, cls_val, line_txt in cls_attrs:
        if FOCUS_NONE_RE.search(cls_val) and not FOCUS_RING_RE.search(cls_val):
            emit(
                "FLR-A11Y-FOCUS",
                "FLOOR",
                "a11y",
                line,
                "outline-none without focus-visible:ring or focus-visible:outline",
                "Add focus-visible:ring-2 focus-visible:ring-accent (or focus-visible:outline).",
            )
        if RIGID_WIDTH_RE.search(cls_val) and not MAX_W_RE.search(cls_val):
            emit(
                "FLR-LYT-OVERFLOW",
                "FLOOR",
                "layout",
                line,
                "Rigid width w-[>360px] without max-w-* overflows 390px mobile viewports",
                "Pair with max-w-full or replace with max-w-[...] + w-full.",
            )
        if W_SCREEN_RE.search(cls_val):
            emit(
                "FLR-LYT-OVERFLOW",
                "FLOOR",
                "layout",
                line,
                "w-screen (100vw) causes horizontal overflow when scrollbars appear",
                "Use w-full instead of w-screen.",
            )
        if CLASS_TRANSITION_ALL_RE.search(cls_val):
            emit(
                "FLR-MOT-TRANSITION-ALL",
                "FLOOR",
                "motion",
                line,
                "transition-all animates layout and paint properties",
                "Specify transition-colors, transition-transform, or transition-opacity.",
            )
        if OPACITY_ZERO_RE.search(cls_val) and TRANSLATE_Y_HIDE_RE.search(cls_val):
            if not NOJS_GUARD_RE.search(cls_val) and not NOJS_GUARD_RE.search(line_txt):
                emit(
                    "FLR-MOT-HIDDEN-NOJS",
                    "FLOOR",
                    "motion",
                    line,
                    "Element starts hidden (opacity-0 + translate-y) without no-js/data-js/x-cloak fallback",
                    "Keep content visible by default or add a no-js/x-cloak/data-js guard.",
                )
        if BG_CLIP_TEXT_RE.search(cls_val) and TEXT_TRANSPARENT_RE.search(cls_val):
            emit(
                "FLR-CLR-GRADIENT-TEXT",
                "FLOOR",
                "color",
                line,
                "Gradient clipped transparent text reduces legibility and reads as AI template slop",
                "Use a solid high-contrast semantic text token such as text-content.",
            )
        if BLUR_ORB_RE.search(cls_val):
            emit(
                "RFX-CLR-BLUR-ORB",
                "REFLEX",
                "color",
                line,
                "Large ambient blur-2xl/3xl orb decoration",
                "Remove decorative blur orbs or use crisp structural borders/surfaces.",
            )
        if BACKDROP_BLUR_RE.search(cls_val) and GLASS_BG_RE.search(cls_val):
            emit(
                "RFX-CLR-GLASS-STACK",
                "REFLEX",
                "color",
                line,
                "Translucent glassmorphism stack lowers contrast over varied backgrounds",
                "Use an opaque semantic surface (bg-surface or bg-surface-muted).",
            )
        if RAW_GRAY_RE.search(cls_val):
            emit(
                "RFX-CLR-RAW-GRAY",
                "REFLEX",
                "tokens",
                line,
                "Raw neutral gray/slate/zinc utility instead of semantic theme token",
                "Replace with semantic surface/content tokens (bg-surface, text-content, border-content/10).",
            )
        if TW_SLOW_RE.search(cls_val):
            emit(
                "RFX-MOT-SLOW",
                "REFLEX",
                "motion",
                line,
                "Sluggish transition duration (>= 500ms) makes UI controls feel sticky",
                "Use crisp 150-250ms durations (duration-150 or duration-200).",
            )
        if ROUNDED_LARGE_RE.search(cls_val) and CRAMPED_PAD_RE.search(cls_val):
            emit(
                "RFX-LYT-CRAMPED-RADIUS",
                "REFLEX",
                "layout",
                line,
                "Large border radius paired with cramped padding (p-1..p-3)",
                "Increase padding (>= p-6 for rounded-2xl/3xl) or reduce corner radius.",
            )
        if profile == "editorial" and UPPERCASE_RE.search(cls_val) and TRACKING_WIDE_RE.search(cls_val):
            emit(
                "RFX-ED-TRACKED-CAPS",
                "REFLEX",
                "type",
                line,
                "Tracked uppercase label violates editorial typography discipline",
                "Use sentence case without tracking-wide/wider/widest.",
            )
        if profile == "app" and APP_CAPS_TAG_RE.search(line_txt):
            if UPPERCASE_RE.search(cls_val) and TRACKING_WIDE_RE.search(cls_val):
                emit(
                    "RFX-ED-TRACKED-CAPS",
                    "REFLEX",
                    "type",
                    line,
                    "Tracked uppercase table header or form label reduces scannability",
                    "Set table heads and form labels in sentence case.",
                )
        if profile == "editorial" and STATUS_DOT_PING_RE.search(cls_val) and ROUNDED_FULL_RE.search(cls_val) and STATUS_DOT_SIZE_RE.search(cls_val):
            emit(
                "RFX-ED-ARROW-DOT",
                "REFLEX",
                "chrome",
                line,
                "Decorative pulsing status dot in editorial layout",
                "Remove decorative pulsing status dot or switch to --profile commercial.",
            )

    # Line-by-line markup checks
    for idx, line_txt in enumerate(masked_lines, start=1):
        if SLOP_FROM_RE.search(line_txt) and SLOP_TO_VIA_RE.search(line_txt):
            emit(
                "FLR-CLR-SLOP-GRADIENT",
                "FLOOR",
                "color",
                idx,
                "Generic purple/indigo/violet AI gradient",
                "Use the project's semantic surface and single accent token.",
            )
        if TW_HEX_RE.search(line_txt):
            emit(
                "FLR-TOK-HEX-LITERAL",
                "FLOOR",
                "tokens",
                idx,
                "Hardcoded hex literal inside Tailwind utility",
                "Declare a token in CSS :root/@theme and reference the semantic utility.",
            )
        for sm in STYLE_ATTR_RE.finditer(line_txt):
            if INLINE_COLOR_PROP_RE.search(sm.group(1)):
                emit(
                    "FLR-DOM-INLINE-COLOR",
                    "FLOOR",
                    "tokens",
                    idx,
                    "Hardcoded color in inline style attribute",
                    "Use CSS variables/tokens instead of inline literal colors.",
                )
        if CLICHE_RE.search(line_txt):
            emit(
                "FLR-CPY-CLICHE",
                "FLOOR",
                "copy",
                idx,
                "Generic LLM marketing cliché copy",
                "Replace with concrete product facts, numbers, scope, or timeline.",
            )
        if FAKE_PROOF_RE.search(line_txt):
            emit(
                "FLR-CPY-FAKE-PROOF",
                "FLOOR",
                "copy",
                idx,
                "Placeholder or invented social proof text",
                "Replace with real brief/database facts or remove unverified claims.",
            )

    # Tag / multiline markup checks
    for bm in BUTTON_BLOCK_RE.finditer(masked):
        attrs, inner = bm.group(1), bm.group(2)
        if BTN_A11Y_ATTR_RE.search(attrs) or SR_ONLY_RE.search(inner):
            continue
        if SVG_BLOCK_RE.search(inner):
            leftover = SVG_BLOCK_RE.sub("", inner)
            leftover = STRIP_TAGS_RE.sub("", leftover).strip()
            if not leftover:
                emit(
                    "FLR-A11Y-ICON-BTN",
                    "FLOOR",
                    "a11y",
                    _line_of_offset(masked, bm.start()),
                    "Icon-only <button> lacks aria-label, title, or .sr-only text",
                    'Add aria-label="Describe action" or <span class="sr-only">...</span>.',
                )

    has_hero = HERO_SECTION_RE.search(masked)
    for im in IMG_TAG_RE.finditer(masked):
        attrs = im.group(1)
        line_no = _line_of_offset(masked, im.start())
        if not ALT_ATTR_RE.search(attrs):
            emit(
                "FLR-A11Y-IMG-ALT",
                "FLOOR",
                "a11y",
                line_no,
                '<img> element is missing an alt attribute (use alt="" if decorative)',
                'Add descriptive alt="..." or alt="" for decorative imagery.',
            )
        in_hero = bool(has_hero and has_hero.start() < im.start() and im.start() - has_hero.start() < 2500)
        if not in_hero and not IMG_EAGER_RE.search(attrs):
            if not IMG_LOADING_RE.search(attrs) or not IMG_DECODING_RE.search(attrs):
                emit(
                    "FIN-IMG-ATTRS",
                    "FINISH",
                    "perf",
                    line_no,
                    'Non-hero <img> missing loading="lazy" or decoding="async"',
                    'Add loading="lazy" decoding="async" on below-the-fold images.',
                )

    for hm in ITALIC_HEADING_RE.finditer(masked):
        emit(
            "RFX-TYP-ITALIC-HEADING",
            "REFLEX",
            "type",
            _line_of_offset(masked, hm.start()),
            "Single italic <em>/<i> highlight inside heading",
            "Keep headings in one uniform font posture.",
        )

    for em in UI_EMOJI_CONTAINER_RE.finditer(masked):
        if EMOJI_CHARS_RE.search(em.group(2)):
            emit(
                "RFX-DOM-EMOJI-ICON",
                "REFLEX",
                "chrome",
                _line_of_offset(masked, em.start()),
                f"Decorative emoji used as UI icon inside <{em.group(1).lower()}>",
                "Replace decorative emoji with a proper SVG icon or plain typography.",
            )

    # Editorial-only multiline / structural checks
    if profile == "editorial":
        for i, line_txt in enumerate(masked_lines):
            if EYEBROW_LINE_RE.search(line_txt):
                window = "\n".join(masked_lines[i : i + 3])
                if HEADING_1_3_RE.search(window):
                    emit(
                        "RFX-ED-EYEBROW",
                        "REFLEX",
                        "chrome",
                        i + 1,
                        "Eyebrow pill/badge placed directly above heading",
                        "Remove the eyebrow pill and strengthen the heading itself.",
                    )
        for am in ARROW_BTN_LINK_RE.finditer(masked):
            emit(
                "RFX-ED-ARROW-DOT",
                "REFLEX",
                "chrome",
                _line_of_offset(masked, am.start()),
                "Template arrow character inside button or link text",
                "Use a clear action verb without glued arrow punctuation.",
            )
        for mm in MID_DOT_CHAIN_RE.finditer(masked):
            emit(
                "RFX-ED-ARROW-DOT",
                "REFLEX",
                "chrome",
                _line_of_offset(masked, mm.start()),
                "Middle-dot chained metadata string",
                "Separate metadata into distinct structured items or clean spacing.",
            )

        # Card-in-card nesting tracker
        stack: list[tuple[str, bool]] = []
        for tm in CARD_TAG_OPEN_RE.finditer(masked):
            is_close = bool(tm.group(1))
            tag = tm.group(2).lower()
            attrs = tm.group(3) or ""
            self_close = bool(tm.group(4))
            if is_close:
                for pos in range(len(stack) - 1, -1, -1):
                    if stack[pos][0] == tag:
                        del stack[pos:]
                        break
                continue
            cls_match = CLASS_ATTR_RE.search(attrs)
            cls_val = next((g for g in cls_match.groups() if g is not None), "") if cls_match else ""
            is_card = bool(
                CARD_BASE_RE.search(cls_val)
                or (
                    BORDER_TOKEN_RE.search(cls_val)
                    and ROUNDED_CARD_RE.search(cls_val)
                    and BG_SURFACE_RE.search(cls_val)
                )
            )
            if is_card and any(c for _, c in stack):
                emit(
                    "RFX-ED-CARD-IN-CARD",
                    "REFLEX",
                    "layout",
                    _line_of_offset(masked, tm.start()),
                    "Nested card container inside an open card",
                    "Replace inner card box with hairline dividers (divide-y) or spacing.",
                )
            if not self_close:
                stack.append((tag, is_card))

    # Finish checks
    if TABULAR_TRIGGER_RE.search(masked) and not TABULAR_VALUE_RE.search(masked):
        m_tab = TABULAR_TRIGGER_RE.search(masked)
        emit(
            "FIN-TYP-TABULAR",
            "FINISH",
            "type",
            _line_of_offset(masked, m_tab.start()) if m_tab else 1,
            "Numeric table/metric block lacks tabular-nums alignment",
            "Add tabular-nums (or font-variant-numeric: tabular-nums) to numeric columns.",
        )

    if profile == "app" and APP_DYNAMIC_DATA_RE.search(masked) and not APP_STATES_OK_RE.search(masked):
        m_dyn = APP_DYNAMIC_DATA_RE.search(masked)
        emit(
            "FIN-APP-STATES",
            "FINISH",
            "app-states",
            _line_of_offset(masked, m_dyn.start()) if m_dyn else 1,
            "Dynamic table/list view lacks visible loading, empty, or error state handling",
            "Render skeleton/loading, empty-with-action, and error-with-retry states.",
        )


def _check_css_file(
    file_path: Path,
    masked: str,
    raw_lines: list[str],
    waiver_info: dict[str, Any],
    profile: str,
    findings: list[dict[str, Any]],
) -> None:
    masked_lines = masked.splitlines()
    token_lines = _css_token_context_lines(masked)
    has_focus_visible = ":focus-visible" in masked

    def emit(rid: str, tier: str, cat: str, line: int, msg: str, fix: str) -> None:
        _add_finding(
            findings,
            rule_id=rid,
            tier=tier,
            category=cat,
            file_path=file_path,
            line=line,
            message=msg,
            snippet=_snippet(raw_lines, line),
            fix=fix,
            waiver_info=waiver_info,
        )

    for idx, line_txt in enumerate(masked_lines, start=1):
        if CSS_OUTLINE_NONE_RE.search(line_txt) and not has_focus_visible:
            emit(
                "FLR-A11Y-FOCUS",
                "FLOOR",
                "a11y",
                idx,
                "CSS removes focus outline without a :focus-visible rule in the stylesheet",
                "Provide a visible :focus-visible outline or ring style.",
            )
        if CSS_100VW_RE.search(line_txt):
            emit(
                "FLR-LYT-OVERFLOW",
                "FLOOR",
                "layout",
                idx,
                "width: 100vw risks horizontal overflow",
                "Use width: 100% instead of 100vw.",
            )
        if CSS_TRANSITION_ALL_RE.search(line_txt):
            emit(
                "FLR-MOT-TRANSITION-ALL",
                "FLOOR",
                "motion",
                idx,
                "transition: all animates layout/paint properties",
                "Transition only transform, opacity, or colors.",
            )
        t_decl = CSS_TRANSITION_DECL_RE.search(line_txt)
        if t_decl and CSS_LAYOUT_PROP_RE.search(t_decl.group(1)):
            emit(
                "FLR-MOT-LAYOUT-ANIM",
                "FLOOR",
                "motion",
                idx,
                "CSS transition animates layout property (width/height/top/left/margin/padding)",
                "Animate transform or opacity instead of geometry properties.",
            )
        if idx not in token_lines:
            for c_decl in CSS_COLOR_DECL_RE.finditer(line_txt):
                val_no_vars = VAR_EXPR_RE.sub("", c_decl.group(2))
                if HEX_OR_RGB_RE.search(val_no_vars):
                    emit(
                        "FLR-TOK-HEX-LITERAL",
                        "FLOOR",
                        "tokens",
                        idx,
                        "Literal hex/rgb color outside :root/@theme/[data-theme] token declaration",
                        "Declare semantic custom properties in :root/@theme and reference var(--...).",
                    )
        if CSS_BLUR_ORB_RE.search(line_txt):
            emit(
                "RFX-CLR-BLUR-ORB",
                "REFLEX",
                "color",
                idx,
                "Large blur(>=40px) decorative filter",
                "Use clean surface contrast or structural borders instead.",
            )
        if CSS_SLOW_RE.search(line_txt):
            emit(
                "RFX-MOT-SLOW",
                "REFLEX",
                "motion",
                idx,
                "Sluggish CSS transition duration (>= 500ms)",
                "Use 150-250ms durations for interactive controls.",
            )

    for selector, start_line, body in _iter_css_blocks(masked):
        sel_low = selector.lower()
        if re.search(r"\b(?:html|body)\b", sel_low) and re.search(r"\boverflow-x\s*:\s*hidden\b", body, re.IGNORECASE):
            rel = body[: re.search(r"\boverflow-x\s*:\s*hidden\b", body, re.IGNORECASE).start()].count("\n")
            emit(
                "FLR-LYT-OVERFLOW-CLIP",
                "FLOOR",
                "layout",
                start_line + rel,
                "overflow-x: hidden on html/body breaks position: sticky",
                "Use overflow-x: clip on html and body.",
            )
        if "@keyframes" in sel_low:
            for km in CSS_KEYFRAME_PROP_RE.finditer(body):
                rel = body[: km.start()].count("\n")
                emit(
                    "FLR-MOT-LAYOUT-ANIM",
                    "FLOOR",
                    "motion",
                    start_line + rel,
                    "@keyframes animates layout property (width/height/top/left/margin/padding)",
                    "Animate transform and opacity inside @keyframes.",
                )
        if re.search(r"\bbackground-clip\s*:\s*text\b", body, re.IGNORECASE) and re.search(
            r"(?:^|[;\s])(?:-webkit-text-fill-color|color)\s*:\s*transparent\b", body, re.IGNORECASE
        ):
            emit(
                "FLR-CLR-GRADIENT-TEXT",
                "FLOOR",
                "color",
                start_line,
                "CSS background-clip: text with transparent fill",
                "Use a solid semantic color token for headings and body text.",
            )
        if profile == "editorial" and re.search(r"\btext-transform\s*:\s*uppercase\b", body, re.IGNORECASE) and re.search(
            r"\bletter-spacing\s*:", body, re.IGNORECASE
        ):
            emit(
                "RFX-ED-TRACKED-CAPS",
                "REFLEX",
                "type",
                start_line,
                "CSS uppercase + letter-spacing tracked capitals",
                "Keep editorial labels in sentence case without extra tracking.",
            )


def lint_files(
    paths: list[str | Path],
    *,
    profile: str | None = None,
    scope: str = "page",
    tier: str = "all",
) -> dict[str, Any]:
    """Run static anti-slop checks on target files/directories."""
    if scope not in SCOPES:
        raise ValueError(f"Unsupported scope: {scope}")
    if tier not in TIERS:
        raise ValueError(f"Unsupported tier: {tier}")
    effective_profile = profile or ("app" if scope == "app" else "commercial")
    if effective_profile not in PROFILES:
        raise ValueError(f"Unsupported profile: {effective_profile}")

    files, skipped_minified = collect_files(paths)
    all_findings: list[dict[str, Any]] = []
    css_motion_files: list[tuple[Path, str, list[str], dict[str, Any]]] = []
    css_has_reduced_motion = False

    for fp in files:
        raw_text = fp.read_text(encoding="utf-8", errors="replace")
        ext = fp.suffix.lower()
        masked = mask_comments(raw_text, ext)
        raw_lines = raw_text.splitlines()
        waiver_info = parse_waivers(raw_text, masked)

        if ext == ".css":
            if REDUCED_MOTION_RE.search(masked):
                css_has_reduced_motion = True
            if CSS_HAS_MOTION_RE.search(masked):
                css_motion_files.append((fp, masked, raw_lines, waiver_info))
            _check_css_file(fp, masked, raw_lines, waiver_info, effective_profile, all_findings)
        else:
            if REDUCED_MOTION_RE.search(masked):
                css_has_reduced_motion = True
            _check_markup_file(fp, masked, raw_lines, waiver_info, effective_profile, all_findings)

    if css_motion_files and not css_has_reduced_motion:
        fp, masked, raw_lines, waiver_info = css_motion_files[0]
        m_mot = CSS_HAS_MOTION_RE.search(masked)
        line_no = _line_of_offset(masked, m_mot.start()) if m_mot else 1
        _add_finding(
            all_findings,
            rule_id="FIN-MOT-REDUCED",
            tier="FINISH",
            category="motion",
            file_path=fp,
            line=line_no,
            message="CSS animations/transitions found without @media (prefers-reduced-motion: reduce)",
            snippet=_snippet(raw_lines, line_no),
            fix="Add @media (prefers-reduced-motion: reduce) fallback disabling non-essential motion.",
            waiver_info=waiver_info,
        )

    allowed_tiers = {"FLOOR"}
    if tier in ("reflex", "all"):
        allowed_tiers.add("REFLEX")
    if tier == "all":
        allowed_tiers.add("FINISH")

    filtered = [f for f in all_findings if f["tier"] in allowed_tiers]
    filtered.sort(key=lambda x: (x["file"], x["line"], x["id"]))

    floor_fail = sum(1 for f in filtered if f["tier"] == "FLOOR")
    reflex_total = sum(1 for f in filtered if f["tier"] == "REFLEX")
    reflex_waived = sum(1 for f in filtered if f["tier"] == "REFLEX" and f["waived"])
    reflex_open = reflex_total - reflex_waived
    finish_count = sum(1 for f in filtered if f["tier"] == "FINISH")

    return {
        "profile": effective_profile,
        "scope": scope,
        "tier": tier,
        "scanned_files": [str(f) for f in files],
        "skipped_minified": skipped_minified,
        "counts": {
            "floor_fail": floor_fail,
            "reflex_open": reflex_open,
            "reflex_waived": reflex_waived,
            "finish": finish_count,
        },
        "findings": filtered,
    }


def extract_snapshot(paths: list[str | Path]) -> dict[str, Any]:
    """Extract functional wiring inventory (links, forms, inputs, endpoints, hooks, handlers, headings)."""
    files, skipped_minified = collect_files(paths)
    links: set[str] = set()
    forms: set[str] = set()
    htmx_endpoints: set[str] = set()
    inputs: set[str] = set()
    test_hooks: set[str] = set()
    handlers: set[str] = set()
    headings: set[str] = set()

    for fp in files:
        if fp.suffix.lower() not in MARKUP_EXTS:
            continue
        raw = fp.read_text(encoding="utf-8", errors="replace")
        masked = mask_comments(raw, fp.suffix.lower())

        for hm in HREF_RE.finditer(masked):
            val = (hm.group(1) or hm.group(2) or "").strip()
            if val and val != "#":
                links.add(val)

        for fm in FORM_TAG_RE.finditer(masked):
            attrs = fm.group(1)
            am = ACTION_ATTR_RE.search(attrs)
            mm = METHOD_ATTR_RE.search(attrs)
            action = (am.group(1) or am.group(2) or "").strip() if am else "(self)"
            method = ((mm.group(1) or mm.group(2) or "").strip() if mm else "GET").upper()
            forms.add(f"{method} {action or '(self)'}")

        for hx in HTMX_EP_RE.finditer(masked):
            verb = hx.group(1).lower()
            url = (hx.group(2) or hx.group(3) or "").strip()
            if url:
                htmx_endpoints.add(f"{verb}={url}")

        for inp in INPUT_NAME_RE.finditer(masked):
            name = (inp.group(1) or inp.group(2) or "").strip()
            if name:
                inputs.add(name)

        for th in TEST_HOOK_RE.finditer(masked):
            attr = th.group(1).lower()
            val = (th.group(2) or th.group(3) or "").strip()
            if val:
                test_hooks.add(f"{attr}={val}")

        for hd in HANDLER_RE.finditer(masked):
            attr = hd.group(1)
            val = next((g for g in hd.groups()[1:] if g is not None), "").strip()
            norm_val = " ".join(val.split())
            if norm_val:
                handlers.add(f"{attr}={norm_val}")

        for h12 in HEADING_12_RE.finditer(masked):
            txt = " ".join(STRIP_TAGS_RE.sub(" ", h12.group(2)).split())
            if txt:
                headings.add(f"h{h12.group(1)}:{txt}")

    return {
        "files": [str(f) for f in files if f.suffix.lower() in MARKUP_EXTS],
        "skipped_minified": skipped_minified,
        "links": sorted(links),
        "forms": sorted(forms),
        "htmx_endpoints": sorted(htmx_endpoints),
        "inputs": sorted(inputs),
        "test_hooks": sorted(test_hooks),
        "handlers": sorted(handlers),
        "headings": sorted(headings),
    }


def _is_drop_allowed(category: str, item: str, allow_drop: set[str]) -> bool:
    if item in allow_drop or f"{category}:{item}" in allow_drop:
        return True
    if "=" in item:
        rhs = item.split("=", 1)[1]
        if rhs in allow_drop:
            return True
    return False


def compare_snapshots(
    before: dict[str, Any],
    after: dict[str, Any],
    allow_drop: list[str] | None = None,
) -> dict[str, Any]:
    """Compare functional wiring snapshots before and after a redesign."""
    allow_set = set(allow_drop or [])
    functional_keys = ("links", "forms", "htmx_endpoints", "inputs", "test_hooks", "handlers")
    dropped: list[dict[str, str]] = []
    allowed_drops: list[dict[str, str]] = []
    preserved_count = 0
    added_count = 0

    for key in functional_keys:
        b_set = set(before.get(key, []))
        a_set = set(after.get(key, []))
        preserved_count += len(b_set & a_set)
        added_count += len(a_set - b_set)
        for missing in sorted(b_set - a_set):
            entry = {"category": key, "item": missing}
            if _is_drop_allowed(key, missing, allow_set):
                allowed_drops.append(entry)
            else:
                dropped.append(entry)

    b_heads = set(before.get("headings", []))
    a_heads = set(after.get("headings", []))
    heading_changes = {
        "removed": sorted(b_heads - a_heads),
        "added": sorted(a_heads - b_heads),
    }

    return {
        "passed": len(dropped) == 0,
        "preserved_count": preserved_count,
        "added_count": added_count,
        "dropped": dropped,
        "allowed_drops": allowed_drops,
        "heading_changes": heading_changes,
    }
