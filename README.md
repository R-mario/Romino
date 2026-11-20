# OnePlus 2 Local LLM + Telegram Group Bot

Servicio ligero y autónomo para ejecutar un LLM local (**`Qwen2.5-0.5B-Instruct` `Q4_0`** sobre `llama.cpp`) conectado a un bot de Telegram directamente en un **OnePlus 2** con **LineageOS + Termux**.

Optimizado para baja latencia en hasta **5 grupos de Telegram** de bajo tráfico, con cuatro modos de intervención totalmente ajustables por `.env` y en tiempo real mediante `/config`:

1. **Respuesta directa:** mención (`@bot`), respuesta (*reply*) al bot, chat privado o palabras clave.
2. **Intervención aleatoria inmediata:** probabilidad configurable al recibir nuevos mensajes en el grupo.
3. **Intervención basada en contexto/resumen reciente del grupo:** proporción configurable de intervenciones que comentan el hilo reciente del grupo sin responder únicamente al último mensaje.
4. **Respuesta diferida a mensajes pasados:** tarea asíncrona en segundo plano que elige aleatoriamente un mensaje anterior dentro de una ventana de antigüedad configurable (`min_age` – `max_age`) y le responde directamente vía `reply_to_message_id`.

---

## Requisitos previos

1. **Migrar el OnePlus 2 de OxygenOS (Android 6.0.1) a LineageOS:** ver guía paso a paso en [docs/FLASHING_ONEPLUS2.md](docs/FLASHING_ONEPLUS2.md).
2. **Crear el bot en Telegram (`@BotFather`):**
   - `/newbot` para obtener el `TELEGRAM_BOT_TOKEN`.
   - `/setprivacy` → selecciona el bot → **`Disable`** (imprescindible para que el bot pueda leer mensajes del grupo, construir el contexto reciente y lanzar intervenciones aleatorias/diferidas).
   - Obtén tu `ADMIN_USER_ID` con `@userinfobot`.

---

## Preparación previa en el PC (antes de conectar el OnePlus 2)

1. **Instala `adb` y `fastboot`** (si aún no están instalados):
   ```bash
   sudo apt install -y android-tools-adb android-tools-fastboot
   ```
2. **Descarga los archivos del dispositivo en `downloads/`** siguiendo [downloads/README.md](downloads/README.md) y verifica todo con:
   ```bash
   bash scripts/pc_check_prereqs.sh
   ```
3. **Prueba localmente la lógica de grupos y los 4 modos de intervención** sin necesidad de Telegram ni teléfono:
   ```bash
   python3 scripts/local_simulator.py --demo
   python3 scripts/local_simulator.py          # Modo interactivo
   ```

---

## Flasheo y Despliegue Automatizados desde el PC

### 1. Migrar el OnePlus 2 a LineageOS e instalar Termux por USB
Guía completa en [docs/FLASHING_ONEPLUS2.md](docs/FLASHING_ONEPLUS2.md) o mediante el asistente guiado por fases:
```bash
bash scripts/pc_flash_oneplus2.sh --step unlock    # Desbloquea bootloader
bash scripts/pc_flash_oneplus2.sh --step twrp      # Flashea y arranca TWRP
bash scripts/pc_flash_oneplus2.sh --step sideload  # Instala LineageOS (+Magisk opcional)
bash scripts/pc_flash_oneplus2.sh --step postboot  # Instala APKs Termux + fix Android 12+
```

### 2. Habilitar SSH en Termux (en el OnePlus 2)
```bash
pkg update && pkg install -y openssh
passwd
sshd
ifconfig   # Anota la IP local del teléfono (puerto SSH: 8022)
```

### 3. Sincronizar y aprovisionar el teléfono en un comando (desde tu PC)
```bash
bash scripts/pc_deploy_ssh.sh IP_DEL_ONEPLUS2 --setup
```
Para futuras actualizaciones de código sin sobrescribir `.env` ni `runtime_overrides.json`:
```bash
bash scripts/pc_deploy_ssh.sh IP_DEL_ONEPLUS2 --restart
```

### 4. Probar rendimiento del modelo en el Snapdragon 810
```bash
~/llama.cpp/build/bin/llama-bench -m ~/models/qwen2.5-0.5b-instruct-q4_0.gguf -t 4 -p 128 -n 64
```

### 5. Configurar `.env` y activar servicios 24/7
Edita `~/oneplus2-llm-bot/.env` con tu `TELEGRAM_BOT_TOKEN` y `ADMIN_USER_ID`. Deja inicialmente `ALLOWED_CHAT_IDS=` vacío para añadir el bot a tus grupos, ejecutar `/id` en cada uno y copiar los IDs obtenidos en `.env`.

Instala los servicios supervisados (`termux-services` + `Termux:Boot`):
```bash
bash scripts/install_services.sh
```
Cierra y vuelve a abrir Termux una vez, y ejecuta:
```bash
termux-wake-lock
sv-enable llama-server && sv up llama-server
sv-enable telegram-bot && sv up telegram-bot
```

---

## Comandos del Bot y Ajuste en Caliente

| Comando | Quién puede usarlo | Función |
| :--- | :--- | :--- |
| `/id` | Cualquier chat | Muestra el `chat_id` actual y el `user_id` para configurar `.env`. |
| `/reset` | Grupos autorizados | Borra el buffer de memoria del chat actual. |
| `/status` | Administrador | Comprueba salud y latencia de `llama-server`, disponibilidad de `bark.cpp`, ocupación del motor y temperatura/batería (`Termux:API`). |
| `/config` | Administrador | Muestra la configuración activa, ajusta parámetros en caliente (persistidos en `runtime_overrides.json` para sobrevivir reinicios) o restaura `.env` con `/config reset`. |
| `/voz` | Grupos autorizados | Sintetiza audio con **Suno Bark (`bark.cpp` `Q4_0`)** y lo envía como nota de voz Opus (`/voz <texto>` o respondiendo a un mensaje con `/voz`). |

Ejemplos de ajuste en caliente:
```text
/config random 0.08            # 8% de intervención aleatoria inmediata
/config summary 0.50           # 50% de las aleatorias comentan el resumen reciente del grupo
/config delayed true           # Activa respuestas diferidas a mensajes pasados
/config delayed_prob 0.20      # 20% de probabilidad por ciclo diferido
/config delayed_min_age 300    # Mensajes pasados de al menos 5 minutos
/config delayed_max_age 7200   # Hasta 2 horas de antigüedad
/config delayed_cooldown 1800  # Mínimo 30 minutos entre diferidos en el mismo grupo
/config delayed_summary 0.25   # 25% de diferidos comentan resumen, 75% responden a un msg concreto
/config tts true               # Activa/desactiva notas de voz con bark.cpp
/config voice 0.10             # 10% de respuestas inmediatas en nota de voz
/config delayed_voice 0.35     # 35% de intervenciones diferidas en nota de voz
/config tts_max_chars 140      # Límite de caracteres por audio (controla latencia en SD810)
/config max_tokens 100         # Recorta longitud máxima para acelerar respuestas
```

---

## Pruebas automatizadas (en PC)

```bash
python3 -m unittest discover -s tests -v
```
Si tienes `pytest` instalado:
```bash
pytest -v
```
