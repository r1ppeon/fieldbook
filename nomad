#!/bin/bash
# NOMAD for Mac — control everything from one command.
#   ./nomad start | stop | status | library | doctor | logs
set -e
cd "$(dirname "$0")"
source ./config.sh
mkdir -p run/logs

BOLD=$(tput bold 2>/dev/null || true); RESET=$(tput sgr0 2>/dev/null || true)
GREEN=$'\033[32m'; RED=$'\033[31m'; YELLOW=$'\033[33m'

up() { curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:$1/"; }

alive() { [ -f "run/$1.pid" ] && kill -0 "$(cat "run/$1.pid")" 2>/dev/null; }

zim_files() { ls "$LIBRARY_DIR"/zim/*.zim 2>/dev/null; }

start_ollama() {
  if ! pgrep -x ollama >/dev/null; then
    nohup "$OLLAMA_BIN" serve > run/logs/ollama.log 2>&1 &
    echo $! > run/ollama.pid
    sleep 2
  fi
}

start_kiwix() {
  alive kiwix && kill "$(cat run/kiwix.pid)" 2>/dev/null && sleep 1 || true
  if [ -n "$(zim_files)" ]; then
    nohup bin/kiwix-serve --address 127.0.0.1 --port "$KIWIX_PORT" \
      "$LIBRARY_DIR"/zim/*.zim > run/logs/kiwix.log 2>&1 &
    echo $! > run/kiwix.pid
  else
    echo "${YELLOW}No knowledge packs downloaded yet — run ./nomad library${RESET}"
  fi
}

start_app() {
  alive app && kill "$(cat run/app.pid)" 2>/dev/null && sleep 1 || true
  nohup ./.venv/bin/python -m uvicorn server.app:app \
    --host 127.0.0.1 --port "$APP_PORT" > run/logs/app.log 2>&1 &
  echo $! > run/app.pid
}

cmd_start() {
  [ -d .venv ] || { echo "Run ./setup.sh first."; exit 1; }
  if [[ "$LIBRARY_DIR" == /Volumes/* ]] && [ ! -d "$LIBRARY_DIR" ]; then
    echo "${RED}Your library drive isn't plugged in (expected at $LIBRARY_DIR).${RESET}"
    echo "Plug it in and try again."
    exit 1
  fi
  echo "Starting NOMAD..."
  start_ollama
  start_kiwix
  start_app
  for _ in $(seq 1 20); do up "$APP_PORT" && break; sleep 0.5; done
  echo
  echo "${BOLD}NOMAD is running.${RESET}"
  echo "  Dashboard + AI chat:  http://localhost:$APP_PORT"
  echo "  Browse raw library:   http://localhost:$KIWIX_PORT"
  open "http://localhost:$APP_PORT" 2>/dev/null || true
}

cmd_stop() {
  for svc in app kiwix ollama; do
    if alive "$svc"; then kill "$(cat "run/$svc.pid")" 2>/dev/null && echo "Stopped $svc"; fi
    rm -f "run/$svc.pid"
  done
}

check() {  # check <label> <ok?> <fix hint>
  if [ "$2" = 0 ]; then echo "  ${GREEN}✓${RESET} $1"; else echo "  ${RED}✗${RESET} $1  ${YELLOW}($3)${RESET}"; FAILED=1; fi
}

cmd_status() {
  echo "${BOLD}NOMAD status${RESET}"
  up "$APP_PORT";   check "Dashboard & chat (port $APP_PORT)" $? "./nomad start"
  up "$KIWIX_PORT"; check "Library server (port $KIWIX_PORT)" $? "./nomad start (and download packs)"
  curl -sf -o /dev/null --max-time 2 "http://127.0.0.1:11434/"; check "AI engine (Ollama)" $? "./nomad start"
  echo
  echo "  Library: $LIBRARY_DIR"
  local n=0 sz=""
  n=$(zim_files | wc -l | tr -d ' ')
  if [ "$n" -gt 0 ]; then
    sz=$(du -shc "$LIBRARY_DIR"/zim/*.zim 2>/dev/null | tail -1 | awk '{print $1}')
    echo "  Packs:   $n installed ($sz)"
  else
    echo "  Packs:   none yet — run ./nomad library"
  fi
  echo "  AI model: $NOMAD_MODEL"
}

cmd_doctor() {
  echo "${BOLD}NOMAD doctor — can this Mac answer questions with no internet?${RESET}"
  FAILED=0
  [ -x bin/kiwix-serve ]; check "Kiwix server installed" $? "./setup.sh"
  [ -d .venv ]; check "Python environment" $? "./setup.sh"
  [ -x "$OLLAMA_BIN" ]; check "Ollama installed" $? "./setup.sh"
  "$OLLAMA_BIN" list 2>/dev/null | grep -q "${NOMAD_MODEL%%:*}"; check "AI model downloaded ($NOMAD_MODEL)" $? "./setup.sh"
  [ -n "$(zim_files)" ]; check "Knowledge packs present" $? "./nomad library"
  up "$APP_PORT"; check "Services running" $? "./nomad start"
  if up "$APP_PORT"; then
    echo "  ... asking the AI a test question (may take ~30s)"
    ANSWER=$(curl -sf --max-time 120 -X POST "http://127.0.0.1:$APP_PORT/api/chat" \
      -H 'Content-Type: application/json' \
      -d '{"messages":[{"role":"user","content":"In one sentence: how can someone make water safe to drink?"}]}' | tr -d '\n')
    echo "$ANSWER" | grep -qiE 'boil|filter|purif|disinfect|chlor|water'; check "AI answered a survival question" $? "see run/logs/app.log"
  fi
  echo
  if [ "$FAILED" = 0 ]; then
    echo "${GREEN}${BOLD}All good. This Mac is disaster-ready — no internet needed.${RESET}"
  else
    echo "${RED}Some checks failed — fixes are shown next to each ✗ above.${RESET}"
  fi
}

case "${1:-}" in
  start)   cmd_start ;;
  stop)    cmd_stop ;;
  status)  cmd_status ;;
  library) NOMAD_DIR="$NOMAD_DIR" LIBRARY_DIR="$LIBRARY_DIR" python3 scripts/library.py; start_kiwix 2>/dev/null || true ;;
  doctor)  cmd_doctor ;;
  logs)    tail -n 40 run/logs/*.log ;;
  *) echo "Usage: ./nomad {start|stop|status|library|doctor|logs}"; exit 1 ;;
esac
