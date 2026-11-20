from __future__ import annotations

import unittest

from bot.context import GroupContextStore


class TestGroupContextStore(unittest.TestCase):
    def test_ring_buffer_maxlen_and_truncation(self) -> None:
        store = GroupContextStore(max_messages_per_chat=3, max_message_chars=25)
        for idx in range(5):
            store.add_message(
                chat_id=-1001,
                message_id=idx,
                user_name="Ana",
                text=f"Mensaje muy largo número {idx} con texto extra",
                timestamp=1000.0 + idx,
            )

        recent = store.get_recent_messages(-1001, limit=10)
        self.assertEqual([m.message_id for m in recent], [2, 3, 4])
        self.assertTrue(all(len(m.text) <= 25 for m in recent))
        self.assertTrue(recent[0].text.endswith("…"))

    def test_eligible_delayed_messages_respects_window_and_replied_flag(self) -> None:
        store = GroupContextStore(max_messages_per_chat=10)
        now = 10_000.0
        store.add_message(-1001, 1, "Luis", "Demasiado antiguo", timestamp=now - 9000)
        store.add_message(-1001, 2, "Marta", "En ventana ok", timestamp=now - 1200)
        store.add_message(-1001, 3, "Bot", "Respuesta del bot", timestamp=now - 1000, is_bot=True)
        store.add_message(-1001, 4, "Carlos", "Ya respondido", timestamp=now - 800)
        store.add_message(-1001, 5, "Elena", "Demasiado reciente", timestamp=now - 60)
        store.mark_replied(-1001, 4)

        eligible = store.get_eligible_delayed_messages(
            chat_id=-1001,
            min_age_seconds=300,
            max_age_seconds=7200,
            now=now,
        )
        self.assertEqual([m.message_id for m in eligible], [2])

    def test_context_around_target_message(self) -> None:
        store = GroupContextStore(max_messages_per_chat=10)
        for i in range(1, 7):
            store.add_message(-1001, i, f"U{i}", f"msg {i}", timestamp=100.0 + i)
        ctx = store.get_context_around_message(-1001, target_message_id=4, limit=3)
        self.assertEqual([m.message_id for m in ctx], [2, 3, 4])

    def test_cooldowns_and_reset(self) -> None:
        store = GroupContextStore()
        self.assertTrue(store.can_intervene(-1001, cooldown_seconds=30, now=1000.0))
        store.record_intervention(-1001, timestamp=1000.0)
        self.assertFalse(store.can_intervene(-1001, cooldown_seconds=30, now=1010.0))
        self.assertTrue(store.can_intervene(-1001, cooldown_seconds=30, now=1030.0))

        store.record_delayed_reply(-1001, timestamp=2000.0)
        self.assertFalse(store.can_delayed_reply(-1001, cooldown_seconds=600, now=2500.0))
        self.assertTrue(store.can_delayed_reply(-1001, cooldown_seconds=600, now=2600.0))

        store.reset_chat(-1001)
        self.assertEqual(store.get_recent_messages(-1001, 5), [])
        self.assertTrue(store.can_delayed_reply(-1001, cooldown_seconds=600, now=2500.0))


if __name__ == "__main__":
    unittest.main()
