#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Arranca y verifica llama-server y telegram-bot en el OnePlus 6T vía ADB Wi-Fi.
# ==============================================================================

TARGET="${1:-192.168.1.57:5555}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ADB="$REPO_DIR/tools/platform-tools/adb"

"$ADB" connect "$TARGET" >/dev/null
"$ADB" -s "$TARGET" wait-for-device

echo "[1/3] Habilitando servicios y arrancando supervisor runsvdir en Termux..."
"$ADB" -s "$TARGET" shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -lc "
  export HOME=/data/data/com.termux/files/home
  export PREFIX=/data/data/com.termux/files/usr
  export PATH=\$PREFIX/bin:\$PATH
  export TMPDIR=\$PREFIX/tmp
  export SVDIR=\$PREFIX/var/service

  rm -f \"\$SVDIR/llama-server/down\" \"\$SVDIR/telegram-bot/down\"

  if ! pgrep -f \"runsvdir -P \$SVDIR\" >/dev/null 2>&1; then
    setsid runsvdir -P \"\$SVDIR\" >/dev/null 2>&1 </dev/null &
    sleep 3
  fi

  sv up llama-server || true
  sv up telegram-bot || true
  sleep 2
  sv status llama-server telegram-bot || true
"'

echo "[2/3] Esperando a que llama-server cargue Qwen2.5-0.5B y responda /health..."
"$ADB" -s "$TARGET" shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -lc "
  export HOME=/data/data/com.termux/files/home
  export PREFIX=/data/data/com.termux/files/usr
  export PATH=\$PREFIX/bin:\$PATH
  export SVDIR=\$PREFIX/var/service

  for i in \$(seq 1 25); do
    if curl -sf http://127.0.0.1:8080/health; then
      echo \"\"
      break
    fi
    sleep 2
  done

  echo \"--- Estado sv ---\"
  sv status llama-server telegram-bot
  echo \"--- Test rápido de inferencia local ---\"
  curl -sf http://127.0.0.1:8080/v1/chat/completions \
    -H \"Content-Type: application/json\" \
    -d '\''{\"messages\":[{\"role\":\"system\",\"content\":\"Responde en 1 frase corta en español.\"},{\"role\":\"user\",\"content\":\"Preséntate como Romino.\"}],\"max_tokens\":40,\"temperature\":0.7}'\''
  echo \"\"
  echo \"--- Logs de llama-server ---\"
  tail -n 10 \$HOME/logs/llama-server/current 2>/dev/null || true
  echo \"--- Logs de telegram-bot ---\"
  tail -n 20 \$HOME/logs/telegram-bot/current 2>/dev/null || true
"'

echo "[3/3] Verificación de binarios bark.cpp + ffmpeg + modelo Q4_0..."
"$ADB" -s "$TARGET" shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -lc "
  export HOME=/data/data/com.termux/files/home
  export PREFIX=/data/data/com.termux/files/usr
  export PATH=\$PREFIX/bin:\$PATH
  ls -lh \$HOME/bin/ \$HOME/models/
  which ffmpeg
"'
