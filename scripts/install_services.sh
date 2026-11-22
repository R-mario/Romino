#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# ==============================================================================
# Instala servicios supervisados runit (termux-services) y autoarranque Termux:Boot
# para llama-server y telegram-bot en OnePlus 2.
# ==============================================================================

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
REPO_DIR="${REPO_DIR:-$HOME/oneplus2-llm-bot}"
LLAMA_BIN="${LLAMA_BIN:-$HOME/bin/llama-server}"
MODEL_FILE="${MODEL_FILE:-$HOME/models/qwen2.5-0.5b-instruct-q4_0.gguf}"
VENV_PYTHON="${VENV_PYTHON:-$HOME/.venv-bot/bin/python}"
SV_DIR="$PREFIX/var/service"
BOOT_DIR="$HOME/.termux/boot"

if [ ! -x "$LLAMA_BIN" ]; then
  echo "Error: No se encuentra $LLAMA_BIN. Ejecuta primero scripts/setup_termux.sh" >&2
  exit 1
fi

if [ ! -f "$MODEL_FILE" ]; then
  echo "Error: No se encuentra el modelo $MODEL_FILE." >&2
  exit 1
fi

echo "[1/3] Configurando servicio runit: llama-server..."
mkdir -p "$SV_DIR/llama-server/log"
cat > "$SV_DIR/llama-server/run" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
export TZ=Europe/Madrid
exec 2>&1
exec "$LLAMA_BIN" \\
  -m "$MODEL_FILE" \\
  --host 127.0.0.1 \\
  --port 8080 \\
  -t 4 \\
  --threads-batch 8 \\
  -c 1024 \\
  --batch-size 256 \\
  --parallel 1 \\
  --no-webui
EOF
chmod +x "$SV_DIR/llama-server/run"

cat > "$SV_DIR/llama-server/log/run" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
mkdir -p "$HOME/logs/llama-server"
exec svlogd -tt "$HOME/logs/llama-server"
EOF
chmod +x "$SV_DIR/llama-server/log/run"

echo "[2/3] Configurando servicio runit: telegram-bot..."
mkdir -p "$SV_DIR/telegram-bot/log"
cat > "$SV_DIR/telegram-bot/run" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
export TZ=Europe/Madrid
exec 2>&1
cd "$REPO_DIR" || exit 1
# Esperar a que llama-server responda antes de lanzar el bot
i=0
while [ "\$i" -lt 30 ]; do
  if curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
  i=\$((i + 1))
done
exec "$VENV_PYTHON" -m bot.main
EOF
chmod +x "$SV_DIR/telegram-bot/run"

cat > "$SV_DIR/telegram-bot/log/run" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
mkdir -p "$HOME/logs/telegram-bot"
exec svlogd "$HOME/logs/telegram-bot"
EOF
chmod +x "$SV_DIR/telegram-bot/log/run"

echo "[3/3] Configurando autoarranque con Termux:Boot..."
mkdir -p "$BOOT_DIR"
cat > "$BOOT_DIR/start-oneplus2-bot.sh" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
sshd
sv-enable llama-server
sv-enable telegram-bot
EOF
chmod +x "$BOOT_DIR/start-oneplus2-bot.sh"

echo ""
echo "Servicios instalados. Para activarlos:"
echo "  1. Cierra y vuelve a abrir Termux (requisito de termux-services la primera vez)."
echo "  2. Ejecuta:"
echo "     termux-wake-lock"
echo "     sv-enable llama-server && sv up llama-server"
echo "     sv-enable telegram-bot && sv up telegram-bot"
echo "  3. Consulta estado: sv status llama-server telegram-bot"
echo "  4. Consulta logs:   tail -f ~/logs/telegram-bot/current"
