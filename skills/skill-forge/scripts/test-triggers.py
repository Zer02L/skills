#!/usr/bin/env python3
"""Test skill prompt/shell trigger rules across Python, JS RegExp, and live router."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def find_repo_router(skill_dir: Path) -> Path | None:
    for parent in (skill_dir, *skill_dir.parents):
        cand = parent / "scripts" / "skill-hook-router.py"
        if cand.is_file():
            return cand
    return None


def find_js_runtime() -> str | None:
    for bin_name in ("bun", "node"):
        found = shutil.which(bin_name)
        if found:
            return found
    return None


def check_js_parity(
    js_bin: str,
    rule: dict[str, Any],
    prompts: list[dict[str, Any]],
    shell_cases: list[dict[str, Any]],
) -> list[str]:
    script = r"""
import fs from "node:fs";
const payload = JSON.parse(fs.readFileSync(0, "utf8"));
const { rule, prompts, shellCases } = payload;
const flags = rule.case_insensitive === false ? "" : "i";
const failures = [];
if (rule.prompt_regex) {
  const re = new RegExp(rule.prompt_regex, flags);
  for (const tc of prompts) {
    const got = re.test(tc.query);
    if (got !== Boolean(tc.should_trigger)) {
      failures.push(`JS prompt mismatch: ${JSON.stringify(tc.query)} got=${got} expected=${Boolean(tc.should_trigger)}`);
    }
  }
}
const deny = (rule.deny_shell || []).map((d) => ({
  re: new RegExp(d.regex, flags),
  allow: d.allow_if_regex ? new RegExp(d.allow_if_regex, flags) : null,
}));
for (const sc of shellCases) {
  let got = false;
  for (const d of deny) {
    if (d.re.test(sc.command) && !(d.allow && d.allow.test(sc.command))) {
      got = true;
      break;
    }
  }
  if (got !== Boolean(sc.should_deny)) {
    failures.push(`JS shell mismatch: ${JSON.stringify(sc.command)} got=${got} expected=${Boolean(sc.should_deny)}`);
  }
}
console.log(JSON.stringify(failures));
"""
    proc = subprocess.run(
        [js_bin, "-e", script] if Path(js_bin).name == "bun" else [js_bin, "--input-type=module", "-e", script],
        input=json.dumps({"rule": rule, "prompts": prompts, "shellCases": shell_cases}),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return [f"JS runtime ({js_bin}) error: {(proc.stderr or proc.stdout).strip()}"]
    return json.loads(proc.stdout)


def check_live_router(
    router: Path,
    skill_name: str,
    prompts: list[dict[str, Any]],
    shell_cases: list[dict[str, Any]],
) -> list[str]:
    failures: list[str] = []
    conv_id = f"skill-forge-test-{os.getpid()}"
    state_file = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "custom-skills-router-state.json"

    def run_router(agent: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        p = subprocess.run(
            ["python3", str(router), agent, event],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )
        if p.returncode != 0:
            raise RuntimeError(f"{agent}/{event} exited {p.returncode}: {p.stderr}")
        return json.loads(p.stdout)

    try:
        pos_prompt = next((t for t in prompts if t.get("should_trigger")), None)
        neg_prompt = next((t for t in prompts if not t.get("should_trigger")), None)

        for agent, event, key in (
            ("antigravity", "PreInvocation", "lastUserInput"),
            ("codex", "UserPromptSubmit", "prompt"),
            ("claude_code", "UserPromptSubmit", "prompt"),
            ("gemini_cli", "BeforeAgent", "prompt"),
        ):
            if pos_prompt is not None:
                res = run_router(agent, event, {"conversationId": f"{conv_id}-{agent}", key: pos_prompt["query"]})
                if skill_name not in json.dumps(res):
                    failures.append(f"Live router {agent}/{event} missed positive query {pos_prompt['query']!r}: {res}")
            if neg_prompt is not None:
                res = run_router(agent, event, {"conversationId": f"{conv_id}-neg-{agent}", key: neg_prompt["query"]})
                if skill_name in json.dumps(res):
                    failures.append(f"Live router {agent}/{event} false-triggered on {neg_prompt['query']!r}: {res}")

        pos_deny = next((s for s in shell_cases if s.get("should_deny")), None)
        neg_deny = next((s for s in shell_cases if not s.get("should_deny")), None)
        for agent, event, payload_fn in (
            ("antigravity", "PreToolUse", lambda c: {"toolCall": {"name": "run_command", "args": {"CommandLine": c}}}),
            ("codex", "PreToolUse", lambda c: {"tool_name": "Bash", "tool_input": {"command": c}}),
            ("claude_code", "PreToolUse", lambda c: {"tool_name": "Bash", "tool_input": {"command": c}}),
            ("gemini_cli", "BeforeTool", lambda c: {"tool_name": "run_shell_command", "tool_input": {"command": c}}),
        ):
            if pos_deny is not None:
                res = run_router(agent, event, payload_fn(pos_deny["command"]))
                if "deny" not in json.dumps(res):
                    failures.append(f"Live router {agent}/{event} failed to deny {pos_deny['command']!r}: {res}")
            if neg_deny is not None:
                res = run_router(agent, event, payload_fn(neg_deny["command"]))
                if "deny" in json.dumps(res):
                    failures.append(f"Live router {agent}/{event} falsely denied {neg_deny['command']!r}: {res}")
    finally:
        if state_file.is_file():
            try:
                entries = json.loads(state_file.read_text(encoding="utf-8"))
                if isinstance(entries, list):
                    cleaned = [x for x in entries if not str(x).startswith(f"{conv_id}")]
                    if cleaned:
                        state_file.write_text(json.dumps(cleaned), encoding="utf-8")
                    else:
                        state_file.unlink()
            except Exception:
                pass

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic trigger and guardrail tests for a skill."
    )
    parser.add_argument("skill_dir", help="Path to the skill directory.")
    parser.add_argument("--test-file", help="Path to trigger-tests.json (default: <skill_dir>/evals/trigger-tests.json).")
    parser.add_argument("--js-check", action="store_true", help="Require JS RegExp parity check via bun or node.")
    parser.add_argument("--live-router", action="store_true", help="Also run end-to-end checks via scripts/skill-hook-router.py.")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary.")
    args = parser.parse_args()

    skill_dir = Path(args.skill_dir).expanduser().resolve()
    hook_file = skill_dir / "hook-triggers.json"
    test_file = Path(args.test_file).expanduser().resolve() if args.test_file else (skill_dir / "evals" / "trigger-tests.json")

    if not hook_file.is_file():
        print(f"Error: {hook_file} not found.", file=sys.stderr)
        return 1
    if not test_file.is_file():
        print(f"Error: {test_file} not found.", file=sys.stderr)
        return 1

    rule = json.loads(hook_file.read_text(encoding="utf-8"))
    tests = json.loads(test_file.read_text(encoding="utf-8"))
    prompts = tests.get("prompts", [])
    shell_cases = tests.get("shell", [])
    flags = re.IGNORECASE if rule.get("case_insensitive", True) else 0

    failures: list[str] = []
    tp = tn = fp = fn = 0

    prompt_pat = rule.get("prompt_regex") or ""
    prompt_re = re.compile(prompt_pat, flags) if prompt_pat else None
    for tc in prompts:
        q = tc["query"]
        expected = bool(tc["should_trigger"])
        got = bool(prompt_re.search(q)) if prompt_re else False
        if expected and got:
            tp += 1
        elif not expected and not got:
            tn += 1
        elif not expected and got:
            fp += 1
            failures.append(f"Python prompt false positive: {q!r}")
        else:
            fn += 1
            failures.append(f"Python prompt false negative: {q!r}")

    deny_compiled = []
    for entry in rule.get("deny_shell") or []:
        allow_pat = entry.get("allow_if_regex")
        deny_compiled.append((
            re.compile(entry["regex"], flags),
            re.compile(allow_pat, flags) if allow_pat else None,
        ))
    for sc in shell_cases:
        cmd = sc["command"]
        expected = bool(sc["should_deny"])
        got = any(dre.search(cmd) and not (are and are.search(cmd)) for dre, are in deny_compiled)
        if expected and got:
            tp += 1
        elif not expected and not got:
            tn += 1
        elif not expected and got:
            fp += 1
            failures.append(f"Python shell false deny: {cmd!r}")
        else:
            fn += 1
            failures.append(f"Python shell missed deny: {cmd!r}")

    js_bin = find_js_runtime()
    js_checked = False
    if js_bin:
        js_checked = True
        failures.extend(check_js_parity(js_bin, rule, prompts, shell_cases))
    elif args.js_check:
        failures.append("--js-check requested, but neither 'bun' nor 'node' was found in PATH")

    live_checked = False
    if args.live_router:
        router = find_repo_router(skill_dir)
        if router is None:
            failures.append("--live-router requested, but scripts/skill-hook-router.py was not found above skill directory")
        else:
            live_checked = True
            failures.extend(check_live_router(router, rule.get("skill", skill_dir.name), prompts, shell_cases))

    total = tp + tn + fp + fn
    precision = (tp / (tp + fp)) if (tp + fp) else 1.0
    recall = (tp / (tp + fn)) if (tp + fn) else 1.0

    summary = {
        "skill": rule.get("skill", skill_dir.name),
        "total_cases": total,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "js_checked": js_checked,
        "live_router_checked": live_checked,
        "failures": failures,
        "passed": len(failures) == 0,
    }

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        print(
            f"Trigger tests for {summary['skill']}: {tp + tn}/{total} passed "
            f"(TP={tp}, TN={tn}, FP={fp}, FN={fn}, precision={precision:.0%}, recall={recall:.0%}, "
            f"js={'ok' if js_checked else 'skipped'}, live_router={'ok' if live_checked else 'skipped'})"
        )
        for fmsg in failures:
            print(f"  - FAIL: {fmsg}", file=sys.stderr)

    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
