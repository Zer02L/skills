"""Parity tests between Python skill-hook-router.py and rendered OpenCode JS plugin."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


sync_hooks = _load_module("sync_hooks", SCRIPTS_DIR / "sync-hooks.py")
router_mod = _load_module("skill_hook_router", SCRIPTS_DIR / "skill-hook-router.py")

MATCHED_SKILL_RE = re.compile(r"^- \[([a-z0-9-]+)\]", re.MULTILINE)


def _find_js_runner() -> list[str] | None:
    node = shutil.which("node")
    if node:
        return [node, "--input-type=module", "-e"]
    bun = shutil.which("bun")
    if bun:
        return [bun, "-e"]
    return None


class TestHookRouterParity(unittest.TestCase):
    def test_python_router_matches_rendered_opencode_plugin(self) -> None:
        js_runner = _find_js_runner()
        if js_runner is None:
            self.skipTest("Neither node nor bun is available in PATH")

        prompts: list[tuple[str, str, bool]] = []
        shell_cases: list[tuple[str, str, bool]] = []
        for test_file in sorted((REPO_ROOT / "skills").glob("*/evals/trigger-tests.json")):
            skill_name = test_file.parent.parent.name
            data = json.loads(test_file.read_text(encoding="utf-8"))
            for tc in data.get("prompts", []):
                prompts.append((skill_name, tc["query"], bool(tc["should_trigger"])))
            for sc in data.get("shell", []):
                shell_cases.append((skill_name, sc["command"], bool(sc["should_deny"])))

        self.assertGreater(len(prompts), 0)
        self.assertGreater(len(shell_cases), 0)

        # Evaluate Python router in-process across all cases
        py_prompt_results: list[list[str]] = []
        for owner, query, expected in prompts:
            resp = router_mod.handle_prompt(
                "claude_code", "UserPromptSubmit", {"prompt": query}, REPO_ROOT
            )
            ctx = resp.get("hookSpecificOutput", {}).get("additionalContext", "")
            matched = sorted(MATCHED_SKILL_RE.findall(ctx))
            self.assertEqual(
                owner in matched,
                expected,
                f"Python router mismatch for {owner} prompt {query!r}: matched={matched}",
            )
            py_prompt_results.append(matched)

        py_shell_results: list[bool] = []
        for owner, cmd, expected in shell_cases:
            resp = router_mod.handle_tool(
                "claude_code",
                "PreToolUse",
                {"tool_name": "Bash", "tool_input": {"command": cmd}},
                REPO_ROOT,
            )
            denied = resp.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
            self.assertEqual(
                denied,
                expected,
                f"Python router mismatch for {owner} shell {cmd!r}: {resp}",
            )
            py_shell_results.append(denied)

        # Evaluate rendered OpenCode JS plugin in a single Node/Bun subprocess
        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = Path(tmp) / "custom-skills-router.mjs"
            plugin_path.write_text(sync_hooks.render_opencode_plugin(REPO_ROOT), encoding="utf-8")

            harness = r"""
import fs from "node:fs";
import { pathToFileURL } from "node:url";

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const mod = await import(pathToFileURL(input.pluginPath).href);
const pluginFactory = mod.CustomSkillsRouterPlugin || mod.default?.server || mod.default;
const hooks = await pluginFactory({});

const matchedRe = /^- \[([a-z0-9-]+)\]/gm;
const promptMatches = [];
for (let i = 0; i < input.prompts.length; i++) {
  const sid = `test-session-${i}`;
  await hooks["chat.message"]({ sessionID: sid }, { parts: [{ type: "text", text: input.prompts[i] }] });
  const sysOut = { system: [] };
  await hooks["experimental.chat.system.transform"]({ sessionID: sid }, sysOut);
  const combined = sysOut.system.join("\n");
  const found = [...combined.matchAll(matchedRe)].map((m) => m[1]).sort();
  promptMatches.push(found);
}

const shellDenied = [];
for (const cmd of input.shells) {
  let denied = false;
  try {
    await hooks["tool.execute.before"]({ tool: "bash" }, { args: { command: cmd } });
  } catch {
    denied = true;
  }
  shellDenied.push(denied);
}

// Verify SKIP_SKILL_HOOKS=1 bypasses both prompt and shell hooks
process.env.SKIP_SKILL_HOOKS = "1";
await hooks["chat.message"]({ sessionID: "skip-sid" }, { parts: [{ type: "text", text: input.positivePrompt }] });
const skipSys = { system: [] };
await hooks["experimental.chat.system.transform"]({ sessionID: "skip-sid" }, skipSys);
let skipShellDenied = false;
try {
  await hooks["tool.execute.before"]({ tool: "bash" }, { args: { command: input.deniedShell } });
} catch {
  skipShellDenied = true;
}

console.log(JSON.stringify({ promptMatches, shellDenied, skipSystemLen: skipSys.system.length, skipShellDenied }));
"""
            pos_prompt = next(q for _, q, exp in prompts if exp)
            pos_shell = next(c for _, c, exp in shell_cases if exp)
            payload = {
                "pluginPath": str(plugin_path),
                "prompts": [q for _, q, _ in prompts],
                "shells": [c for _, c, _ in shell_cases],
                "positivePrompt": pos_prompt,
                "deniedShell": pos_shell,
            }
            env = dict(os.environ)
            env.pop("SKIP_SKILL_HOOKS", None)
            proc = subprocess.run(
                [*js_runner, harness],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            js_res = json.loads(proc.stdout)

        for idx, (owner, query, expected) in enumerate(prompts):
            with self.subTest(prompt=query):
                self.assertEqual(js_res["promptMatches"][idx], py_prompt_results[idx])
                self.assertEqual(owner in js_res["promptMatches"][idx], expected)

        for idx, (owner, cmd, expected) in enumerate(shell_cases):
            with self.subTest(shell=cmd):
                self.assertEqual(js_res["shellDenied"][idx], py_shell_results[idx])
                self.assertEqual(js_res["shellDenied"][idx], expected)

        self.assertEqual(js_res["skipSystemLen"], 0)
        self.assertFalse(js_res["skipShellDenied"])

    def test_antigravity_dedup_and_skip_env_via_cli(self) -> None:
        router = SCRIPTS_DIR / "skill-hook-router.py"
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ)
            env["XDG_RUNTIME_DIR"] = tmp
            env.pop("SKIP_SKILL_HOOKS", None)

            payload1 = json.dumps({
                "conversationId": "conv-dedup-1",
                "lastUserInput": "создай оптимизированный скилл для docker",
            })
            r1 = subprocess.run(
                [sys.executable, str(router), "antigravity", "PreInvocation"],
                input=payload1, capture_output=True, text=True, env=env,
            )
            self.assertEqual(r1.returncode, 0)
            self.assertIn("injectSteps", json.loads(r1.stdout))

            # Identical conversationId + prompt -> deduplicated passthrough
            r2 = subprocess.run(
                [sys.executable, str(router), "antigravity", "PreInvocation"],
                input=payload1, capture_output=True, text=True, env=env,
            )
            self.assertEqual(r2.returncode, 0)
            self.assertEqual(json.loads(r2.stdout), {})

            # Different prompt in same conversation -> injects again
            payload3 = json.dumps({
                "conversationId": "conv-dedup-1",
                "lastUserInput": "найди узкие места в этом python сервисе",
            })
            r3 = subprocess.run(
                [sys.executable, str(router), "antigravity", "PreInvocation"],
                input=payload3, capture_output=True, text=True, env=env,
            )
            self.assertEqual(r3.returncode, 0)
            self.assertIn("injectSteps", json.loads(r3.stdout))

            # SKIP_SKILL_HOOKS=1 passes through PreToolUse with ask
            skip_env = dict(env, SKIP_SKILL_HOOKS="1")
            r_skip = subprocess.run(
                [sys.executable, str(router), "antigravity", "PreToolUse"],
                input=json.dumps({"toolCall": {"name": "run_command", "args": {"CommandLine": "flatpak run ai.storyteller.figcraft"}}}),
                capture_output=True, text=True, env=skip_env,
            )
            self.assertEqual(r_skip.returncode, 0)
            self.assertEqual(json.loads(r_skip.stdout), {"decision": "ask"})


if __name__ == "__main__":
    unittest.main()
