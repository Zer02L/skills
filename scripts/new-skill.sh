#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEMPLATE_FILE="$REPO_ROOT/templates/skill-template/SKILL.md"
SKILLS_DIR="$REPO_ROOT/skills"

usage() {
  cat <<'EOF'
Usage: ./scripts/new-skill.sh <skill-name> [OPTIONS]

Scaffold a new skill under skills/<skill-name>/ from templates/skill-template/SKILL.md.

Options:
  --with-scripts      Create an empty scripts/ subdirectory
  --with-references   Create an empty references/ subdirectory
  --with-assets       Create an empty assets/ subdirectory
  -h, --help          Show this help message
EOF
}

WITH_SCRIPTS=0
WITH_REFERENCES=0
WITH_ASSETS=0
SKILL_NAME=""

while [ $# -gt 0 ]; do
  case "$1" in
    --with-scripts)
      WITH_SCRIPTS=1
      shift
      ;;
    --with-references)
      WITH_REFERENCES=1
      shift
      ;;
    --with-assets)
      WITH_ASSETS=1
      shift
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
      if [ -n "$SKILL_NAME" ]; then
        echo "Error: expected a single <skill-name>, got extra argument '$1'" >&2
        usage >&2
        exit 2
      fi
      SKILL_NAME="$1"
      shift
      ;;
  esac
done

if [ -z "$SKILL_NAME" ]; then
  echo "Error: <skill-name> is required." >&2
  usage >&2
  exit 2
fi

if ! [[ "$SKILL_NAME" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]]; then
  echo "Error: invalid skill name '$SKILL_NAME'. Use kebab-case (lowercase letters, digits, single hyphens)." >&2
  exit 1
fi

if [ "${#SKILL_NAME}" -gt 64 ]; then
  echo "Error: skill name '$SKILL_NAME' is too long (${#SKILL_NAME} chars; max 64)." >&2
  exit 1
fi

if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "Error: template file not found: $TEMPLATE_FILE" >&2
  exit 1
fi

TARGET_DIR="$SKILLS_DIR/$SKILL_NAME"
if [ -e "$TARGET_DIR" ]; then
  echo "Error: target directory already exists: $TARGET_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"
if [ "$WITH_SCRIPTS" -eq 1 ]; then
  mkdir -p "$TARGET_DIR/scripts"
fi
if [ "$WITH_REFERENCES" -eq 1 ]; then
  mkdir -p "$TARGET_DIR/references"
fi
if [ "$WITH_ASSETS" -eq 1 ]; then
  mkdir -p "$TARGET_DIR/assets"
fi

python3 - "$TEMPLATE_FILE" "$TARGET_DIR/SKILL.md" "$SKILL_NAME" <<'PY'
import pathlib
import sys

template_path = pathlib.Path(sys.argv[1])
dest_path = pathlib.Path(sys.argv[2])
skill_name = sys.argv[3]

text = template_path.read_text(encoding="utf-8")
dest_path.write_text(text.replace("__SKILL_NAME__", skill_name), encoding="utf-8")
PY

echo "Created skill scaffold: $TARGET_DIR"
echo "Next steps:"
echo "  1. Edit $TARGET_DIR/SKILL.md"
echo "  2. ./scripts/validate.py --strict $SKILL_NAME"
echo "  3. ./scripts/sync-to-manager.sh $SKILL_NAME --deploy claude_code"
