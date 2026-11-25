#!/usr/bin/env python3
"""Zero-dependency UI preflight, anti-slop linter, and redesign wiring contract CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import _rules  # noqa: E402

TOKEN_DECL_RE = re.compile(r"(--(?:color|radius|font|dur|duration|ease|spacing|shadow)[a-z0-9-]*)\s*:\s*([^;{}\n]+)", re.IGNORECASE)
FONT_FACE_RE = re.compile(r"@font-face\s*\{[^}]*font-family\s*:\s*['\"]?([^'\";}\n]+)", re.IGNORECASE | re.DOTALL)
CDN_FONT_RE = re.compile(
    r"https?://(?:fonts\.googleapis\.com|fonts\.gstatic\.com|api\.fontshare\.com|use\.typekit\.net|fonts\.cdnfonts\.com)[^\"'\s>)]*",
    re.IGNORECASE,
)
TW_V4_RE = re.compile(r"""(?:@import\s+["']tailwindcss["']|@theme\s*\{)""", re.IGNORECASE)
TW_V3_RE = re.compile(r"@tailwind\s+(?:base|components|utilities)\b", re.IGNORECASE)
ALPINE_RE = re.compile(r"\bx-(?:data|show|on:|model)\b")
HTMX_RE = re.compile(r"\bhx-(?:get|post|put|patch|delete|swap|target|trigger)\b")
PRESET_COLOR_RE = re.compile(r'"(?:primary_color|accent_color|background_color|surface|accent)"')


def _detect_project_signals(root: Path) -> dict[str, Any]:
    stacks: list[str] = []
    markers: list[str] = []
    tokens: list[dict[str, str]] = []
    seen_tokens: set[str] = set()
    self_hosted_fonts: set[str] = set()
    cdn_fonts: set[str] = set()
    font_files: list[str] = []
    docs: list[str] = []
    presets: list[str] = []
    skipped_minified: list[str] = []

    go_mod = root / "go.mod"
    if go_mod.is_file():
        go_txt = go_mod.read_text(encoding="utf-8", errors="replace")
        stacks.append("Go")
        markers.append("go.mod")
        if "github.com/a-h/templ" in go_txt:
            stacks.append("Go Templ")

    pkg_json = root / "package.json"
    if pkg_json.is_file():
        markers.append("package.json")
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            pkg = {}
        deps: dict[str, str] = {}
        for sec in ("dependencies", "devDependencies", "peerDependencies"):
            if isinstance(pkg.get(sec), dict):
                deps.update(pkg[sec])
        if "next" in deps:
            stacks.append("Next.js")
        if "react" in deps and "Next.js" not in stacks:
            stacks.append("React")
        if "nuxt" in deps:
            stacks.append("Nuxt")
        if "vue" in deps and "Nuxt" not in stacks:
            stacks.append("Vue")
        if "@sveltejs/kit" in deps or "svelte" in deps:
            stacks.append("Svelte")
        if "astro" in deps:
            stacks.append("Astro")
        if "alpinejs" in deps:
            stacks.append("Alpine.js")
        if "htmx.org" in deps:
            stacks.append("HTMX")
        tw_ver = str(deps.get("tailwindcss", "") or deps.get("@tailwindcss/cli", ""))
        if tw_ver:
            if "4" in tw_ver and "3" not in tw_ver.split(".")[0]:
                stacks.append("Tailwind CSS v4")
            else:
                stacks.append("Tailwind CSS")

    for doc_name in ("DESIGN.md", "design.md", "AGENTS.md", "CLAUDE.md"):
        if (root / doc_name).is_file():
            docs.append(doc_name)

    presets_dir = root / "presets"
    if presets_dir.is_dir():
        presets = sorted(p.name for p in presets_dir.iterdir() if p.is_file() and p.suffix == ".json")

    ext_counts: dict[str, int] = {}
    has_tw_v4 = False
    has_tw_v3 = False
    has_alpine = False
    has_htmx = False

    for cur_root, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in _rules.SKIP_DIRS)
        for fname in sorted(files):
            fp = Path(cur_root) / fname
            low = fname.lower()
            if low.startswith("tailwind.config."):
                markers.append(str(fp.relative_to(root)))
                has_tw_v3 = True
                continue
            if low.endswith((".woff2", ".woff", ".ttf", ".otf")):
                if len(font_files) < 20:
                    font_files.append(str(fp.relative_to(root)))
                continue

            ext = fp.suffix.lower()
            if ext not in _rules.SUPPORTED_EXTS:
                continue
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            if _rules.is_minified_css(fp):
                skipped_minified.append(str(fp.relative_to(root)))
                continue

            text = fp.read_text(encoding="utf-8", errors="replace")
            if ext == ".css":
                if TW_V4_RE.search(text):
                    has_tw_v4 = True
                elif TW_V3_RE.search(text):
                    has_tw_v3 = True
                for fm in FONT_FACE_RE.finditer(text):
                    self_hosted_fonts.add(fm.group(1).strip())
                for cm in CDN_FONT_RE.finditer(text):
                    cdn_fonts.add(cm.group(0))
                masked_css = _rules.mask_comments(text, ".css")
                token_lines = _rules._css_token_context_lines(masked_css)
                for line_no, line in enumerate(masked_css.splitlines(), start=1):
                    if line_no not in token_lines:
                        continue
                    for tm in TOKEN_DECL_RE.finditer(line):
                        tname = tm.group(1).strip()
                        if tname not in seen_tokens:
                            seen_tokens.add(tname)
                            tokens.append({
                                "name": tname,
                                "value": " ".join(tm.group(2).split())[:60],
                                "file": str(fp.relative_to(root)),
                            })
            else:
                if not has_alpine and ALPINE_RE.search(text):
                    has_alpine = True
                if not has_htmx and HTMX_RE.search(text):
                    has_htmx = True
                for cm in CDN_FONT_RE.finditer(text):
                    cdn_fonts.add(cm.group(0))

    if ext_counts.get(".templ", 0) > 0 and "Go Templ" not in stacks:
        stacks.append("Go Templ")
    if ext_counts.get(".vue", 0) > 0 and "Vue" not in stacks and "Nuxt" not in stacks:
        stacks.append("Vue")
    if ext_counts.get(".svelte", 0) > 0 and "Svelte" not in stacks:
        stacks.append("Svelte")
    if ext_counts.get(".astro", 0) > 0 and "Astro" not in stacks:
        stacks.append("Astro")
    if (ext_counts.get(".tsx", 0) > 0 or ext_counts.get(".jsx", 0) > 0) and "React" not in stacks and "Next.js" not in stacks:
        stacks.append("React/JSX")
    if has_tw_v4 and "Tailwind CSS v4" not in stacks:
        stacks.append("Tailwind CSS v4")
    elif has_tw_v3 and "Tailwind CSS" not in stacks and "Tailwind CSS v4" not in stacks:
        stacks.append("Tailwind CSS v3")
    if has_alpine and "Alpine.js" not in stacks:
        stacks.append("Alpine.js")
    if has_htmx and "HTMX" not in stacks:
        stacks.append("HTMX")

    font_mode = "none"
    if self_hosted_fonts or font_files:
        font_mode = "self-hosted+cdn" if cdn_fonts else "self-hosted"
    elif cdn_fonts:
        font_mode = "cdn"

    return {
        "root": str(root.resolve()),
        "stacks": stacks,
        "markers": sorted(set(markers)),
        "template_counts": dict(sorted(ext_counts.items())),
        "docs": docs,
        "presets_count": len(presets),
        "presets_sample": presets[:8],
        "font_mode": font_mode,
        "self_hosted_fonts": sorted(self_hosted_fonts),
        "font_files_sample": font_files[:10],
        "cdn_fonts": sorted(cdn_fonts)[:8],
        "tokens_total": len(tokens),
        "tokens": tokens[:40],
        "skipped_minified": skipped_minified,
    }


def _cmd_preflight(args: argparse.Namespace) -> int:
    root = Path(args.dir).expanduser()
    if not root.is_dir():
        print(f"[ERROR] Directory not found: {args.dir}", file=sys.stderr)
        return 2

    info = _detect_project_signals(root)
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0

    print(f"Pre-flight: {info['root']}")
    print(f"  Stacks:     {', '.join(info['stacks']) or 'plain HTML/CSS'}")
    if info["docs"]:
        print(f"  Docs:       {', '.join(info['docs'])}")
    if info["presets_count"]:
        sample = ", ".join(info["presets_sample"][:5])
        print(f"  Presets:    {info['presets_count']} JSON ({sample})")
    print(f"  Fonts:      {info['font_mode']}" + (f" ({', '.join(info['self_hosted_fonts'])})" if info["self_hosted_fonts"] else ""))
    if info["cdn_fonts"]:
        print(f"  CDN links:  {len(info['cdn_fonts'])} detected")
    print(f"  Tokens:     {info['tokens_total']} semantic CSS vars found (showing up to 15):")
    for tok in info["tokens"][:15]:
        print(f"    {tok['name']}: {tok['value']}  ({tok['file']})")
    if info["skipped_minified"]:
        print(f"  Skipped:    {len(info['skipped_minified'])} minified/compiled CSS bundle(s)")
    return 0


def _cmd_lint(args: argparse.Namespace) -> int:
    paths = args.paths or ["."]
    try:
        report = _rules.lint_files(
            paths,
            profile=args.profile,
            scope=args.scope,
            tier=args.tier,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    counts = report["counts"]
    passed = (
        counts["floor_fail"] == 0
        and counts["reflex_open"] == 0
        and (not args.strict or counts["finish"] == 0)
    )
    report["passed"] = passed

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        summary = (
            f"Floor {counts['floor_fail']} FAIL · "
            f"Reflex {counts['reflex_open']} ({counts['reflex_waived']} waived) · "
            f"Finish {counts['finish']}"
        )
        print(
            f"[ui-lint] profile={report['profile']} scope={report['scope']} "
            f"files={len(report['scanned_files'])} :: {summary}"
        )
        if report["skipped_minified"]:
            print(f"  (skipped {len(report['skipped_minified'])} minified/compiled CSS bundle(s))")

        shown = report["findings"][: args.limit]
        for f in shown:
            tag = f"{f['tier']}{' [WAIVED]' if f['waived'] else ''}"
            loc = f"{Path(f['file']).name}:{f['line']}"
            print(f"  [{tag}] {f['id']} {loc} — {f['message']}")
            if f.get("waiver_rejected"):
                print(f"      waiver rejected: {f['waiver_rejected']}")
            elif f["waived"]:
                print(f"      waived: {f['waiver_reason']}")
            else:
                print(f"      fix: {f['fix']}")
        extra = len(report["findings"]) - len(shown)
        if extra > 0:
            print(f"  (+{extra} more findings; re-run with --limit or --json)")

    return 0 if passed else 1


def _cmd_snapshot(args: argparse.Namespace) -> int:
    try:
        snap = _rules.extract_snapshot(args.paths)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"out": str(out_path), "snapshot": snap}, indent=2, ensure_ascii=False))
    else:
        print(
            f"[ui-snapshot] saved {out_path} :: "
            f"links={len(snap['links'])} forms={len(snap['forms'])} "
            f"htmx={len(snap['htmx_endpoints'])} inputs={len(snap['inputs'])} "
            f"hooks={len(snap['test_hooks'])} handlers={len(snap['handlers'])} "
            f"headings={len(snap['headings'])}"
        )
    return 0


def _cmd_kept(args: argparse.Namespace) -> int:
    before_path = Path(args.before)
    if not before_path.is_file():
        print(f"[ERROR] Snapshot file not found: {args.before}", file=sys.stderr)
        return 2
    try:
        before_data = json.loads(before_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Invalid snapshot JSON {args.before}: {exc}", file=sys.stderr)
        return 2

    try:
        after_data = _rules.extract_snapshot(args.paths)
    except FileNotFoundError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    diff = _rules.compare_snapshots(before_data, after_data, allow_drop=args.allow_drop)
    if args.json:
        print(json.dumps(diff, indent=2, ensure_ascii=False))
    else:
        status = "PASS" if diff["passed"] else "FAIL"
        print(
            f"[ui-kept] {status} :: preserved={diff['preserved_count']} "
            f"added={diff['added_count']} dropped={len(diff['dropped'])} "
            f"allowed_drops={len(diff['allowed_drops'])}"
        )
        for d in diff["dropped"]:
            print(f"  [DROPPED] {d['category']}: {d['item']}")
        for a in diff["allowed_drops"]:
            print(f"  [ALLOWED] {a['category']}: {a['item']}")
        if diff["heading_changes"]["removed"] or diff["heading_changes"]["added"]:
            print(
                f"  headings changed: -{len(diff['heading_changes']['removed'])} "
                f"+{len(diff['heading_changes']['added'])}"
            )

    return 0 if diff["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Universal zero-dependency UI preflight, anti-slop linter, and redesign wiring check."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("preflight", help="Inspect stack, CSS tokens, fonts, and design docs in a repo.")
    p_pre.add_argument("dir", nargs="?", default=".", help="Target repository directory (default: .)")
    p_pre.add_argument("--json", action="store_true", help="Print JSON output.")

    p_lint = sub.add_parser("lint", help="Lint UI templates and stylesheets against Floor/Reflex/Finish rules.")
    p_lint.add_argument("paths", nargs="*", help="Files or directories to scan (default: .)")
    p_lint.add_argument("--profile", choices=_rules.PROFILES, default=None, help="Rule profile.")
    p_lint.add_argument("--scope", choices=_rules.SCOPES, default="page", help="Target scope.")
    p_lint.add_argument(
        "--tier",
        choices=_rules.TIERS,
        default="all",
        help="Check up to tier: floor (FLOOR only), reflex (FLOOR+REFLEX), all (FLOOR+REFLEX+FINISH).",
    )
    p_lint.add_argument("--strict", action="store_true", help="Fail on FINISH checks as well.")
    p_lint.add_argument("--limit", type=int, default=40, help="Max findings printed in text mode.")
    p_lint.add_argument("--json", action="store_true", help="Print JSON output.")

    p_snap = sub.add_parser("snapshot", help="Record functional wiring before a redesign.")
    p_snap.add_argument("paths", nargs="+", help="Files or directories to snapshot.")
    p_snap.add_argument("--out", required=True, help="Output JSON snapshot path.")
    p_snap.add_argument("--json", action="store_true", help="Print JSON output.")

    p_kept = sub.add_parser("kept", help="Verify redesign preserved links, forms, inputs, hooks, and handlers.")
    p_kept.add_argument("paths", nargs="+", help="Files or directories after redesign.")
    p_kept.add_argument("--before", required=True, help="Baseline snapshot JSON path.")
    p_kept.add_argument(
        "--allow-drop",
        action="append",
        default=[],
        help="Explicitly allow dropping a specific item (repeatable).",
    )
    p_kept.add_argument("--json", action="store_true", help="Print JSON output.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "preflight":
        return _cmd_preflight(args)
    if args.cmd == "lint":
        return _cmd_lint(args)
    if args.cmd == "snapshot":
        return _cmd_snapshot(args)
    if args.cmd == "kept":
        return _cmd_kept(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
