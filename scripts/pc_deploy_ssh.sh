#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Despliega o actualiza el proyecto desde el PC hacia el OnePlus 2 por SSH (8022)
# preservando .env y runtime_overrides.json en el teléfono.
#
# Uso:
#   bash scripts/pc_deploy_ssh.sh 192.168.1.50           # Solo sincroniza archivos
#   bash scripts/pc_deploy_ssh.sh 192.168.1.50 --setup   # Sincroniza y ejecuta setup_termux.sh
#   bash scripts/pc_deploy_ssh.sh 192.168.1.50 --restart # Sincroniza y reinicia telegram-bot
# ==============================================================================

if [ "$#" -lt 1 ]; then
  echo "Uso: $0 <IP_DEL_ONEPLUS2> [--setup|--restart]"
  exit 1
fi

TARGET_HOST="$1"
ACTION="${2:-sync}"
SSH_PORT="${SSH_PORT:-8022}"
REMOTE_DIR="${REMOTE_DIR:-~/oneplus2-llm-bot}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "Sincronizando $REPO_DIR -> ${TARGET_HOST}:${REMOTE_DIR} (puerto SSH $SSH_PORT)..."
ssh -p "$SSH_PORT" "$TARGET_HOST" "mkdir -p $REMOTE_DIR"

rsync -avz --delete \
  -e "ssh -p $SSH_PORT" \
  --exclude '.git/' \
  --exclude '.env' \
  --exclude 'runtime_overrides.json' \
  --exclude 'downloads/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.venv/' \
  --exclude '.venv-bot/' \
  --exclude '*.pyc' \
  "$REPO_DIR/" "${TARGET_HOST}:${REMOTE_DIR}/"

case "$ACTION" in
  sync)
    echo "Sincronización completada."
    ;;
  --setup)
    echo "Ejecutando scripts/setup_termux.sh en el OnePlus 2..."
    ssh -t -p "$SSH_PORT" "$TARGET_HOST" "cd $REMOTE_DIR && bash scripts/setup_termux.sh"
    ;;
  --restart)
    echo "Reiniciando servicio telegram-bot en el OnePlus 2..."
    ssh -p "$SSH_PORT" "$TARGET_HOST" "sv restart telegram-bot && sv status llama-server telegram-bot"
    ;;
  *)
    echo "Opción desconocida: $ACTION (usa --setup o --restart)" >&2
    exit 1
    ;;
esac
