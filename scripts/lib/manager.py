#!/usr/bin/env python3
"""Validate custom skills in this repo and install/update them in Skills Manager."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _LIB_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from lib.common import REPO_ROOT, SKILLS_DIR, resolve_skill_targets  # noqa: E402


def resolve_sm_cli(home: Path | None = None) -> str:
    """Resolve the Skills Manager CLI binary via bridge check or PATH."""
    base_home = home or Path.home()
    bin_dir = base_home / ".skills-manager" / "bin"
    binary = bin_dir / "skills-manager-cli"
    if not binary.exists() and (bin_dir / "skills-manager-cli.exe").exists():
        binary = bin_dir / "skills-manager-cli.exe"
    version_file = bin_dir / ".version"

    ver_ok = version_file.is_file() and version_file.stat().st_size > 0
    bin_ok = binary.is_file() and os.access(binary, os.X_OK)

    if ver_ok and bin_ok:
        return str(binary)
    if ver_ok or binary.exists():
        raise RuntimeError(
            f"Skills Manager CLI bridge is broken in {bin_dir}. "
            "Open the Skills Manager desktop app once to republish it."
        )

    found = shutil.which("skills-manager-cli")
    if found and os.access(found, os.X_OK):
        return found
    raise RuntimeError(
        f"skills-manager-cli not found in {bin_dir} or PATH. Install or open Skills Manager first."
    )


def run_cli(sm: str, args: list[str], allow_fail: bool = False) -> tuple[int, str, str]:
    proc = subprocess.run([sm, *args], capture_output=True, text=True)
    if proc.returncode != 0 and not allow_fail:
        msg = proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"Command failed: {sm} {' '.join(args)}\n{msg}")
    return proc.returncode, proc.stdout, proc.stderr


def parse_json_output(raw: str) -> object | None:
    text = raw.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def find_held_back(data: object) -> list[str]:
    if isinstance(data, dict):
        hb = data.get("held_back_removals")
        if isinstance(hb, list) and hb:
            return [str(x) for x in hb]
        for val in data.values():
            found = find_held_back(val)
            if found:
                return found
    elif isinstance(data, list):
        for item in data:
            found = find_held_back(item)
            if found:
                return found
    return []


def extract_id(data: object) -> str | None:
    if isinstance(data, dict):
        if isinstance(data.get("id"), str) and data["id"]:
            return data["id"]
        for key in ("skill", "result", "data"):
            if key in data:
                found = extract_id(data[key])
                if found:
                    return found
    elif isinstance(data, list) and len(data) == 1:
        return extract_id(data[0])
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="./scripts/sync-to-manager.sh",
        description="Validate custom skills in this repo and install/update them in Skills Manager.",
    )
    parser.add_argument("--all", action="store_true", help="Sync all skills inside skills/.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and preview actions without modifying Skills Manager.",
    )
    parser.add_argument(
        "--deploy",
        action="append",
        dest="deploy_agents",
        default=[],
        metavar="AGENT",
        help="Deploy synced skill(s) to an agent (repeatable, e.g. --deploy claude_code).",
    )
    parser.add_argument(
        "--backup",
        action="store_true",
        help="Commit and push changes in Skills Manager's Git backup repo.",
    )
    parser.add_argument(
        "--backup-message",
        default="sync custom skills",
        metavar="MSG",
        help='Commit message used with --backup (default: "sync custom skills").',
    )
    parser.add_argument(
        "--hooks",
        action="store_true",
        help="Also run scripts/sync-hooks.py across detected hook-capable agents.",
    )
    parser.add_argument(
        "targets",
        nargs="*",
        metavar="SKILL",
        help="Skill name(s) under skills/ or path(s) to skill directories.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.all and not args.targets:
        print("Error: pass --all or at least one <skill-name-or-path>.", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return 2
    if args.all and args.targets:
        print("Error: cannot combine --all with explicit skill arguments.", file=sys.stderr)
        parser.print_usage(sys.stderr)
        return 2
    if any(not a for a in args.deploy_agents):
        print("Error: --deploy requires a non-empty <agent> key.", file=sys.stderr)
        return 2
    if not args.backup_message:
        print("Error: --backup-message requires a non-empty message.", file=sys.stderr)
        return 2

    try:
        sm = resolve_sm_cli()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.all:
        targets, _ = resolve_skill_targets([], REPO_ROOT)
        if not targets:
            print(f"No skills found in {SKILLS_DIR} — nothing to sync.")
            return 0
    else:
        targets, missing = resolve_skill_targets(args.targets, REPO_ROOT)
        if missing:
            print(f"Error: skill directory not found for '{missing[0]}'.", file=sys.stderr)
            return 1

    target_dirs = [os.path.realpath(str(p)) for p in targets]

    val_proc = subprocess.run([sys.executable, str(_SCRIPTS_DIR / "validate.py"), *target_dirs])
    if val_proc.returncode != 0:
        return val_proc.returncode

    _, list_out, _ = run_cli(sm, ["--json", "skills", "list"])
    skills_list = json.loads(list_out)

    had_error = False
    synced_any = False

    for skill_dir in target_dirs:
        skill_name = Path(skill_dir).name
        print(f"\n=== {skill_name} ({skill_dir}) ===")

        local_match = None
        name_matches = []
        for entry in skills_list:
            src_type = entry.get("source_type")
            src_ref = entry.get("source_ref")
            if src_type == "local" and isinstance(src_ref, str) and os.path.realpath(src_ref) == skill_dir:
                local_match = entry
                break
            if entry.get("name") == skill_name:
                name_matches.append(entry)

        skill_id: str | None = None

        if local_match is not None:
            skill_id = local_match["id"]
            if args.dry_run:
                rc, out, err = run_cli(sm, ["--json", "skills", "check", skill_id], allow_fail=True)
                if rc != 0:
                    print(f"[ERROR] skills check failed: {(err or out).strip()}", file=sys.stderr)
                    had_error = True
                    continue
                print(f"[DRY-RUN] Already tracked locally (id={skill_id}). Check result:")
                print(f"  {out.strip()}")
            else:
                rc, out, err = run_cli(sm, ["--json", "skills", "update", skill_id], allow_fail=True)
                if rc != 0:
                    print(f"[ERROR] skills update failed: {(err or out).strip()}", file=sys.stderr)
                    had_error = True
                    continue
                parsed = parse_json_output(out)
                held_back = find_held_back(parsed) if parsed is not None else []
                if held_back:
                    print(
                        f"[WARN] Update held back for {skill_name} (id={skill_id}) because extra files "
                        f"exist in the library/deployed copy: {', '.join(held_back)}"
                    )
                    print("  Confirm in the Skills Manager desktop app or resolve those files before retrying.")
                else:
                    print(f"[UPDATED] {skill_name} (id={skill_id})")
                    synced_any = True

        elif name_matches:
            conflict = name_matches[0]
            src_type = conflict.get("source_type")
            src_ref = conflict.get("source_ref")
            cid = conflict.get("id")
            if src_type == "git":
                print(
                    f"[CONFLICT] Skill '{skill_name}' (id={cid}) is already tracked from git ({src_ref}).\n"
                    f"  Commit & push your repo changes first, then run: {sm} skills update {cid}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"[CONFLICT] Skill '{skill_name}' already exists in Skills Manager "
                    f"(id={cid}, source_type={src_type}, source_ref={src_ref}).\n"
                    f"  Skipping install to avoid creating a duplicate entry.",
                    file=sys.stderr,
                )
            had_error = True
            continue

        else:
            if args.dry_run:
                print(f"[DRY-RUN] Would install: {sm} skills install {skill_dir} --local")
            else:
                rc, out, err = run_cli(sm, ["--json", "skills", "install", skill_dir, "--local"], allow_fail=True)
                if rc != 0:
                    print(f"[ERROR] skills install failed: {(err or out).strip()}", file=sys.stderr)
                    had_error = True
                    continue
                parsed = parse_json_output(out)
                skill_id = extract_id(parsed) if parsed is not None else None
                _, list_out2, _ = run_cli(sm, ["--json", "skills", "list"])
                skills_list = json.loads(list_out2)
                if skill_id is None:
                    for entry in skills_list:
                        if (
                            entry.get("source_type") == "local"
                            and isinstance(entry.get("source_ref"), str)
                            and os.path.realpath(entry["source_ref"]) == skill_dir
                        ):
                            skill_id = entry["id"]
                            break
                print(f"[INSTALLED] {skill_name} (id={skill_id or 'unknown'})")
                synced_any = True

        if args.deploy_agents:
            agent_args: list[str] = []
            for a in args.deploy_agents:
                agent_args.extend(["--agent", a])

            if args.dry_run:
                if skill_id is not None:
                    rc, out, err = run_cli(
                        sm,
                        ["--json", "skills", "deploy", skill_id, *agent_args, "--dry-run"],
                        allow_fail=True,
                    )
                    if rc != 0:
                        print(f"[ERROR] dry-run deploy failed: {(err or out).strip()}", file=sys.stderr)
                        had_error = True
                    else:
                        print(f"[DRY-RUN] Deploy preview: {out.strip()}")
                else:
                    print(f"[DRY-RUN] Would deploy {skill_name} to: {', '.join(args.deploy_agents)}")
            else:
                if skill_id is None:
                    print(f"[ERROR] Cannot deploy {skill_name}: failed to determine skill id.", file=sys.stderr)
                    had_error = True
                else:
                    rc, out, err = run_cli(
                        sm,
                        ["--json", "skills", "deploy", skill_id, *agent_args],
                        allow_fail=True,
                    )
                    if rc != 0:
                        err_json = parse_json_output(err) or parse_json_output(out)
                        if isinstance(err_json, dict) and err_json.get("code") == "TARGET_CONFLICT":
                            conflicts = err_json.get("details", {}).get("conflicts", [])
                            print(f"[ERROR] Deploy refused due to target conflict(s) for {skill_name}:", file=sys.stderr)
                            for c in conflicts:
                                print(f"  - {c.get('path')}: {c.get('reason')}", file=sys.stderr)
                        else:
                            print(f"[ERROR] skills deploy failed: {(err or out).strip()}", file=sys.stderr)
                        had_error = True
                    else:
                        print(f"[DEPLOYED] {skill_name} -> {', '.join(args.deploy_agents)}")

    if args.backup:
        print("\n=== Git Backup ===")
        if args.dry_run:
            print(f"[DRY-RUN] Would commit (message: {args.backup_message!r}) and push Skills Manager backup repo.")
        else:
            _, status_out, _ = run_cli(sm, ["--json", "git", "status"])
            status = json.loads(status_out)
            if not status.get("is_repo"):
                print("[WARN] Skills Manager backup repository is not initialized; skipping backup.")
            else:
                if status.get("has_changes"):
                    run_cli(sm, ["--json", "git", "commit", "-m", args.backup_message])
                    print(f"[BACKUP] Committed changes: {args.backup_message}")
                    _, status_out, _ = run_cli(sm, ["--json", "git", "status"])
                    status = json.loads(status_out)
                else:
                    print("[BACKUP] No uncommitted changes in Skills Manager backup repo.")
                if status.get("ahead", 0) > 0:
                    run_cli(sm, ["--json", "git", "push"])
                    print("[BACKUP] Pushed to remote.")
                elif synced_any:
                    print("[BACKUP] Remote is already up to date.")

    if had_error:
        return 1

    if args.hooks:
        print("\n=== Syncing Universal Agent Hooks ===")
        hook_cmd = [sys.executable, str(_SCRIPTS_DIR / "sync-hooks.py")]
        if args.dry_run:
            hook_cmd.append("--dry-run")
        hook_proc = subprocess.run(hook_cmd)
        if hook_proc.returncode != 0:
            return hook_proc.returncode

    return 0


if __name__ == "__main__":
    sys.exit(main())
