#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Aprovisiona el OnePlus 6T por ADB sobre Wi-Fi (192.168.1.57:5555):
#   1. Conecta por ADB TCP/IP y verifica el dispositivo
#   2. Instala Termux, Termux:Boot y Termux:API (sin cortes USB)
#   3. Excluye las 3 apps de Doze y abre Termux hasta completar su bootstrap
#   4. Transfiere el proyecto (+ .env) y el modelo Qwen2.5-0.5B al home de Termux
#      usando run-as com.termux (pipe directo, compatible con SELinux Android 11)
# ==============================================================================

TARGET="${1:-192.168.1.57:5555}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ADB="$REPO_DIR/tools/platform-tools/adb"

echo "[1/5] Conectando por ADB Wi-Fi a $TARGET..."
"$ADB" connect "$TARGET"
"$ADB" -s "$TARGET" wait-for-device
"$ADB" devices -l

echo "[2/5] Instalando Termux, Termux:Boot y Termux:API por Wi-Fi..."
"$ADB" -s "$TARGET" install -r "$REPO_DIR/downloads/termux-app_v0.118.3+github-debug_arm64-v8a.apk"
"$ADB" -s "$TARGET" install -r "$REPO_DIR/downloads/termux-boot-app_v0.8.1+github.debug.apk"
"$ADB" -s "$TARGET" install -r "$REPO_DIR/downloads/termux-api-app_v0.53.0+github.debug.apk"

echo "[3/5] Excluyendo de optimización de batería (Doze) y lanzando Termux..."
"$ADB" -s "$TARGET" shell '
  dumpsys deviceidle whitelist +com.termux
  dumpsys deviceidle whitelist +com.termux.boot
  dumpsys deviceidle whitelist +com.termux.api
  am start -n com.termux/.app.TermuxActivity
'

echo "Esperando a que Termux descomprima su entorno base (/data/data/com.termux/files/usr/bin/bash)..."
READY=0
for i in $(seq 1 30); do
  if "$ADB" -s "$TARGET" shell 'run-as com.termux test -x /data/data/com.termux/files/usr/bin/bash' >/dev/null 2>&1; then
    READY=1
    break
  fi
  sleep 2
done

if [ "$READY" != "1" ]; then
  echo "ERROR: Termux no terminó de inicializar su bootstrap en 60s (asegúrate de tener la pantalla desbloqueada)." >&2
  exit 1
fi
echo "Termux bootstrap listo."

echo "[4/5] Transfiriendo código del proyecto y .env al home de Termux..."
tar -C "$REPO_DIR" \
  --exclude='.git' \
  --exclude='downloads' \
  --exclude='tools' \
  --exclude='__pycache__' \
  --exclude='.pytest_cache' \
  --exclude='.venv' \
  -cf - . \
  | "$ADB" -s "$TARGET" shell 'run-as com.termux sh -c "mkdir -p /data/data/com.termux/files/home/oneplus2-llm-bot && tar -xf - -C /data/data/com.termux/files/home/oneplus2-llm-bot && chmod 600 /data/data/com.termux/files/home/oneplus2-llm-bot/.env"'

echo "[5/5] Transfiriendo modelo Qwen2.5-0.5B-Instruct (Q4_0, 409 MB) a ~/models/..."
if [ -f "$REPO_DIR/downloads/qwen2.5-0.5b-instruct-q4_0.gguf" ]; then
  "$ADB" -s "$TARGET" push "$REPO_DIR/downloads/qwen2.5-0.5b-instruct-q4_0.gguf" /data/local/tmp/qwen-0.5b.gguf
  "$ADB" -s "$TARGET" shell '
    run-as com.termux sh -c "mkdir -p /data/data/com.termux/files/home/models"
    cat /data/local/tmp/qwen-0.5b.gguf | run-as com.termux sh -c "cat > /data/data/com.termux/files/home/models/qwen2.5-0.5b-instruct-q4_0.gguf"
    rm -f /data/local/tmp/qwen-0.5b.gguf
  '
fi

echo "Verificando archivos en Termux..."
"$ADB" -s "$TARGET" shell 'run-as com.termux ls -lh /data/data/com.termux/files/home/oneplus2-llm-bot /data/data/com.termux/files/home/models'
echo "Fase de transferencia completada."
