#!/usr/bin/env python3
"""Unified quality gate for the skills repository (stdlib only)."""

from __future__ import annotations

import argparse
import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from lib.common import REPO_ROOT, SKILL_FORGE_SCRIPTS, SKILLS_DIR  # noqa: E402


def run_step(title: str, cmd: list[str], *, cwd: Path | None = None) -> int:
    print(f"\n==> {title}")
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    if proc.returncode != 0:
        print(f"[FAILED] {title} (exit {proc.returncode})", file=sys.stderr)
    return proc.returncode


def check_py_compile() -> int:
    print("==> 1/5 Compile Python scripts")
    py_files: list[Path] = []
    for base in (REPO_ROOT / "scripts", REPO_ROOT / "tests"):
        if base.is_dir():
            py_files.extend(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)
    if SKILLS_DIR.is_dir():
        for skill_dir in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")):
            scripts_dir = skill_dir / "scripts"
            if scripts_dir.is_dir():
                py_files.extend(p for p in scripts_dir.rglob("*.py") if "__pycache__" not in p.parts)

    py_files = sorted(set(py_files))
    for py_file in py_files:
        try:
            py_compile.compile(str(py_file), doraise=True)
        except py_compile.PyCompileError as exc:
            print(f"[ERROR] {py_file.relative_to(REPO_ROOT)}: {exc}", file=sys.stderr)
            return 1
    print(f"Compiled {len(py_files)} Python file(s) cleanly.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run all validation, audit, trigger parity, and unit tests in the skills repository."
    )
    parser.add_argument(
        "--require-js",
        action="store_true",
        help="Require bun or node for JS RegExp parity checks.",
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip the unittest suite under tests/.",
    )
    args = parser.parse_args(argv)

    if check_py_compile() != 0:
        return 1

    if run_step(
        "2/5 Validate skills (strict)",
        [sys.executable, str(_SCRIPT_DIR / "validate.py"), "--strict"],
    ) != 0:
        return 1

    skill_dirs = sorted(
        p for p in SKILLS_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
    ) if SKILLS_DIR.is_dir() else []

    if skill_dirs:
        if run_step(
            "3/5 Audit token budgets & structure (strict)",
            [
                sys.executable,
                str(SKILL_FORGE_SCRIPTS / "audit-skill.py"),
                "--strict",
                *[str(d) for d in skill_dirs],
            ],
        ) != 0:
            return 1

    print("\n==> 4/5 Test skill hook triggers (live router + JS parity)")
    has_js = bool(shutil.which("bun") or shutil.which("node"))
    use_js = args.require_js or has_js
    tested_triggers = 0
    for skill_dir in skill_dirs:
        hook_file = skill_dir / "hook-triggers.json"
        if not hook_file.is_file():
            continue
        test_file = skill_dir / "evals" / "trigger-tests.json"
        hook_data = json.loads(hook_file.read_text(encoding="utf-8"))
        if hook_data.get("enabled") is True and not test_file.is_file():
            print(
                f"[ERROR] {skill_dir.name}: enabled hook-triggers.json requires evals/trigger-tests.json",
                file=sys.stderr,
            )
            return 1
        if test_file.is_file():
            cmd = [
                sys.executable,
                str(SKILL_FORGE_SCRIPTS / "test-triggers.py"),
                str(skill_dir),
                "--live-router",
            ]
            if use_js:
                cmd.append("--js-check")
            proc = subprocess.run(cmd)
            if proc.returncode != 0:
                return proc.returncode
            tested_triggers += 1
    if tested_triggers == 0:
        print("No trigger tests found.")

    if not args.skip_tests:
        if run_step(
            "5/5 Run unit test suite",
            [sys.executable, "-m", "unittest", "discover", "-s", str(REPO_ROOT / "tests"), "-v"],
            cwd=REPO_ROOT,
        ) != 0:
            return 1

    print("\nAll repository checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
