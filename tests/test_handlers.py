from __future__ import annotations

import asyncio
import random
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from bot.config import BotConfig, load_runtime_overrides
from bot.context import GroupContextStore
from bot.handlers import BotController, apply_runtime_config, reset_runtime_config
from bot.triggers import InterventionType


class _StubLLM:
    def __init__(self, reply: str = "Buena idea.", delay: float = 0.0) -> None:
        self.reply = reply
        self.delay = delay
        self.calls: list[dict[str, Any]] = []

    async def check_health(self) -> tuple[bool, float]:
        return (True, 12.0)

    async def generate(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.reply

    async def summarize_memory(self, **kwargs: Any) -> str:
        self.calls.append({"summarize": True, **kwargs})
        return "Grupo de amigos hablando de cine y tecnología."


class _FakeBot:
    def __init__(self) -> None:
        self.id = 999
        self.username = "oneplus_bot"
        self.first_name = "OnePlusBot"
        self.actions: list[tuple[int, str]] = []
        self.sent_messages: list[dict[str, Any]] = []
        self.sent_voices: list[dict[str, Any]] = []
        self._next_msg_id = 500

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        self.actions.append((chat_id, action))

    async def send_message(
        self, chat_id: int, text: str, reply_to_message_id: int | None = None
    ) -> Any:
        self._next_msg_id += 1
        entry = {
            "message_id": self._next_msg_id,
            "chat_id": chat_id,
            "text": text,
            "reply_to_message_id": reply_to_message_id,
        }
        self.sent_messages.append(entry)
        return SimpleNamespace(message_id=self._next_msg_id)

    async def send_voice(
        self,
        chat_id: int,
        voice: bytes,
        reply_to_message_id: int | None = None,
        caption: str | None = None,
    ) -> Any:
        self._next_msg_id += 1
        entry = {
            "message_id": self._next_msg_id,
            "chat_id": chat_id,
            "voice": voice,
            "reply_to_message_id": reply_to_message_id,
            "caption": caption,
        }
        self.sent_voices.append(entry)
        return SimpleNamespace(message_id=self._next_msg_id)


class _StubTTS:
    def __init__(self, available: bool = True, fail: bool = False) -> None:
        self.available = available
        self.fail = fail
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return self.available

    async def synthesize_ogg(self, text: str, **kwargs: Any) -> bytes:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("bark timeout")
        return b"OggS_TEST_AUDIO"


class _FakeMessage:
    def __init__(
        self,
        message_id: int,
        text: str,
        reply_to_message: Any = None,
    ) -> None:
        self.message_id = message_id
        self.text = text
        self.reply_to_message = reply_to_message
        self.replies: list[str] = []

    async def reply_text(self, text: str) -> Any:
        self.replies.append(text)
        return SimpleNamespace(message_id=self.message_id + 1000)


class _FixedRng:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)

    def random(self) -> float:
        return self._values.pop(0) if self._values else 0.99

    def shuffle(self, seq: list) -> None:
        return None

    def choice(self, seq: list):
        return seq[0]


class TestHandlers(unittest.IsolatedAsyncioTestCase):
    def _make_update(
        self,
        *,
        chat_id: int,
        chat_type: str,
        user_id: int,
        user_name: str,
        msg_id: int,
        text: str,
    ) -> tuple[Any, _FakeMessage]:
        msg = _FakeMessage(msg_id, text)
        update = SimpleNamespace(
            effective_message=msg,
            effective_chat=SimpleNamespace(id=chat_id, type=chat_type),
            effective_user=SimpleNamespace(id=user_id, first_name=user_name, is_bot=False),
        )
        return update, msg

    def test_runtime_config_updates_and_rollback(self) -> None:
        cfg = BotConfig(telegram_bot_token="123:abc")
        res = apply_runtime_config(cfg, "random", "0.25")
        self.assertIn("0.25", res)
        self.assertAlmostEqual(cfg.random_reply_probability, 0.25)

        with self.assertRaises(ValueError):
            apply_runtime_config(cfg, "random", "2.5")
        # Rollback intacto
        self.assertAlmostEqual(cfg.random_reply_probability, 0.25)

    async def test_group_summary_sends_standalone_message_without_reply(self) -> None:
        cfg = BotConfig(
            telegram_bot_token="123:abc",
            allowed_chat_ids={-1001},
            random_reply_probability=1.0,
            summary_intervention_ratio=1.0,
            group_cooldown_seconds=0,
        )
        store = GroupContextStore()
        store.add_message(-1001, 1, "Ana", "Vaya calor hace hoy", timestamp=100.0)
        llm = _StubLLM(reply="Se nota que ha llegado el verano de golpe.")
        controller = BotController(cfg, store, llm, rng=_FixedRng([0.0, 0.0]))
        bot = _FakeBot()
        ctx = SimpleNamespace(bot=bot, args=[])

        update, msg = self._make_update(
            chat_id=-1001,
            chat_type="supergroup",
            user_id=10,
            user_name="Luis",
            msg_id=2,
            text="Sí, 36 grados ahora mismo",
        )
        await controller.handle_message(update, ctx)

        self.assertEqual(msg.replies, [])
        self.assertEqual(len(bot.sent_messages), 1)
        self.assertIsNone(bot.sent_messages[0]["reply_to_message_id"])
        self.assertEqual(llm.calls[0]["intervention"], InterventionType.RANDOM_GROUP_SUMMARY)

    async def test_delayed_cycle_replies_to_past_message_and_marks_replied(self) -> None:
        cfg = BotConfig(
            telegram_bot_token="123:abc",
            allowed_chat_ids={-1001},
            delayed_reply_enabled=True,
            delayed_reply_probability=1.0,
            delayed_reply_min_age_seconds=300,
            delayed_reply_max_age_seconds=3600,
            delayed_reply_cooldown_seconds=600,
            delayed_summary_ratio=0.0,
            group_cooldown_seconds=0,
        )
        store = GroupContextStore()
        now = 5000.0
        store.add_message(-1001, 42, "Marta", "Me recomendáis unos cascos?", timestamp=now - 1200)
        llm = _StubLLM(reply="Llego tarde, pero unos Sony WH van muy bien.")
        controller = BotController(cfg, store, llm, rng=_FixedRng([0.0, 0.9]))
        bot = _FakeBot()

        fired = await controller.run_delayed_cycle(bot, now=now)
        self.assertTrue(fired)
        self.assertEqual(len(bot.sent_messages), 1)
        self.assertEqual(bot.sent_messages[0]["reply_to_message_id"], 42)
        self.assertEqual(llm.calls[0]["intervention"], InterventionType.DELAYED_PAST_REPLY)

        # El mensaje 42 ya queda marcado como respondido y no vuelve a salir elegible
        eligible = store.get_eligible_delayed_messages(-1001, 300, 3600, now=now + 700)
        self.assertEqual(eligible, [])

    async def test_concurrency_semaphore_drops_overlapping_request(self) -> None:
        cfg = BotConfig(
            telegram_bot_token="123:abc",
            allowed_chat_ids={-1001},
            notify_when_busy=True,
        )
        store = GroupContextStore()
        llm = _StubLLM(reply="Listo.", delay=0.1)
        controller = BotController(cfg, store, llm)
        bot = _FakeBot()
        ctx = SimpleNamespace(bot=bot, args=[])

        u1, m1 = self._make_update(
            chat_id=-1001,
            chat_type="group",
            user_id=1,
            user_name="Ana",
            msg_id=10,
            text="@oneplus_bot hola 1",
        )
        u2, m2 = self._make_update(
            chat_id=-1001,
            chat_type="group",
            user_id=2,
            user_name="Luis",
            msg_id=11,
            text="@oneplus_bot hola 2",
        )

        t1 = asyncio.create_task(controller.handle_message(u1, ctx))
        await asyncio.sleep(0.02)
        await controller.handle_message(u2, ctx)
        await t1

        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(m1.replies, ["Listo."])
        self.assertEqual(len(m2.replies), 1)
        self.assertIn("Procesando", m2.replies[0])

    async def test_cmd_config_restricted_to_admin(self) -> None:
        cfg = BotConfig(telegram_bot_token="123:abc", admin_user_id=777)
        controller = BotController(cfg, GroupContextStore(), _StubLLM())

        # Usuario no admin: ignorado
        u_non_admin, m_non_admin = self._make_update(
            chat_id=100, chat_type="private", user_id=111, user_name="Otro", msg_id=1, text="/config random 0.9"
        )
        await controller.cmd_config(u_non_admin, SimpleNamespace(args=["random", "0.9"]))
        self.assertEqual(m_non_admin.replies, [])
        self.assertAlmostEqual(cfg.random_reply_probability, 0.05)

        # Admin: aplica cambio
        u_admin, m_admin = self._make_update(
            chat_id=777, chat_type="private", user_id=777, user_name="Admin", msg_id=2, text="/config random 0.3"
        )
        await controller.cmd_config(u_admin, SimpleNamespace(args=["random", "0.3"]))
        self.assertAlmostEqual(cfg.random_reply_probability, 0.3)
        self.assertIn("actualizado", m_admin.replies[0])

    async def test_cmd_config_persists_and_resets_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            overrides_file = Path(tmp) / "runtime_overrides.json"
            env_file.write_text(
                "TELEGRAM_BOT_TOKEN=123:abc\nADMIN_USER_ID=777\nRANDOM_REPLY_PROBABILITY=0.05\n",
                encoding="utf-8",
            )
            cfg = BotConfig.load(env_path=env_file, overrides_path=overrides_file)
            controller = BotController(cfg, GroupContextStore(), _StubLLM())

            u1, m1 = self._make_update(
                chat_id=777, chat_type="private", user_id=777, user_name="Admin", msg_id=1, text="/config random 0.4"
            )
            await controller.cmd_config(u1, SimpleNamespace(args=["random", "0.4"]))
            self.assertAlmostEqual(load_runtime_overrides(overrides_file)["random_reply_probability"], 0.4)
            self.assertIn("guardado", m1.replies[0])

            # Recarga simulando reinicio del teléfono
            reloaded = BotConfig.load(env_path=env_file, overrides_path=overrides_file)
            self.assertAlmostEqual(reloaded.random_reply_probability, 0.4)

            # /config reset restaura .env y borra overrides
            u2, m2 = self._make_update(
                chat_id=777, chat_type="private", user_id=777, user_name="Admin", msg_id=2, text="/config reset"
            )
            await controller.cmd_config(u2, SimpleNamespace(args=["reset"]))
            self.assertFalse(overrides_file.exists())
            self.assertAlmostEqual(cfg.random_reply_probability, 0.05)
            self.assertIn("restaurada", m2.replies[0])

    async def test_delayed_reply_sends_voice_when_selected_and_falls_back_on_error(self) -> None:
        cfg = BotConfig(
            telegram_bot_token="123:abc",
            allowed_chat_ids={-1001},
            delayed_reply_enabled=True,
            delayed_reply_probability=1.0,
            delayed_reply_min_age_seconds=300,
            delayed_reply_max_age_seconds=3600,
            delayed_reply_cooldown_seconds=0,
            delayed_summary_ratio=0.0,
            delayed_voice_probability=1.0,
            group_cooldown_seconds=0,
        )
        store = GroupContextStore()
        now = 5000.0
        store.add_message(-1001, 42, "Marta", "Habéis visto el partido?", timestamp=now - 1000)

        tts_ok = _StubTTS(available=True, fail=False)
        controller = BotController(
            cfg, store, _StubLLM(reply="Vaya remontada al final."), tts_client=tts_ok, rng=_FixedRng([0.0, 0.9, 0.0])
        )
        bot = _FakeBot()
        fired = await controller.run_delayed_cycle(bot, now=now)
        self.assertTrue(fired)
        self.assertEqual(len(bot.sent_voices), 1)
        self.assertEqual(bot.sent_voices[0]["reply_to_message_id"], 42)
        self.assertEqual(bot.sent_messages, [])

        # Si bark.cpp falla, debe hacer fallback limpio a texto
        store.add_message(-1001, 43, "Luis", "Alguien juega hoy?", timestamp=now - 900)
        tts_fail = _StubTTS(available=True, fail=True)
        controller_fail = BotController(
            cfg, store, _StubLLM(reply="Me apunto luego."), tts_client=tts_fail, rng=_FixedRng([0.0, 0.9, 0.0])
        )
        bot2 = _FakeBot()
        fired2 = await controller_fail.run_delayed_cycle(bot2, now=now)
        self.assertTrue(fired2)
        self.assertEqual(bot2.sent_voices, [])
        self.assertEqual(len(bot2.sent_messages), 1)
        self.assertEqual(bot2.sent_messages[0]["reply_to_message_id"], 43)

    async def test_cmd_voz_speaks_direct_text(self) -> None:
        cfg = BotConfig(telegram_bot_token="123:abc", allowed_chat_ids={-1001})
        tts = _StubTTS(available=True)
        controller = BotController(cfg, GroupContextStore(), _StubLLM(), tts_client=tts)
        bot = _FakeBot()
        u, m = self._make_update(
            chat_id=-1001, chat_type="group", user_id=10, user_name="Mario", msg_id=88, text="/voz hola [laughter]"
        )
        await controller.cmd_voz(u, SimpleNamespace(bot=bot, args=["hola", "[laughter]"]))
        self.assertEqual(tts.calls, ["hola [laughter]"])
        self.assertEqual(len(bot.sent_voices), 1)
        self.assertEqual(bot.sent_voices[0]["reply_to_message_id"], 88)

    async def test_cmd_start_responds_with_help(self) -> None:
        cfg = BotConfig(telegram_bot_token="123:abc")
        controller = BotController(cfg, GroupContextStore(), _StubLLM())
        u, m = self._make_update(
            chat_id=5099546, chat_type="private", user_id=5099546, user_name="Romino", msg_id=1, text="/start"
        )
        await controller.cmd_start(u, SimpleNamespace(bot=_FakeBot(), args=[]))
        self.assertEqual(m.replies, ["Yo soy Romino Empeños"])

    async def test_cmd_memoria_and_background_refresh(self) -> None:
        cfg = BotConfig(
            telegram_bot_token="123:abc",
            admin_user_id=777,
            allowed_chat_ids={-1001},
            memory_enabled=True,
            memory_update_every_messages=2,
        )
        store = GroupContextStore()
        llm = _StubLLM()
        controller = BotController(cfg, store, llm)
        bot = _FakeBot()

        store.add_message(-1001, 1, "Ana", "Vamos al cine", timestamp=100.0)
        store.add_message(-1001, 2, "Luis", "Mejor hablamos de Linux", timestamp=110.0)

        # Mantenimiento automático actualiza memoria al alcanzar el umbral
        refreshed = await controller.run_memory_maintenance()
        self.assertEqual(refreshed, 1)
        self.assertIn("cine y tecnología", store.get_memory(-1001))

        # /memoria add añade nota manual como admin
        u_add, m_add = self._make_update(
            chat_id=-1001, chat_type="supergroup", user_id=777, user_name="Admin", msg_id=3, text="/memoria add Son de Madrid."
        )
        await controller.cmd_memoria(u_add, SimpleNamespace(bot=bot, args=["add", "Son", "de", "Madrid."]))
        self.assertIn("Son de Madrid.", store.get_memory(-1001))
        self.assertIn("Nota añadida", m_add.replies[0])

        # /memoria clear borra la memoria
        u_clr, m_clr = self._make_update(
            chat_id=-1001, chat_type="supergroup", user_id=777, user_name="Admin", msg_id=4, text="/memoria clear"
        )
        await controller.cmd_memoria(u_clr, SimpleNamespace(bot=bot, args=["clear"]))
        self.assertEqual(store.get_memory(-1001), "")
        self.assertIn("borrada", m_clr.replies[0])

    async def test_cmd_logs_reads_tail_for_admin_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_file = Path(tmp) / "current"
            log_file.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")
            cfg = BotConfig(telegram_bot_token="123:abc", admin_user_id=777)
            controller = BotController(cfg, GroupContextStore(), _StubLLM(), log_file_path=log_file)

            u_other, m_other = self._make_update(
                chat_id=100, chat_type="private", user_id=111, user_name="Otro", msg_id=1, text="/romino_logs"
            )
            await controller.cmd_logs(u_other, SimpleNamespace(bot=_FakeBot(), args=[]))
            self.assertEqual(m_other.replies, [])

            u_adm, m_adm = self._make_update(
                chat_id=777, chat_type="private", user_id=777, user_name="Admin", msg_id=2, text="/romino_logs 2"
            )
            await controller.cmd_logs(u_adm, SimpleNamespace(bot=_FakeBot(), args=["2"]))
            self.assertEqual(len(m_adm.replies), 1)
            self.assertIn("line3\nline4", m_adm.replies[0])
            self.assertNotIn("line1", m_adm.replies[0])


if __name__ == "__main__":
    unittest.main()
