#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# ==============================================================================
# Aprovisionamiento de Termux en OnePlus 2 (LineageOS Android 7.0+, ARM64)
# Instala compilador, compila llama-server (CPU NEON), descarga Qwen2.5-0.5B Q4_0
# y prepara el entorno virtual Python del bot.
# ==============================================================================

REPO_DIR="${REPO_DIR:-$HOME/oneplus2-llm-bot}"
LLAMA_DIR="${LLAMA_DIR:-$HOME/llama.cpp}"
BARK_DIR="${BARK_DIR:-$HOME/bark.cpp}"
BIN_DIR="${BIN_DIR:-$HOME/bin}"
MODELS_DIR="${MODELS_DIR:-$HOME/models}"
VENV_DIR="${VENV_DIR:-$HOME/.venv-bot}"
MODEL_FILE="$MODELS_DIR/qwen2.5-0.5b-instruct-q4_0.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_0.gguf"
BARK_F16_URL="https://huggingface.co/Green-Sky/bark-ggml/resolve/main/bark-small_weights-f16.bin"
BARK_F16_FILE="$MODELS_DIR/bark-small_weights-f16.bin"
BARK_Q4_FILE="$MODELS_DIR/bark-small_weights-q4_0.bin"
INSTALL_BARK="${INSTALL_BARK:-1}"
CLEAN_BUILD_DIRS="${CLEAN_BUILD_DIRS:-1}"
BUILD_JOBS="${BUILD_JOBS:-4}"

mkdir -p "$BIN_DIR" "$MODELS_DIR"

echo "[1/6] Actualizando paquetes de Termux..."
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
  ffmpeg \
  termux-services \
  termux-api

echo "[2/6] Clonando o actualizando llama.cpp..."
if [ -d "$LLAMA_DIR/.git" ]; then
  git -C "$LLAMA_DIR" pull --ff-only
else
  git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "$LLAMA_DIR"
fi

echo "[3/6] Compilando llama-server y llama-bench estáticos (CPU ARM64 NEON, ahorro 16 GB)..."
cmake -S "$LLAMA_DIR" -B "$LLAMA_DIR/build" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=OFF \
  -DLLAMA_CURL=OFF \
  -DGGML_VULKAN=OFF \
  -DLLAMA_BUILD_TESTS=OFF \
  -DLLAMA_BUILD_EXAMPLES=OFF

cmake --build "$LLAMA_DIR/build" --config Release -j"$BUILD_JOBS" \
  --target llama-server llama-bench

cp "$LLAMA_DIR/build/bin/llama-server" "$BIN_DIR/llama-server"
cp "$LLAMA_DIR/build/bin/llama-bench" "$BIN_DIR/llama-bench"
chmod +x "$BIN_DIR/llama-server" "$BIN_DIR/llama-bench"

if [ "$CLEAN_BUILD_DIRS" = "1" ]; then
  echo "Limpiando archivos intermedios de compilación de llama.cpp..."
  rm -rf "$LLAMA_DIR/build"
fi

echo "[4/6] Verificando modelo Qwen2.5-0.5B-Instruct (Q4_0)..."
if [ ! -f "$MODEL_FILE" ]; then
  wget -c -O "$MODEL_FILE" "$MODEL_URL"
else
  echo "Modelo ya presente en $MODEL_FILE"
fi

echo "[5/6] Preparando entorno virtual Python en $VENV_DIR..."
if [ ! -d "$VENV_DIR" ]; then
  python -m venv "$VENV_DIR"
fi
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$REPO_DIR/requirements.txt"

if [ ! -f "$REPO_DIR/.env" ]; then
  cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
  echo "Creado $REPO_DIR/.env desde .env.example. Edítalo con tu TELEGRAM_BOT_TOKEN."
fi

if [ "$INSTALL_BARK" = "1" ]; then
  echo "[6/6] Compilando bark.cpp (Suno Bark GGML) y preparando bark-small Q4_0..."
  if [ -d "$BARK_DIR/.git" ]; then
    git -C "$BARK_DIR" pull --ff-only
    git -C "$BARK_DIR" submodule update --init --recursive
  else
    git clone --recursive --depth 1 https://github.com/PABannier/bark.cpp.git "$BARK_DIR"
  fi

  cmake -S "$BARK_DIR" -B "$BARK_DIR/build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_SHARED_LIBS=OFF \
    -DBARK_BUILD_TESTS=OFF
  cmake --build "$BARK_DIR/build" --config Release -j"$BUILD_JOBS" \
    --target main quantize

  cp "$BARK_DIR/build/examples/main/main" "$BIN_DIR/bark-main"
  chmod +x "$BIN_DIR/bark-main"

  if [ ! -f "$BARK_Q4_FILE" ]; then
    echo "Descargando pesos GGML bark-small (f16) para cuantizar a Q4_0..."
    wget -c -O "$BARK_F16_FILE" "$BARK_F16_URL"
    "$BARK_DIR/build/examples/quantize/quantize" "$BARK_F16_FILE" "$BARK_Q4_FILE" q4_0
    rm -f "$BARK_F16_FILE"
    echo "Modelo cuantizado listo en $BARK_Q4_FILE"
  else
    echo "Modelo bark-small Q4_0 ya presente en $BARK_Q4_FILE"
  fi

  if [ "$CLEAN_BUILD_DIRS" = "1" ]; then
    echo "Limpiando archivos intermedios de compilación de bark.cpp..."
    rm -rf "$BARK_DIR/build"
  fi
else
  echo "[6/6] Instalación de bark.cpp omitida (INSTALL_BARK=0)."
fi

echo ""
echo "Aprovisionamiento completado. Espacio libre actual:"
df -h "$HOME" || true
echo "Siguiente paso recomendado:"
echo "  1. Probar benchmark: $BIN_DIR/llama-bench -m $MODEL_FILE -t 4 -p 128 -n 64"
echo "  2. Verificar .env en: $REPO_DIR/.env"
echo "  3. Instalar servicios 24/7: bash $REPO_DIR/scripts/install_services.sh"
