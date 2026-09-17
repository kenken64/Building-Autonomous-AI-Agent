#!/usr/bin/env bash
#
# Workshop environment setup for macOS and Ubuntu/Debian.
#
# Creates a virtual environment for a workshop lab, installs its
# dependencies, and seeds the .env file from .env.example.
#
# Usage:
#   ./setup.sh                              # set up the default lab
#   ./setup.sh agentmart_agent_ecosystem    # set up a specific lab
#   ./setup.sh --help
#
set -euo pipefail

DEFAULT_LAB="agentmart_agent_ecosystem"
MIN_PY_MAJOR=3
MIN_PY_MINOR=10

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------- output ----
if [ -t 1 ]; then
  BOLD="$(printf '\033[1m')"; RED="$(printf '\033[31m')"
  GREEN="$(printf '\033[32m')"; YELLOW="$(printf '\033[33m')"
  CYAN="$(printf '\033[36m')"; RESET="$(printf '\033[0m')"
else
  BOLD=""; RED=""; GREEN=""; YELLOW=""; CYAN=""; RESET=""
fi

info()  { printf '%s==>%s %s\n' "$CYAN$BOLD" "$RESET" "$*"; }
ok()    { printf '%s  ok%s %s\n' "$GREEN" "$RESET" "$*"; }
warn()  { printf '%swarn%s %s\n' "$YELLOW" "$RESET" "$*" >&2; }
die()   { printf '%serror%s %s\n' "$RED$BOLD" "$RESET" "$*" >&2; exit 1; }

usage() {
  cat <<USAGE
Usage: ${0##*/} [LAB_DIRECTORY]

Sets up a Python virtual environment for a workshop lab on macOS or Ubuntu.

Arguments:
  LAB_DIRECTORY   Lab folder under workshop/ (default: ${DEFAULT_LAB})

Options:
  -f, --force     Recreate the virtual environment from scratch
      --reset-db  Drop and rebuild the seeded product listing
      --no-seed   Skip seeding the product listing
  -h, --help      Show this help

Examples:
  ./setup.sh
  ./setup.sh ${DEFAULT_LAB}
  ./setup.sh --force --reset-db
USAGE
}

# ------------------------------------------------------------------ args ----
FORCE=0
SEED=1
RESET_DB=0
LAB=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)   usage; exit 0 ;;
    -f|--force)  FORCE=1; shift ;;
    --no-seed)   SEED=0; shift ;;
    --reset-db)  RESET_DB=1; shift ;;
    -*)          die "Unknown option: $1 (try --help)" ;;
    *)           LAB="$1"; shift ;;
  esac
done
LAB="${LAB:-$DEFAULT_LAB}"
LAB="${LAB%/}"

LAB_DIR="$SCRIPT_DIR/$LAB"
[ -d "$LAB_DIR" ] || die "Lab folder not found: $LAB_DIR
Available labs:
$(find "$SCRIPT_DIR" -mindepth 2 -maxdepth 2 -name requirements.txt -exec dirname {} \; | xargs -n1 basename | sed 's/^/  - /')"
[ -f "$LAB_DIR/requirements.txt" ] || die "No requirements.txt in $LAB_DIR"

# --------------------------------------------------------------- platform ----
OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM="macOS" ;;
  Linux)  PLATFORM="Linux" ;;
  *)      PLATFORM="$OS"; warn "Untested platform: $OS" ;;
esac
info "Platform: $PLATFORM"
info "Lab: $LAB"

# ----------------------------------------------------------------- python ----
find_python() {
  local candidate
  for candidate in python3.13 python3.12 python3.11 python3.10 python3 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info[:2] >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 1)" 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

PYTHON="$(find_python || true)"
if [ -z "$PYTHON" ]; then
  printf '%s\n' "Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ was not found on PATH." >&2
  if [ "$PLATFORM" = "macOS" ]; then
    printf '%s\n' "Install it with:  brew install python@3.12" >&2
  else
    printf '%s\n' "Install it with:  sudo apt update && sudo apt install -y python3 python3-venv python3-pip" >&2
  fi
  exit 1
fi
ok "Python: $PYTHON ($("$PYTHON" -c 'import platform; print(platform.python_version())'))"

# On Debian/Ubuntu the venv module ships separately from the interpreter.
if ! "$PYTHON" -c "import venv, ensurepip" >/dev/null 2>&1; then
  if [ "$PLATFORM" = "Linux" ]; then
    PY_MM="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    die "The venv module is missing. Install it with:
  sudo apt update && sudo apt install -y python${PY_MM}-venv"
  fi
  die "The venv module is unavailable for $PYTHON."
fi

# -------------------------------------------------------------------- venv ----
VENV_DIR="$LAB_DIR/.venv"
if [ "$FORCE" -eq 1 ] && [ -d "$VENV_DIR" ]; then
  info "Removing existing virtual environment"
  rm -rf "$VENV_DIR"
fi

if [ -x "$VENV_DIR/bin/python" ]; then
  ok "Reusing virtual environment: $VENV_DIR"
else
  info "Creating virtual environment: $VENV_DIR"
  "$PYTHON" -m venv "$VENV_DIR" || die "Failed to create the virtual environment."
  ok "Virtual environment created"
fi

VENV_PY="$VENV_DIR/bin/python"
[ -x "$VENV_PY" ] || die "Virtual environment looks broken (missing $VENV_PY). Re-run with --force."

# ---------------------------------------------------------------- install ----
info "Upgrading pip"
"$VENV_PY" -m pip install --quiet --upgrade pip setuptools wheel

info "Installing dependencies from $LAB/requirements.txt"
"$VENV_PY" -m pip install --requirement "$LAB_DIR/requirements.txt"
ok "Dependencies installed"

# ------------------------------------------------------------------- seed ----
SEED_SCRIPT="$LAB_DIR/seed_data.py"
if [ "$SEED" -eq 1 ] && [ -f "$SEED_SCRIPT" ]; then
  info "Seeding the product listing"
  SEED_ARGS=""
  [ "$RESET_DB" -eq 1 ] && SEED_ARGS="--reset"
  # Run from the lab directory so relative data/ paths resolve.
  ( cd "$LAB_DIR" && "$VENV_PY" seed_data.py $SEED_ARGS ) || die "Seeding failed."
  ok "Product listing seeded"
elif [ "$SEED" -eq 0 ]; then
  warn "Skipping data seeding (--no-seed)"
fi

# -------------------------------------------------------------------- env ----
if [ -f "$LAB_DIR/.env.example" ]; then
  if [ -f "$LAB_DIR/.env" ]; then
    ok ".env already exists (left unchanged)"
  else
    cp "$LAB_DIR/.env.example" "$LAB_DIR/.env"
    ok "Created .env from .env.example"
  fi
fi

# ------------------------------------------------------------------- done ----
printf '\n%sSetup complete.%s\n\n' "$GREEN$BOLD" "$RESET"
cat <<NEXT
Next steps:

  1. Activate the environment:
       cd $LAB_DIR
       source .venv/bin/activate

  2. Add your OpenRouter key to .env:
       OPENROUTER_API_KEY=sk-or-...

  3. Inspect the seeded product listing:
       python seed_data.py --list --category audio/earbuds --max-price 120

  4. Try the workflow without calling the model:
       python agentmart_ecosystem.py --dry-run "Find me wireless earbuds under \$120 with good battery life."

  5. Run it live:
       python agentmart_ecosystem.py "Find me wireless earbuds under \$120 with good battery life."

  Re-seed at any time with:  python seed_data.py --reset
  Deactivate with:           deactivate
NEXT
