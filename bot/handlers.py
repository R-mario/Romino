from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import subprocess
from typing import Any

from bot.config import (
    BotConfig,
    load_runtime_overrides,
    parse_env_file,
    save_runtime_overrides,
)
from bot.context import GroupContextStore
from bot.llm_client import LlamaClient
from bot.triggers import (
    InterventionType,
    decide_live_intervention,
    is_chat_allowed,
    select_delayed_intervention,
)

logger = logging.getLogger(__name__)


def _parse_bool_arg(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "on", "si", "sí", "yes"}:
        return True
    if normalized in {"0", "false", "off", "no"}:
        return False
    raise ValueError(f"Se esperaba true/false (recibido: {raw!r})")


def apply_runtime_config(config: BotConfig, key: str, raw_value: str) -> str:
    """Ajusta parámetros en caliente con validación atómica (rollback si falla)."""
    normalized = key.strip().lower()
    field_map: dict[str, tuple[str, Any]] = {
        "direct": ("direct_reply_enabled", _parse_bool_arg),
        "random": ("random_reply_probability", float),
        "summary": ("summary_intervention_ratio", float),
        "cooldown": ("group_cooldown_seconds", int),
        "delayed": ("delayed_reply_enabled", _parse_bool_arg),
        "delayed_prob": ("delayed_reply_probability", float),
        "delayed_interval": ("delayed_reply_check_interval_seconds", int),
        "delayed_min_age": ("delayed_reply_min_age_seconds", int),
        "delayed_max_age": ("delayed_reply_max_age_seconds", int),
        "delayed_cooldown": ("delayed_reply_cooldown_seconds", int),
        "delayed_summary": ("delayed_summary_ratio", float),
        "max_tokens": ("max_tokens", int),
        "temp": ("temperature", float),
    }
    if normalized not in field_map:
        valid = ", ".join(sorted(field_map.keys()))
        raise ValueError(f"Parámetro desconocido: {key!r}. Válidos: {valid}")

    attr_name, parser = field_map[normalized]
    previous_value = getattr(config, attr_name)
    new_value = parser(raw_value)
    setattr(config, attr_name, new_value)
    try:
        config.validate()
    except Exception:
        setattr(config, attr_name, previous_value)
        raise

    persisted_note = ""
    if config.overrides_path is not None:
        overrides = load_runtime_overrides(config.overrides_path)
        overrides[attr_name] = new_value
        save_runtime_overrides(config.overrides_path, overrides)
        persisted_note = " (guardado para futuros reinicios)"

    return f"Parámetro `{normalized}` actualizado: `{previous_value}` -> `{new_value}`{persisted_note}"


def reset_runtime_config(config: BotConfig) -> str:
    """Elimina overrides persistidos y restaura valores base desde .env."""
    if config.overrides_path is not None and config.overrides_path.exists():
        config.overrides_path.unlink()

    if config.env_path is not None:
        env_values = parse_env_file(config.env_path)
        merged = dict(env_values)
        merged.setdefault("TELEGRAM_BOT_TOKEN", config.telegram_bot_token)
        fresh = BotConfig.from_mapping(
            merged,
            overrides_path=config.overrides_path,
            env_path=config.env_path,
        )
        for attr in (
            "direct_reply_enabled",
            "random_reply_probability",
            "summary_intervention_ratio",
            "group_cooldown_seconds",
            "delayed_reply_enabled",
            "delayed_reply_probability",
            "delayed_reply_check_interval_seconds",
            "delayed_reply_min_age_seconds",
            "delayed_reply_max_age_seconds",
            "delayed_reply_cooldown_seconds",
            "delayed_summary_ratio",
            "max_tokens",
            "temperature",
        ):
            setattr(config, attr, getattr(fresh, attr))

    return "Overrides en caliente eliminados; configuración restaurada desde .env."


def format_runtime_config(config: BotConfig) -> str:
    return (
        "Configuración activa:\n"
        f"- direct: {config.direct_reply_enabled}\n"
        f"- random: {config.random_reply_probability}\n"
        f"- summary: {config.summary_intervention_ratio}\n"
        f"- cooldown: {config.group_cooldown_seconds}s\n"
        f"- delayed: {config.delayed_reply_enabled}\n"
        f"- delayed_prob: {config.delayed_reply_probability}\n"
        f"- delayed_interval: {config.delayed_reply_check_interval_seconds}s\n"
        f"- delayed_min_age: {config.delayed_reply_min_age_seconds}s\n"
        f"- delayed_max_age: {config.delayed_reply_max_age_seconds}s\n"
        f"- delayed_cooldown: {config.delayed_reply_cooldown_seconds}s\n"
        f"- delayed_summary: {config.delayed_summary_ratio}\n"
        f"- max_tokens: {config.max_tokens}\n"
        f"- temp: {config.temperature}\n\n"
        "Uso: /config <parametro> <valor>"
    )


def read_termux_battery() -> str | None:
    """Consulta termux-battery-status si está instalado en Android/Termux."""
    if not shutil.which("termux-battery-status"):
        return None
    try:
        proc = subprocess.run(
            ["termux-battery-status"],
            capture_output=True,
            text=True,
            timeout=4,
            check=True,
        )
        data = json.loads(proc.stdout)
        pct = data.get("percentage", "?")
        temp = data.get("temperature", "?")
        status = data.get("status", "?")
        return f"{pct}% | {temp}°C | {status}"
    except Exception:
        return None


class BotController:
    """Orquesta comandos, mensajes entrantes y el ciclo diferido en segundo plano."""

    def __init__(
        self,
        config: BotConfig,
        store: GroupContextStore,
        llm_client: LlamaClient,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.llm = llm_client
        self.rng = rng or random.Random()
        self.busy_semaphore = asyncio.Semaphore(1)

    def _is_admin(self, user_id: int | None) -> bool:
        if self.config.admin_user_id is None:
            return True
        return user_id == self.config.admin_user_id

    async def cmd_id(self, update: Any, context: Any) -> None:
        msg = update.effective_message
        chat = update.effective_chat
        user = update.effective_user
        if not msg or not chat:
            return
        user_part = f"\nTu user_id: {user.id}" if user else ""
        await msg.reply_text(f"ID de este chat: {chat.id}{user_part}")

    async def cmd_reset(self, update: Any, context: Any) -> None:
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return
        if not is_chat_allowed(chat.id, self.config.allowed_chat_ids):
            return
        self.store.reset_chat(chat.id)
        await msg.reply_text("Memoria de contexto de este chat reiniciada.")

    async def cmd_status(self, update: Any, context: Any) -> None:
        msg = update.effective_message
        user = update.effective_user
        if not msg or not self._is_admin(user.id if user else None):
            return
        ok, latency_ms = await self.llm.check_health()
        llm_state = f"OK ({latency_ms:.0f} ms)" if ok else "NO DISPONIBLE"
        battery = read_termux_battery() or "No disponible (fuera de Termux:API)"
        text = (
            f"Estado del servicio:\n"
            f"- llama-server: {llm_state}\n"
            f"- Motor ocupado: {'Sí' if self.busy_semaphore.locked() else 'No'}\n"
            f"- Chats en memoria: {len(self.store.active_chat_ids())} "
            f"(grupos: {len(self.store.group_chat_ids())})\n"
            f"- Batería/Temp: {battery}\n"
            f"- Prob. aleatoria: {self.config.random_reply_probability} "
            f"(resumen: {self.config.summary_intervention_ratio})\n"
            f"- Diferido activo: {self.config.delayed_reply_enabled} "
            f"(prob: {self.config.delayed_reply_probability})"
        )
        await msg.reply_text(text)

    async def cmd_config(self, update: Any, context: Any) -> None:
        msg = update.effective_message
        user = update.effective_user
        if not msg or not self._is_admin(user.id if user else None):
            return
        args = getattr(context, "args", None) or []
        if not args:
            await msg.reply_text(format_runtime_config(self.config))
            return
        if len(args) == 1 and args[0].strip().lower() == "reset":
            await msg.reply_text(reset_runtime_config(self.config))
            return
        if len(args) != 2:
            await msg.reply_text("Uso correcto: /config <parametro> <valor> o /config reset")
            return
        try:
            summary = apply_runtime_config(self.config, args[0], args[1])
            await msg.reply_text(summary)
        except Exception as exc:
            await msg.reply_text(f"Error de configuración: {exc}")

    async def handle_message(self, update: Any, context: Any) -> None:
        msg = update.effective_message
        chat = update.effective_chat
        user = update.effective_user
        if not msg or not chat or not msg.text:
            return
        if user and getattr(user, "is_bot", False):
            return

        chat_id = chat.id
        if not is_chat_allowed(chat_id, self.config.allowed_chat_ids):
            return

        user_name = (getattr(user, "first_name", None) or "Usuario") if user else "Usuario"
        text = msg.text.strip()
        if not text:
            return

        stored = self.store.add_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            user_name=user_name,
            text=text,
            is_bot=False,
        )

        is_private = getattr(chat, "type", "") == "private"
        bot_username = getattr(context.bot, "username", None)
        is_mentioned = bool(bot_username and f"@{bot_username.lower()}" in text.lower())
        reply_to = getattr(msg, "reply_to_message", None)
        reply_from = getattr(reply_to, "from_user", None) if reply_to else None
        is_reply_to_bot = bool(reply_from and reply_from.id == context.bot.id)

        intervention = decide_live_intervention(
            config=self.config,
            store=self.store,
            chat_id=chat_id,
            text=text,
            is_private=is_private,
            is_mentioned=is_mentioned,
            is_reply_to_bot=is_reply_to_bot,
            rng=self.rng,
        )
        if intervention == InterventionType.NONE:
            return

        if self.busy_semaphore.locked():
            if intervention == InterventionType.DIRECT_REPLY and self.config.notify_when_busy:
                await msg.reply_text("Procesando otra consulta, inténtalo en unos segundos.")
            return

        async with self.busy_semaphore:
            await context.bot.send_chat_action(chat_id=chat_id, action="typing")
            recent = self.store.get_recent_messages(chat_id, self.config.prompt_context_messages)
            try:
                reply = await self.llm.generate(
                    intervention=intervention,
                    context_messages=recent,
                )
            except Exception as exc:
                logger.warning("Error consultando llama-server: %s", exc)
                if intervention == InterventionType.DIRECT_REPLY and is_private:
                    await msg.reply_text("Error consultando el motor LLM local.")
                return

            if not reply:
                return

            if intervention == InterventionType.RANDOM_GROUP_SUMMARY:
                sent = await context.bot.send_message(chat_id=chat_id, text=reply)
            else:
                sent = await msg.reply_text(reply)
                self.store.mark_replied(chat_id, stored.message_id)

            self.store.record_intervention(chat_id)
            sent_id = getattr(sent, "message_id", 0)
            self.store.add_message(
                chat_id=chat_id,
                message_id=sent_id,
                user_name=getattr(context.bot, "first_name", None) or "Bot",
                text=reply,
                is_bot=True,
            )

    async def run_delayed_cycle(self, bot: Any, now: float | None = None) -> bool:
        """Ejecuta una iteración del selector diferido. Devuelve True si publicó un mensaje."""
        if self.busy_semaphore.locked():
            return False

        selected = select_delayed_intervention(
            config=self.config,
            store=self.store,
            now=now,
            rng=self.rng,
        )
        if selected is None:
            return False

        chat_id, intervention, target_msg = selected

        async with self.busy_semaphore:
            if intervention == InterventionType.DELAYED_PAST_REPLY and target_msg is not None:
                ctx_messages = self.store.get_context_around_message(
                    chat_id, target_msg.message_id, self.config.prompt_context_messages
                )
            else:
                ctx_messages = self.store.get_recent_messages(
                    chat_id, self.config.prompt_context_messages
                )

            try:
                await bot.send_chat_action(chat_id=chat_id, action="typing")
                reply = await self.llm.generate(
                    intervention=intervention,
                    context_messages=ctx_messages,
                    target_message=target_msg,
                )
            except Exception as exc:
                logger.warning("Error en intervención diferida (chat %s): %s", chat_id, exc)
                return False

            if not reply:
                return False

            try:
                if intervention == InterventionType.DELAYED_PAST_REPLY and target_msg is not None:
                    sent = await bot.send_message(
                        chat_id=chat_id,
                        text=reply,
                        reply_to_message_id=target_msg.message_id,
                    )
                    self.store.mark_replied(chat_id, target_msg.message_id)
                else:
                    sent = await bot.send_message(chat_id=chat_id, text=reply)
            except Exception as exc:
                logger.warning("No se pudo enviar respuesta diferida en chat %s: %s", chat_id, exc)
                return False

            self.store.record_delayed_reply(chat_id, timestamp=now)
            sent_id = getattr(sent, "message_id", 0)
            self.store.add_message(
                chat_id=chat_id,
                message_id=sent_id,
                user_name=getattr(bot, "first_name", None) or "Bot",
                text=reply,
                timestamp=now,
                is_bot=True,
            )
            return True

    async def delayed_loop(self, bot: Any) -> None:
        """Loop asíncrono en segundo plano para respuestas diferidas a mensajes pasados."""
        logger.info("Loop de intervenciones diferidas iniciado.")
        while True:
            interval = max(10, self.config.delayed_reply_check_interval_seconds)
            await asyncio.sleep(interval)
            try:
                await self.run_delayed_cycle(bot)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Fallo no esperado en delayed_loop: %s", exc)
