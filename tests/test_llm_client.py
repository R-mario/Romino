from __future__ import annotations

import unittest
from typing import Any

from bot.config import BotConfig
from bot.context import StoredMessage
from bot.llm_client import LlamaClient, build_chat_messages, clean_reply
from bot.triggers import InterventionType


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeHttpClient:
    def __init__(self, get_resp: _FakeResponse, post_resp: _FakeResponse) -> None:
        self.get_resp = get_resp
        self.post_resp = post_resp
        self.last_post_json: dict[str, Any] | None = None

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self.get_resp

    async def post(self, url: str, json: dict[str, Any], **kwargs: Any) -> _FakeResponse:
        self.last_post_json = json
        return self.post_resp


class TestLlamaClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.config = BotConfig(telegram_bot_token="123:abc", max_tokens=110)
        self.msgs = [
            StoredMessage(1, -1001, "Ana", "Qué película vemos?", 100.0),
            StoredMessage(2, -1001, "Luis", "Alguna de ciencia ficción", 110.0),
        ]

    def test_clean_reply_strips_prefixes_and_quotes(self) -> None:
        self.assertEqual(clean_reply('  Bot: "Vamos con Dune"  '), "Vamos con Dune")
        self.assertEqual(clean_reply("Asistente: Perfecto"), "Perfecto")

    def test_build_chat_messages_modes(self) -> None:
        summary_msgs = build_chat_messages(
            config=self.config,
            intervention=InterventionType.RANDOM_GROUP_SUMMARY,
            context_messages=self.msgs,
        )
        self.assertEqual(summary_msgs[0]["role"], "system")
        self.assertIn(self.config.summary_intervention_instruction, summary_msgs[1]["content"])

        delayed_msgs = build_chat_messages(
            config=self.config,
            intervention=InterventionType.DELAYED_PAST_REPLY,
            context_messages=self.msgs,
            target_message=self.msgs[0],
        )
        self.assertIn("Ana: Qué película vemos?", delayed_msgs[1]["content"])
        self.assertIn(self.config.delayed_reply_instruction, delayed_msgs[1]["content"])

    async def test_health_and_generate(self) -> None:
        fake_http = _FakeHttpClient(
            get_resp=_FakeResponse(200, {"status": "ok"}),
            post_resp=_FakeResponse(
                200,
                {"choices": [{"message": {"content": "Bot: Interstellar nunca falla."}}]},
            ),
        )
        client = LlamaClient(self.config, http_client=fake_http)

        ok, latency = await client.check_health()
        self.assertTrue(ok)
        self.assertGreaterEqual(latency, 0.0)

        reply = await client.generate(
            intervention=InterventionType.DIRECT_REPLY,
            context_messages=self.msgs,
        )
        self.assertEqual(reply, "Interstellar nunca falla.")
        assert fake_http.last_post_json is not None
        self.assertTrue(fake_http.last_post_json["cache_prompt"])
        self.assertEqual(fake_http.last_post_json["max_tokens"], 110)

    async def test_health_error_returns_false(self) -> None:
        fake_http = _FakeHttpClient(
            get_resp=_FakeResponse(503, {"status": "loading model"}),
            post_resp=_FakeResponse(503, {}),
        )
        client = LlamaClient(self.config, http_client=fake_http)
        ok, _ = await client.check_health()
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
