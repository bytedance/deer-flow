#!/bin/bash
# =============================================================================
# echart-skill Installer (macOS / Linux)
# =============================================================================
# Installs echart-skill Python dependencies. Online PyPI installation is the
# default; local wheels are only for separately distributed offline archives.
#
# Usage:
#   bash scripts/install.sh              # full install (core + optional)
#   bash scripts/install.sh --core-only  # core dependencies only
#   bash scripts/install.sh --offline    # force separately supplied wheels/
# =============================================================================

set -euo pipefail

# --- helpers ---------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { printf "${CYAN}ℹ${NC}  %s\n" "$*"; }
ok()    { printf "${GREEN}✅${NC} %s\n" "$*"; }
warn()  { printf "${YELLOW}⚠${NC}  %s\n" "$*"; }
err()   { printf "${RED}❌${NC} %s\n" "$*"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
WHEELS_DIR="$ROOT_DIR/wheels"
CORE_REQ="$ROOT_DIR/requirements-core.txt"
FULL_REQ="$ROOT_DIR/requirements.txt"

CORE_ONLY=false
FORCE_OFFLINE=false

for arg in "$@"; do
    case "$arg" in
        --core-only) CORE_ONLY=true ;;
        --offline)   FORCE_OFFLINE=true ;;
        --help|-h)
            echo "Usage: bash scripts/install.sh [--core-only] [--offline]"
            echo ""
            echo "Options:"
            echo "  --core-only   Install only core dependencies (duckdb, pandas, …)"
            echo "  --offline     Force offline mode (requires wheels/ directory)"
            exit 0
            ;;
        *) err "Unknown option: $arg"; exit 1 ;;
    esac
done

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║          echart-skill  Dependency Installer              ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# --- check Python ----------------------------------------------------------
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null || true)
        if [[ "$ver" == "(3, 10)" || "$ver" == "(3, 11)" || "$ver" == "(3, 12)" || "$ver" == "(3, 13)" ]]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    err "Python 3.10+ is required but was not found."
    echo "   Install it from https://www.python.org/downloads/"
    exit 1
fi

PY_VER=$("$PYTHON" --version 2>&1)
info "Using $PY_VER ($PYTHON)"

# --- detect install mode ---------------------------------------------------
OFFLINE_MODE=false
if $FORCE_OFFLINE; then
    OFFLINE_MODE=true
elif [[ -d "$WHEELS_DIR" ]] && ls "$WHEELS_DIR"/*.whl &>/dev/null; then
    OFFLINE_MODE=true
fi

if $OFFLINE_MODE; then
    ok "Offline mode — installing from pre-downloaded wheels"
else
    info "Online mode — installing from PyPI"
    warn "Offline wheels are not bundled in the skill package."
fi

REQ_FILE="$FULL_REQ"
if $CORE_ONLY; then
    REQ_FILE="$CORE_REQ"
    info "Installing CORE dependencies only"
else
    info "Installing FULL dependencies (core + optional)"
fi

# --- detect platform for wheel filtering -----------------------------------
PLATFORM_TAG=""
case "$(uname -s)" in
    Darwin)
        ARCH=$(uname -m)
        if [[ "$ARCH" == "arm64" ]]; then
            PLATFORM_TAG="macosx.*arm64"
        else
            PLATFORM_TAG="macosx.*x86_64"
        fi
        ;;
    Linux)
        PLATFORM_TAG="manylinux.*x86_64"
        ;;
    *)
        warn "Unknown platform; will try to install without platform filter"
        ;;
esac

# --- install ---------------------------------------------------------------
echo ""
info "Installing dependencies …"
echo ""

if $OFFLINE_MODE; then
    # Offline: use local wheels only
    set +e
    "$PYTHON" -m pip install \
        --no-index \
        --find-links="$WHEELS_DIR" \
        -r "$REQ_FILE" \
        --quiet
    PIP_EXIT=$?
    set -e

    if [[ $PIP_EXIT -ne 0 ]]; then
        err "Offline install failed (exit code $PIP_EXIT)"
        echo ""
        warn "Try online mode:  bash scripts/install.sh"
        exit $PIP_EXIT
    fi
else
    # Online: standard pip install from PyPI
    "$PYTHON" -m pip install -r "$REQ_FILE"
fi

ok "Dependencies installed successfully."

# --- summary ---------------------------------------------------------------
echo ""
echo "────────────────────────────────────────────"
echo "  echart-skill installation complete ✨"
echo "────────────────────────────────────────────"
echo ""

# Show installed versions
"$PYTHON" -c "
import importlib.metadata as m
for pkg in ['duckdb','pandas','openpyxl','pydantic','structlog']:
    try:
        v = m.version(pkg)
        print(f'  {pkg:15s} {v}')
    except Exception:
        pass
" 2>/dev/null || true

echo ""
echo "  📊 Run your agent and type /help to get started!"
echo ""
