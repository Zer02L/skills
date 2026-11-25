#!/usr/bin/env python3
"""Rotation-aware dealer for UI macrostructures, material directions, and section variety."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
from pathlib import Path
from typing import Any

PROFILES = ("commercial", "editorial", "app")
MATERIALS = ("photo", "product", "words", "data")
JOBS = ("buy", "book", "signup", "subscribe", "hire", "try", "operate", "read")

MACROSTRUCTURES: list[dict[str, Any]] = [
    {
        "slug": "bento-grid",
        "name": "Bento Grid",
        "profiles": ("commercial", "editorial"),
        "materials": ("product", "photo", "data"),
        "jobs": ("try", "signup", "buy"),
        "sections": ["Split", "Bento", "Table", "Offer"],
        "summary": "Asymmetric 8/4 or 7/5 modular showcase pairing hero offer with product capabilities.",
    },
    {
        "slug": "split-studio",
        "name": "Split Studio",
        "profiles": ("commercial", "editorial"),
        "materials": ("photo", "product"),
        "jobs": ("hire", "book", "buy"),
        "sections": ["Split", "Showcase", "Rows", "Form"],
        "summary": "Balanced 50/50 or 60/40 diptych alternating copy and crisp visual evidence.",
    },
    {
        "slug": "workbench",
        "name": "Workbench",
        "profiles": ("commercial", "app"),
        "materials": ("product", "data"),
        "jobs": ("try", "signup", "operate"),
        "sections": ["Split", "Switcher", "Steps", "Offer"],
        "summary": "Interactive live product preview up front followed by workflow switcher and pricing.",
    },
    {
        "slug": "catalogue",
        "name": "Catalogue",
        "profiles": ("commercial",),
        "materials": ("photo", "product"),
        "jobs": ("buy", "book"),
        "sections": ["Split", "Grid", "Offer", "Form"],
        "summary": "Direct storefront grid with scannable prices, filters, and immediate purchase or booking CTA.",
    },
    {
        "slug": "narrative-workflow",
        "name": "Narrative Workflow",
        "profiles": ("commercial", "editorial"),
        "materials": ("photo", "product", "words"),
        "jobs": ("hire", "book", "signup"),
        "sections": ["Split", "Steps", "Pinned", "Form"],
        "summary": "Outcome-led hero into numbered execution stages, proof estimates, and intake form.",
    },
    {
        "slug": "feature-stack",
        "name": "Feature Stack",
        "profiles": ("commercial", "editorial"),
        "materials": ("product", "photo"),
        "jobs": ("try", "buy", "hire"),
        "sections": ["Showcase", "Pinned", "Figures", "Offer"],
        "summary": "Sticky narrative column beside full-bleed scrolling visual frames.",
    },
    {
        "slug": "stat-led",
        "name": "Stat-Led",
        "profiles": ("commercial", "editorial"),
        "materials": ("data", "words"),
        "jobs": ("hire", "signup", "try"),
        "sections": ["Statement", "Figures", "Table", "Form"],
        "summary": "Verified benchmark or SLA headline paired with structured comparison evidence.",
    },
    {
        "slug": "photographic",
        "name": "Photographic",
        "profiles": ("editorial", "commercial"),
        "materials": ("photo",),
        "jobs": ("book", "hire", "buy"),
        "sections": ["Showcase", "Split", "Rail", "Form"],
        "summary": "Large-format editorial photography carries the page while concise copy handles booking.",
    },
    {
        "slug": "long-document",
        "name": "Long Document",
        "profiles": ("editorial",),
        "materials": ("words", "data"),
        "jobs": ("read", "subscribe", "hire"),
        "sections": ["Statement", "Rows", "Figures", "Form"],
        "summary": "Measured single-column essay with hairline facts and zero decorative clutter.",
    },
    {
        "slug": "manifesto",
        "name": "Manifesto",
        "profiles": ("editorial",),
        "materials": ("words",),
        "jobs": ("read", "subscribe", "signup"),
        "sections": ["Statement", "Band", "Rows", "Offer"],
        "summary": "Large typographic thesis first, grounded by contrasting band and direct commitment.",
    },
    {
        "slug": "index-first",
        "name": "Index-First",
        "profiles": ("editorial", "app"),
        "materials": ("words", "data"),
        "jobs": ("read", "operate", "hire"),
        "sections": ["Index", "Rows", "Table", "Form"],
        "summary": "Structured hairline directory putting navigation, archives, or records at the top.",
    },
    {
        "slug": "conversational-faq",
        "name": "Conversational FAQ",
        "profiles": ("commercial", "editorial"),
        "materials": ("words", "product"),
        "jobs": ("buy", "hire", "book"),
        "sections": ["Split", "Rows", "Table", "Form"],
        "summary": "Direct high-trust objection handling with visible answers instead of cramped accordions.",
    },
    {
        "slug": "table-workspace",
        "name": "Table Workspace",
        "profiles": ("app",),
        "materials": ("data", "product"),
        "jobs": ("operate",),
        "sections": ["Index", "Table", "Switcher", "Form"],
        "summary": "Filter-first operational view with tabular-nums grid, inline actions, and URL state.",
    },
    {
        "slug": "master-detail",
        "name": "Master-Detail Console",
        "profiles": ("app",),
        "materials": ("data", "words", "product"),
        "jobs": ("operate",),
        "sections": ["Index", "Split", "Schedule", "Rows"],
        "summary": "Queue or record index paired with dense contextual inspector and zero hero bloat.",
    },
]

DIRECTIONS: list[dict[str, Any]] = [
    {
        "slug": "warm-paper-ink",
        "name": "Warm Paper & Charcoal Ink",
        "profiles": ("editorial", "commercial"),
        "polarity": "light",
        "surface_ladder": "warm off-white -> soft bone -> crisp white card",
        "radius": "soft (6-8px)",
        "accent_posture": "single terracotta or vermilion action accent",
        "typography_roles": "humanist/editorial serif display + clean sans body (prefer project fonts)",
    },
    {
        "slug": "swiss-broadsheet",
        "name": "Swiss Broadsheet Hairline",
        "profiles": ("editorial", "commercial", "app"),
        "polarity": "light",
        "surface_ladder": "neutral white -> 1px hairlines -> muted stone band",
        "radius": "sharp (2-4px)",
        "accent_posture": "signal red or cobalt reserved for active CTA and focus rings",
        "typography_roles": "tight grotesk display + tabular sans/mono for figures",
    },
    {
        "slug": "slate-atelier",
        "name": "Slate Atelier",
        "profiles": ("commercial", "editorial"),
        "polarity": "dark",
        "surface_ladder": "deep charcoal -> elevated graphite -> 10% hairline border",
        "radius": "soft (6-10px)",
        "accent_posture": "warm amber or brass CTA with dark ink label",
        "typography_roles": "high-contrast serif or condensed display + neutral sans body",
    },
    {
        "slug": "clinical-utility",
        "name": "Clinical Utility",
        "profiles": ("commercial", "app"),
        "polarity": "light",
        "surface_ladder": "cool porcelain -> crisp white panels -> hairline dividers",
        "radius": "medium (6-8px)",
        "accent_posture": "deep cobalt or teal accent strictly on primary controls",
        "typography_roles": "legible sans throughout with tabular numerals (zero decorative display)",
    },
    {
        "slug": "industrial-blueprint",
        "name": "Industrial Blueprint",
        "profiles": ("commercial", "app"),
        "polarity": "dark",
        "surface_ladder": "midnight slate -> steel panel -> crisp 1px grid rules",
        "radius": "sharp (0-4px)",
        "accent_posture": "high-contrast lime or safety orange strictly for action/status",
        "typography_roles": "geometric sans display + monospace technical metadata",
    },
    {
        "slug": "nordic-craft",
        "name": "Nordic Craft Tactile",
        "profiles": ("commercial", "editorial"),
        "polarity": "light",
        "surface_ladder": "linen surface -> sand muted band -> subtle card elevation",
        "radius": "soft (8-12px)",
        "accent_posture": "forest green or burnt sienna single accent",
        "typography_roles": "warm humanist sans headings + readable 16px+ sans body",
    },
    {
        "slug": "obsidian-console",
        "name": "Obsidian Console",
        "profiles": ("app", "commercial"),
        "polarity": "dark",
        "surface_ladder": "near-black canvas -> matte slate cards -> subtle light border",
        "radius": "sharp (4-6px)",
        "accent_posture": "crisp cyan or emerald reserved for active state and primary submit",
        "typography_roles": "clean UI sans + tabular mono for IDs, timestamps, and metrics",
    },
    {
        "slug": "archival-vellum",
        "name": "Archival Vellum",
        "profiles": ("editorial",),
        "polarity": "light",
        "surface_ladder": "cream vellum -> pale parchment band -> hairline rules only",
        "radius": "sharp (0-2px)",
        "accent_posture": "burgundy or espresso ink accent, zero pill buttons",
        "typography_roles": "classical serif headings + restrained sans body",
    },
    {
        "slug": "high-contrast-retail",
        "name": "High-Contrast Retail",
        "profiles": ("commercial",),
        "polarity": "light",
        "surface_ladder": "pure white -> light neutral product wells -> dark footer band",
        "radius": "medium (8px)",
        "accent_posture": "vivid coral or emerald primary buy button, muted neutral badges",
        "typography_roles": "bold grotesk headline + scannable sans price/spec copy",
    },
    {
        "slug": "daylight-workbench",
        "name": "Daylight Workbench",
        "profiles": ("app",),
        "polarity": "light",
        "surface_ladder": "cool slate-50 canvas -> white workspace tables -> 1px crisp borders",
        "radius": "medium (6px)",
        "accent_posture": "controlled royal blue for primary action, active tab, and focus",
        "typography_roles": "single UI sans family + tabular-nums on all numeric columns",
    },
]

HERO_POSTURES = {
    "commercial": [
        "Split-offer: concise headline + one proof line + primary CTA on left, live product/photo right",
        "Editorial-stage: bold offer headline above full-bleed product frame with inline action bar",
        "Asymmetric-workbench: compact value statement paired with interactive preview or calculator",
        "Direct-catalogue: compact search/filter bar + immediate category strip above the fold",
    ],
    "editorial": [
        "Settled-split: left-aligned 7-word headline + single sentence + one quiet link, photo right",
        "Statement-first: large set type across 8 columns, concrete fact below, zero decorative pill",
        "Full-bleed-frame: crisp edge-to-edge photograph with bottom-left headline and one action",
    ],
    "app": [
        "Top-bar shell: compact header with breadcrumb + primary action + inline filter toolbar",
        "Split-workbench: collapsible navigation rail (>7 destinations) + sticky table header",
        "Command-header: URL-synced tabs + search/filter strip directly above data grid",
    ],
}

AVOID_POOL = [
    "three-identical-icon-cards",
    "centered-eyebrow-pill-stack",
    "violet-gradient-hero-orb",
    "fake-testimonial-carousel",
    "generic-newsletter-footer-band",
    "box-in-box-shadow-cards",
]


def _load_log(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.is_file():
        return []
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and isinstance(data.get("entries"), list):
        return [x for x in data["entries"] if isinstance(x, dict)]
    return []


def _pick_with_rotation(
    candidates: list[dict[str, Any]],
    recent_slugs: list[str],
    count: int,
    rng: random.Random,
) -> tuple[list[dict[str, Any]], bool]:
    """Pick up to `count` items preferring ones not in `recent_slugs`; gracefully fall back."""
    fresh = [c for c in candidates if c["slug"] not in recent_slugs]
    exhausted = len(fresh) == 0
    pool = list(fresh) if fresh else list(candidates)
    rng.shuffle(pool)

    picked = pool[:count]
    if len(picked) < count:
        used_now = {p["slug"] for p in picked}
        # Fill remainder from least-recently-used candidates without duplicating
        recency_rank = {slug: idx for idx, slug in enumerate(recent_slugs)}
        rest = [c for c in candidates if c["slug"] not in used_now]
        rest.sort(key=lambda c: recency_rank.get(c["slug"], -1), reverse=True)
        picked.extend(rest[: count - len(picked)])
    return picked, exhausted


def _cmd_deal(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    log_path = Path(args.log)
    entries = _load_log(log_path)

    recent_macros = [e["macrostructure"] for e in entries[:4] if isinstance(e.get("macrostructure"), str)]
    recent_dirs = [e["direction"] for e in entries[:4] if isinstance(e.get("direction"), str)]
    recent_heroes = [e["hero"] for e in entries[:3] if isinstance(e.get("hero"), str)]

    macro_pool = [
        m for m in MACROSTRUCTURES
        if args.profile in m["profiles"] and args.material in m["materials"]
    ]
    if not macro_pool:
        macro_pool = [m for m in MACROSTRUCTURES if args.profile in m["profiles"]] or list(MACROSTRUCTURES)
    job_preferred = [m for m in macro_pool if args.job in m["jobs"]]
    if job_preferred:
        macro_pool = job_preferred

    picked_macros, macro_exhausted = _pick_with_rotation(macro_pool, recent_macros, 1, rng)
    chosen_macro = picked_macros[0]

    dir_pool = [d for d in DIRECTIONS if args.profile in d["profiles"]] or list(DIRECTIONS)
    picked_dirs, dir_exhausted = _pick_with_rotation(dir_pool, recent_dirs, args.count, rng)

    hero_options = HERO_POSTURES.get(args.profile, HERO_POSTURES["commercial"])
    fresh_heroes = [h for h in hero_options if h not in recent_heroes] or list(hero_options)
    chosen_hero = rng.choice(fresh_heroes)

    avoid_pool = list(AVOID_POOL)
    rng.shuffle(avoid_pool)
    avoid = avoid_pool[:2]

    result = {
        "profile": args.profile,
        "material": args.material,
        "job": args.job,
        "history_entries": len(entries),
        "rotation_exhausted": macro_exhausted or dir_exhausted,
        "macrostructure": chosen_macro,
        "hero_or_shell": chosen_hero,
        "directions": picked_dirs,
        "avoid_compositions": avoid,
    }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"[ui-deal] profile={args.profile} material={args.material} job={args.job} (history={len(entries)})")
    print(f"  Macrostructure: {chosen_macro['slug']} ({chosen_macro['name']}) — {chosen_macro['summary']}")
    print(f"  Sections:       {' -> '.join(chosen_macro['sections'])}")
    print(f"  Hero / Shell:   {chosen_hero}")
    print(f"  Avoid:          {', '.join(avoid)}")
    print("  Candidate directions:")
    for i, d in enumerate(picked_dirs, start=1):
        print(
            f"    {i}. {d['slug']} [{d['polarity']}, {d['radius']}] — "
            f"{d['surface_ladder']}; accent: {d['accent_posture']}; type: {d['typography_roles']}"
        )
    return 0


def _cmd_log(args: argparse.Namespace) -> int:
    log_path = Path(args.log)
    entries = _load_log(log_path)
    entry = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "profile": args.profile,
        "macrostructure": args.macrostructure,
        "direction": args.direction,
        "hero": args.hero or "",
        "note": args.note or "",
    }
    updated = [entry, *entries][:50]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps({"entries": updated}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps({"log": str(log_path), "entry": entry, "total": len(updated)}, indent=2, ensure_ascii=False))
    else:
        print(f"[ui-log] recorded {args.macrostructure} + {args.direction} ({args.profile}) -> {log_path} ({len(updated)} entries)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rotation-aware dealer for UI macrostructures, directions, and section variety."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_deal = sub.add_parser("deal", help="Deal macrostructure, hero/shell, and candidate material directions.")
    p_deal.add_argument("--profile", choices=PROFILES, required=True)
    p_deal.add_argument("--material", choices=MATERIALS, required=True)
    p_deal.add_argument("--job", choices=JOBS, required=True)
    p_deal.add_argument("--log", default=".ui-craft/log.json", help="Rotation log JSON file.")
    p_deal.add_argument("--count", type=int, default=3, help="Number of candidate directions to deal.")
    p_deal.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducible output.")
    p_deal.add_argument("--json", action="store_true", help="Print JSON output.")

    p_log = sub.add_parser("log", help="Prepend a build decision to the rotation log.")
    p_log.add_argument("--log", default=".ui-craft/log.json", help="Rotation log JSON file.")
    p_log.add_argument("--profile", choices=PROFILES, required=True)
    p_log.add_argument("--macrostructure", required=True)
    p_log.add_argument("--direction", required=True)
    p_log.add_argument("--hero", default="")
    p_log.add_argument("--note", default="")
    p_log.add_argument("--json", action="store_true", help="Print JSON output.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "deal":
        return _cmd_deal(args)
    if args.cmd == "log":
        return _cmd_log(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
