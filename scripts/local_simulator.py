#!/usr/bin/env python3
"""Simulador interactivo local para probar la lógica de grupos, probabilidades,
intervenciones resumen, respuestas diferidas y /config sin necesidad de Telegram ni teléfono.

Uso:
  python3 scripts/local_simulator.py --demo
  python3 scripts/local_simulator.py               # Modo interactivo en terminal
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.config import BotConfig
from bot.context import GroupContextStore
from bot.handlers import BotController
from bot.llm_client import LlamaClient
from bot.triggers import InterventionType


class MockLocalLLM:
    """Simula respuestas breves en español diferenciando cada modo de intervención."""

    async def check_health(self) -> tuple[bool, float]:
        return (True, 8.5)

    async def generate(
        self,
        *,
        intervention: InterventionType,
        context_messages: list[Any],
        target_message: Any = None,
    ) -> str:
        if intervention in (
            InterventionType.RANDOM_GROUP_SUMMARY,
            InterventionType.DELAYED_GROUP_SUMMARY,
        ):
            return "[RESUMEN GRUPO] Parece que hoy el debate en el grupo viene animado."
        if intervention == InterventionType.DELAYED_PAST_REPLY and target_message is not None:
            return f"[DIFERIDO -> #{target_message.message_id} de {target_message.user_name}] Lo acabo de ver ahora, buen punto."
        last = context_messages[-1].text if context_messages else ""
        return f"[DIRECTO] Totalmente de acuerdo con eso de '{last[:40]}'."


class ConsoleBot:
    def __init__(self) -> None:
        self.id = 999
        self.username = "oneplus_bot"
        self.first_name = "OnePlusBot"
        self._msg_id = 1000

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        return None

    async def send_message(
        self, chat_id: int, text: str, reply_to_message_id: int | None = None
    ) -> Any:
        self._msg_id += 1
        prefix = f" (reply a #{reply_to_message_id})" if reply_to_message_id else " (al grupo)"
        print(f"  🤖 Bot{prefix}: {text}")
        return SimpleNamespace(message_id=self._msg_id)


class ConsoleMessage:
    def __init__(self, msg_id: int, text: str) -> None:
        self.message_id = msg_id
        self.text = text
        self.reply_to_message = None

    async def reply_text(self, text: str) -> Any:
        print(f"  🤖 Bot (reply a #{self.message_id}): {text}")
        return SimpleNamespace(message_id=self.message_id + 1000)


async def run_demo(llama_url: str | None) -> None:
    cfg = BotConfig(
        telegram_bot_token="demo:token",
        allowed_chat_ids={-1001},
        admin_user_id=1,
        llama_base_url=llama_url or "http://127.0.0.1:8080",
        group_cooldown_seconds=0,
        random_reply_probability=1.0,
        summary_intervention_ratio=1.0,
        delayed_reply_enabled=True,
        delayed_reply_probability=1.0,
        delayed_reply_min_age_seconds=300,
        delayed_reply_max_age_seconds=7200,
        delayed_reply_cooldown_seconds=0,
        delayed_summary_ratio=0.0,
    )
    store = GroupContextStore(max_messages_per_chat=cfg.max_context_messages)
    llm: Any = LlamaClient(cfg) if llama_url else MockLocalLLM()
    controller = BotController(cfg, store, llm)
    bot = ConsoleBot()
    ctx = SimpleNamespace(bot=bot, args=[])

    print("=== Demostración de los 4 modos de intervención ===")
    base_ts = time.time() - 1200
    store.add_message(-1001, 1, "Ana", "¿Qué tal va el OnePlus 2 con LineageOS?", timestamp=base_ts)
    print("👤 Ana (#1, hace 20 min): ¿Qué tal va el OnePlus 2 con LineageOS?")

    # 1. Respuesta directa por mención
    print("\n[1] Mención directa (@oneplus_bot):")
    m2 = ConsoleMessage(2, "@oneplus_bot danos tu opinión rápida")
    u2 = SimpleNamespace(
        effective_message=m2,
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=2, first_name="Luis", is_bot=False),
    )
    print("👤 Luis (#2): @oneplus_bot danos tu opinión rápida")
    await controller.handle_message(u2, ctx)

    # 2. Intervención aleatoria comentando el resumen reciente del grupo
    print("\n[2] Intervención aleatoria con resumen de contexto de grupo:")
    m3 = ConsoleMessage(3, "Pues a mí me sorprende que aguante un LLM local")
    u3 = SimpleNamespace(
        effective_message=m3,
        effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
        effective_user=SimpleNamespace(id=3, first_name="Marta", is_bot=False),
    )
    print("👤 Marta (#3): Pues a mí me sorprende que aguante un LLM local")
    await controller.handle_message(u3, ctx)

    # 3. Respuesta diferida al mensaje antiguo #1 (de hace 20 minutos)
    print("\n[3] Ciclo diferido respondiendo al mensaje antiguo #1:")
    fired = await controller.run_delayed_cycle(bot, now=time.time())
    print(f"  -> Ciclo diferido disparado: {fired}")

    if isinstance(llm, LlamaClient):
        await llm.aclose()


async def run_interactive(llama_url: str | None) -> None:
    cfg = BotConfig(
        telegram_bot_token="demo:token",
        allowed_chat_ids={-1001},
        admin_user_id=1,
        llama_base_url=llama_url or "http://127.0.0.1:8080",
        group_cooldown_seconds=0,
        random_reply_probability=0.35,
        summary_intervention_ratio=0.5,
        delayed_reply_min_age_seconds=5,
        delayed_reply_max_age_seconds=3600,
        delayed_reply_cooldown_seconds=0,
        delayed_reply_probability=1.0,
    )
    store = GroupContextStore(max_messages_per_chat=cfg.max_context_messages)
    llm: Any = LlamaClient(cfg) if llama_url else MockLocalLLM()
    controller = BotController(cfg, store, llm)
    bot = ConsoleBot()
    msg_id = 0

    print("Simulador interactivo de grupo (chat_id=-1001, mención=@oneplus_bot).")
    print("Comandos: /delayed (forzar ciclo diferido), /config [param valor], /status, /quit")
    while True:
        try:
            line = input("\nTú> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line or line == "/quit":
            break
        if line == "/delayed":
            fired = await controller.run_delayed_cycle(bot, now=time.time())
            if not fired:
                print("  (Ningún mensaje antiguo elegible todavía; espera 5s tras enviar uno.)")
            continue
        if line.startswith("/config"):
            parts = line.split()[1:]
            msg = ConsoleMessage(0, line)
            upd = SimpleNamespace(
                effective_message=msg,
                effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
                effective_user=SimpleNamespace(id=1, first_name="Admin", is_bot=False),
            )
            await controller.cmd_config(upd, SimpleNamespace(bot=bot, args=parts))
            continue
        if line == "/status":
            msg = ConsoleMessage(0, line)
            upd = SimpleNamespace(
                effective_message=msg,
                effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
                effective_user=SimpleNamespace(id=1, first_name="Admin", is_bot=False),
            )
            await controller.cmd_status(upd, SimpleNamespace(bot=bot, args=[]))
            continue

        msg_id += 1
        msg = ConsoleMessage(msg_id, line)
        upd = SimpleNamespace(
            effective_message=msg,
            effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
            effective_user=SimpleNamespace(id=1, first_name="Mario", is_bot=False),
        )
        await controller.handle_message(upd, SimpleNamespace(bot=bot, args=[]))

    if isinstance(llm, LlamaClient):
        await llm.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulador local del bot de grupos.")
    parser.add_argument("--demo", action="store_true", help="Ejecuta demostración automática.")
    parser.add_argument("--llama-url", default=None, help="URL opcional de un llama-server real.")
    args = parser.parse_args()
    if args.demo:
        asyncio.run(run_demo(args.llama_url))
    else:
        asyncio.run(run_interactive(args.llama_url))


if __name__ == "__main__":
    main()
