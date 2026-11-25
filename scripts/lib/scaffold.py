#!/usr/bin/env python3
"""Scaffold a new skill under skills/<skill-name>/ from templates/skill-template/."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _LIB_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.common import REPO_ROOT, SKILLS_DIR, load_skill_spec  # noqa: E402


def scaffold_skill(
    skill_name: str,
    *,
    with_scripts: bool = False,
    with_references: bool = False,
    with_assets: bool = False,
    with_hook: bool = False,
    skills_dir: Path = SKILLS_DIR,
    template_dir: Path = REPO_ROOT / "templates" / "skill-template",
) -> Path:
    """Create a new skill directory from template_dir under skills_dir."""
    spec = load_skill_spec()
    if not skill_name:
        raise ValueError("<skill-name> is required.")
    if not spec.NAME_RE.match(skill_name):
        raise ValueError(
            f"invalid skill name '{skill_name}'. Use kebab-case (lowercase letters, digits, single hyphens)."
        )
    if len(skill_name) > 64:
        raise ValueError(f"skill name '{skill_name}' is too long ({len(skill_name)} chars; max 64).")

    template_file = template_dir / "SKILL.md"
    if not template_file.is_file():
        raise FileNotFoundError(f"template file not found: {template_file}")

    hook_template_file = template_dir / "hook-triggers.json"
    if with_hook and not hook_template_file.is_file():
        raise FileNotFoundError(f"hook template file not found: {hook_template_file}")

    target_dir = skills_dir / skill_name
    if target_dir.exists():
        raise FileExistsError(f"target directory already exists: {target_dir}")

    target_dir.mkdir(parents=True, exist_ok=False)
    if with_scripts:
        (target_dir / "scripts").mkdir()
    if with_references:
        (target_dir / "references").mkdir()
    if with_assets:
        (target_dir / "assets").mkdir()

    skill_text = template_file.read_text(encoding="utf-8")
    (target_dir / "SKILL.md").write_text(
        skill_text.replace("__SKILL_NAME__", skill_name), encoding="utf-8"
    )

    if with_hook:
        hook_text = hook_template_file.read_text(encoding="utf-8")
        (target_dir / "hook-triggers.json").write_text(
            hook_text.replace("__SKILL_NAME__", skill_name), encoding="utf-8"
        )
        tests_template = template_dir / "evals" / "trigger-tests.json"
        if tests_template.is_file():
            (target_dir / "evals").mkdir(exist_ok=True)
            tests_text = tests_template.read_text(encoding="utf-8")
            (target_dir / "evals" / "trigger-tests.json").write_text(
                tests_text.replace("__SKILL_NAME__", skill_name), encoding="utf-8"
            )

    return target_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="./scripts/new-skill.sh",
        description="Scaffold a new skill under skills/<skill-name>/ from templates/skill-template/SKILL.md.",
    )
    parser.add_argument("skill_name", help="Skill name in kebab-case (max 64 chars).")
    parser.add_argument("--with-scripts", action="store_true", help="Create an empty scripts/ subdirectory.")
    parser.add_argument("--with-references", action="store_true", help="Create an empty references/ subdirectory.")
    parser.add_argument("--with-assets", action="store_true", help="Create an empty assets/ subdirectory.")
    parser.add_argument("--with-hook", action="store_true", help="Scaffold a starter hook-triggers.json (disabled by default).")
    args = parser.parse_args(argv)

    try:
        target_dir = scaffold_skill(
            args.skill_name,
            with_scripts=args.with_scripts,
            with_references=args.with_references,
            with_assets=args.with_assets,
            with_hook=args.with_hook,
        )
    except (ValueError, FileNotFoundError, FileExistsError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created skill scaffold: {target_dir}")
    print("Next steps:")
    print(f"  1. Edit {target_dir}/SKILL.md")
    print(f"  2. ./scripts/validate.py --strict {args.skill_name}")
    print(f"  3. ./scripts/sync-to-manager.sh {args.skill_name} --deploy claude_code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
