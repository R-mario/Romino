# Guía de Migración: OnePlus 2 de OxygenOS (Android 6.0.1) a LineageOS

El OnePlus 2 (`oneplus2`) finalizó soporte oficial en **OxygenOS 3.6.1 (Android 6.0.1)**. Dado que el entorno moderno de **Termux** exige **Android 7.0 o superior**, el primer paso obligatorio es instalar una Custom ROM ligera basada en **LineageOS** sin Google Apps (GApps).

> **Advertencia:** Desbloquear el *bootloader* borra por completo los datos del teléfono. Haz copia de seguridad previa si queda algo importante en el terminal.

---

## 1. Selección de versión de LineageOS recomendada

Para usar el OnePlus 2 exclusivamente como servidor local de LLM + Bot de Telegram:

- **Opción A (Máxima estabilidad y menor consumo de RAM):** **LineageOS 17.1 (Android 10)** — última compilación oficial de LineageOS para `oneplus2`. No tiene *Phantom Process Killer* y consume muy poca RAM.
- **Opción B (Android más reciente):** **LineageOS 20 (Android 13)** no oficial de XDA Developers — muy estable, pero requiere ejecutar el comando ADB del Paso 6 para desactivar el *Phantom Process Killer*.
- **No instales GApps (Google Play Services):** ahorrarás entre 400 y 600 MB de RAM libres para el modelo y evitarás procesos en segundo plano.

Descargas necesarias en tu PC:
1. Herramientas **ADB y Fastboot** (`sudo apt install android-tools-adb android-tools-fastboot` en Linux).
2. **TWRP Recovery** para `oneplus2` (`twrp-3.x.x-x-oneplus2.img` desde [twrp.me](https://twrp.me/oneplus/oneplustwo.html)).
3. ZIP de **LineageOS** para `oneplus2` (desde el foro oficial de OnePlus 2 en XDA Developers).
4. *(Opcional, recomendado para proteger la batería 24/7)* APK/ZIP de **Magisk** para disponer de *root* y usar **ACC (Advanced Charging Controller)**.

---

## 2. Desbloqueo del Bootloader

1. En el OnePlus 2 (OxygenOS):
   - Ve a **Ajustes → Información del teléfono** y pulsa 7 veces sobre **Número de compilación** para activar *Opciones de desarrollador*.
   - Entra en **Ajustes → Opciones de desarrollador** y activa:
     - **Desbloqueo OEM** (*OEM Unlocking*)
     - **Depuración USB** (*USB Debugging*)
2. Conecta el teléfono al PC por cable USB-C y verifica conexión:
   ```bash
   adb devices
   adb reboot bootloader
   ```
3. En modo *Fastboot*, desbloquea el *bootloader* (borrará el dispositivo):
   ```bash
   fastboot devices
   fastboot oem unlock
   ```
4. Confirma el desbloqueo en la pantalla del teléfono y deja que reinicie.

---

## 3. Instalación de TWRP Recovery

1. Vuelve a entrar en modo *Fastboot* (apaga el móvil y enciéndelo manteniendo **Volumen Arriba + Encendido**, o usa `adb reboot bootloader`).
2. Flashea TWRP y arranca directamente en el *recovery*:
   ```bash
   fastboot flash recovery twrp-oneplus2.img
   fastboot boot twrp-oneplus2.img
   ```
   *(Importante: entra en TWRP antes de arrancar OxygenOS de nuevo o el sistema sobrescribirá el recovery).*

---

## 4. Flasheo limpio de LineageOS (sin GApps)

Dentro de **TWRP**:
1. Ve a **Wipe → Advanced Wipe** y selecciona **Dalvik / ART Cache**, **System**, **Data** y **Cache** (desliza para confirmar).
2. Ve a **Advanced → ADB Sideload** y desliza para iniciar la escucha.
3. Desde el PC, envía el ZIP de LineageOS:
   ```bash
   adb sideload lineage-XX.X-XXXXXXXX-oneplus2.zip
   ```
4. *(Opcional, para root)* Si vas a limitar la carga de batería con ACC, vuelve a **ADB Sideload** y envía Magisk (`Magisk-vXX.X.zip`, renombrando `.apk` a `.zip`).
5. Pulsa **Reboot System**. El primer arranque tardará entre 3 y 5 minutos.

---

## 5. Configuración inicial para modo servidor 24/7

1. Conecta el OnePlus 2 a tu red Wi-Fi (preferiblemente banda 5 GHz estable) y asigna una **IP estática** en tu router para acceder siempre por SSH a la misma dirección.
2. Instala las tres APKs oficiales desde **F-Droid** o **GitHub Releases** (`arm64-v8a`, todas firmadas por la misma fuente; nunca mezcles Play Store y F-Droid):
   - **Termux**
   - **Termux:Boot** (para autoarranque tras reinicio)
   - **Termux:API** (para lectura de temperatura y batería)
3. Abre cada una de las tres aplicaciones al menos una vez para inicializar permisos.
4. En **Ajustes → Aplicaciones → Uso de batería**, selecciona **Sin restricciones** (*No optimizar*) para **Termux**, **Termux:Boot** y **Termux:API**.
5. Desactiva Bluetooth, NFC, ubicación y reduce el brillo al mínimo. Retira cualquier funda del teléfono para mejorar la disipación pasiva del Snapdragon 810.

---

## 6. Obligatorio si instalaste Android 12 o superior (LineageOS 19–22)

En Android 12+, el *Phantom Process Killer* mata los procesos hijos de Termux (`llama-server` y Python). Con depuración USB activada, ejecuta una sola vez desde tu PC:

```bash
adb shell "/system/bin/device_config set_sync_disabled_for_tests persistent"
adb shell "/system/bin/device_config put activity_manager max_phantom_processes 2147483647"
```

*(En LineageOS 17.1 / Android 10 este paso no es necesario).*

---

## 7. Protección de batería para operación 24/7

Mantener una batería de litio de 2015 al 100 % enchufada permanentemente acelera su degradación y puede provocar hinchamiento.

- **Con *root* (Magisk + ACC — solución ideal):**
  Instala el módulo **ACC (Advanced Charging Controller)** en Magisk y limita la ventana de carga al 40–65 %:
  ```bash
  su -c "acc 65 40"
  ```
  El teléfono mantendrá la carga oscilando de forma segura entre el 40 % y el 65 %, minimizando el calor y el estrés químico de la celda.

- **Sin *root* (alternativa hardware):**
  Conecta el cargador del OnePlus 2 a un **enchufe inteligente temporizado** programado en ciclos (por ejemplo, 1 hora encendido / 4 horas apagado) y habilita `scripts/health_monitor.sh` para recibir alertas por Telegram si la batería baja del 15 % o supera los 42 °C.
