#!/usr/bin/env python3
"""Validate skill directories in this repository using the canonical skill-forge spec."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from lib.common import REPO_ROOT, load_skill_spec, resolve_skill_targets  # noqa: E402


def validate_skill_dir(skill_dir: Path) -> tuple[list[str], list[str]]:
    """Validate a single skill directory and return (errors, warnings)."""
    spec = load_skill_spec()
    _, errors, warnings = spec.validate_skill_structure(skill_dir)
    return errors, warnings


def resolve_targets(args: list[str], repo_root: Path) -> tuple[list[Path], list[str]]:
    return resolve_skill_targets(args, repo_root)


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

    targets, missing = resolve_skill_targets(parsed.skills, REPO_ROOT)

    if missing:
        for item in missing:
            print(f"[ERROR] {item}: skill directory not found", file=sys.stderr)
        return 1

    if not targets:
        print(f"No skills found in {REPO_ROOT / 'skills'} — nothing to validate.")
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

    if total_errors > 0 or (parsed.strict and total_warnings > 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
