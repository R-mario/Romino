from __future__ import annotations

from enum import Enum
import random
import re

from bot.config import BotConfig
from bot.context import GroupContextStore, StoredMessage


class InterventionType(str, Enum):
    NONE = "none"
    DIRECT_REPLY = "direct_reply"
    RANDOM_DIRECT_REPLY = "random_direct_reply"
    RANDOM_GROUP_SUMMARY = "random_group_summary"
    DELAYED_PAST_REPLY = "delayed_past_reply"
    DELAYED_GROUP_SUMMARY = "delayed_group_summary"


def is_chat_allowed(chat_id: int, allowed_chat_ids: set[int]) -> bool:
    return not allowed_chat_ids or chat_id in allowed_chat_ids


def contains_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """Detecta palabras clave por límites de palabra para evitar falsos positivos (p. ej. 'ia' en 'día')."""
    if not keywords:
        return False
    for kw in keywords:
        if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text, re.IGNORECASE):
            return True
    return False


def decide_live_intervention(
    *,
    config: BotConfig,
    store: GroupContextStore,
    chat_id: int,
    text: str,
    is_private: bool,
    is_mentioned: bool,
    is_reply_to_bot: bool,
    now: float | None = None,
    rng: random.Random | None = None,
) -> InterventionType:
    """Determina si el bot debe intervenir inmediatamente ante un mensaje entrante."""
    if not is_chat_allowed(chat_id, config.allowed_chat_ids):
        return InterventionType.NONE

    # 1. Respuesta directa explícita (privado, mención @bot o palabra clave)
    explicit_direct = is_private or is_mentioned or contains_keyword(text, config.keywords)
    if explicit_direct:
        if config.direct_reply_enabled:
            return InterventionType.DIRECT_REPLY
        return InterventionType.NONE

    # 1b. Respuesta específica cuando citan (reply) un mensaje del bot en un grupo
    if is_reply_to_bot:
        if not config.direct_reply_enabled or config.reply_to_bot_probability <= 0.0:
            return InterventionType.NONE
        rand = rng or random
        if config.reply_to_bot_probability >= 1.0 or rand.random() < config.reply_to_bot_probability:
            return InterventionType.DIRECT_REPLY
        return InterventionType.NONE

    # 2. En grupo sin mención directa: respetar cooldown y probabilidad aleatoria
    if config.random_reply_probability <= 0.0:
        return InterventionType.NONE

    if not store.can_intervene(chat_id, config.group_cooldown_seconds, now=now):
        return InterventionType.NONE

    rand = rng or random
    if rand.random() >= config.random_reply_probability:
        return InterventionType.NONE

    # 3. Decidir si comenta el resumen reciente del grupo o responde al último mensaje
    recent = store.get_recent_messages(chat_id, config.prompt_context_messages)
    has_enough_for_summary = len(recent) >= 2
    if has_enough_for_summary and rand.random() < config.summary_intervention_ratio:
        return InterventionType.RANDOM_GROUP_SUMMARY

    return InterventionType.RANDOM_DIRECT_REPLY


def select_delayed_intervention(
    *,
    config: BotConfig,
    store: GroupContextStore,
    now: float | None = None,
    rng: random.Random | None = None,
) -> tuple[int, InterventionType, StoredMessage | None] | None:
    """
    Evalúa los grupos activos y selecciona opcionalmente una intervención diferida:
    - DELAYED_PAST_REPLY: responde haciendo reply a un mensaje antiguo dentro de [min_age, max_age].
    - DELAYED_GROUP_SUMMARY: publica un comentario sobre el contexto reciente del grupo.
    """
    if not config.delayed_reply_enabled or config.delayed_reply_probability <= 0.0:
        return None

    rand = rng or random
    candidate_chats = [
        cid
        for cid in store.group_chat_ids()
        if is_chat_allowed(cid, config.allowed_chat_ids)
        and store.can_delayed_reply(cid, config.delayed_reply_cooldown_seconds, now=now)
        and store.can_intervene(cid, config.group_cooldown_seconds, now=now)
    ]
    if not candidate_chats:
        return None

    rand.shuffle(candidate_chats)

    for chat_id in candidate_chats:
        eligible_messages = store.get_eligible_delayed_messages(
            chat_id=chat_id,
            min_age_seconds=config.delayed_reply_min_age_seconds,
            max_age_seconds=config.delayed_reply_max_age_seconds,
            now=now,
        )
        if not eligible_messages:
            continue

        if rand.random() >= config.delayed_reply_probability:
            continue

        recent = store.get_recent_messages(chat_id, config.prompt_context_messages)
        if len(recent) >= 2 and rand.random() < config.delayed_summary_ratio:
            return (chat_id, InterventionType.DELAYED_GROUP_SUMMARY, None)

        target_msg = rand.choice(eligible_messages)
        return (chat_id, InterventionType.DELAYED_PAST_REPLY, target_msg)

    return None
