#!/usr/bin/env python3
"""Universal, idempotent installer for cross-agent skill hooks."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from lib.common import (  # noqa: E402
    REPO_ROOT,
    atomic_write_text,
    load_skill_spec,
    read_json_object,
)

ROUTER_MARKER = "skill-hook-router.py"
ANTIGRAVITY_KEY = "custom-skills-router"

SUPPORTED_AGENTS = ("antigravity", "codex", "claude_code", "gemini_cli", "opencode")
NON_HOOK_SKILLS_MANAGER_AGENTS = (
    ("deepseek_harness", "~/.dsh/skills"),
    ("omp_agent", "~/.omp/agent/skills"),
    ("command_code", "~/.commandcode/skills"),
    ("pi", "~/.pi/agent/skills"),
)


@dataclass(frozen=True)
class HooksJsonAgentSpec:
    name: str
    config_rel: tuple[str, ...]
    file_rel: tuple[str, ...]
    prompt_event: str
    tool_event: str
    tool_matcher: str | None = None


HOOKS_JSON_AGENTS: dict[str, HooksJsonAgentSpec] = {
    "codex": HooksJsonAgentSpec(
        name="codex",
        config_rel=(".codex",),
        file_rel=(".codex", "hooks.json"),
        prompt_event="UserPromptSubmit",
        tool_event="PreToolUse",
        tool_matcher=None,
    ),
    "claude_code": HooksJsonAgentSpec(
        name="claude_code",
        config_rel=(".claude",),
        file_rel=(".claude", "settings.json"),
        prompt_event="UserPromptSubmit",
        tool_event="PreToolUse",
        tool_matcher="Bash",
    ),
    "gemini_cli": HooksJsonAgentSpec(
        name="gemini_cli",
        config_rel=(".gemini",),
        file_rel=(".gemini", "settings.json"),
        prompt_event="BeforeAgent",
        tool_event="BeforeTool",
        tool_matcher="run_shell_command|shell|bash",
    ),
}


def repo_root() -> Path:
    return REPO_ROOT


def router_path(root: Path) -> Path:
    return root / "scripts" / ROUTER_MARKER


def validate_all_trigger_files(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    skills_dir = root / "skills"
    rules: list[dict[str, Any]] = []
    errors: list[str] = []
    if not skills_dir.is_dir():
        return rules, errors

    spec = load_skill_spec()
    for path in sorted(skills_dir.glob("*/hook-triggers.json")):
        rel = str(path.relative_to(root))
        data, h_errors, _ = spec.validate_hook_triggers_file(
            path, path.parent.name, prefix=rel
        )
        errors.extend(h_errors)
        if data is not None:
            data["_path"] = str(path)
            rules.append(data)

    return rules, errors


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


def sync_antigravity(
    router: Path, uninstall: bool, dry_run: bool, *, home: Path | None = None
) -> tuple[str, str]:
    base_home = home or Path.home()
    path = base_home / ".gemini" / "config" / "hooks.json"
    existed = path.exists()
    if uninstall and not existed:
        return "absent", str(path)

    data = read_json_object(path)
    before = json.dumps(data, sort_keys=True) if existed else None

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
    return ("removed" if uninstall else ("created" if not existed else "updated")), str(path)


def sync_hooks_json_agent(
    spec: HooksJsonAgentSpec,
    router: Path,
    uninstall: bool,
    dry_run: bool,
    *,
    home: Path | None = None,
) -> tuple[str, str]:
    base_home = home or Path.home()
    path = base_home.joinpath(*spec.file_rel)
    existed = path.exists()
    if uninstall and not existed:
        return "absent", str(path)

    data = read_json_object(path)
    before = json.dumps(data, sort_keys=True) if existed else None

    hooks_map = data.get("hooks")
    if hooks_map is None:
        hooks_map = {}
    if not isinstance(hooks_map, dict):
        raise ValueError(f"{path}: 'hooks' must be an object")

    if uninstall:
        remove_router_from_hooks_map(hooks_map, (spec.prompt_event, spec.tool_event))
        if hooks_map:
            data["hooks"] = hooks_map
        else:
            data.pop("hooks", None)
    else:
        upsert_hook_group(
            hooks_map,
            spec.prompt_event,
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command_str(router, spec.name, spec.prompt_event),
                        "timeout": 5,
                    }
                ]
            },
        )
        tool_group: dict[str, Any] = {}
        if spec.tool_matcher is not None:
            tool_group["matcher"] = spec.tool_matcher
        tool_group["hooks"] = [
            {
                "type": "command",
                "command": command_str(router, spec.name, spec.tool_event),
                "timeout": 5,
            }
        ]
        upsert_hook_group(hooks_map, spec.tool_event, tool_group)
        data["hooks"] = hooks_map

    after = json.dumps(data, sort_keys=True)
    if before == after:
        return "unchanged", str(path)
    if not dry_run:
        atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return ("removed" if uninstall else ("created" if not existed else "updated")), str(path)


def render_opencode_plugin(root: Path, *, home: Path | None = None) -> str:
    base_home = home or Path.home()
    tpl_path = _SCRIPT_DIR / "lib" / "opencode-plugin.js.tpl"
    template = tpl_path.read_text(encoding="utf-8")
    skills_dir_literal = json.dumps(str(root / "skills"))
    sm_skills_literal = json.dumps(str(base_home / ".skills-manager" / "skills"))
    generator_path = str(root / "scripts" / "sync-hooks.py")
    return (
        template.replace("__GENERATOR_PATH__", generator_path)
        .replace("__REPO_SKILLS_DIR__", skills_dir_literal)
        .replace("__SM_SKILLS_DIR__", sm_skills_literal)
    )


def sync_opencode(
    root: Path, uninstall: bool, dry_run: bool, *, home: Path | None = None
) -> tuple[str, str]:
    base_home = home or Path.home()
    path = base_home / ".config" / "opencode" / "plugins" / "custom-skills-router.js"
    existed = path.exists()
    if uninstall:
        if not existed:
            return "absent", str(path)
        if not dry_run:
            path.unlink()
        return "removed", str(path)

    rendered = render_opencode_plugin(root, home=base_home)
    if existed and path.read_text(encoding="utf-8") == rendered:
        return "unchanged", str(path)
    if not dry_run:
        atomic_write_text(path, rendered, backup=False)
    return ("created" if not existed else "updated"), str(path)


def agent_config_dir(agent: str, *, home: Path | None = None) -> Path:
    base_home = home or Path.home()
    if agent == "antigravity":
        return base_home / ".gemini" / "config"
    if agent == "opencode":
        return base_home / ".config" / "opencode"
    if agent in HOOKS_JSON_AGENTS:
        return base_home.joinpath(*HOOKS_JSON_AGENTS[agent].config_rel)
    raise KeyError(f"Unsupported agent: {agent}")


def detect_installed_agents(*, home: Path | None = None) -> list[str]:
    return [a for a in SUPPORTED_AGENTS if agent_config_dir(a, home=home).is_dir()]


def check_agent_status(agent: str, *, home: Path | None = None) -> tuple[bool, str]:
    base_home = home or Path.home()
    if agent == "antigravity":
        p = base_home / ".gemini" / "config" / "hooks.json"
        if not p.is_file():
            return False, str(p)
        data = read_json_object(p)
        return (ANTIGRAVITY_KEY in data), str(p)
    if agent == "opencode":
        p = base_home / ".config" / "opencode" / "plugins" / "custom-skills-router.js"
        return p.is_file(), str(p)
    spec = HOOKS_JSON_AGENTS.get(agent)
    if spec is None:
        return False, ""
    p = base_home.joinpath(*spec.file_rel)
    if not p.is_file():
        return False, str(p)
    data = read_json_object(p)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False, str(p)
    has_prompt = any(
        is_router_handler(h)
        for grp in (hooks.get(spec.prompt_event) or [])
        if isinstance(grp, dict)
        for h in (grp.get("hooks") or [])
    )
    has_tool = any(
        is_router_handler(h)
        for grp in (hooks.get(spec.tool_event) or [])
        if isinstance(grp, dict)
        for h in (grp.get("hooks") or [])
    )
    return (has_prompt and has_tool), str(p)


def sync_agent(
    agent: str,
    root: Path,
    router: Path,
    uninstall: bool,
    dry_run: bool,
    *,
    home: Path | None = None,
) -> tuple[str, str]:
    if agent == "antigravity":
        return sync_antigravity(router, uninstall, dry_run, home=home)
    if agent == "opencode":
        return sync_opencode(root, uninstall, dry_run, home=home)
    if agent in HOOKS_JSON_AGENTS:
        return sync_hooks_json_agent(
            HOOKS_JSON_AGENTS[agent], router, uninstall, dry_run, home=home
        )
    raise KeyError(f"Unsupported agent: {agent}")


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

    prefix = "[DRY-RUN] " if args.dry_run else ""
    for ag in targets:
        try:
            action, path = sync_agent(ag, root, router, args.uninstall, args.dry_run)
        except Exception as exc:
            print(f"[ERROR] {ag}: {exc}", file=sys.stderr)
            return 1
        print(f"{prefix}[{action.upper()}] {ag}: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
