#!/bin/bash
# NOMAD for Mac — one-command setup.
# Installs: Homebrew (if missing), Python, Ollama, the Kiwix server, and a
# local AI model sized to this Mac's memory. Internet required for setup only.
set -e
cd "$(dirname "$0")"
source ./config.sh

KIWIX_TOOLS_VERSION="3.8.2"
BOLD=$(tput bold 2>/dev/null || true); RESET=$(tput sgr0 2>/dev/null || true)

step() { echo; echo "${BOLD}==> $1${RESET}"; }

[ "$(uname)" = "Darwin" ] || { echo "This setup is for macOS."; exit 1; }
ARCH=$(uname -m)   # arm64 (Apple Silicon) or x86_64 (Intel)

step "Checking Homebrew"
if ! command -v brew >/dev/null; then
  echo "Homebrew (the Mac package manager) isn't installed. Installing it now..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  [ "$ARCH" = "arm64" ] && eval "$(/opt/homebrew/bin/brew shellenv)" || eval "$(/usr/local/bin/brew shellenv)"
fi
echo "Homebrew OK: $(brew --version | head -1)"

step "Installing Ollama (runs the local AI) and Python"
brew list ollama >/dev/null 2>&1 || brew install ollama
brew list python@3.12 >/dev/null 2>&1 || brew install python@3.12
PYTHON="$(brew --prefix python@3.12)/bin/python3.12"

step "Installing the Kiwix server (serves the offline library)"
if [ ! -x bin/kiwix-serve ]; then
  mkdir -p bin
  TARBALL="kiwix-tools_macos-${ARCH}-${KIWIX_TOOLS_VERSION}.tar.gz"
  URL="https://download.kiwix.org/release/kiwix-tools/${TARBALL}"
  echo "Downloading ${URL}"
  curl -fL --retry 3 -o "bin/${TARBALL}" "$URL"
  curl -fsL -o "bin/${TARBALL}.md5" "${URL}.md5"
  (cd bin && md5 -q "$TARBALL" | grep -qf <(awk '{print $1}' "$TARBALL.md5")) \
    || { echo "Checksum mismatch on the Kiwix download — try again."; exit 1; }
  tar -xzf "bin/${TARBALL}" -C bin --strip-components 1
  rm -f "bin/${TARBALL}" "bin/${TARBALL}.md5"
fi
echo "kiwix-serve OK: $(bin/kiwix-serve --version | head -1)"

step "Setting up the chat server (Python environment)"
[ -d .venv ] || "$PYTHON" -m venv .venv
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r server/requirements.txt
echo "Python environment OK"

step "Choosing an AI model for this Mac"
MEM_GB=$(( $(sysctl -n hw.memsize) / 1073741824 ))
if   [ "$MEM_GB" -lt 10 ]; then MODEL="qwen3:4b"
elif [ "$MEM_GB" -lt 20 ]; then MODEL="qwen3:8b"
elif [ "$MEM_GB" -lt 40 ]; then MODEL="qwen3:14b"
else                            MODEL="qwen3:30b"
fi
echo "This Mac has ${MEM_GB} GB of memory -> using ${BOLD}${MODEL}${RESET}"
grep -q '^NOMAD_MODEL=' config.local.sh 2>/dev/null || echo "NOMAD_MODEL=\"$MODEL\"" >> config.local.sh
source ./config.sh   # pick up any existing override

step "Downloading the AI model (${NOMAD_MODEL}) — a few GB, one time only"
if ! pgrep -x ollama >/dev/null; then
  nohup ollama serve > run/logs/ollama.log 2>&1 &
  sleep 3
fi
ollama pull "$NOMAD_MODEL"

echo
echo "${BOLD}Setup complete!${RESET} Next steps:"
echo "  1. ./nomad library   — choose and download your knowledge packs"
echo "  2. ./nomad start     — start NOMAD and open the dashboard"
