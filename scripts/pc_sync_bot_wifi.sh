#!/usr/bin/env bash
set -euo pipefail

# Sincroniza bot/ (sin tocar .env ni estado) y reinicia telegram-bot en el OnePlus 6T por ADB Wi-Fi.
TARGET="${1:-192.168.1.57:5555}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ADB="$REPO_DIR/tools/platform-tools/adb"

"$ADB" connect "$TARGET" >/dev/null
"$ADB" -s "$TARGET" wait-for-device

tar -C "$REPO_DIR" --exclude='__pycache__' -cf - bot \
  | "$ADB" -s "$TARGET" shell 'run-as com.termux sh -c "tar -xf - -C /data/data/com.termux/files/home/oneplus2-llm-bot"'

"$ADB" -s "$TARGET" shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -lc "
  export HOME=/data/data/com.termux/files/home
  export PREFIX=/data/data/com.termux/files/usr
  export PATH=\$PREFIX/bin:\$PATH
  export SVDIR=\$PREFIX/var/service
  sv restart telegram-bot
  sleep 3
  sv status llama-server telegram-bot
  tail -n 10 \$HOME/logs/telegram-bot/current 2>/dev/null || true
"'
