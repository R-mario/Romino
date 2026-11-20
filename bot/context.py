from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time


@dataclass
class StoredMessage:
    message_id: int
    chat_id: int
    user_name: str
    text: str
    timestamp: float
    is_bot: bool = False
    already_replied: bool = False

    def format_line(self) -> str:
        return f"{self.user_name}: {self.text}"


class GroupContextStore:
    """Almacena un buffer circular acotado por chat y controla cooldowns."""

    def __init__(self, max_messages_per_chat: int = 15, max_message_chars: int = 280) -> None:
        self.max_messages_per_chat = max_messages_per_chat
        self.max_message_chars = max_message_chars
        self._messages: dict[int, deque[StoredMessage]] = {}
        self._last_intervention_ts: dict[int, float] = {}
        self._last_delayed_reply_ts: dict[int, float] = {}

    def _truncate(self, text: str) -> str:
        cleaned = " ".join(text.strip().split())
        if len(cleaned) <= self.max_message_chars:
            return cleaned
        return cleaned[: self.max_message_chars - 1].rstrip() + "…"

    def add_message(
        self,
        chat_id: int,
        message_id: int,
        user_name: str,
        text: str,
        timestamp: float | None = None,
        is_bot: bool = False,
    ) -> StoredMessage:
        ts = time.time() if timestamp is None else timestamp
        buf = self._messages.setdefault(chat_id, deque(maxlen=self.max_messages_per_chat))
        stored = StoredMessage(
            message_id=message_id,
            chat_id=chat_id,
            user_name=user_name.strip() or "Usuario",
            text=self._truncate(text),
            timestamp=ts,
            is_bot=is_bot,
        )
        buf.append(stored)
        return stored

    def get_recent_messages(self, chat_id: int, limit: int) -> list[StoredMessage]:
        buf = self._messages.get(chat_id)
        if not buf or limit <= 0:
            return []
        return list(buf)[-limit:]

    def format_recent_context(self, chat_id: int, limit: int) -> str:
        return "\n".join(msg.format_line() for msg in self.get_recent_messages(chat_id, limit))

    def mark_replied(self, chat_id: int, message_id: int) -> None:
        buf = self._messages.get(chat_id)
        if not buf:
            return
        for msg in buf:
            if msg.message_id == message_id:
                msg.already_replied = True
                break

    def record_intervention(self, chat_id: int, timestamp: float | None = None) -> None:
        ts = time.time() if timestamp is None else timestamp
        self._last_intervention_ts[chat_id] = ts

    def record_delayed_reply(self, chat_id: int, timestamp: float | None = None) -> None:
        ts = time.time() if timestamp is None else timestamp
        self._last_delayed_reply_ts[chat_id] = ts
        self._last_intervention_ts[chat_id] = ts

    def can_intervene(self, chat_id: int, cooldown_seconds: int, now: float | None = None) -> bool:
        if cooldown_seconds <= 0:
            return True
        current = time.time() if now is None else now
        last = self._last_intervention_ts.get(chat_id)
        if last is None:
            return True
        return (current - last) >= cooldown_seconds

    def can_delayed_reply(
        self, chat_id: int, cooldown_seconds: int, now: float | None = None
    ) -> bool:
        if cooldown_seconds <= 0:
            return True
        current = time.time() if now is None else now
        last = self._last_delayed_reply_ts.get(chat_id)
        if last is None:
            return True
        return (current - last) >= cooldown_seconds

    def get_eligible_delayed_messages(
        self,
        chat_id: int,
        min_age_seconds: int,
        max_age_seconds: int,
        now: float | None = None,
    ) -> list[StoredMessage]:
        buf = self._messages.get(chat_id)
        if not buf:
            return []
        current = time.time() if now is None else now
        eligible: list[StoredMessage] = []
        for msg in buf:
            if msg.is_bot or msg.already_replied:
                continue
            age = current - msg.timestamp
            if min_age_seconds <= age <= max_age_seconds:
                eligible.append(msg)
        return eligible

    def get_context_around_message(
        self, chat_id: int, target_message_id: int, limit: int
    ) -> list[StoredMessage]:
        """Devuelve mensajes previos e incluyendo el mensaje objetivo para dar contexto fiel."""
        buf = list(self._messages.get(chat_id, ()))
        if not buf or limit <= 0:
            return []
        idx = next((i for i, m in enumerate(buf) if m.message_id == target_message_id), None)
        if idx is None:
            return buf[-limit:]
        start = max(0, idx - limit + 1)
        return buf[start : idx + 1]

    def reset_chat(self, chat_id: int) -> None:
        self._messages.pop(chat_id, None)
        self._last_intervention_ts.pop(chat_id, None)
        self._last_delayed_reply_ts.pop(chat_id, None)

    def active_chat_ids(self) -> list[int]:
        return list(self._messages.keys())

    def group_chat_ids(self) -> list[int]:
        # En Telegram los chats de grupo/supergrupo tienen chat_id negativo.
        return [cid for cid in self._messages.keys() if cid < 0]
