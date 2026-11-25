"""Unit tests for repository tooling: scaffold.py, manager.py, and test-triggers.py isolation."""

from __future__ import annotations

from contextlib import redirect_stderr
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
LIB_DIR = SCRIPTS_DIR / "lib"
SKILL_FORGE_SCRIPTS = REPO_ROOT / "skills" / "skill-forge" / "scripts"

for p in (SCRIPTS_DIR, LIB_DIR, SKILL_FORGE_SCRIPTS):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import _spec  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


scaffold = _load_module("scaffold", LIB_DIR / "scaffold.py")
manager = _load_module("manager", LIB_DIR / "manager.py")


class TestScaffold(unittest.TestCase):
    def test_scaffold_skill_with_all_options(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            skills_dir.mkdir()
            created = scaffold.scaffold_skill(
                "sample-skill-2",
                with_scripts=True,
                with_references=True,
                with_assets=True,
                with_hook=True,
                skills_dir=skills_dir,
            )
            self.assertTrue((created / "SKILL.md").is_file())
            self.assertTrue((created / "hook-triggers.json").is_file())
            self.assertTrue((created / "scripts").is_dir())
            self.assertTrue((created / "references").is_dir())
            self.assertTrue((created / "assets").is_dir())

            _, errors, warnings = _spec.validate_skill_structure(created)
            self.assertEqual(errors, [])
            self.assertTrue(any("TODO:" in w for w in warnings))

            hook_data = json.loads((created / "hook-triggers.json").read_text(encoding="utf-8"))
            self.assertEqual(hook_data["skill"], "sample-skill-2")
            self.assertFalse(hook_data["enabled"])
            tests_file = created / "evals" / "trigger-tests.json"
            self.assertTrue(tests_file.is_file())
            tests_text = tests_file.read_text(encoding="utf-8")
            self.assertNotIn("__SKILL_NAME__", tests_text)
            tests_data = json.loads(tests_text)
            self.assertIn("sample-skill-2", tests_data["prompts"][0]["query"])

    def test_scaffold_validation_and_conflict_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp) / "skills"
            skills_dir.mkdir()
            for bad in ("", "BadName", "bad_name", "a" * 65):
                with self.assertRaises(ValueError):
                    scaffold.scaffold_skill(bad, skills_dir=skills_dir)

            scaffold.scaffold_skill("dup-skill", skills_dir=skills_dir)
            with self.assertRaises(FileExistsError):
                scaffold.scaffold_skill("dup-skill", skills_dir=skills_dir)


class TestManager(unittest.TestCase):
    def test_helpers(self) -> None:
        self.assertEqual(
            manager.find_held_back({"result": [{"held_back_removals": ["extra.txt"]}]}),
            ["extra.txt"],
        )
        self.assertEqual(manager.find_held_back({"ok": True}), [])
        self.assertEqual(manager.extract_id([{"data": {"id": "sk-123"}}]), "sk-123")
        self.assertIsNone(manager.extract_id([{"id": "a"}, {"id": "b"}]))

    def test_cli_flag_validation(self) -> None:
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.assertEqual(manager.main([]), 2)
            self.assertEqual(manager.main(["--all", "skill-forge"]), 2)


class TestTriggerRunnerIsolation(unittest.TestCase):
    def test_live_router_does_not_touch_caller_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as runtime_dir:
            sentinel = Path(runtime_dir) / "custom-skills-router-state.json"
            sentinel_body = '["keep-this-sentinel"]'
            sentinel.write_text(sentinel_body, encoding="utf-8")

            env = dict(os.environ)
            env["XDG_RUNTIME_DIR"] = runtime_dir
            proc = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_FORGE_SCRIPTS / "test-triggers.py"),
                    str(REPO_ROOT / "skills" / "skill-forge"),
                    "--live-router",
                ],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            self.assertTrue(sentinel.is_file())
            self.assertEqual(sentinel.read_text(encoding="utf-8"), sentinel_body)

    def test_rejects_empty_or_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "demo-skill"
            skill_dir.mkdir()
            (skill_dir / "hook-triggers.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "enabled": True,
                    "skill": "demo-skill",
                    "prompt_regex": r"\bdemo\b",
                }),
                encoding="utf-8",
            )
            empty_tests = Path(tmp) / "empty.json"
            empty_tests.write_text('{"prompts": [], "shell": []}', encoding="utf-8")
            p_empty = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_FORGE_SCRIPTS / "test-triggers.py"),
                    str(skill_dir),
                    "--test-file",
                    str(empty_tests),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_empty.returncode, 1)
            self.assertIn("no test cases", p_empty.stderr)

            typo_tests = Path(tmp) / "typo.json"
            typo_tests.write_text('{"prompt": [{"query": "demo", "should_trigger": true}]}', encoding="utf-8")
            p_typo = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_FORGE_SCRIPTS / "test-triggers.py"),
                    str(skill_dir),
                    "--test-file",
                    str(typo_tests),
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(p_typo.returncode, 1)
            self.assertIn("unknown key", p_typo.stderr)


if __name__ == "__main__":
    unittest.main()
