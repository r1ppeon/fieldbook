#!/bin/bash
# NOMAD for Mac — one-command setup. No admin password, no Homebrew needed.
# Installs into this folder: the Kiwix library server, Ollama (local AI),
# a private Python environment, and an AI model sized to this Mac's memory.
# Internet is required for setup only.
set -e
cd "$(dirname "$0")"
mkdir -p bin run/logs
source ./config.sh

KIWIX_TOOLS_VERSION="3.8.2"
BOLD=$(tput bold 2>/dev/null || true); RESET=$(tput sgr0 2>/dev/null || true)
step() { echo; echo "${BOLD}==> $1${RESET}"; }

[ "$(uname)" = "Darwin" ] || { echo "This setup is for macOS."; exit 1; }
ARCH=$(uname -m)   # arm64 (Apple Silicon) or x86_64 (Intel)

step "Installing the Kiwix server (serves the offline library)"
if [ ! -x bin/kiwix-serve ]; then
  TARBALL="kiwix-tools_macos-${ARCH}-${KIWIX_TOOLS_VERSION}.tar.gz"
  URL="https://download.kiwix.org/release/kiwix-tools/${TARBALL}"
  curl -fL --retry 3 -o "bin/${TARBALL}" "$URL"
  curl -fsL -o "bin/${TARBALL}.md5" "${URL}.md5"
  (cd bin && md5 -q "$TARBALL" | grep -qf <(awk '{print $1}' "$TARBALL.md5")) \
    || { echo "Checksum mismatch on the Kiwix download — run setup again."; exit 1; }
  tar -xzf "bin/${TARBALL}" -C bin --strip-components 1
  rm -f "bin/${TARBALL}" "bin/${TARBALL}.md5"
fi
echo "kiwix-serve OK: $(bin/kiwix-serve --version | head -1)"

step "Installing Ollama (runs the local AI)"
if command -v ollama >/dev/null; then
  echo "Ollama already installed: $(command -v ollama)"
elif [ -x bin/ollama ]; then
  echo "Ollama OK (bin/ollama)"
else
  curl -fL --retry 3 -o bin/ollama-darwin.tgz \
    "https://github.com/ollama/ollama/releases/latest/download/ollama-darwin.tgz"
  tar -xzf bin/ollama-darwin.tgz -C bin
  rm -f bin/ollama-darwin.tgz
  echo "Ollama OK (bin/ollama)"
fi
source ./config.sh   # re-resolve OLLAMA_BIN now that it exists

step "Setting up the chat server (private Python environment)"
# Find a modern Python; otherwise fetch one with uv (no admin needed).
PYTHON=""
for cand in python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$cand" >/dev/null && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null; then
    PYTHON="$cand"; break
  fi
done
if [ ! -d .venv ]; then
  if [ -n "$PYTHON" ]; then
    "$PYTHON" -m venv .venv
  else
    echo "No modern Python found — fetching a private one (this is normal)."
    [ -x bin/uv ] || curl -LsSf https://astral.sh/uv/install.sh | UV_INSTALL_DIR="$PWD/bin" UV_NO_MODIFY_PATH=1 sh
    bin/uv venv --seed --python 3.12 .venv
  fi
fi
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r server/requirements.txt
echo "Python environment OK: $(./.venv/bin/python --version)"

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

step "Downloading the AI model (${NOMAD_MODEL}) — several GB, one time only"
if ! pgrep -x ollama >/dev/null; then
  nohup "$OLLAMA_BIN" serve > run/logs/ollama.log 2>&1 &
  sleep 3
fi
"$OLLAMA_BIN" pull "$NOMAD_MODEL"

echo
echo "${BOLD}Setup complete!${RESET} Next steps:"
echo "  1. ./nomad library   — choose and download your knowledge packs"
echo "  2. ./nomad start     — start NOMAD and open the dashboard"
