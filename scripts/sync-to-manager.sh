#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/skills"
VALIDATOR="$SCRIPT_DIR/validate.py"

usage() {
  cat <<'EOF'
Usage: ./scripts/sync-to-manager.sh [OPTIONS] (--all | <skill-name-or-path>...)

Validate custom skills in this repo and install/update them in Skills Manager.

Options:
  --all                     Sync all skills inside skills/
  --dry-run                 Validate and preview actions without modifying Skills Manager
  --deploy <agent>          Deploy synced skill(s) to an agent (repeatable, e.g. --deploy claude_code)
  --backup                  Commit and push changes in Skills Manager's Git backup repo
  --backup-message <msg>    Commit message used with --backup (default: "sync custom skills")
  --hooks                   Also run scripts/sync-hooks.py across detected hook-capable agents
  -h, --help                Show this help message
EOF
}

DRY_RUN=0
SYNC_ALL=0
DO_BACKUP=0
DO_HOOKS=0
BACKUP_MSG="sync custom skills"
DEPLOY_AGENTS=()
RAW_TARGETS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --all)
      SYNC_ALL=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --deploy)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "Error: --deploy requires an <agent> key." >&2
        exit 2
      fi
      DEPLOY_AGENTS+=("$2")
      shift 2
      ;;
    --backup)
      DO_BACKUP=1
      shift
      ;;
    --hooks)
      DO_HOOKS=1
      shift
      ;;
    --backup-message)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "Error: --backup-message requires a non-empty message." >&2
        exit 2
      fi
      BACKUP_MSG="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Error: unknown option '$1'" >&2
      usage >&2
      exit 2
      ;;
    *)
      RAW_TARGETS+=("$1")
      shift
      ;;
  esac
done

if [ "$SYNC_ALL" -eq 0 ] && [ "${#RAW_TARGETS[@]}" -eq 0 ]; then
  echo "Error: pass --all or at least one <skill-name-or-path>." >&2
  usage >&2
  exit 2
fi

if [ "$SYNC_ALL" -eq 1 ] && [ "${#RAW_TARGETS[@]}" -gt 0 ]; then
  echo "Error: cannot combine --all with explicit skill arguments." >&2
  usage >&2
  exit 2
fi

# Resolve skills-manager-cli using the Skills Manager bridge check.
D="$HOME/.skills-manager/bin"
B="$D/skills-manager-cli"
[ -e "$B" ] || B="$B.exe"
SM=""
if [ -s "$D/.version" ] && [ -x "$B" ]; then
  SM="$B"
elif [ -s "$D/.version" ] || [ -e "$B" ]; then
  echo "Error: Skills Manager CLI bridge is broken in $D. Open the Skills Manager desktop app once to republish it." >&2
  exit 1
else
  P="$(command -v skills-manager-cli 2>/dev/null || true)"
  if [ -n "$P" ] && [ -x "$P" ]; then
    SM="$P"
  else
    echo "Error: skills-manager-cli not found in $D or PATH. Install or open Skills Manager first." >&2
    exit 1
  fi
fi

# Resolve target skill directories.
TARGET_DIRS=()
if [ "$SYNC_ALL" -eq 1 ]; then
  if [ -d "$SKILLS_DIR" ]; then
    while IFS= read -r dir; do
      [ -n "$dir" ] && TARGET_DIRS+=("$dir")
    done < <(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d ! -name '.*' | sort)
  fi
  if [ "${#TARGET_DIRS[@]}" -eq 0 ]; then
    echo "No skills found in $SKILLS_DIR — nothing to sync."
    exit 0
  fi
else
  for item in "${RAW_TARGETS[@]}"; do
    if [ -d "$item" ]; then
      TARGET_DIRS+=("$(cd "$item" && pwd -P)")
    elif [[ "$item" != */* && "$item" != .* ]] && [ -d "$SKILLS_DIR/$item" ]; then
      TARGET_DIRS+=("$(cd "$SKILLS_DIR/$item" && pwd -P)")
    else
      echo "Error: skill directory not found for '$item'." >&2
      exit 1
    fi
  done
fi

# Validate all target skills first.
python3 "$VALIDATOR" "${TARGET_DIRS[@]}"

# Hand off matching, install/update, deploy, and optional backup to Python for safe JSON handling.
python3 - "$SM" "$DRY_RUN" "$DO_BACKUP" "$BACKUP_MSG" "${#DEPLOY_AGENTS[@]}" "${DEPLOY_AGENTS[@]}" "${TARGET_DIRS[@]}" <<'PY'
import json
import os
import subprocess
import sys
from pathlib import Path


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


def main() -> int:
    sm = sys.argv[1]
    dry_run = sys.argv[2] == "1"
    do_backup = sys.argv[3] == "1"
    backup_msg = sys.argv[4]
    num_agents = int(sys.argv[5])
    agents = sys.argv[6 : 6 + num_agents]
    target_dirs = [os.path.realpath(p) for p in sys.argv[6 + num_agents :]]

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
            if dry_run:
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
            if dry_run:
                print(f"[DRY-RUN] Would install: {sm} skills install {skill_dir} --local")
            else:
                rc, out, err = run_cli(sm, ["--json", "skills", "install", skill_dir, "--local"], allow_fail=True)
                if rc != 0:
                    print(f"[ERROR] skills install failed: {(err or out).strip()}", file=sys.stderr)
                    had_error = True
                    continue
                parsed = parse_json_output(out)
                skill_id = extract_id(parsed) if parsed is not None else None
                # Refresh list to reliably resolve skill_id
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

        if agents:
            agent_args: list[str] = []
            for a in agents:
                agent_args.extend(["--agent", a])

            if dry_run:
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
                    print(f"[DRY-RUN] Would deploy {skill_name} to: {', '.join(agents)}")
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
                        print(f"[DEPLOYED] {skill_name} -> {', '.join(agents)}")

    if do_backup:
        print("\n=== Git Backup ===")
        if dry_run:
            print(f"[DRY-RUN] Would commit (message: {backup_msg!r}) and push Skills Manager backup repo.")
        else:
            _, status_out, _ = run_cli(sm, ["--json", "git", "status"])
            status = json.loads(status_out)
            if not status.get("is_repo"):
                print("[WARN] Skills Manager backup repository is not initialized; skipping backup.")
            else:
                if status.get("has_changes"):
                    run_cli(sm, ["--json", "git", "commit", "-m", backup_msg])
                    print(f"[BACKUP] Committed changes: {backup_msg}")
                    _, status_out, _ = run_cli(sm, ["--json", "git", "status"])
                    status = json.loads(status_out)
                else:
                    print("[BACKUP] No uncommitted changes in Skills Manager backup repo.")
                if status.get("ahead", 0) > 0:
                    run_cli(sm, ["--json", "git", "push"])
                    print("[BACKUP] Pushed to remote.")
                elif synced_any:
                    print("[BACKUP] Remote is already up to date.")

    return 1 if had_error else 0


if __name__ == "__main__":
    sys.exit(main())
PY

if [ "$DO_HOOKS" -eq 1 ]; then
  echo ""
  echo "=== Syncing Universal Agent Hooks ==="
  HOOK_ARGS=()
  if [ "$DRY_RUN" -eq 1 ]; then
    HOOK_ARGS+=(--dry-run)
  fi
  python3 "$SCRIPT_DIR/sync-hooks.py" "${HOOK_ARGS[@]}"
fi