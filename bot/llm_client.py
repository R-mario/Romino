from __future__ import annotations

import re
import time
from typing import Any, Sequence

from bot.config import BotConfig
from bot.context import StoredMessage
from bot.triggers import InterventionType

_LEADING_LABEL_RE = re.compile(r"^(?:bot|asistente|assistant|respuesta)\s*:\s*", re.IGNORECASE)


def clean_reply(raw_text: str) -> str:
    """Limpia prefijos redundantes o comillas externas que a veces emiten modelos pequeños."""
    text = raw_text.strip()
    text = _LEADING_LABEL_RE.sub("", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", "«"):
        text = text[1:-1].strip()
    return text


def build_chat_messages(
    *,
    config: BotConfig,
    intervention: InterventionType,
    context_messages: Sequence[StoredMessage],
    target_message: StoredMessage | None = None,
) -> list[dict[str, str]]:
    """Construye el payload de mensajes con system prompt fijo para maximizar KV-cache."""
    conversation = "\n".join(m.format_line() for m in context_messages)

    if intervention in (InterventionType.RANDOM_GROUP_SUMMARY, InterventionType.DELAYED_GROUP_SUMMARY):
        user_content = (
            f"Conversación reciente del grupo:\n{conversation}\n\n"
            f"Instrucción: {config.summary_intervention_instruction}"
        )
    elif intervention == InterventionType.DELAYED_PAST_REPLY and target_message is not None:
        user_content = (
            f"Contexto previo del grupo:\n{conversation}\n\n"
            f"Mensaje anterior al que vas a responder ahora:\n{target_message.format_line()}\n\n"
            f"Instrucción: {config.delayed_reply_instruction}"
        )
    else:
        user_content = (
            f"Conversación reciente:\n{conversation}\n\n"
            "Responde directamente y de forma breve al último mensaje."
        )

    return [
        {"role": "system", "content": config.system_prompt},
        {"role": "user", "content": user_content},
    ]


class LlamaClient:
    """Cliente HTTP asíncrono persistente para la API OpenAI-compatible de llama-server."""

    def __init__(self, config: BotConfig, http_client: Any | None = None) -> None:
        self.config = config
        self._client = http_client
        self._owns_client = http_client is None

    def _get_client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(
                base_url=self.config.llama_base_url,
                timeout=self.config.llm_timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def check_health(self) -> tuple[bool, float]:
        """Comprueba GET /health en llama-server y devuelve (ok, latencia_ms)."""
        start = time.monotonic()
        try:
            resp = await self._get_client().get("/health", timeout=5.0)
            elapsed_ms = (time.monotonic() - start) * 1000.0
            if resp.status_code == 200:
                payload = resp.json()
                return (payload.get("status") == "ok", elapsed_ms)
            return (False, elapsed_ms)
        except Exception:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            return (False, elapsed_ms)

    async def generate(
        self,
        *,
        intervention: InterventionType,
        context_messages: Sequence[StoredMessage],
        target_message: StoredMessage | None = None,
    ) -> str:
        messages = build_chat_messages(
            config=self.config,
            intervention=intervention,
            context_messages=context_messages,
            target_message=target_message,
        )
        payload = {
            "messages": messages,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
            "top_p": self.config.top_p,
            "repeat_penalty": self.config.repeat_penalty,
            "cache_prompt": True,
        }
        resp = await self._get_client().post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return ""
        raw_content = choices[0].get("message", {}).get("content", "")
        return clean_reply(raw_content)
