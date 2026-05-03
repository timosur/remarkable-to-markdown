#!/usr/bin/env bash
# install.sh — one-shot installer for rm2md.
#
# Designed to be runnable straight from the network without cloning:
#
#   curl -fsSL https://raw.githubusercontent.com/timosur/remarkable-to-markdown/main/install.sh | bash
#
# Installs rm2md user-wide so you can run it from any directory:
#
#   $XDG_DATA_HOME/rm2md/bin/        bundled rmapi binary (downloaded)
#   $XDG_DATA_HOME/rm2md/venv/       managed virtualenv (only when pipx is missing)
#   $XDG_CONFIG_HOME/rm2md/config    central config file (key=value, .env-style)
#   ~/.local/bin/rm2md               entry point on PATH (or pipx-managed)
#
# Re-running upgrades the existing install in place.
#
# Environment overrides:
#   RM2MD_REF=main         git ref / tag to install (default: main)
#   PYTHON=python3.11      python interpreter to use (default: python3, must be 3.10+)

set -euo pipefail

# ---------- config ---------------------------------------------------------

REPO_SLUG="timosur/remarkable-to-markdown"
REPO_URL="https://github.com/${REPO_SLUG}.git"
RAW_BASE="https://raw.githubusercontent.com/${REPO_SLUG}"
REF="${RM2MD_REF:-main}"

PYTHON_BIN="${PYTHON:-python3}"

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
DATA_DIR="$XDG_DATA_HOME/rm2md"
CONFIG_DIR="$XDG_CONFIG_HOME/rm2md"
CONFIG_FILE="$CONFIG_DIR/config"
LOCAL_BIN="$HOME/.local/bin"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n'  "$*" >&2; }
err()  { printf '\033[1;31mxx\033[0m  %s\n'  "$*" >&2; }

# ---------- 1. prerequisites ----------------------------------------------

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  err "$PYTHON_BIN not found. Install Python 3.10+ and re-run."
  exit 1
fi

PY_VERSION="$("$PYTHON_BIN" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
  err "Python 3.10+ required (found $PY_VERSION). Set PYTHON=/path/to/python3.11 and re-run."
  exit 1
fi
log "Using Python $PY_VERSION ($("$PYTHON_BIN" -c 'import sys; print(sys.executable)'))"

if ! command -v curl >/dev/null 2>&1; then
  err "curl is required."
  exit 1
fi
if ! command -v git >/dev/null 2>&1; then
  err "git is required (used by pip to fetch the package from GitHub)."
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library("cairo") else 1)' 2>/dev/null; then
  warn "libcairo not detected. cairosvg will fail at runtime."
  case "$(uname -s)" in
    Darwin) warn "  -> brew install cairo" ;;
    Linux)  warn "  -> sudo apt install libcairo2  (or your distro's equivalent)" ;;
  esac
fi

# ---------- 2. rmapi binary -----------------------------------------------

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64)              RMAPI_NAME="rmapi-darwin-arm64" ;;
  Linux-aarch64|Linux-arm64) RMAPI_NAME="rmapi-linux-arm64"  ;;
  *)                         RMAPI_NAME="" ;;
esac

mkdir -p "$DATA_DIR/bin" "$CONFIG_DIR" "$LOCAL_BIN"

if [ -n "$RMAPI_NAME" ]; then
  RMAPI_DEST="$DATA_DIR/bin/$RMAPI_NAME"
  if [ -f "./bin/$RMAPI_NAME" ]; then
    log "Using local ./bin/$RMAPI_NAME"
    install -m 0755 "./bin/$RMAPI_NAME" "$RMAPI_DEST"
  else
    log "Downloading $RMAPI_NAME from $REF"
    curl -fsSL "$RAW_BASE/$REF/bin/$RMAPI_NAME" -o "$RMAPI_DEST.tmp"
    mv "$RMAPI_DEST.tmp" "$RMAPI_DEST"
    chmod 0755 "$RMAPI_DEST"
  fi
  log "Installed rmapi binary to $RMAPI_DEST"
else
  warn "No bundled rmapi binary for $(uname -s)-$(uname -m). Install rmapi onto your PATH."
fi

# ---------- 3. install rm2md ----------------------------------------------

PIP_TARGET="git+${REPO_URL}@${REF}"

if command -v pipx >/dev/null 2>&1; then
  log "Installing rm2md via pipx (--force upgrades existing)"
  pipx install --force --python "$PYTHON_BIN" "$PIP_TARGET" >/dev/null
  RM2MD_PATH="$(command -v rm2md || true)"
else
  warn "pipx not found. Falling back to managed venv at $DATA_DIR/venv."
  warn "  Tip: install pipx for cleaner upgrades (https://pipx.pypa.io)."
  VENV_DIR="$DATA_DIR/venv"
  if [ ! -d "$VENV_DIR" ]; then
    log "Creating virtualenv in $VENV_DIR/"
    "$PYTHON_BIN" -m venv "$VENV_DIR"
  fi
  log "Installing rm2md into $VENV_DIR/ from $PIP_TARGET"
  "$VENV_DIR/bin/pip" install --upgrade pip >/dev/null
  "$VENV_DIR/bin/pip" install --upgrade "$PIP_TARGET" >/dev/null

  ln -sfn "$VENV_DIR/bin/rm2md" "$LOCAL_BIN/rm2md"
  RM2MD_PATH="$LOCAL_BIN/rm2md"
  log "Symlinked $RM2MD_PATH -> $VENV_DIR/bin/rm2md"
fi

# ---------- 4. central config --------------------------------------------

if [ ! -f "$CONFIG_FILE" ]; then
  log "Creating central config at $CONFIG_FILE"
  cat > "$CONFIG_FILE" <<'EOF'
# rm2md central config — read by rm2md when MISTRAL_API_KEY is not in the
# environment and no ./.env is present in the working directory.
#
# Get a key at https://console.mistral.ai/api-keys
MISTRAL_API_KEY=
EOF
  chmod 600 "$CONFIG_FILE"
  warn "Edit $CONFIG_FILE and set MISTRAL_API_KEY."
else
  log "Existing config kept at $CONFIG_FILE"
fi

# ---------- 5. PATH hint --------------------------------------------------

case ":$PATH:" in
  *":$LOCAL_BIN:"*) ;;
  *) warn "$LOCAL_BIN is not on your PATH. Add this to your shell rc:"
     warn "  export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac

cat <<EOF

$(log "Setup complete.")

Installed:
  rm2md            ${RM2MD_PATH:-(check pipx list)}
  rmapi binary     $DATA_DIR/bin/
  central config   $CONFIG_FILE

Next steps:
  1. Edit $CONFIG_FILE and set MISTRAL_API_KEY
  2. rm2md login          # pair this machine with the reMarkable cloud
  3. rm2md ls             # browse your cloud
  4. rm2md pull "/Notes/Some Document"
EOF
