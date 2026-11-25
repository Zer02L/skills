"""Unit tests for canonical skill spec parsing, validation, and audit-skill.py."""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_FORGE_DIR = REPO_ROOT / "skills" / "skill-forge"
SKILL_FORGE_SCRIPTS = SKILL_FORGE_DIR / "scripts"

if str(SKILL_FORGE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SKILL_FORGE_SCRIPTS))

import _spec  # noqa: E402


def _load_audit_module():
    spec = importlib.util.spec_from_file_location(
        "audit_skill", SKILL_FORGE_SCRIPTS / "audit-skill.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


audit_skill_mod = _load_audit_module()


class TestFrontmatterParser(unittest.TestCase):
    def test_stdlib_frontmatter_features(self) -> None:
        doc = (
            "---\n"
            "name: demo-skill  # inline comment\n"
            'description: "Line1\\nLine2 \\"quoted\\" \\x41 \\u0042"\n'
            "license: 'MIT ''custom'''\n"
            "allowed-tools: [Bash, \"Read,Write\", 3, true, null]\n"
            "metadata:\n"
            "  author: test\n"
            "  tags:\n"
            "    - one\n"
            "    - two\n"
            "compatibility: >-\n"
            "  Python 3 stdlib\n"
            "  across platforms\n"
            "---\n"
            "# Body\n"
        )
        fm, fm_raw, line_count = _spec.extract_frontmatter(doc, use_pyyaml=False)
        self.assertEqual(fm["name"], "demo-skill")
        self.assertEqual(fm["description"], 'Line1\nLine2 "quoted" A B')
        self.assertEqual(fm["license"], "MIT 'custom'")
        self.assertEqual(fm["allowed-tools"], ["Bash", "Read,Write", 3, True, None])
        self.assertEqual(fm["metadata"], {"author": "test", "tags": ["one", "two"]})
        self.assertEqual(fm["compatibility"], "Python 3 stdlib across platforms")
        self.assertTrue(fm_raw.startswith("---\n"))
        self.assertTrue(fm_raw.endswith("---"))
        self.assertEqual(line_count, 16)

    def test_block_scalar_chomp_modes(self) -> None:
        doc = (
            "---\n"
            "name: chomp-test\n"
            "description: |\n"
            "  alpha\n"
            "  beta\n"
            "license: |+\n"
            "  keep\n"
            "\n"
            "compatibility: |-\n"
            "  trim\n"
            "---\n"
        )
        fm, _, _ = _spec.extract_frontmatter(doc, use_pyyaml=False)
        self.assertEqual(fm["description"], "alpha\nbeta\n")
        self.assertEqual(fm["license"], "keep\n\n")
        self.assertEqual(fm["compatibility"], "trim")

    def test_frontmatter_errors(self) -> None:
        cases = [
            "no opening delimiter\nname: a\n---\n",
            "---\nname: a\nmissing closing\n",
            "---\nname: a\nname: b\n---\n",
            "---\nname: a\n\tbad: tab\n---\n",
        ]
        for content in cases:
            with self.subTest(content=content):
                with self.assertRaises(_spec.FrontmatterError):
                    _spec.extract_frontmatter(content, use_pyyaml=False)

    def test_pyyaml_error_converted_to_frontmatter_error(self) -> None:
        fake_yaml = SimpleNamespace(
            safe_load=lambda _text: (_ for _ in ()).throw(ValueError("bad yaml"))
        )
        with patch.object(_spec, "yaml", fake_yaml):
            with self.assertRaises(_spec.FrontmatterError):
                _spec.extract_frontmatter("---\nname: [unclosed\n---\n", use_pyyaml=True)


class TestHookTriggersSpec(unittest.TestCase):
    def test_valid_hook_triggers(self) -> None:
        data = {
            "schema_version": 1,
            "enabled": True,
            "skill": "my-skill",
            "case_insensitive": True,
            "prompt_regex": r"\bmy-skill\b",
            "hint": "Read SKILL.md first.",
            "deny_shell": [
                {
                    "regex": r"\bforbidden\b",
                    "allow_if_regex": r"\bwrapper\.sh\b",
                    "reason": "Use wrapper.sh",
                }
            ],
        }
        errors, warnings = _spec.validate_hook_triggers_data(data, "my-skill")
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_invalid_hook_triggers_and_warnings(self) -> None:
        bad = {
            "schema_version": True,
            "enabled": "yes",
            "skill": "other-skill",
            "case_insensitive": "true",
            "prompt_regex": r"(?i)\btest\b",
            "hint": 123,
            "deny_shell": "not-a-list",
        }
        errors, _ = _spec.validate_hook_triggers_data(bad, "my-skill")
        joined = "\n".join(errors)
        self.assertIn("schema_version", joined)
        self.assertIn("enabled", joined)
        self.assertIn("skill", joined)
        self.assertIn("case_insensitive", joined)
        self.assertIn("inline flags", joined)
        self.assertIn("hint", joined)
        self.assertIn("deny_shell", joined)

        cyr_warn = {
            "schema_version": 1,
            "enabled": True,
            "skill": "my-skill",
            "prompt_regex": r"\bскилл\b",
            "hint": "TODO: replace me",
            "deny_shell": [{"regex": "[unclosed"}],
        }
        errors2, warnings2 = _spec.validate_hook_triggers_data(cyr_warn, "my-skill")
        self.assertTrue(any("invalid regex" in e for e in errors2))
        self.assertTrue(any("Cyrillic" in w for w in warnings2))
        self.assertTrue(any("TODO:" in w for w in warnings2))


class TestAuditSkill(unittest.TestCase):
    def test_independent_line_and_token_warnings_and_scripts_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "heavy-skill"
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(parents=True)

            # >500 lines AND >2000 tokens (~8000+ bytes)
            body_lines = [f"- Rule {i}: keep payloads bounded and deterministic." for i in range(520)]
            skill_md = (
                "---\n"
                "name: heavy-skill\n"
                "description: Test skill with both high line count and high token count.\n"
                "---\n\n" + "\n".join(body_lines) + "\n"
            )
            (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

            # Non-executable public script with shebang -> warning
            (scripts_dir / "run.py").write_text("#!/usr/bin/env python3\nprint('ok')\n", encoding="utf-8")
            # Internal helper starting with '_' -> ignored from scripts_count and chmod check
            (scripts_dir / "_helper.py").write_text("#!/usr/bin/env python3\nX = 1\n", encoding="utf-8")

            res = audit_skill_mod.audit_skill(skill_dir)
            self.assertEqual(res["errors"], [])
            warnings = "\n".join(res["warnings"])
            self.assertIn("500 lines", warnings)
            self.assertIn("Active SKILL.md is ~", warnings)
            self.assertIn("chmod +x", warnings)
            self.assertEqual(res["metrics"]["scripts_count"], 1)

    def test_skill_forge_is_standalone_portable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            copied = Path(tmp) / "skill-forge"
            shutil.copytree(SKILL_FORGE_DIR, copied)
            proc = subprocess.run(
                [sys.executable, str(copied / "scripts" / "audit-skill.py"), "--strict", "--json", str(copied)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(len(payload), 1)
            self.assertEqual(payload[0]["errors"], [])
            self.assertEqual(payload[0]["warnings"], [])
            self.assertEqual(payload[0]["metrics"]["scripts_count"], 3)

    def test_broken_refs_portability_and_enabled_hook_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "port-skill"
            scripts_dir = skill_dir / "scripts"
            refs_dir = skill_dir / "references"
            scripts_dir.mkdir(parents=True)
            refs_dir.mkdir(parents=True)

            (scripts_dir / "existing.py").write_text(
                "#!/usr/bin/env python3\nfrom lib.common import REPO_ROOT\nPATH = '/Users/bob/work'\n",
                encoding="utf-8",
            )
            (scripts_dir / "existing.py").chmod(0o755)
            (refs_dir / "guide.md").write_text("# Guide\n", encoding="utf-8")

            (skill_dir / "SKILL.md").write_text(
                (
                    "---\n"
                    "name: port-skill\n"
                    "description: Test broken references, hardcoded home path, and missing evals.\n"
                    "---\n\n"
                    "- Repo command `./scripts/check.py` and wildcard `references/*.md` and `scripts/_*.py`.\n"
                    "- Valid: `scripts/existing.py` and `references/guide.md`.\n"
                    "- Broken: `scripts/missing.py` and `references/missing.md`.\n"
                    "- Bad path: `/home/alice/repo`\n"
                ),
                encoding="utf-8",
            )
            (skill_dir / "hook-triggers.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "enabled": True,
                    "skill": "port-skill",
                    "prompt_regex": r"\bport-skill\b",
                    "hint": "Use port-skill.",
                    "deny_shell": [],
                }),
                encoding="utf-8",
            )

            res = audit_skill_mod.audit_skill(skill_dir)
            self.assertEqual(res["errors"], [])
            joined = "\n".join(res["warnings"])
            self.assertIn("scripts/missing.py", joined)
            self.assertIn("references/missing.md", joined)
            self.assertNotIn("check.py", joined)
            self.assertNotIn("guide.md", joined)
            self.assertIn("SKILL.md contains a hardcoded user home path", joined)
            self.assertIn("scripts/existing.py contains a hardcoded user home path", joined)
            self.assertIn("scripts/existing.py imports from repo-root scripts/lib", joined)
            self.assertIn("evals/trigger-tests.json is missing", joined)

            # Disabled hook should not require evals/trigger-tests.json
            (skill_dir / "hook-triggers.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "enabled": False,
                    "skill": "port-skill",
                    "prompt_regex": r"\bport-skill\b",
                }),
                encoding="utf-8",
            )
            res_disabled = audit_skill_mod.audit_skill(skill_dir)
            self.assertNotIn("evals/trigger-tests.json is missing", "\n".join(res_disabled["warnings"]))

    def test_target_strict_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "target-skill"
            refs_dir = skill_dir / "references"
            refs_dir.mkdir(parents=True)

            # ~170 idle tokens (>150, <=250), ~170 lines (>150, <=500), ~1750 active tokens (>1500, <=2000)
            long_desc = "Trigger whenever auditing " + ("word " * 120) + "end."
            body_lines = [f"- Rule {i}: keep payloads bounded." for i in range(165)]
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: target-skill\ndescription: {long_desc}\n---\n\n" + "\n".join(body_lines) + "\n",
                encoding="utf-8",
            )
            # ~2800 reference tokens (>2500, <=3500)
            (refs_dir / "big.md").write_text("x" * 11200, encoding="utf-8")

            res_default = audit_skill_mod.audit_skill(skill_dir, target_strict=False)
            self.assertEqual(res_default["errors"], [])
            self.assertEqual(res_default["warnings"], [])

            res_target = audit_skill_mod.audit_skill(skill_dir, target_strict=True)
            self.assertEqual(res_target["errors"], [])
            joined = "\n".join(res_target["warnings"])
            self.assertIn("Idle frontmatter", joined)
            self.assertIn("target <= 150 lines", joined)
            self.assertIn("Active SKILL.md", joined)
            self.assertIn("Reference references/big.md", joined)


if __name__ == "__main__":
    unittest.main()
