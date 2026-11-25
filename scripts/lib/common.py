"""Shared utilities for repository-level scripts (not imported by standalone skills)."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
SKILL_FORGE_SCRIPTS = SKILLS_DIR / "skill-forge" / "scripts"


def load_skill_spec() -> ModuleType:
    """Load the canonical skill specification module from skills/skill-forge/scripts/_spec.py."""
    if "_spec" in sys.modules:
        return sys.modules["_spec"]
    spec_path = SKILL_FORGE_SCRIPTS / "_spec.py"
    if not spec_path.is_file():
        raise RuntimeError(f"Canonical skill spec module not found: {spec_path}")
    spec = importlib.util.spec_from_file_location("_spec", spec_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load skill spec module: {spec_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["_spec"] = module
    spec.loader.exec_module(module)
    return module


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from path, returning {} when missing or blank."""
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a top-level JSON object")
    return data


def atomic_write_text(
    path: Path,
    content: str,
    backup: bool = True,
    backup_suffix: str = ".bak-skills-router",
) -> None:
    """Atomically write UTF-8 text to path, creating an optional backup first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        bak = path.with_name(path.name + backup_suffix)
        shutil.copy2(path, bak)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def resolve_skill_targets(
    args: list[str], repo_root: Path = REPO_ROOT
) -> tuple[list[Path], list[str]]:
    """Resolve skill names or directory paths into (existing_dirs, missing_inputs)."""
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
