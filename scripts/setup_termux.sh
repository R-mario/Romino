#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# ==============================================================================
# Aprovisionamiento de Termux en OnePlus 2 (LineageOS Android 7.0+, ARM64)
# Instala compilador, compila llama-server (CPU NEON), descarga Qwen2.5-0.5B Q4_0
# y prepara el entorno virtual Python del bot.
# ==============================================================================

REPO_DIR="${REPO_DIR:-$HOME/oneplus2-llm-bot}"
LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
MODELS_DIR="${MODELS_DIR:-$HOME/models}"
VENV_DIR="${VENV_DIR:-$HOME/.venv-bot}"
MODEL_FILE="$MODELS_DIR/qwen2.5-0.5b-instruct-q4_0.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_0.gguf"
BUILD_JOBS="${BUILD_JOBS:-4}"

echo "[1/5] Actualizando paquetes de Termux..."
pkg update -y
pkg upgrade -y
pkg install -y \
  git \
  cmake \
  clang \
  make \
  ninja \
  python \
  openssh \
  curl \
  wget \
  termux-services \
  termux-api

echo "[2/5] Clonando o actualizando llama.cpp..."
if [ -d "$LLAMA_DIR/.git" ]; then
  git -C "$LLAMA_DIR" pull --ff-only
else
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
fi

echo "[3/5] Compilando llama-server y llama-bench (CPU ARM64 NEON, sin Vulkan)..."
cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DLLAMA_CURL=OFF \
  -DGGML_VULKAN=OFF \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF

cmake --build "$LLAMA_DIR/build" --config Release -j"$BUILD_JOBS" \
  --target llama-server llama-bench

echo "[4/5] Descargando modelo Qwen2.5-0.5B-Instruct (Q4_0)..."
mkdir -p "$MODELS_DIR"
if [ ! -f "$MODEL_FILE" ]; then
  wget -c -O "$MODEL_FILE" "$MODEL_URL"
else
  echo "Modelo ya presente en $MODEL_FILE"
fi

echo "[5/5] Preparando entorno virtual Python en $VENV_DIR..."
if [ ! -d "$VENV_DIR" ]; then
  python -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  echo "Creado $REPO_DIR/.env desde .env.example. Edítalo con tu TELEGRAM_BOT_TOKEN."
fi

echo ""
echo "Aprovisionamiento completado."
echo "Siguiente paso recomendado:"
echo "  1. Probar benchmark: $LLAMA_DIR/build/bin/llama-bench -m $MODEL_FILE -t 4 -p 128 -n 64"
echo "  2. Editar token y grupos en: $REPO_DIR/.env"
echo "  3. Instalar servicios 24/7: bash $REPO_DIR/scripts/install_services.sh"
