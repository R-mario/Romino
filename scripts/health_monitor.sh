#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

# ==============================================================================
# Monitor térmico y de batería para OnePlus 2 (requiere app Termux:API).
# Envía alerta al ADMIN_USER_ID por Telegram si la temperatura supera el umbral
# o la batería cae por debajo del mínimo configurado.
# ==============================================================================

REPO_DIR="${REPO_DIR:-$HOME/oneplus2-llm-bot}"
ENV_FILE="$REPO_DIR/.env"
STATE_FILE="${STATE_FILE:-$HOME/.oneplus2_health_last_alert}"
MAX_TEMP_C="${MAX_TEMP_C:-42}"
MIN_BATTERY_PCT="${MIN_BATTERY_PCT:-15}"
ALERT_COOLDOWN_SECONDS="${ALERT_COOLDOWN_SECONDS:-1800}"

if ! command -v termux-battery-status >/dev/null 2>&1; then
  echo "termux-battery-status no está disponible (instala termux-api y la app Termux:API)." >&2
  exit 1
fi

if [ ! -f "$ENV_FILE" ]; then
  echo "No se encuentra $ENV_FILE." >&2
  exit 1
fi

read_env_var() {
  local key="$1"
  grep -E "^${key}=" "$ENV_FILE" | head -n1 | cut -d'=' -f2- | tr -d '\r' | sed -e 's/^"//' -e 's/"$//'
}

BOT_TOKEN="$(read_env_var TELEGRAM_BOT_TOKEN)"
ADMIN_ID="$(read_env_var ADMIN_USER_ID)"

if [ -z "$BOT_TOKEN" ] || [ -z "$ADMIN_ID" ]; then
  echo "TELEGRAM_BOT_TOKEN y ADMIN_USER_ID deben estar definidos en $ENV_FILE." >&2
  exit 1
fi

BATTERY_JSON="$(termux-battery-status)"
PARSED="$(python3 -c '
import json, sys
d = json.loads(sys.argv[1])
print(f"{d.get(\"percentage\", 100)} {d.get(\"temperature\", 0.0)} {d.get(\"status\", \"UNKNOWN\")}")
' "$BATTERY_JSON")"

read -r PCT TEMP STATUS <<< "$PARSED"

ALERT_MSG=""
IS_HOT="$(python3 -c "print(1 if float('$TEMP') >= float('$MAX_TEMP_C') else 0)")"
IS_LOW="$(python3 -c "print(1 if int('$PCT') <= int('$MIN_BATTERY_PCT') else 0)")"

if [ "$IS_HOT" = "1" ]; then
  ALERT_MSG="Temperatura alta en OnePlus 2: ${TEMP} C (umbral: ${MAX_TEMP_C} C)."
fi
if [ "$IS_LOW" = "1" ]; then
  ALERT_MSG="${ALERT_MSG:+$ALERT_MSG }Bateria baja en OnePlus 2: ${PCT}% (estado: ${STATUS})."
fi

if [ -z "$ALERT_MSG" ]; then
  exit 0
fi

NOW="$(date +%s)"
if [ -f "$STATE_FILE" ]; then
  LAST="$(cat "$STATE_FILE" || echo 0)"
  if [ $((NOW - LAST)) -lt "$ALERT_COOLDOWN_SECONDS" ]; then
    exit 0
  fi
fi

curl -sf -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  -d "chat_id=${ADMIN_ID}" \
  --data-urlencode "text=[Alerta OnePlus 2] ${ALERT_MSG}" >/dev/null

echo "$NOW" > "$STATE_FILE"
