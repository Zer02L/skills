#!/usr/bin/env python3
"""Universal skill hook router for Antigravity, Codex, Claude Code, and Gemini CLI."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

PROMPT_EVENTS = {"PreInvocation", "UserPromptSubmit", "BeforeAgent"}
TOOL_EVENTS = {"PreToolUse", "BeforeTool"}
SHELL_TOOLS = {
    "run_command",
    "bash",
    "shell",
    "exec_command",
    "run_shell_command",
    "local_shell",
    "execute_command",
    "shell_command",
}
MAX_DEDUP_KEYS = 100


def passthrough_response(agent: str, event: str) -> dict[str, Any]:
    if agent == "antigravity" and event == "PreToolUse":
        return {"decision": "ask"}
    return {}


def emit(obj: dict[str, Any]) -> int:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return 0


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def rule_search_dirs(root: Path) -> list[Path]:
    env_dirs = os.environ.get("SKILL_HOOKS_DIRS", "").strip()
    if env_dirs:
        return [Path(p).expanduser() for p in env_dirs.split(os.pathsep) if p.strip()]
    return [root / "skills"]


def load_rules(root: Path) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for skills_dir in rule_search_dirs(root):
        if not skills_dir.is_dir():
            continue
        for path in sorted(skills_dir.glob("*/hook-triggers.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict) or data.get("enabled") is not True:
                continue
            skill = data.get("skill") or path.parent.name
            if not isinstance(skill, str) or not skill:
                continue
            data["_skill"] = skill
            data["_dir"] = path.parent
            rules.append(data)
    return rules


def resolve_skill_paths(
    skill_name: str, root: Path, fallback_dir: Path | None = None
) -> tuple[Path, Path | None]:
    sm_dir = Path.home() / ".skills-manager" / "skills" / skill_name
    base = (
        sm_dir
        if (sm_dir / "SKILL.md").is_file()
        else (fallback_dir or (root / "skills" / skill_name))
    )
    skill_md = base / "SKILL.md"
    scripts_dir = base / "scripts"
    return skill_md, (scripts_dir if scripts_dir.is_dir() else None)


def extract_prompt(payload: dict[str, Any]) -> str:
    for key in ("lastUserInput", "prompt", "user_prompt", "userPrompt", "message"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
        if isinstance(val, dict):
            for sub in ("content", "text"):
                sv = val.get(sub)
                if isinstance(sv, str) and sv.strip():
                    return sv
    inp = payload.get("input")
    if isinstance(inp, dict):
        for key in ("prompt", "message", "text"):
            val = inp.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


def extract_shell_command(payload: dict[str, Any]) -> str:
    tool_name = ""
    args: Any = None

    tc = payload.get("toolCall")
    if isinstance(tc, dict):
        tool_name = str(tc.get("name") or "")
        args = tc.get("args")
    else:
        tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
        args = payload.get("tool_input") or payload.get("toolInput") or payload.get("args")

    if tool_name and tool_name.lower() not in SHELL_TOOLS:
        return ""

    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        for key in ("CommandLine", "command", "cmd"):
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val
    return ""


def dedup_state_path() -> Path:
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")
    return base / "custom-skills-router-state.json"


def seen_before(conv_id: str, prompt: str) -> bool:
    if not conv_id or not prompt:
        return False
    import hashlib
    import tempfile

    digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    key = f"{conv_id}:{digest}"
    state_file = dedup_state_path()

    keys: list[str] = []
    try:
        if state_file.is_file():
            loaded = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                keys = [str(x) for x in loaded]
    except Exception:
        keys = []

    if key in keys:
        return True

    keys.append(key)
    keys = keys[-MAX_DEDUP_KEYS:]
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="router-state-", dir=str(state_file.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(keys, fh)
            os.replace(tmp_name, state_file)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
    except Exception:
        pass
    return False


def format_prompt_response(agent: str, event: str, hint_text: str) -> dict[str, Any]:
    if agent == "antigravity":
        return {"injectSteps": [{"systemMessage": {"systemMessage": hint_text}}]}
    if agent in ("codex", "claude_code"):
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": hint_text,
            }
        }
    if agent == "gemini_cli":
        return {
            "hookSpecificOutput": {
                "hookEventName": "BeforeAgent",
                "additionalContext": hint_text,
            }
        }
    return {}


def format_deny_response(agent: str, event: str, reason: str) -> dict[str, Any]:
    if agent == "antigravity":
        return {"decision": "deny", "reason": reason}
    if agent in ("codex", "claude_code"):
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    if agent == "gemini_cli":
        return {"decision": "deny", "reason": reason}
    return {}


def handle_prompt(agent: str, event: str, payload: dict[str, Any], root: Path) -> dict[str, Any]:
    prompt = extract_prompt(payload)
    if not prompt:
        return passthrough_response(agent, event)

    rules = load_rules(root)
    if not rules:
        return passthrough_response(agent, event)

    matched_lines: list[str] = []
    for rule in rules:
        pattern = rule.get("prompt_regex")
        if not isinstance(pattern, str) or not pattern:
            continue
        flags = re.IGNORECASE if rule.get("case_insensitive", True) else 0
        try:
            if not re.search(pattern, prompt, flags):
                continue
        except re.error:
            continue
        skill = rule["_skill"]
        hint = str(rule.get("hint") or f"Use the `{skill}` skill.").strip()
        skill_md, scripts_dir = resolve_skill_paths(skill, root, rule.get("_dir"))
        loc = f"SKILL.md: {skill_md}"
        if scripts_dir is not None:
            loc += f", scripts: {scripts_dir}"
        matched_lines.append(f"- [{skill}] {hint} ({loc})")

    if not matched_lines:
        return passthrough_response(agent, event)

    if agent == "antigravity" and event == "PreInvocation":
        conv_id = str(payload.get("conversationId") or payload.get("session_id") or "")
        if seen_before(conv_id, prompt):
            return passthrough_response(agent, event)

    combined = "[Custom Skills Hook] Relevant local skill(s) matched this prompt:\n" + "\n".join(
        matched_lines
    )
    return format_prompt_response(agent, event, combined)


def handle_tool(agent: str, event: str, payload: dict[str, Any], root: Path) -> dict[str, Any]:
    cmd = extract_shell_command(payload)
    if not cmd:
        return passthrough_response(agent, event)

    rules = load_rules(root)
    for rule in rules:
        deny_list = rule.get("deny_shell")
        if not isinstance(deny_list, list) or not deny_list:
            continue
        flags = re.IGNORECASE if rule.get("case_insensitive", True) else 0
        skill = rule["_skill"]
        for entry in deny_list:
            if not isinstance(entry, dict):
                continue
            pattern = entry.get("regex")
            if not isinstance(pattern, str) or not pattern:
                continue
            try:
                if not re.search(pattern, cmd, flags):
                    continue
                allow_pat = entry.get("allow_if_regex")
                if isinstance(allow_pat, str) and allow_pat and re.search(allow_pat, cmd, flags):
                    continue
            except re.error:
                continue
            skill_md, _ = resolve_skill_paths(skill, root, rule.get("_dir"))
            reason = str(entry.get("reason") or f"Blocked by `{skill}` skill hook.").strip()
            return format_deny_response(agent, event, f"{reason} [Skill: {skill_md}]")

    return passthrough_response(agent, event)


def main() -> int:
    if len(sys.argv) != 3:
        sys.stderr.write("Usage: skill-hook-router.py <agent> <event>\n")
        return 2

    agent = sys.argv[1]
    event = sys.argv[2]

    if os.environ.get("SKIP_SKILL_HOOKS") == "1":
        try:
            sys.stdin.read()
        except Exception:
            pass
        return emit(passthrough_response(agent, event))

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        return emit(passthrough_response(agent, event))

    root = repo_root()
    try:
        if event in PROMPT_EVENTS:
            return emit(handle_prompt(agent, event, payload, root))
        if event in TOOL_EVENTS:
            return emit(handle_tool(agent, event, payload, root))
    except Exception:
        pass

    return emit(passthrough_response(agent, event))


if __name__ == "__main__":
    sys.exit(main())
