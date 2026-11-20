from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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

    def test_persists_messages_and_replied_state_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "context_state.json"
            store1 = GroupContextStore(max_messages_per_chat=10, state_path=state_file)
            store1.add_message(-1001, 10, "Ana", "Mensaje antes del reinicio", timestamp=1000.0)
            store1.add_message(-1001, 11, "Luis", "Segundo mensaje", timestamp=1010.0)
            store1.mark_replied(-1001, 10)
            store1.record_delayed_reply(-1001, timestamp=1050.0)

            # Simular reinicio del teléfono cargando el mismo archivo
            store2 = GroupContextStore(max_messages_per_chat=10, state_path=state_file)
            recent = store2.get_recent_messages(-1001, 5)
            self.assertEqual([m.message_id for m in recent], [10, 11])
            self.assertTrue(recent[0].already_replied)
            self.assertFalse(recent[1].already_replied)
            self.assertFalse(store2.can_delayed_reply(-1001, cooldown_seconds=600, now=1200.0))

    def test_group_memory_persistence_and_jsonl_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_file = Path(tmp) / "context_state.json"
            archive_dir = Path(tmp) / "history"
            store = GroupContextStore(
                max_messages_per_chat=10,
                state_path=state_file,
                archive_dir=archive_dir,
                memory_max_chars=120,
            )
            store.add_message(-1001, 1, "Ana", "Nos encanta el fútbol", timestamp=100.0)
            store.add_message(-1001, 2, "Luis", "Y los videojuegos retro", timestamp=110.0)
            self.assertTrue(store.needs_memory_refresh(-1001, every_n_messages=2))
            store.set_memory(-1001, "Grupo de amigos aficionados al fútbol y videojuegos retro.")
            self.assertFalse(store.needs_memory_refresh(-1001, every_n_messages=2))

            # El archivo JSONL debe registrar los 2 mensajes
            jsonl_file = archive_dir / "chat_-1001.jsonl"
            self.assertTrue(jsonl_file.exists())
            self.assertEqual(len(jsonl_file.read_text(encoding="utf-8").splitlines()), 2)

            # Reinicio: la memoria persiste y /reset no la borra
            reloaded = GroupContextStore(max_messages_per_chat=10, state_path=state_file)
            self.assertIn("videojuegos retro", reloaded.get_memory(-1001))
            reloaded.reset_chat(-1001)
            self.assertIn("videojuegos retro", reloaded.get_memory(-1001))
            reloaded.clear_memory(-1001)
            self.assertEqual(reloaded.get_memory(-1001), "")


if __name__ == "__main__":
    unittest.main()
