"""Unit tests for scripts/sync-hooks.py using isolated temporary HOME directories."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_sync_hooks():
    spec = importlib.util.spec_from_file_location("sync_hooks", SCRIPTS_DIR / "sync-hooks.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sync_hooks"] = mod
    spec.loader.exec_module(mod)
    return mod


sync_hooks = _load_sync_hooks()


class TestSyncHooks(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.router = REPO_ROOT / "scripts" / "skill-hook-router.py"
        for ag in sync_hooks.SUPPORTED_AGENTS:
            sync_hooks.agent_config_dir(ag, home=self.home).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_install_status_idempotent_and_uninstall_all_agents(self) -> None:
        detected = sync_hooks.detect_installed_agents(home=self.home)
        self.assertEqual(set(detected), set(sync_hooks.SUPPORTED_AGENTS))

        for ag in sync_hooks.SUPPORTED_AGENTS:
            with self.subTest(agent=ag):
                installed, _ = sync_hooks.check_agent_status(ag, home=self.home)
                self.assertFalse(installed)

                action1, _ = sync_hooks.sync_agent(
                    ag, REPO_ROOT, self.router, uninstall=False, dry_run=False, home=self.home
                )
                self.assertEqual(action1, "created")
                installed2, _ = sync_hooks.check_agent_status(ag, home=self.home)
                self.assertTrue(installed2)

                action2, _ = sync_hooks.sync_agent(
                    ag, REPO_ROOT, self.router, uninstall=False, dry_run=False, home=self.home
                )
                self.assertEqual(action2, "unchanged")

                action3, _ = sync_hooks.sync_agent(
                    ag, REPO_ROOT, self.router, uninstall=True, dry_run=False, home=self.home
                )
                self.assertEqual(action3, "removed")
                installed3, _ = sync_hooks.check_agent_status(ag, home=self.home)
                self.assertFalse(installed3)

    def test_codex_uninstall_when_absent_does_not_create_file(self) -> None:
        action, path_str = sync_hooks.sync_agent(
            "codex", REPO_ROOT, self.router, uninstall=True, dry_run=False, home=self.home
        )
        self.assertEqual(action, "absent")
        self.assertFalse(Path(path_str).exists())

    def test_preserves_unrelated_user_hooks_and_settings(self) -> None:
        settings_path = self.home / ".claude" / "settings.json"
        initial = {
            "permissions": {"allow": ["Read"]},
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Write",
                        "hooks": [{"type": "command", "command": "echo user-write-hook"}],
                    }
                ],
                "PostToolUse": [
                    {"hooks": [{"type": "command", "command": "echo post-hook"}]}
                ],
            },
        }
        settings_path.write_text(json.dumps(initial), encoding="utf-8")

        action, _ = sync_hooks.sync_agent(
            "claude_code", REPO_ROOT, self.router, uninstall=False, dry_run=False, home=self.home
        )
        self.assertEqual(action, "updated")
        after_install = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(after_install["permissions"], {"allow": ["Read"]})
        self.assertIn("PostToolUse", after_install["hooks"])
        self.assertEqual(len(after_install["hooks"]["PreToolUse"]), 2)

        action_rm, _ = sync_hooks.sync_agent(
            "claude_code", REPO_ROOT, self.router, uninstall=True, dry_run=False, home=self.home
        )
        self.assertEqual(action_rm, "removed")
        after_uninstall = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(after_uninstall, initial)

    def test_dry_run_makes_no_writes(self) -> None:
        for ag in sync_hooks.SUPPORTED_AGENTS:
            action, path_str = sync_hooks.sync_agent(
                ag, REPO_ROOT, self.router, uninstall=False, dry_run=True, home=self.home
            )
            self.assertEqual(action, "created")
            self.assertFalse(Path(path_str).exists())


if __name__ == "__main__":
    unittest.main()
