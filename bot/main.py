from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from bot.config import BotConfig
from bot.context import GroupContextStore
from bot.handlers import BotController
from bot.llm_client import LlamaClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def build_application(env_path: Path | None = None) -> Any:
    config = BotConfig.load(env_path)
    store = GroupContextStore(
        max_messages_per_chat=config.max_context_messages,
        max_message_chars=config.max_message_chars,
    )
    llm_client = LlamaClient(config)
    controller = BotController(config=config, store=store, llm_client=llm_client)

    delayed_task: asyncio.Task[None] | None = None

    async def post_init(application: Any) -> None:
        nonlocal delayed_task
        delayed_task = asyncio.create_task(controller.delayed_loop(application.bot))
        logger.info(
            "Bot inicializado. Grupos autorizados: %s",
            sorted(config.allowed_chat_ids) if config.allowed_chat_ids else "TODOS (modo descubrimiento)",
        )

    async def post_shutdown(application: Any) -> None:
        nonlocal delayed_task
        if delayed_task is not None:
            delayed_task.cancel()
            try:
                await delayed_task
            except asyncio.CancelledError:
                pass
        await llm_client.aclose()
        logger.info("Bot detenido limpiamente.")

    app = (
        ApplicationBuilder()
        .token(config.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("id", controller.cmd_id))
    app.add_handler(CommandHandler("reset", controller.cmd_reset))
    app.add_handler(CommandHandler("status", controller.cmd_status))
    app.add_handler(CommandHandler("config", controller.cmd_config))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, controller.handle_message))
    return app


def main() -> None:
    app = build_application()
    logger.info("Iniciando polling de Telegram...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
