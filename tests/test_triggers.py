from __future__ import annotations

import random
import unittest

from bot.config import BotConfig
from bot.context import GroupContextStore
from bot.triggers import (
    InterventionType,
    decide_live_intervention,
    select_delayed_intervention,
)


class FixedRng:
    """RNG determinista para pruebas unitarias (sin consumir floats en shuffle/choice)."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)

    def random(self) -> float:
        return self._values.pop(0) if self._values else 0.99

    def shuffle(self, seq: list) -> None:
        return None

    def choice(self, seq: list):
        return seq[0]


class TestTriggers(unittest.TestCase):
    def _base_config(self) -> BotConfig:
        return BotConfig(
            telegram_bot_token="123:abc",
            allowed_chat_ids={-1001, 555},
            keywords=("oneplus",),
            random_reply_probability=0.2,
            summary_intervention_ratio=0.5,
            group_cooldown_seconds=30,
            delayed_reply_enabled=True,
            delayed_reply_probability=0.5,
            delayed_reply_min_age_seconds=300,
            delayed_reply_max_age_seconds=3600,
            delayed_reply_cooldown_seconds=600,
            delayed_summary_ratio=0.25,
        )

    def test_blocks_unlisted_chat(self) -> None:
        cfg = self._base_config()
        store = GroupContextStore()
        result = decide_live_intervention(
            config=cfg,
            store=store,
            chat_id=-9999,
            text="@mibot hola",
            is_private=False,
            is_mentioned=True,
            is_reply_to_bot=False,
        )
        self.assertEqual(result, InterventionType.NONE)

    def test_direct_triggers_mention_reply_keyword_private(self) -> None:
        cfg = self._base_config()
        store = GroupContextStore()
        for kwargs in (
            dict(chat_id=555, text="hola", is_private=True, is_mentioned=False, is_reply_to_bot=False),
            dict(chat_id=-1001, text="@bot ey", is_private=False, is_mentioned=True, is_reply_to_bot=False),
            dict(chat_id=-1001, text="sí claro", is_private=False, is_mentioned=False, is_reply_to_bot=True),
            dict(chat_id=-1001, text="mi OnePlus va genial", is_private=False, is_mentioned=False, is_reply_to_bot=False),
        ):
            result = decide_live_intervention(config=cfg, store=store, **kwargs)
            self.assertEqual(result, InterventionType.DIRECT_REPLY)

    def test_keyword_word_boundaries_prevent_false_positives(self) -> None:
        cfg = self._base_config()
        cfg.keywords = ("ia", "romino")
        cfg.random_reply_probability = 0.0
        store = GroupContextStore()

        # No debe dispararse en palabras que contienen 'ia' como subcadena
        for benign in ("buenos días", "había mucha gente", "gracias familia", "qué historia"):
            res = decide_live_intervention(
                config=cfg,
                store=store,
                chat_id=-1001,
                text=benign,
                is_private=False,
                is_mentioned=False,
                is_reply_to_bot=False,
            )
            self.assertEqual(res, InterventionType.NONE, f"Falso positivo con: {benign}")

        # Sí debe dispararse con palabra completa 'IA' o 'Romino'
        for trigger in ("qué opinas de la IA?", "IA dime algo", "ey Romino!", "romino ven"):
            res = decide_live_intervention(
                config=cfg,
                store=store,
                chat_id=-1001,
                text=trigger,
                is_private=False,
                is_mentioned=False,
                is_reply_to_bot=False,
            )
            self.assertEqual(res, InterventionType.DIRECT_REPLY, f"No disparó con: {trigger}")

    def test_reply_to_bot_respects_specific_probability(self) -> None:
        cfg = self._base_config()
        cfg.reply_to_bot_probability = 0.4
        cfg.random_reply_probability = 1.0  # No debe caer en aleatorio si se citó y no tocó
        store = GroupContextStore()

        # 0.2 < 0.4 -> responde
        yes_res = decide_live_intervention(
            config=cfg,
            store=store,
            chat_id=-1001,
            text="jajaja tal cual",
            is_private=False,
            is_mentioned=False,
            is_reply_to_bot=True,
            rng=FixedRng([0.2]),
        )
        self.assertEqual(yes_res, InterventionType.DIRECT_REPLY)

        # 0.7 >= 0.4 -> ignora (sin caer en random_reply)
        no_res = decide_live_intervention(
            config=cfg,
            store=store,
            chat_id=-1001,
            text="jajaja tal cual",
            is_private=False,
            is_mentioned=False,
            is_reply_to_bot=True,
            rng=FixedRng([0.7]),
        )
        self.assertEqual(no_res, InterventionType.NONE)

    def test_random_live_summary_vs_direct(self) -> None:
        cfg = self._base_config()
        store = GroupContextStore()
        store.add_message(-1001, 1, "Ana", "Vamos al cine hoy?", timestamp=100.0)
        store.add_message(-1001, 2, "Luis", "Mejor cenar pizza", timestamp=110.0)

        # 0.1 < 0.2 (dispara aleatorio), 0.3 < 0.5 (elige resumen de grupo)
        summary_res = decide_live_intervention(
            config=cfg,
            store=store,
            chat_id=-1001,
            text="Mejor cenar pizza",
            is_private=False,
            is_mentioned=False,
            is_reply_to_bot=False,
            now=120.0,
            rng=FixedRng([0.1, 0.3]),
        )
        self.assertEqual(summary_res, InterventionType.RANDOM_GROUP_SUMMARY)

        # 0.1 < 0.2 (dispara aleatorio), 0.8 >= 0.5 (elige respuesta directa al último msg)
        direct_res = decide_live_intervention(
            config=cfg,
            store=store,
            chat_id=-1001,
            text="Mejor cenar pizza",
            is_private=False,
            is_mentioned=False,
            is_reply_to_bot=False,
            now=120.0,
            rng=FixedRng([0.1, 0.8]),
        )
        self.assertEqual(direct_res, InterventionType.RANDOM_DIRECT_REPLY)

    def test_random_respects_group_cooldown(self) -> None:
        cfg = self._base_config()
        store = GroupContextStore()
        store.record_intervention(-1001, timestamp=100.0)
        res = decide_live_intervention(
            config=cfg,
            store=store,
            chat_id=-1001,
            text="hola a todos",
            is_private=False,
            is_mentioned=False,
            is_reply_to_bot=False,
            now=110.0,
            rng=FixedRng([0.01, 0.01]),
        )
        self.assertEqual(res, InterventionType.NONE)

    def test_select_delayed_past_reply_and_summary(self) -> None:
        cfg = self._base_config()
        store = GroupContextStore()
        now = 5000.0
        store.add_message(-1001, 10, "Ana", "Alguien probó LineageOS?", timestamp=now - 1000)
        store.add_message(-1001, 11, "Pepe", "Yo lo puse ayer", timestamp=now - 900)

        # Primera tirada (0.1 < 0.5 dispara), segunda tirada (0.8 >= 0.25 -> reply a mensaje pasado)
        selected = select_delayed_intervention(
            config=cfg,
            store=store,
            now=now,
            rng=FixedRng([0.1, 0.8]),
        )
        self.assertIsNotNone(selected)
        chat_id, intervention, target = selected
        self.assertEqual(chat_id, -1001)
        self.assertEqual(intervention, InterventionType.DELAYED_PAST_REPLY)
        self.assertIsNotNone(target)
        self.assertIn(target.message_id, {10, 11})

        # Primera tirada (0.1 < 0.5 dispara), segunda tirada (0.1 < 0.25 -> resumen diferido)
        selected_summary = select_delayed_intervention(
            config=cfg,
            store=store,
            now=now,
            rng=FixedRng([0.1, 0.1]),
        )
        self.assertIsNotNone(selected_summary)
        _, intervention_s, target_s = selected_summary
        self.assertEqual(intervention_s, InterventionType.DELAYED_GROUP_SUMMARY)
        self.assertIsNone(target_s)


if __name__ == "__main__":
    unittest.main()
