#!/usr/bin/env python3
"""Universal, idempotent installer for cross-agent skill hooks."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROUTER_MARKER = "skill-hook-router.py"
ANTIGRAVITY_KEY = "custom-skills-router"
INLINE_RE_FLAG = re.compile(r"\(\?(?:[aiLmsux]+(?:-[imsx]+)?|-[imsx]+)[):]")

SUPPORTED_AGENTS = ("antigravity", "codex", "claude_code", "gemini_cli", "opencode")
NON_HOOK_SKILLS_MANAGER_AGENTS = (
    ("deepseek_harness", "~/.dsh/skills"),
    ("omp_agent", "~/.omp/agent/skills"),
    ("command_code", "~/.commandcode/skills"),
    ("pi", "~/.pi/agent/skills"),
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def router_path(root: Path) -> Path:
    return root / "scripts" / ROUTER_MARKER


def validate_all_trigger_files(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    skills_dir = root / "skills"
    rules: list[dict[str, Any]] = []
    errors: list[str] = []
    if not skills_dir.is_dir():
        return rules, errors

    for path in sorted(skills_dir.glob("*/hook-triggers.json")):
        rel = str(path.relative_to(root))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{rel}: invalid JSON ({exc})")
            continue
        if not isinstance(data, dict):
            errors.append(f"{rel}: root must be a JSON object")
            continue

        sv = data.get("schema_version")
        if not isinstance(sv, int) or isinstance(sv, bool) or sv != 1:
            errors.append(f"{rel}: schema_version must be 1")
        if not isinstance(data.get("enabled"), bool):
            errors.append(f"{rel}: 'enabled' must be a boolean")
        skill = data.get("skill")
        if not isinstance(skill, str) or skill != path.parent.name:
            errors.append(f"{rel}: 'skill' must match directory name '{path.parent.name}'")
        ci = data.get("case_insensitive", True)
        if not isinstance(ci, bool):
            errors.append(f"{rel}: 'case_insensitive' must be a boolean")

        for field_name, pat in (("prompt_regex", data.get("prompt_regex")),):
            if pat is not None:
                if not isinstance(pat, str):
                    errors.append(f"{rel}: '{field_name}' must be a string")
                else:
                    if INLINE_RE_FLAG.search(pat):
                        errors.append(
                            f"{rel}: '{field_name}' uses inline regex flags like (?i); use 'case_insensitive' instead for JS portability"
                        )
                    try:
                        re.compile(pat)
                    except re.error as exc:
                        errors.append(f"{rel}: invalid regex in '{field_name}': {exc}")

        deny_shell = data.get("deny_shell", [])
        if deny_shell is not None:
            if not isinstance(deny_shell, list):
                errors.append(f"{rel}: 'deny_shell' must be an array")
            else:
                for idx, entry in enumerate(deny_shell):
                    if not isinstance(entry, dict):
                        errors.append(f"{rel}: deny_shell[{idx}] must be an object")
                        continue
                    for rkey, required in (("regex", True), ("allow_if_regex", False)):
                        rval = entry.get(rkey)
                        if rval is None:
                            if required:
                                errors.append(f"{rel}: deny_shell[{idx}].{rkey} is required")
                            continue
                        if not isinstance(rval, str) or (required and not rval):
                            errors.append(f"{rel}: deny_shell[{idx}].{rkey} must be a non-empty string")
                            continue
                        if INLINE_RE_FLAG.search(rval):
                            errors.append(
                                f"{rel}: deny_shell[{idx}].{rkey} uses inline regex flags; use 'case_insensitive' instead"
                            )
                        try:
                            re.compile(rval)
                        except re.error as exc:
                            errors.append(f"{rel}: invalid regex in deny_shell[{idx}].{rkey}: {exc}")

        data["_path"] = str(path)
        rules.append(data)

    return rules, errors


def read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        return {}
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a top-level JSON object")
    return data


def atomic_write_text(path: Path, content: str, backup: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if backup and path.exists():
        bak = path.with_name(path.name + ".bak-skills-router")
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


def is_router_handler(handler: object) -> bool:
    return (
        isinstance(handler, dict)
        and isinstance(handler.get("command"), str)
        and ROUTER_MARKER in handler["command"]
    )


def strip_router_groups(groups: object) -> list[dict[str, Any]]:
    if not isinstance(groups, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for grp in groups:
        if not isinstance(grp, dict):
            continue
        hooks = grp.get("hooks")
        if not isinstance(hooks, list):
            cleaned.append(grp)
            continue
        kept = [h for h in hooks if not is_router_handler(h)]
        if kept:
            new_grp = dict(grp)
            new_grp["hooks"] = kept
            cleaned.append(new_grp)
    return cleaned


def upsert_hook_group(
    hooks_root: dict[str, Any], event: str, group: dict[str, Any]
) -> None:
    existing = strip_router_groups(hooks_root.get(event))
    existing.append(group)
    hooks_root[event] = existing


def remove_router_from_hooks_map(hooks_root: dict[str, Any], events: tuple[str, ...]) -> None:
    for ev in events:
        if ev in hooks_root:
            kept = strip_router_groups(hooks_root.get(ev))
            if kept:
                hooks_root[ev] = kept
            else:
                del hooks_root[ev]


def command_str(router: Path, agent: str, event: str) -> str:
    return f"python3 '{router}' {agent} {event}"


def sync_antigravity(router: Path, uninstall: bool, dry_run: bool) -> tuple[str, str]:
    path = Path.home() / ".gemini" / "config" / "hooks.json"
    data = read_json_object(path)
    before = json.dumps(data, sort_keys=True)

    if uninstall:
        data.pop(ANTIGRAVITY_KEY, None)
    else:
        data[ANTIGRAVITY_KEY] = {
            "PreInvocation": [
                {
                    "type": "command",
                    "command": command_str(router, "antigravity", "PreInvocation"),
                    "timeout": 5,
                }
            ],
            "PreToolUse": [
                {
                    "matcher": "run_command",
                    "hooks": [
                        {
                            "type": "command",
                            "command": command_str(router, "antigravity", "PreToolUse"),
                            "timeout": 5,
                        }
                    ],
                }
            ],
        }

    after = json.dumps(data, sort_keys=True)
    if before == after:
        return "unchanged", str(path)
    if not dry_run:
        atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return ("removed" if uninstall else "updated"), str(path)


def sync_codex(router: Path, uninstall: bool, dry_run: bool) -> tuple[str, str]:
    path = Path.home() / ".codex" / "hooks.json"
    data = read_json_object(path)
    before = json.dumps(data, sort_keys=True)

    hooks_map = data.get("hooks")
    if hooks_map is None:
        hooks_map = {}
    if not isinstance(hooks_map, dict):
        raise ValueError(f"{path}: 'hooks' must be an object")

    if uninstall:
        remove_router_from_hooks_map(hooks_map, ("UserPromptSubmit", "PreToolUse"))
    else:
        upsert_hook_group(
            hooks_map,
            "UserPromptSubmit",
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command_str(router, "codex", "UserPromptSubmit"),
                        "timeout": 5,
                    }
                ]
            },
        )
        upsert_hook_group(
            hooks_map,
            "PreToolUse",
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command_str(router, "codex", "PreToolUse"),
                        "timeout": 5,
                    }
                ]
            },
        )
    data["hooks"] = hooks_map

    after = json.dumps(data, sort_keys=True)
    if before == after:
        return "unchanged", str(path)
    if not dry_run:
        atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return ("removed" if uninstall else "updated"), str(path)


def sync_claude_code(router: Path, uninstall: bool, dry_run: bool) -> tuple[str, str]:
    path = Path.home() / ".claude" / "settings.json"
    existed = path.exists()
    data = read_json_object(path)
    before = json.dumps(data, sort_keys=True) if existed else None

    hooks_map = data.get("hooks")
    if hooks_map is None:
        hooks_map = {}
    if not isinstance(hooks_map, dict):
        raise ValueError(f"{path}: 'hooks' must be an object")

    if uninstall:
        if not existed:
            return "absent", str(path)
        remove_router_from_hooks_map(hooks_map, ("UserPromptSubmit", "PreToolUse"))
        if hooks_map:
            data["hooks"] = hooks_map
        else:
            data.pop("hooks", None)
    else:
        upsert_hook_group(
            hooks_map,
            "UserPromptSubmit",
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command_str(router, "claude_code", "UserPromptSubmit"),
                        "timeout": 5,
                    }
                ]
            },
        )
        upsert_hook_group(
            hooks_map,
            "PreToolUse",
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": command_str(router, "claude_code", "PreToolUse"),
                        "timeout": 5,
                    }
                ],
            },
        )
        data["hooks"] = hooks_map

    after = json.dumps(data, sort_keys=True)
    if before == after:
        return "unchanged", str(path)
    if not dry_run:
        atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return ("removed" if uninstall else ("created" if not existed else "updated")), str(path)


def sync_gemini_cli(router: Path, uninstall: bool, dry_run: bool) -> tuple[str, str]:
    path = Path.home() / ".gemini" / "settings.json"
    existed = path.exists()
    data = read_json_object(path)
    before = json.dumps(data, sort_keys=True) if existed else None

    hooks_map = data.get("hooks")
    if hooks_map is None:
        hooks_map = {}
    if not isinstance(hooks_map, dict):
        raise ValueError(f"{path}: 'hooks' must be an object")

    if uninstall:
        if not existed:
            return "absent", str(path)
        remove_router_from_hooks_map(hooks_map, ("BeforeAgent", "BeforeTool"))
        if hooks_map:
            data["hooks"] = hooks_map
        else:
            data.pop("hooks", None)
    else:
        upsert_hook_group(
            hooks_map,
            "BeforeAgent",
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command_str(router, "gemini_cli", "BeforeAgent"),
                        "timeout": 5,
                    }
                ]
            },
        )
        upsert_hook_group(
            hooks_map,
            "BeforeTool",
            {
                "matcher": "run_shell_command|shell|bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": command_str(router, "gemini_cli", "BeforeTool"),
                        "timeout": 5,
                    }
                ],
            },
        )
        data["hooks"] = hooks_map

    after = json.dumps(data, sort_keys=True)
    if before == after:
        return "unchanged", str(path)
    if not dry_run:
        atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return ("removed" if uninstall else ("created" if not existed else "updated")), str(path)


def render_opencode_plugin(root: Path) -> str:
    skills_dir_literal = json.dumps(str(root / "skills"))
    sm_skills_literal = json.dumps(str(Path.home() / ".skills-manager" / "skills"))
    return f"""// Auto-generated by {root / 'scripts' / 'sync-hooks.py'}. Do not edit manually.
import fs from "node:fs";
import path from "node:path";

const REPO_SKILLS_DIR = {skills_dir_literal};
const SM_SKILLS_DIR = {sm_skills_literal};
const SHELL_TOOLS = new Set([
  "bash",
  "shell",
  "run_command",
  "exec_command",
  "run_shell_command",
  "local_shell",
  "execute_command",
  "shell_command",
]);

let cachedKey = "";
let cachedRules = [];

function loadRules() {{
  try {{
    if (!fs.existsSync(REPO_SKILLS_DIR)) return [];
    const entries = fs.readdirSync(REPO_SKILLS_DIR, {{ withFileTypes: true }});
    const parts = [];
    const files = [];
    for (const ent of entries) {{
      if (!ent.isDirectory() || ent.name.startsWith(".")) continue;
      const rulePath = path.join(REPO_SKILLS_DIR, ent.name, "hook-triggers.json");
      try {{
        const st = fs.statSync(rulePath);
        if (st.isFile()) {{
          parts.push(`${{rulePath}}:${{st.mtimeMs}}:${{st.size}}`);
          files.push(rulePath);
        }}
      }} catch {{
        // Ignore missing rule file
      }}
    }}
    const key = parts.sort().join("|");
    if (key === cachedKey) return cachedRules;

    const rules = [];
    for (const rulePath of files.sort()) {{
      try {{
        const data = JSON.parse(fs.readFileSync(rulePath, "utf8"));
        if (!data || data.enabled !== true) continue;
        const skill = data.skill || path.basename(path.dirname(rulePath));
        const flags = data.case_insensitive === false ? "" : "i";
        const promptRe =
          typeof data.prompt_regex === "string" && data.prompt_regex
            ? new RegExp(data.prompt_regex, flags)
            : null;
        const denyRules = [];
        if (Array.isArray(data.deny_shell)) {{
          for (const d of data.deny_shell) {{
            if (!d || typeof d.regex !== "string" || !d.regex) continue;
            denyRules.push({{
              re: new RegExp(d.regex, flags),
              allowRe:
                typeof d.allow_if_regex === "string" && d.allow_if_regex
                  ? new RegExp(d.allow_if_regex, flags)
                  : null,
              reason: String(d.reason || `Blocked by ${{skill}} skill hook.`),
            }});
          }}
        }}
        const smSkillMd = path.join(SM_SKILLS_DIR, skill, "SKILL.md");
        const baseDir = fs.existsSync(smSkillMd)
          ? path.join(SM_SKILLS_DIR, skill)
          : path.join(REPO_SKILLS_DIR, skill);
        const skillMd = path.join(baseDir, "SKILL.md");
        const scriptsDir = path.join(baseDir, "scripts");
        rules.push({{
          skill,
          hint: String(data.hint || `Use the ${{skill}} skill.`).trim(),
          promptRe,
          denyRules,
          skillMd,
          scriptsDir: fs.existsSync(scriptsDir) ? scriptsDir : null,
        }});
      }} catch {{
        // Fail-open on malformed rule
      }}
    }}
    cachedKey = key;
    cachedRules = rules;
    return rules;
  }} catch {{
    return [];
  }}
}}

export const CustomSkillsRouterPlugin = async (_ctx) => {{
  const pendingHintsBySession = new Map();

  return {{
    "chat.message": async (input, output) => {{
      try {{
        const sid = input?.sessionID || "__default__";
        if (process.env.SKIP_SKILL_HOOKS === "1") {{
          pendingHintsBySession.delete(sid);
          return;
        }}
        const text = (output?.parts || [])
          .filter((p) => p && !p.synthetic && typeof p.text === "string")
          .map((p) => p.text)
          .join("\\n");
        if (!text.trim()) {{
          pendingHintsBySession.delete(sid);
          return;
        }}
        const matches = [];
        for (const rule of loadRules()) {{
          if (!rule.promptRe || !rule.promptRe.test(text)) continue;
          let loc = `SKILL.md: ${{rule.skillMd}}`;
          if (rule.scriptsDir) loc += `, scripts: ${{rule.scriptsDir}}`;
          matches.push(`- [${{rule.skill}}] ${{rule.hint}} (${{loc}})`);
        }}
        if (matches.length > 0) {{
          pendingHintsBySession.set(
            sid,
            "[Custom Skills Hook] Relevant local skill(s) matched this prompt:\\n" +
              matches.join("\\n")
          );
        }} else {{
          pendingHintsBySession.delete(sid);
        }}
      }} catch {{
        // Fail-open
      }}
    }},

    "experimental.chat.system.transform": async (input, output) => {{
      try {{
        if (process.env.SKIP_SKILL_HOOKS === "1") return;
        const sid = input?.sessionID || "__default__";
        const hint = pendingHintsBySession.get(sid);
        if (!hint || !Array.isArray(output?.system)) return;
        if (!output.system.includes(hint)) {{
          output.system.push(hint);
        }}
      }} catch {{
        // Fail-open
      }}
    }},

    "tool.execute.before": async (input, output) => {{
      if (process.env.SKIP_SKILL_HOOKS === "1") return;
      const toolName = String(input?.tool || "").toLowerCase();
      if (toolName && !SHELL_TOOLS.has(toolName)) return;
      const args = output?.args;
      const cmd =
        typeof args === "string"
          ? args
          : args?.command || args?.cmd || args?.CommandLine || "";
      if (typeof cmd !== "string" || !cmd.trim()) return;

      for (const rule of loadRules()) {{
        for (const d of rule.denyRules) {{
          if (!d.re.test(cmd)) continue;
          if (d.allowRe && d.allowRe.test(cmd)) continue;
          throw new Error(`${{d.reason}} [Skill: ${{rule.skillMd}}]`);
        }}
      }}
    }},
  }};
}};

export default process.env.ORCA_OPENCODE_PLUGIN_API === "v1"
  ? CustomSkillsRouterPlugin
  : {{
      id: "custom-skills-router",
      server: CustomSkillsRouterPlugin,
    }};
"""


def sync_opencode(root: Path, uninstall: bool, dry_run: bool) -> tuple[str, str]:
    path = Path.home() / ".config" / "opencode" / "plugins" / "custom-skills-router.js"
    existed = path.exists()
    if uninstall:
        if not existed:
            return "absent", str(path)
        if not dry_run:
            path.unlink()
        return "removed", str(path)

    rendered = render_opencode_plugin(root)
    if existed and path.read_text(encoding="utf-8") == rendered:
        return "unchanged", str(path)
    if not dry_run:
        atomic_write_text(path, rendered, backup=False)
    return ("created" if not existed else "updated"), str(path)


def agent_config_dir(agent: str) -> Path:
    home = Path.home()
    return {
        "antigravity": home / ".gemini" / "config",
        "codex": home / ".codex",
        "claude_code": home / ".claude",
        "gemini_cli": home / ".gemini",
        "opencode": home / ".config" / "opencode",
    }[agent]


def detect_installed_agents() -> list[str]:
    return [a for a in SUPPORTED_AGENTS if agent_config_dir(a).is_dir()]


def check_agent_status(agent: str) -> tuple[bool, str]:
    home = Path.home()
    if agent == "antigravity":
        p = home / ".gemini" / "config" / "hooks.json"
        if not p.is_file():
            return False, str(p)
        data = read_json_object(p)
        return (ANTIGRAVITY_KEY in data), str(p)
    if agent == "codex":
        p = home / ".codex" / "hooks.json"
        if not p.is_file():
            return False, str(p)
        data = read_json_object(p)
        hooks = data.get("hooks", {})
        has_prompt = any(
            is_router_handler(h)
            for grp in hooks.get("UserPromptSubmit", [])
            for h in (grp.get("hooks") or [])
        )
        has_tool = any(
            is_router_handler(h)
            for grp in hooks.get("PreToolUse", [])
            for h in (grp.get("hooks") or [])
        )
        return (has_prompt and has_tool), str(p)
    if agent == "claude_code":
        p = home / ".claude" / "settings.json"
        if not p.is_file():
            return False, str(p)
        data = read_json_object(p)
        hooks = data.get("hooks", {})
        has_prompt = any(
            is_router_handler(h)
            for grp in hooks.get("UserPromptSubmit", [])
            for h in (grp.get("hooks") or [])
        )
        has_tool = any(
            is_router_handler(h)
            for grp in hooks.get("PreToolUse", [])
            for h in (grp.get("hooks") or [])
        )
        return (has_prompt and has_tool), str(p)
    if agent == "gemini_cli":
        p = home / ".gemini" / "settings.json"
        if not p.is_file():
            return False, str(p)
        data = read_json_object(p)
        hooks = data.get("hooks", {})
        has_prompt = any(
            is_router_handler(h)
            for grp in hooks.get("BeforeAgent", [])
            for h in (grp.get("hooks") or [])
        )
        has_tool = any(
            is_router_handler(h)
            for grp in hooks.get("BeforeTool", [])
            for h in (grp.get("hooks") or [])
        )
        return (has_prompt and has_tool), str(p)
    if agent == "opencode":
        p = home / ".config" / "opencode" / "plugins" / "custom-skills-router.js"
        return p.is_file(), str(p)
    return False, ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install, update, inspect, or remove universal skill hooks across installed AI agents."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing agent configuration files.",
    )
    parser.add_argument(
        "--uninstall",
        action="store_true",
        help="Remove managed custom-skills-router hooks while preserving other user hooks.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show configured skill hook rules and installation status per agent.",
    )
    parser.add_argument(
        "--agent",
        action="append",
        choices=SUPPORTED_AGENTS,
        help="Limit operation to specific agent(s). Defaults to all detected hook-capable agents.",
    )
    args = parser.parse_args()

    root = repo_root()
    router = router_path(root)
    rules, errors = validate_all_trigger_files(root)
    if errors:
        for err in errors:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    if args.status:
        print("=== Skill hook rules ===")
        if not rules:
            print("  (none)")
        for r in rules:
            state = "enabled" if r.get("enabled") else "disabled"
            deny_n = len(r.get("deny_shell") or [])
            print(f"  - {r['skill']}: {state} (deny_shell={deny_n})")

        print("\n=== Hook-capable agents ===")
        for ag in SUPPORTED_AGENTS:
            detected = agent_config_dir(ag).is_dir()
            if not detected:
                print(f"  - {ag}: not detected")
                continue
            installed, path = check_agent_status(ag)
            print(f"  - {ag}: {'installed' if installed else 'not installed'} ({path})")

        print("\n=== Skills-only agents (no native hook API; rely on SKILL.md description) ===")
        for ag, skills_dir in NON_HOOK_SKILLS_MANAGER_AGENTS:
            if Path(os.path.expanduser(skills_dir)).parent.is_dir():
                print(f"  - {ag}: detected ({skills_dir})")
        return 0

    if not args.uninstall and not router.is_file():
        print(f"[ERROR] Router script not found: {router}", file=sys.stderr)
        return 1

    targets = args.agent if args.agent else detect_installed_agents()
    if not targets:
        print("No supported hook-capable agent directories detected.")
        return 0

    handlers = {
        "antigravity": lambda: sync_antigravity(router, args.uninstall, args.dry_run),
        "codex": lambda: sync_codex(router, args.uninstall, args.dry_run),
        "claude_code": lambda: sync_claude_code(router, args.uninstall, args.dry_run),
        "gemini_cli": lambda: sync_gemini_cli(router, args.uninstall, args.dry_run),
        "opencode": lambda: sync_opencode(root, args.uninstall, args.dry_run),
    }

    prefix = "[DRY-RUN] " if args.dry_run else ""
    for ag in targets:
        try:
            action, path = handlers[ag]()
        except Exception as exc:
            print(f"[ERROR] {ag}: {exc}", file=sys.stderr)
            return 1
        print(f"{prefix}[{action.upper()}] {ag}: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
