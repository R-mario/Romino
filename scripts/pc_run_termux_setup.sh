#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Ejecuta setup_termux.sh (compilación llama.cpp + bark.cpp + venv Python +
# cuantización bark-small Q4_0), ejecuta llama-bench e instala/arranca los
# servicios 24/7 en el OnePlus 6T a través de ADB Wi-Fi (run-as com.termux).
# ==============================================================================

TARGET="${1:-192.168.1.57:5555}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ADB="$REPO_DIR/tools/platform-tools/adb"

echo "[1/4] Verificando conexión ADB Wi-Fi con $TARGET y sincronizando scripts..."
"$ADB" connect "$TARGET" >/dev/null
"$ADB" -s "$TARGET" wait-for-device

tar -C "$REPO_DIR" --exclude='.git' --exclude='downloads' --exclude='tools' \
  --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.venv' -cf - scripts bot requirements.txt \
  | "$ADB" -s "$TARGET" shell 'run-as com.termux sh -c "tar -xf - -C /data/data/com.termux/files/home/oneplus2-llm-bot"'

echo "[2/4] Ejecutando scripts/setup_termux.sh dentro de Termux (puede tardar 5-10 min)..."
"$ADB" -s "$TARGET" shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -lc "
  export HOME=/data/data/com.termux/files/home
  export PREFIX=/data/data/com.termux/files/usr
  export PATH=\$PREFIX/bin:\$PATH
  export TMPDIR=\$PREFIX/tmp
  if [ -f \$PREFIX/lib/libtermux-exec-ld-preload.so ]; then
    export LD_PRELOAD=\$PREFIX/lib/libtermux-exec-ld-preload.so
  elif [ -f \$PREFIX/lib/libtermux-exec.so ]; then
    export LD_PRELOAD=\$PREFIX/lib/libtermux-exec.so
  fi
  mkdir -p \$TMPDIR
  bash \$HOME/oneplus2-llm-bot/scripts/setup_termux.sh
"'

echo "[3/4] Ejecutando benchmark llama-bench en Snapdragon 845..."
"$ADB" -s "$TARGET" shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -lc "
  export HOME=/data/data/com.termux/files/home
  export PREFIX=/data/data/com.termux/files/usr
  export PATH=\$PREFIX/bin:\$PATH
  \$HOME/bin/llama-bench -m \$HOME/models/qwen2.5-0.5b-instruct-q4_0.gguf -t 4 -p 128 -n 64
"'

echo "[4/4] Instalando y arrancando servicios supervisados (llama-server + telegram-bot)..."
"$ADB" -s "$TARGET" shell 'run-as com.termux /data/data/com.termux/files/usr/bin/bash -lc "
  export HOME=/data/data/com.termux/files/home
  export PREFIX=/data/data/com.termux/files/usr
  export PATH=\$PREFIX/bin:\$PATH
  export TMPDIR=\$PREFIX/tmp
  export SVDIR=\$PREFIX/var/service
  bash \$HOME/oneplus2-llm-bot/scripts/install_services.sh
  termux-wake-lock || true
  if ! pgrep -f runsvdir >/dev/null 2>&1; then
    nohup runsvdir -P \"\$SVDIR\" >/dev/null 2>&1 </dev/null &
    sleep 2
  fi
  sv-enable llama-server || true
  sv-enable telegram-bot || true
  sv up llama-server || true
  sv up telegram-bot || true
  echo \"Esperando a llama-server /health...\"
  for i in \$(seq 1 20); do
    if curl -sf http://127.0.0.1:8080/health; then
      echo \"\"
      break
    fi
    sleep 2
  done
  sv status llama-server telegram-bot || true
  echo \"--- Últimas líneas de telegram-bot ---\"
  tail -n 15 \$HOME/logs/telegram-bot/current 2>/dev/null || true
"'
