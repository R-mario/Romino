#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Asistente interactivo en PC para migrar OnePlus 2 (OxygenOS -> LineageOS)
# e instalar automáticamente Termux + Termux:Boot + Termux:API vía ADB.
#
# Uso:
#   bash scripts/pc_flash_oneplus2.sh --step unlock    # Desbloquea bootloader
#   bash scripts/pc_flash_oneplus2.sh --step twrp      # Flashea y arranca TWRP
#   bash scripts/pc_flash_oneplus2.sh --step sideload  # ADB sideload LineageOS (+Magisk opcional)
#   bash scripts/pc_flash_oneplus2.sh --step postboot  # Instala APKs Termux + fix Android 12+
#   bash scripts/pc_flash_oneplus2.sh --step all       # Secuencia completa guiada
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DL_DIR="$REPO_DIR/downloads"
STEP="${2:-}"

if [ -d "$REPO_DIR/tools/platform-tools" ]; then
  export PATH="$REPO_DIR/tools/platform-tools:$PATH"
fi

if [ "${1:-}" != "--step" ] || [ -z "$STEP" ]; then
  echo "Uso: $0 --step <unlock|twrp|sideload|postboot|all>"
  exit 1
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' no está instalado. Instala con: sudo apt install -y android-tools-adb android-tools-fastboot" >&2
    exit 1
  fi
}

find_one() {
  local pattern="$1"
  shopt -s nullglob
  local matches=($DL_DIR/$pattern)
  shopt -u nullglob
  if [ "${#matches[@]}" -eq 0 ]; then
    echo ""
  else
    echo "${matches[0]}"
  fi
}

confirm() {
  local prompt="$1"
  read -r -p "$prompt [escribe 'SI' para continuar]: " ans
  if [ "$ans" != "SI" ]; then
    echo "Operación cancelada por el usuario."
    exit 0
  fi
}

step_unlock() {
  require_cmd adb
  require_cmd fastboot
  echo "=== Paso 1: Desbloqueo de Bootloader (BORRA TODOS LOS DATOS) ==="
  echo "Asegúrate de haber activado 'Desbloqueo OEM' y 'Depuración USB' en OxygenOS."
  adb devices
  confirm "¿Reiniciar en modo Fastboot y ejecutar 'fastboot oem unlock'?"
  adb reboot bootloader
  echo "Esperando dispositivo en Fastboot..."
  sleep 5
  fastboot devices
  fastboot oem unlock
  echo "Confirma en la pantalla del OnePlus 2 si lo solicita y espera a que reinicie."
}

step_twrp() {
  require_cmd fastboot
  local twrp_img
  twrp_img="$(find_one '*twrp*oneplus2*.img')"
  if [ -z "$twrp_img" ]; then
    echo "Error: No se encuentra imagen TWRP en downloads/*twrp*oneplus2*.img" >&2
    exit 1
  fi
  echo "=== Paso 2: Flasheo de TWRP ($(basename "$twrp_img")) ==="
  echo "Pon el OnePlus 2 en modo Fastboot (Volumen Arriba + Encendido, o 'adb reboot bootloader')."
  fastboot devices
  confirm "¿Flashear TWRP en la partición recovery y arrancar directamente en TWRP?"
  fastboot flash recovery "$twrp_img"
  fastboot boot "$twrp_img"
  echo "El OnePlus 2 debería estar arrancando en TWRP."
}

step_sideload() {
  require_cmd adb
  local rom_zip magisk_zip
  rom_zip="$(find_one '*lineage*oneplus2*.zip')"
  magisk_zip="$(find_one '*Magisk*.zip')"
  if [ -z "$rom_zip" ]; then
    echo "Error: No se encuentra ROM LineageOS en downloads/*lineage*oneplus2*.zip" >&2
    exit 1
  fi

  echo "=== Paso 3: Instalación de LineageOS ($(basename "$rom_zip")) ==="
  echo "En TWRP del teléfono:"
  echo "  1. (Viniendo de OxygenOS) Wipe -> Format Data -> escribe 'yes' -> Reboot -> Recovery."
  echo "  2. Wipe -> Advanced Wipe -> selecciona Dalvik/ART Cache, System, Data y Cache -> desliza."
  echo "  3. Advanced -> ADB Sideload -> desliza para escuchar."
  confirm "¿Está TWRP esperando en modo ADB Sideload?"
  adb sideload "$rom_zip"

  if [ -n "$magisk_zip" ]; then
    echo ""
    echo "Se detectó Magisk opcional: $(basename "$magisk_zip")"
    read -r -p "¿Quieres instalar Magisk ahora (vuelve a abrir Advanced -> ADB Sideload en TWRP)? [s/N]: " install_m
    if [ "${install_m,,}" = "s" ]; then
      adb sideload "$magisk_zip"
    fi
  fi

  echo "Sideload completado. Pulsa 'Reboot System' en TWRP y completa la configuración inicial de LineageOS."
}

step_postboot() {
  require_cmd adb
  echo "=== Paso 4: Post-arranque en LineageOS (APKs Termux + ajustes Android) ==="
  echo "En LineageOS activa 'Depuración USB' en Opciones de desarrollador y acepta la huella RSA en pantalla."
  adb devices
  confirm "¿Aparece el dispositivo como 'device' (autorizado)?"

  for pattern in '*termux-app*.apk' '*termux-boot*.apk' '*termux-api*.apk'; do
    local apk
    apk="$(find_one "$pattern")"
    if [ -n "$apk" ]; then
      echo "Instalando $(basename "$apk")..."
      adb install -r "$apk"
    else
      echo "Aviso: No encontrado downloads/$pattern (puedes instalarlo manualmente después)."
    fi
  done

  local sdk
  sdk="$(adb shell getprop ro.build.version.sdk | tr -d '\r\n')"
  echo "Android SDK detectado en el OnePlus 2: $sdk"
  if [ -n "$sdk" ] && [ "$sdk" -ge 31 ]; then
    echo "Android 12+ detectado: desactivando Phantom Process Killer para proteger Termux..."
    adb shell "/system/bin/device_config set_sync_disabled_for_tests persistent"
    adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
    echo "Phantom Process Killer desactivado."
  else
    echo "Android < 12 detectado: no es necesario parchear Phantom Process Killer."
  fi

  echo ""
  echo "Siguiente paso en el OnePlus 2:"
  echo "  1. Abre Termux, Termux:Boot y Termux:API al menos una vez."
  echo "  2. Desactiva optimización de batería para las 3 apps."
  echo "  3. En Termux ejecuta: pkg update && pkg install -y openssh && passwd && sshd && ifconfig"
  echo "  4. Desde este PC ejecuta: bash scripts/pc_deploy_ssh.sh <IP_DEL_ONEPLUS2> --setup"
}

case "$STEP" in
  unlock)   step_unlock ;;
  twrp)     step_twrp ;;
  sideload) step_sideload ;;
  postboot) step_postboot ;;
  all)
    step_unlock
    step_twrp
    step_sideload
    step_postboot
    ;;
  *)
    echo "Paso inválido: $STEP. Usa unlock, twrp, sideload, postboot o all." >&2
    exit 1
    ;;
esac
