#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Verifica en el PC las herramientas necesarias (adb, fastboot, ssh, rsync)
# y los archivos descargados en downloads/ antes de conectar el OnePlus 2.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DL_DIR="$REPO_DIR/downloads"

if [ -d "$REPO_DIR/tools/platform-tools" ]; then
  export PATH="$REPO_DIR/tools/platform-tools:$PATH"
fi

MISSING_TOOLS=0
MISSING_FILES=0

check_cmd() {
  local cmd="$1"
  local hint="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    printf "  [OK]    %-10s (%s)\n" "$cmd" "$(command -v "$cmd")"
  else
    printf "  [FALTA] %-10s -> %s\n" "$cmd" "$hint"
    MISSING_TOOLS=$((MISSING_TOOLS + 1))
  fi
}

check_glob() {
  local label="$1"
  local pattern="$2"
  local required="$3"
  shopt -s nullglob
  local matches=($DL_DIR/$pattern)
  shopt -u nullglob
  if [ "${#matches[@]}" -gt 0 ]; then
    printf "  [OK]    %-24s (%s)\n" "$label" "$(basename "${matches[0]}")"
  elif [ "$required" = "req" ]; then
    printf "  [FALTA] %-24s (patrón: downloads/%s)\n" "$label" "$pattern"
    MISSING_FILES=$((MISSING_FILES + 1))
  else
    printf "  [OPC]   %-24s (opcional: downloads/%s)\n" "$label" "$pattern"
  fi
}

echo "=== 1. Herramientas del PC ==="
check_cmd adb      "sudo apt install -y android-tools-adb android-tools-fastboot"
check_cmd fastboot "sudo apt install -y android-tools-adb android-tools-fastboot"
check_cmd ssh      "sudo apt install -y openssh-client"
check_cmd scp      "sudo apt install -y openssh-client"
check_cmd rsync    "sudo apt install -y rsync"
check_cmd python3  "sudo apt install -y python3"

echo ""
echo "=== 2. Archivos en downloads/ para el OnePlus 2 ==="
check_glob "TWRP Recovery"     "*twrp*oneplus2*.img"        req
check_glob "ROM LineageOS"     "*lineage*oneplus2*.zip"     req
check_glob "APK Termux"        "*termux-app*.apk"           req
check_glob "APK Termux:Boot"   "*termux-boot*.apk"          req
check_glob "APK Termux:API"    "*termux-api*.apk"           req
check_glob "Magisk (root/ACC)" "*Magisk*.zip"               opt

echo ""
echo "=== 3. Detección de dispositivo conectado ==="
if command -v adb >/dev/null 2>&1; then
  adb devices | sed 's/^/  /'
else
  echo "  (omitido: adb no instalado)"
fi

if command -v fastboot >/dev/null 2>&1; then
  FB_OUT="$(fastboot devices || true)"
  if [ -n "$FB_OUT" ]; then
    echo "  Fastboot detectado:"
    echo "$FB_OUT" | sed 's/^/    /'
  fi
fi

echo ""
if [ "$MISSING_TOOLS" -eq 0 ] && [ "$MISSING_FILES" -eq 0 ]; then
  echo "Estado: LISTO para conectar el OnePlus 2 y ejecutar scripts/pc_flash_oneplus2.sh"
  exit 0
fi

echo "Resumen pendiente: $MISSING_TOOLS herramienta(s) del PC, $MISSING_FILES archivo(s) en downloads/."
echo "Consulta downloads/README.md para las fuentes oficiales de descarga."
exit 0
