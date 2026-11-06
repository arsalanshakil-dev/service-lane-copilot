#!/usr/bin/env bash
# Installs and starts Service Lane Copilot on macOS and Linux (issue #67).
#
# Run it once to install; run it again any time to start the app. Finished steps are skipped.
#   1. Checks for Git, Python 3.11+, Node.js 20.9+ and Ollama; offers to install missing ones.
#   2. Downloads the project (or updates it with --update).
#   3. Creates the Python environment and installs the backend packages.
#   4. Asks for the Supabase URL and secret key and saves them only in backend/.env.
#   5. Pulls the local AI models (qwen3.5:4b and qwen3:1.7b).
#   6. Installs and builds the web app.
#   7. Starts the API and the web app in the background and opens the browser.
# Everything listens on this computer only (127.0.0.1).
#
# Usage:
#   bash install.sh                 install (first time) and start
#   bash install.sh --update        pull the latest code, rebuild, start
#   bash install.sh --stop          stop the app
#   bash install.sh --help          all options
set -euo pipefail

REPO_URL="https://github.com/arsalanshakil-dev/service-lane-copilot.git"
INSTALL_DIR="${HOME}/service-lane-copilot"
API_PORT=8000
WEB_PORT=3000
UPDATE=0; SMALL_MODEL_ONLY=0; NO_START=0; RESET_KEYS=0; STOP=0
NVM_VERSION="v0.40.3"

usage() {
  cat <<'EOF'
Usage: bash install.sh [options]
  --install-dir DIR    where to put the project (default: ~/service-lane-copilot)
  --update             pull the latest code and rebuild
  --small-model-only   pull only the smaller, faster model (qwen3:1.7b)
  --no-start           install and build, but do not start the servers
  --reset-keys         ask for the Supabase URL and key again
  --web-port PORT      web app port (default 3000)
  --stop               stop the running app
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --update) UPDATE=1; shift ;;
    --small-model-only) SMALL_MODEL_ONLY=1; shift ;;
    --no-start) NO_START=1; shift ;;
    --reset-keys) RESET_KEYS=1; shift ;;
    --web-port) WEB_PORT="$2"; shift 2 ;;
    --stop) STOP=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 2 ;;
  esac
done

if [ "$SMALL_MODEL_ONLY" = 1 ]; then MODELS=("qwen3:1.7b"); else MODELS=("qwen3.5:4b" "qwen3:1.7b"); fi

if [ -t 1 ]; then C=$'\033[36m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'; else C=; G=; Y=; R=; N=; fi
step() { printf '\n%s==> %s%s\n' "$C" "$1" "$N"; }
ok()   { printf '    %s%s%s\n' "$G" "$1" "$N"; }
note() { printf '    %s%s%s\n' "$Y" "$1" "$N"; }
fail() { printf '\n%sERROR: %s%s\n' "$R" "$1" "$N" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }
confirm() { local a; read -r -p "    $1 [Y/n] " a </dev/tty || a=n; [[ -z "$a" || "$a" =~ ^[Yy] ]]; }

# Version compare: ver_ge 3.12.1 3.11 -> true
ver_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -t. -k1,1n -k2,2n -k3,3n | head -n1)" = "$2" ]; }
ver_of() { grep -Eo '[0-9]+\.[0-9]+(\.[0-9]+)?' <<<"$1" | head -n1; }

url_ok() { curl -fsS -m 5 -o /dev/null "$1" 2>/dev/null; }
wait_url() {
  local url="$1" secs="$2" i=0
  while [ "$i" -lt "$secs" ]; do url_ok "$url" && return 0; sleep 2; i=$((i + 2)); done
  return 1
}
port_busy() {
  if have lsof; then lsof -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  elif have ss; then ss -ltn "sport = :$1" | grep -q LISTEN
  else return 1; fi
}

OS="$(uname -s)"
case "$OS" in
  Darwin) PLATFORM=mac ;;
  Linux) PLATFORM=linux ;;
  *) fail "This script supports macOS and Linux. On Windows use scripts/install-windows.ps1." ;;
esac

PKG=""
if [ "$PLATFORM" = linux ]; then
  for p in apt-get dnf pacman zypper; do have "$p" && { PKG="$p"; break; }; done
fi
SUDO=""; [ "$(id -u)" -ne 0 ] && have sudo && SUDO="sudo"

pkg_install() {  # pkg_install <description> <brew pkgs> <apt pkgs> <dnf pkgs> <pacman pkgs> <zypper pkgs>
  local what="$1"
  if [ "$PLATFORM" = mac ]; then
    have brew || fail "$what is missing. Install Homebrew from https://brew.sh (or install $what yourself), then run this script again."
    confirm "$what is missing. Install it now with Homebrew?" || fail "$what is required."
    # shellcheck disable=SC2086
    brew install $2
  else
    case "$PKG" in
      apt-get) confirm "$what is missing. Install it now with apt (needs sudo)?" || fail "$what is required."
               $SUDO apt-get update -qq; $SUDO apt-get install -y $3 ;;
      dnf)     confirm "$what is missing. Install it now with dnf (needs sudo)?" || fail "$what is required."
               $SUDO dnf install -y $4 ;;
      pacman)  confirm "$what is missing. Install it now with pacman (needs sudo)?" || fail "$what is required."
               $SUDO pacman -S --noconfirm $5 ;;
      zypper)  confirm "$what is missing. Install it now with zypper (needs sudo)?" || fail "$what is required."
               $SUDO zypper install -y $6 ;;
      *) fail "$what is missing and no supported package manager was found. Install it yourself, then run this script again." ;;
    esac
  fi
}

find_python() {
  local c v
  for c in python3.13 python3.12 python3.11 python3; do
    have "$c" || continue
    v="$(ver_of "$("$c" --version 2>&1)")"
    if [ -n "$v" ] && ver_ge "$v" 3.11; then echo "$c"; return 0; fi
  done
  return 1
}

load_nvm() { export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"; [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 || true; }
node_ok() { have node && ver_ge "$(ver_of "$(node --version)")" 20.9; }

project_root() {
  local here
  here="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || true)"
  if [ -n "$here" ] && [ -f "$here/backend/app/main.py" ]; then echo "$here"; return; fi
  echo "$INSTALL_DIR"
}

stop_app() {
  local root run pidfile pid
  root="$(project_root)"; run="$root/.run"
  for pidfile in "$run/web.pid" "$run/api.pid"; do
    [ -f "$pidfile" ] || continue
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; ok "Stopped process $pid"; fi
    rm -f "$pidfile"
  done
}

if [ "$STOP" = 1 ]; then step "Stopping Service Lane Copilot"; stop_app; exit 0; fi

echo "Service Lane Copilot installer ($PLATFORM)"
echo "Synthetic demo data only. Everything runs on this computer."

# ---------------------------------------------------------------- 1. prerequisites
step "Checking prerequisites"
have curl || pkg_install "curl" "curl" "curl" "curl" "curl" "curl"

have git || pkg_install "Git" "git" "git" "git" "git" "git"
ok "Git: $(git --version | sed 's/git version //')"

PY="$(find_python || true)"
if [ -z "$PY" ]; then
  pkg_install "Python 3.12" "python@3.12" "python3 python3-venv python3-pip" "python3 python3-pip" "python python-pip" "python312"
  PY="$(find_python || true)"
  [ -n "$PY" ] || fail "Python 3.11 or newer is still missing (your Linux release may ship an older one). Install Python 3.11+ (for example from https://www.python.org), then run this script again."
fi
if [ "$PLATFORM" = linux ] && ! "$PY" -c "import venv, ensurepip" >/dev/null 2>&1; then
  pv="$("$PY" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
  pkg_install "Python venv support" "" "python${pv}-venv" "python3-pip" "python" "python3-virtualenv"
fi
ok "Python: $("$PY" --version 2>&1)"

load_nvm
if ! node_ok; then
  if [ "$PLATFORM" = mac ]; then
    pkg_install "Node.js" "node" "" "" "" ""
  else
    note "Node.js 20.9 or newer is needed (Linux packages are often older)."
    confirm "Install Node.js 22 for your user with nvm ($NVM_VERSION)?" || fail "Node.js 20.9+ is required."
    curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/${NVM_VERSION}/install.sh" | PROFILE=/dev/null bash
    load_nvm
    nvm install 22 >/dev/null
    nvm use 22 >/dev/null
  fi
  node_ok || fail "Node.js 20.9 or newer was not found after installing. Open a new terminal and run this script again."
fi
ok "Node.js: $(node --version)"

if ! have ollama; then
  if [ "$PLATFORM" = mac ]; then
    pkg_install "Ollama" "ollama" "" "" "" ""
  else
    confirm "Ollama is missing. Install it now with the official installer from ollama.com (needs sudo)?" || fail "Ollama is required."
    curl -fsSL https://ollama.com/install.sh | sh
  fi
  have ollama || fail "Ollama was not found after installing. Open a new terminal and run this script again."
fi
ok "Ollama: installed"

# ---------------------------------------------------------------- 2. project files
step "Getting the project"
ROOT="$(project_root)"
if [ -f "$ROOT/backend/app/main.py" ]; then
  ok "Using the project in $ROOT"
else
  if [ -d "$ROOT" ] && [ -n "$(ls -A "$ROOT" 2>/dev/null)" ]; then
    fail "$ROOT exists and is not empty. Choose another folder with --install-dir."
  fi
  git clone --depth 1 "$REPO_URL" "$ROOT" || fail "Could not download the project from $REPO_URL."
  ok "Downloaded to $ROOT"
fi
if [ "$UPDATE" = 1 ]; then
  [ -d "$ROOT/.git" ] || fail "--update needs a Git checkout; $ROOT is not one."
  git -C "$ROOT" pull --ff-only || fail "Could not update the project. If you changed files in $ROOT, undo those changes and try again."
  ok "Updated to the latest version"
fi
BACKEND="$ROOT/backend"; FRONTEND="$ROOT/frontend"; RUN="$ROOT/.run"
mkdir -p "$RUN"

hash_of() { if have sha256sum; then sha256sum "$1" | cut -d' ' -f1; else shasum -a 256 "$1" | cut -d' ' -f1; fi; }

# ---------------------------------------------------------------- 3. backend
step "Setting up the Python API"
VENV_PY="$BACKEND/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then "$PY" -m venv "$BACKEND/.venv" || fail "Could not create the Python environment."; fi
REQ_HASH="$(hash_of "$BACKEND/requirements.txt")"
REQ_MARK="$BACKEND/.venv/.requirements-sha256"
if [ "$UPDATE" = 1 ] || [ ! -f "$REQ_MARK" ] || [ "$(cat "$REQ_MARK")" != "$REQ_HASH" ]; then
  "$VENV_PY" -m pip install --disable-pip-version-check --quiet --upgrade pip
  "$VENV_PY" -m pip install --disable-pip-version-check --quiet -r "$BACKEND/requirements.txt" \
    || fail "Installing the Python packages failed. Check your internet connection and run the script again."
  echo "$REQ_HASH" > "$REQ_MARK"
  ok "Python packages installed"
else
  ok "Python packages already installed"
fi

# ---------------------------------------------------------------- 4. database keys
step "Database connection"
ENV_FILE="$BACKEND/.env"
if [ "$RESET_KEYS" = 1 ] || [ ! -f "$ENV_FILE" ]; then
  echo "    The app reads its demo data from a Supabase database."
  echo "    Use the URL and secret key you were given privately. The key is saved only in backend/.env."
  URL=""; KEY=""
  until [[ "$URL" =~ ^https?://[^[:space:]]+$ ]]; do read -r -p "    Supabase URL (https://....supabase.co): " URL </dev/tty; done
  until [ -n "$KEY" ]; do read -r -s -p "    Supabase secret key (hidden): " KEY </dev/tty; echo; done
  ( umask 077
    { echo "# Written by scripts/install.sh. Keep this file private; never commit or share it."
      echo "SUPABASE_URL=$URL"
      echo "SUPABASE_SECRET_KEY=$KEY"
      echo "OLLAMA_TIMEOUT_SECONDS=600"; } > "$ENV_FILE" )
  KEY=""
  ok "Saved backend/.env (readable only by you)"
else
  ok "backend/.env already exists (use --reset-keys to enter new values)"
fi

# ---------------------------------------------------------------- 5. local AI
step "Local AI models (Ollama)"
if ! url_ok "http://127.0.0.1:11434/api/tags"; then
  if [ "$PLATFORM" = mac ] && [ -d "/Applications/Ollama.app" ]; then open -a Ollama
  else nohup ollama serve > "$RUN/ollama.log" 2>&1 & fi
  wait_url "http://127.0.0.1:11434/api/tags" 60 || fail "Ollama did not start. Start Ollama yourself (ollama serve), then run this script again."
fi
INSTALLED="$(ollama list 2>/dev/null | awk 'NR>1 {print $1}')"
for model in "${MODELS[@]}"; do
  if grep -qx "$model" <<<"$INSTALLED"; then ok "$model already installed"; continue; fi
  note "Downloading $model (a few GB; this can take a while)..."
  ollama pull "$model" || fail "Could not download $model. Check your internet connection and run the script again."
  ok "$model installed"
done

# ---------------------------------------------------------------- 6. web app
step "Setting up the web app"
LOCK_HASH="$(hash_of "$FRONTEND/package-lock.json")"
NPM_MARK="$FRONTEND/node_modules/.package-lock-sha256"
if [ ! -f "$NPM_MARK" ] || [ "$(cat "$NPM_MARK")" != "$LOCK_HASH" ]; then
  (cd "$FRONTEND" && npm ci --no-audit --no-fund) || fail "Installing the web app packages failed."
  echo "$LOCK_HASH" > "$NPM_MARK"
  ok "Web packages installed"
else
  ok "Web packages already installed"
fi
HEAD="no-git"; [ -d "$ROOT/.git" ] && HEAD="$(git -C "$ROOT" rev-parse HEAD)"
BUILD_MARK="$FRONTEND/.next/.built-from"
if [ ! -f "$FRONTEND/.next/BUILD_ID" ] || [ ! -f "$BUILD_MARK" ] || [ "$(cat "$BUILD_MARK")" != "$HEAD" ]; then
  note "Building the web app (one or two minutes)..."
  (cd "$FRONTEND" && npm run build) || fail "Building the web app failed."
  echo "$HEAD" > "$BUILD_MARK"
  ok "Web app built"
else
  ok "Web app already built"
fi

if [ "$NO_START" = 1 ]; then step "Installed. Run this script again to start the app."; exit 0; fi

# ---------------------------------------------------------------- 7. start
step "Starting the app"
if ! url_ok "http://127.0.0.1:$API_PORT/api/health"; then
  port_busy "$API_PORT" && fail "Port $API_PORT is used by another program. Stop it, then run this script again."
  (cd "$BACKEND" || exit 1; nohup "$VENV_PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$API_PORT" > "$RUN/api.log" 2>&1 & echo $! > "$RUN/api.pid")
fi
wait_url "http://127.0.0.1:$API_PORT/api/health" 120 \
  || fail "The API did not start. See $RUN/api.log. Most often the Supabase URL or key is wrong: run with --reset-keys."
COUNT="$(curl -fsS "http://127.0.0.1:$API_PORT/api/health" | grep -Eo '"record_count": *[0-9]+' | grep -Eo '[0-9]+$' || echo "?")"
ok "API running: $COUNT vehicle records in the database"

WEB_URL="http://127.0.0.1:$WEB_PORT"
if ! url_ok "$WEB_URL"; then
  port_busy "$WEB_PORT" && fail "Port $WEB_PORT is used by another program. Run with --web-port 3001."
  (cd "$FRONTEND" || exit 1; nohup node node_modules/next/dist/bin/next start -H 127.0.0.1 -p "$WEB_PORT" > "$RUN/web.log" 2>&1 & echo $! > "$RUN/web.pid")
fi
wait_url "$WEB_URL" 90 || fail "The web app did not start. See $RUN/web.log."
ok "Web app running at $WEB_URL"

if [ "$PLATFORM" = mac ]; then open "$WEB_URL"; elif have xdg-open; then xdg-open "$WEB_URL" >/dev/null 2>&1 || true; fi
echo
printf '%sService Lane Copilot is running at %s%s\n' "$G" "$WEB_URL" "$N"
echo "  - Stop it with:   bash \"$ROOT/scripts/install.sh\" --stop"
echo "  - Start it later: run this script again (it skips the install steps)."
echo "  - Logs:           $RUN/api.log and $RUN/web.log"
echo "  - The first AI answer can take 1-3 minutes while the model loads."
echo "  - The demo guide is in $ROOT/docs/guide/TESTER_GUIDE.md"
