#!/usr/bin/env bash
set -euo pipefail

APP_ID="${FIGCRAFT_FLATPAK_ID:-ai.storyteller.figcraft}"
NO_SYSTEM_FONTS=1
EXTRA_MOUNTS=()

usage() {
  cat <<'EOF'
Usage: fc.sh [--system-fonts] [--mount DIR]... <subcommand> [args...]

Flatpak-aware wrapper for ai.storyteller.figcraft (figcraft-cli / figcraft).
Defaults to --no-system-fonts and auto-mounts Flatpak --filesystem paths.

Global options (must appear before <subcommand>):
  --system-fonts        Enable host system font indexing (disabled by default for speed)
  --mount DIR           Grant Flatpak access to an extra host directory (repeatable)
  -h, --help            Show this help

Subcommands:
  run [--in F] [--out F] [--compact] [SCRIPT|-]
                        Run JSON array or JSONL command script (reads stdin if omitted or '-')
  info <FILE>           Print document summary JSON
  render <FILE> --out <OUT> [opts...]
                        Render page image
  export <FILE> --out <OUT> [opts...]
                        Export frame(s), layer, or file
  convert <IN> <OUT>    Convert between supported extensions
  lookup <QUERY> [--limit N]
                        Search commands with bounded output (default limit: 25)
  inspect-code <FILE> [--node ID|NAME] [--lang LANG]
                        Generate code (default lang: react) for a node or first top-level frame
  gui [args...]         Launch FigCraft GUI
  mcp [args...]         Start FigCraft MCP server on stdio
  raw [args...]         Pass arguments straight to figcraft-cli
EOF
}

ensure_flatpak() {
  if ! command -v flatpak >/dev/null 2>&1; then
    echo "Error: 'flatpak' command not found." >&2
    exit 1
  fi
  if [ ! -d "$HOME/.local/share/flatpak/app/$APP_ID" ] && [ ! -d "/var/lib/flatpak/app/$APP_ID" ]; then
    if ! flatpak info "$APP_ID" >/dev/null 2>&1; then
      echo "Error: Flatpak app '$APP_ID' is not installed." >&2
      exit 1
    fi
  fi
}

while [ $# -gt 0 ]; do
  case "$1" in
    --system-fonts)
      NO_SYSTEM_FONTS=0
      shift
      ;;
    --mount)
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "Error: --mount requires a directory path." >&2
        exit 2
      fi
      EXTRA_MOUNTS+=("$2")
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Error: unknown global option '$1' (global options go before <subcommand>)." >&2
      usage >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if [ $# -lt 1 ]; then
  usage >&2
  exit 2
fi

SUBCMD="$1"
shift

ensure_flatpak

PY_CODE="$(cat <<'__FC_PY__'
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FILE_PATH_CMD_PREFIXES = ("file.", "image.", "variable.", "plugin.")


def existing_mount_dir(path_str: str) -> str:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    # Normalize without requiring leaf to exist
    norm = Path(os.path.abspath(str(p)))
    cur = norm if norm.is_dir() else norm.parent
    while not cur.exists() and cur != cur.parent:
        cur = cur.parent
    return os.path.realpath(cur)


def abs_host_path(path_str: str) -> str:
    p = Path(path_str).expanduser()
    if not p.is_absolute():
        return os.path.abspath(str(Path.cwd() / p))
    return os.path.abspath(str(p))


def build_flatpak_cmd(
    app_id: str,
    mounts: list[str],
    binary: str,
    cli_args: list[str],
    allow_mounts: bool = True,
) -> list[str]:
    cmd = ["flatpak", "run"]
    if allow_mounts:
        seen: set[str] = set()
        for m in mounts:
            real = existing_mount_dir(m)
            if real not in seen:
                seen.add(real)
                cmd.append(f"--filesystem={real}")
    if binary:
        cmd.append(f"--command={binary}")
    cmd.append(app_id)
    cmd.extend(cli_args)
    return cmd


def collect_and_rewrite_step_paths(step: object, mounts: list[str]) -> None:
    if not isinstance(step, dict):
        return
    cmd_name = step.get("command")
    params = step.get("params")
    if isinstance(cmd_name, str) and isinstance(params, dict):
        if cmd_name == "command.batch" and isinstance(params.get("commands"), list):
            for sub in params["commands"]:
                collect_and_rewrite_step_paths(sub, mounts)
        elif cmd_name.startswith(FILE_PATH_CMD_PREFIXES):
            raw_path = params.get("path")
            if isinstance(raw_path, str) and raw_path.strip() and "://" not in raw_path:
                abs_p = abs_host_path(raw_path)
                params["path"] = abs_p
                mounts.append(abs_p)
            if cmd_name == "file.open" and isinstance(params.get("variables"), str):
                v = params["variables"]
                if v.strip() and not v.lstrip().startswith("{") and "://" not in v:
                    abs_v = abs_host_path(v)
                    params["variables"] = abs_v
                    mounts.append(abs_v)


def parse_script_text(raw: str) -> tuple[bool, list[dict]]:
    stripped = raw.strip()
    if not stripped:
        raise ValueError("Script input is empty.")
    if stripped.startswith("["):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError("JSON script root must be an array of command objects.")
        return True, data
    steps: list[dict] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        s = line.strip()
        if not s:
            continue
        obj = json.loads(s)
        if not isinstance(obj, dict):
            raise ValueError(f"Line {lineno} in JSONL script must be a JSON object.")
        steps.append(obj)
    return False, steps


def compact_run_line(line: str) -> str:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        return line
    if not isinstance(obj, dict):
        return line
    out: dict[str, object] = {
        "step": obj.get("step"),
        "command": obj.get("command"),
        "ok": obj.get("ok"),
    }
    if not obj.get("ok"):
        if "error" in obj:
            out["error"] = obj["error"]
        if obj.get("rolledBack"):
            out["rolledBack"] = True
        return json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    res = obj.get("result")
    if isinstance(res, dict):
        for k in ("id", "ids", "path", "format", "bytes", "total", "language", "name"):
            if k in res:
                out[k] = res[k]
    elif isinstance(res, list):
        summary = []
        for item in res:
            if isinstance(item, dict):
                picked = {k: item[k] for k in ("id", "ids", "path", "format", "bytes", "ok", "error") if k in item}
                summary.append(picked if picked else item)
            else:
                summary.append(item)
        out["result"] = summary
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def cmd_run(app_id: str, no_sys_fonts: bool, base_mounts: list[str], args: list[str]) -> int:
    in_file: str | None = None
    out_file: str | None = None
    compact = False
    script_arg: str | None = None
    passthrough: list[str] = []

    i = 0
    while i < len(args):
        a = args[i]
        if a == "--in":
            i += 1
            if i >= len(args):
                print("Error: --in requires a file path.", file=sys.stderr)
                return 2
            in_file = args[i]
        elif a == "--out":
            i += 1
            if i >= len(args):
                print("Error: --out requires a file path.", file=sys.stderr)
                return 2
            out_file = args[i]
        elif a == "--compact":
            compact = True
        elif a.startswith("--automation-read-root=") or a.startswith("--automation-write-root="):
            val = a.split("=", 1)[1]
            base_mounts.append(val)
            passthrough.extend([a.split("=", 1)[0], abs_host_path(val)])
        elif a in ("--automation-read-root", "--automation-write-root"):
            i += 1
            if i >= len(args):
                print(f"Error: {a} requires a directory.", file=sys.stderr)
                return 2
            base_mounts.append(args[i])
            passthrough.extend([a, abs_host_path(args[i])])
        elif a.startswith("-") and a != "-":
            print(f"Error: unknown option '{a}' for run.", file=sys.stderr)
            return 2
        else:
            if script_arg is not None:
                print(f"Error: unexpected extra script argument '{a}'.", file=sys.stderr)
                return 2
            script_arg = a
        i += 1

    if script_arg is None or script_arg == "-":
        raw_script = sys.stdin.read()
    else:
        script_path = Path(script_arg).expanduser()
        if not script_path.is_file():
            print(f"Error: script file not found: {script_arg}", file=sys.stderr)
            return 1
        raw_script = script_path.read_text(encoding="utf-8")

    try:
        is_array, steps = parse_script_text(raw_script)
    except Exception as exc:
        print(f"Error: invalid script JSON: {exc}", file=sys.stderr)
        return 1

    mounts = list(base_mounts)
    for st in steps:
        collect_and_rewrite_step_paths(st, mounts)

    cli_args: list[str] = ["run"]
    if no_sys_fonts:
        cli_args.append("--no-system-fonts")
    if in_file is not None:
        abs_in = abs_host_path(in_file)
        mounts.append(abs_in)
        cli_args.extend(["--in", abs_in])
    if out_file is not None:
        abs_out = abs_host_path(out_file)
        mounts.append(abs_out)
        cli_args.extend(["--out", abs_out])
    cli_args.extend(passthrough)

    with tempfile.TemporaryDirectory(prefix="fc-run-") as tmpdir:
        mounts.append(tmpdir)
        staged = os.path.join(tmpdir, "script.json" if is_array else "script.jsonl")
        with open(staged, "w", encoding="utf-8") as fh:
            if is_array:
                json.dump(steps, fh, ensure_ascii=False)
            else:
                for st in steps:
                    fh.write(json.dumps(st, ensure_ascii=False) + "\n")
        cli_args.append(staged)

        cmd = build_flatpak_cmd(app_id, mounts, "figcraft-cli", cli_args)
        if not compact:
            proc = subprocess.run(cmd)
            return proc.returncode

        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.stdout:
            for line in proc.stdout.splitlines():
                if line.strip():
                    print(compact_run_line(line))
        if proc.stderr:
            sys.stderr.write(proc.stderr)
        return proc.returncode


def cmd_info(app_id: str, no_sys_fonts: bool, base_mounts: list[str], args: list[str]) -> int:
    if not args:
        print("Error: info requires <FILE>.", file=sys.stderr)
        return 2
    mounts = list(base_mounts)
    cli_args: list[str] = ["info", "--json"]
    if no_sys_fonts:
        cli_args.append("--no-system-fonts")
    for a in args:
        if a.startswith("-"):
            if a != "--json":
                cli_args.append(a)
        else:
            abs_f = abs_host_path(a)
            mounts.append(abs_f)
            cli_args.append(abs_f)
    cmd = build_flatpak_cmd(app_id, mounts, "figcraft-cli", cli_args)
    return subprocess.run(cmd).returncode


def cmd_file_op(subcmd: str, app_id: str, no_sys_fonts: bool, base_mounts: list[str], args: list[str]) -> int:
    mounts = list(base_mounts)
    cli_args: list[str] = [subcmd]
    if no_sys_fonts:
        cli_args.append("--no-system-fonts")

    expect_val: str | None = None
    for a in args:
        if expect_val is not None:
            if expect_val in ("--out", "-o", "--automation-read-root", "--automation-write-root"):
                abs_p = abs_host_path(a)
                mounts.append(abs_p)
                cli_args.append(abs_p)
            else:
                cli_args.append(a)
            expect_val = None
            continue

        if a in ("--out", "-o", "--format", "--scale", "--page", "--node", "--bleed", "--vd-compat", "--automation-read-root", "--automation-write-root"):
            cli_args.append(a)
            expect_val = a
        elif a.startswith(("--out=", "--automation-read-root=", "--automation-write-root=")):
            flag, val = a.split("=", 1)
            abs_p = abs_host_path(val)
            mounts.append(abs_p)
            cli_args.extend([flag, abs_p])
        elif a.startswith("-"):
            cli_args.append(a)
        else:
            abs_p = abs_host_path(a)
            mounts.append(abs_p)
            cli_args.append(abs_p)

    cmd = build_flatpak_cmd(app_id, mounts, "figcraft-cli", cli_args)
    return subprocess.run(cmd).returncode


def cmd_lookup(app_id: str, base_mounts: list[str], args: list[str]) -> int:
    limit = 25
    query_parts: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--limit":
            i += 1
            if i >= len(args):
                print("Error: --limit requires an integer.", file=sys.stderr)
                return 2
            limit = int(args[i])
        elif a.startswith("-"):
            print(f"Error: unknown option '{a}' for lookup.", file=sys.stderr)
            return 2
        else:
            query_parts.append(a)
        i += 1

    if not query_parts:
        print("Error: lookup requires <QUERY> (pass a keyword such as 'auto layout', 'variable', or 'export').", file=sys.stderr)
        return 2
    query = " ".join(query_parts)

    cmd = build_flatpak_cmd(
        app_id,
        base_mounts,
        "figcraft-cli",
        ["commands", "--json", "--no-system-fonts", "--filter", query],
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        return proc.returncode

    matches = json.loads(proc.stdout)
    total = len(matches)
    shown = matches[: max(0, limit)]
    for item in shown:
        flag = "*" if item.get("undoable") else ""
        shortcut = f" [{item['shortcut']}]" if item.get("shortcut") else ""
        print(f"{item['id']}{flag}  {item.get('label', '')}{shortcut}")
        if item.get("params"):
            print(f"    {item['params']}")
    if total > len(shown):
        print(f"\n... showing {len(shown)} of {total} matching commands; refine query or pass --limit {total}.")
    elif total == 0:
        print(f"No commands matched '{query}'.")
    return 0


def cmd_inspect_code(app_id: str, no_sys_fonts: bool, base_mounts: list[str], args: list[str]) -> int:
    file_arg: str | None = None
    node_arg: str | None = None
    lang = "react"
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--node":
            i += 1
            if i >= len(args):
                print("Error: --node requires an id or layer name.", file=sys.stderr)
                return 2
            node_arg = args[i]
        elif a == "--lang":
            i += 1
            if i >= len(args):
                print("Error: --lang requires a language name.", file=sys.stderr)
                return 2
            lang = args[i]
        elif a.startswith("-"):
            print(f"Error: unknown option '{a}' for inspect-code.", file=sys.stderr)
            return 2
        else:
            if file_arg is not None:
                print(f"Error: unexpected extra argument '{a}'.", file=sys.stderr)
                return 2
            file_arg = a
        i += 1

    if file_arg is None:
        print("Error: inspect-code requires <FILE>.", file=sys.stderr)
        return 2

    abs_file = abs_host_path(file_arg)
    if not os.path.isfile(abs_file):
        print(f"Error: file not found: {file_arg}", file=sys.stderr)
        return 1

    mounts = list(base_mounts) + [abs_file]
    steps: list[dict] = []

    if node_arg is None:
        info_cmd = build_flatpak_cmd(
            app_id,
            mounts,
            "figcraft-cli",
            ["info", "--json", "--no-system-fonts", abs_file],
        )
        info_proc = subprocess.run(info_cmd, capture_output=True, text=True)
        if info_proc.returncode != 0:
            sys.stderr.write(info_proc.stderr)
            return info_proc.returncode
        info_data = json.loads(info_proc.stdout)
        frame_id = None
        pages = info_data.get("pages") or []
        if pages and pages[0].get("frames"):
            frame_id = pages[0]["frames"][0].get("id")
        code_params: dict[str, object] = {"language": lang}
        if frame_id is not None:
            code_params["id"] = frame_id
        steps.append({"command": "inspect.code", "params": code_params})
    elif re.fullmatch(r"\d+", node_arg):
        steps.append({"command": "inspect.code", "params": {"id": int(node_arg), "language": lang}})
    else:
        steps.append({"command": "node.find", "as": "found", "params": {"name": node_arg, "limit": 1}})
        steps.append({
            "command": "inspect.code",
            "params": {"id": {"$ref": "found", "field": "ids/0"}, "language": lang},
        })

    with tempfile.TemporaryDirectory(prefix="fc-code-") as tmpdir:
        mounts.append(tmpdir)
        staged = os.path.join(tmpdir, "inspect.json")
        with open(staged, "w", encoding="utf-8") as fh:
            json.dump(steps, fh)
        cli_args = ["run"]
        if no_sys_fonts:
            cli_args.append("--no-system-fonts")
        cli_args.extend(["--in", abs_file, staged])
        proc = subprocess.run(
            build_flatpak_cmd(app_id, mounts, "figcraft-cli", cli_args),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr or proc.stdout)
            return proc.returncode
        last_line = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1]
        res = json.loads(last_line)
        if not res.get("ok"):
            print(f"Error: {res.get('error', 'inspect.code failed')}", file=sys.stderr)
            return 1
        code_obj = res.get("result", {})
        print(code_obj.get("code", ""))
    return 0


def main() -> int:
    app_id = sys.argv[1]
    no_sys_fonts = sys.argv[2] == "1"
    n_mounts = int(sys.argv[3])
    base_mounts = sys.argv[4 : 4 + n_mounts]
    subcmd = sys.argv[4 + n_mounts]
    rest = sys.argv[5 + n_mounts :]

    if subcmd == "run":
        return cmd_run(app_id, no_sys_fonts, base_mounts, rest)
    if subcmd == "info":
        return cmd_info(app_id, no_sys_fonts, base_mounts, rest)
    if subcmd in ("render", "export", "convert"):
        return cmd_file_op(subcmd, app_id, no_sys_fonts, base_mounts, rest)
    if subcmd == "lookup":
        return cmd_lookup(app_id, base_mounts, rest)
    if subcmd == "inspect-code":
        return cmd_inspect_code(app_id, no_sys_fonts, base_mounts, rest)
    if subcmd == "gui":
        mounts = list(base_mounts)
        gui_args: list[str] = []
        for a in rest:
            if not a.startswith("-") and os.path.exists(os.path.expanduser(a)):
                ap = abs_host_path(a)
                mounts.append(ap)
                gui_args.append(ap)
            else:
                gui_args.append(a)
        cmd = build_flatpak_cmd(app_id, mounts, "", gui_args)
        return subprocess.run(cmd).returncode
    if subcmd == "mcp":
        has_attach = any(a == "--attach" or a.startswith("--attach=") for a in rest)
        cli_args = ["mcp"]
        if no_sys_fonts:
            cli_args.append("--no-system-fonts")
        cli_args.extend(rest)
        cmd = build_flatpak_cmd(app_id, base_mounts, "figcraft-cli", cli_args, allow_mounts=not has_attach)
        return subprocess.run(cmd).returncode
    if subcmd == "raw":
        cli_args = list(rest)
        if no_sys_fonts and "--no-system-fonts" not in cli_args:
            if cli_args and not cli_args[0].startswith("-"):
                cli_args = [cli_args[0], "--no-system-fonts", *cli_args[1:]]
        cmd = build_flatpak_cmd(app_id, base_mounts, "figcraft-cli", cli_args)
        return subprocess.run(cmd).returncode

    print(f"Error: unknown subcommand '{subcmd}'.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
__FC_PY__
)"
exec python3 -c "$PY_CODE" "$APP_ID" "$NO_SYSTEM_FONTS" "${#EXTRA_MOUNTS[@]}" "${EXTRA_MOUNTS[@]}" "$SUBCMD" "$@"
