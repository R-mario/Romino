from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


def parse_env_file(path: Path) -> dict[str, str]:
    """Lee un archivo .env sencillo sin dependencias externas."""
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, raw_val = line.split("=", 1)
        key = key.strip()
        val = raw_val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        values[key] = val
    return values


def load_runtime_overrides(path: Path) -> dict[str, Any]:
    """Carga ajustes persistidos por /config si existe runtime_overrides.json."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_runtime_overrides(path: Path, overrides: Mapping[str, Any]) -> None:
    """Guarda ajustes en caliente de forma atómica para sobrevivir reinicios."""
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(dict(overrides), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _parse_bool(raw: str, default: bool) -> bool:
    if not raw:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "si", "sí", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Valor booleano inválido: {raw!r}")


def _parse_int_set(raw: str) -> set[int]:
    if not raw.strip():
        return set()
    result: set[int] = set()
    for item in raw.split(","):
        cleaned = item.strip()
        if cleaned:
            result.add(int(cleaned))
    return result


def _parse_keywords(raw: str) -> tuple[str, ...]:
    if not raw.strip():
        return ()
    return tuple(k.strip().lower() for k in raw.split(",") if k.strip())


def _validate_probability(name: str, value: float) -> float:
    if not (0.0 <= value <= 1.0):
        raise ValueError(f"{name} debe estar entre 0.0 y 1.0 (recibido: {value})")
    return value


def _validate_non_negative(name: str, value: int | float) -> None:
    if value < 0:
        raise ValueError(f"{name} no puede ser negativo (recibido: {value})")


@dataclass
class BotConfig:
    telegram_bot_token: str
    allowed_chat_ids: set[int] = field(default_factory=set)
    admin_user_id: int | None = None

    # Motor LLM
    llama_base_url: str = "http://127.0.0.1:8080"
    llm_timeout_seconds: float = 45.0
    max_tokens: int = 120
    temperature: float = 0.8
    top_p: float = 0.9
    repeat_penalty: float = 1.15

    # Prompts
    system_prompt: str = (
        "Eres un participante más en un grupo de Telegram en español. "
        "Responde de forma muy breve (1 a 3 frases), natural, directa y sin formalismos innecesarios."
    )
    summary_intervention_instruction: str = (
        "Haz un comentario breve (1 a 2 frases) reaccionando de forma general al tema "
        "que se está comentando recientemente en el grupo, sin limitarte solo al último mensaje."
    )
    delayed_reply_instruction: str = (
        "Retoma con naturalidad el mensaje anterior indicado haciendo un comentario breve "
        "(1 a 2 frases), como alguien que acaba de leer ese mensaje del grupo un rato después."
    )

    # Contexto
    max_context_messages: int = 15
    prompt_context_messages: int = 6
    max_message_chars: int = 280

    # Triggers e intervenciones
    direct_reply_enabled: bool = True
    keywords: tuple[str, ...] = ()
    group_cooldown_seconds: int = 15
    random_reply_probability: float = 0.05
    summary_intervention_ratio: float = 0.40

    # Intervenciones diferidas
    delayed_reply_enabled: bool = True
    delayed_reply_check_interval_seconds: int = 300
    delayed_reply_probability: float = 0.15
    delayed_reply_min_age_seconds: int = 300
    delayed_reply_max_age_seconds: int = 7200
    delayed_reply_cooldown_seconds: int = 1800
    delayed_summary_ratio: float = 0.25

    # Concurrencia
    notify_when_busy: bool = False

    # Síntesis de voz local (bark.cpp GGML bajo demanda)
    tts_enabled: bool = True
    bark_bin: str = "~/bin/bark-main"
    bark_model_path: str = "~/models/bark-small_weights-q4_0.bin"
    bark_threads: int = 8
    bark_timeout_seconds: float = 180.0
    voice_reply_probability: float = 0.10
    delayed_voice_probability: float = 0.35
    tts_max_chars: int = 140
    tts_send_text_caption: bool = False

    # Persistencia de estado y ajustes en caliente (/config)
    overrides_path: Path | None = None
    env_path: Path | None = None
    context_state_path: Path | None = None

    def validate(self) -> None:
        if not self.telegram_bot_token.strip():
            raise ValueError("TELEGRAM_BOT_TOKEN es obligatorio.")
        if self.max_tokens <= 0:
            raise ValueError("MAX_TOKENS debe ser mayor que 0.")
        if self.llm_timeout_seconds <= 0:
            raise ValueError("LLM_TIMEOUT_SECONDS debe ser mayor que 0.")
        if self.max_context_messages <= 0:
            raise ValueError("MAX_CONTEXT_MESSAGES debe ser mayor que 0.")
        if self.prompt_context_messages <= 0:
            raise ValueError("PROMPT_CONTEXT_MESSAGES debe ser mayor que 0.")
        if self.prompt_context_messages > self.max_context_messages:
            raise ValueError("PROMPT_CONTEXT_MESSAGES no puede superar MAX_CONTEXT_MESSAGES.")
        if self.max_message_chars < 20:
            raise ValueError("MAX_MESSAGE_CHARS debe ser al menos 20.")
        if self.temperature <= 0:
            raise ValueError("TEMPERATURE debe ser mayor que 0.")

        _validate_probability("RANDOM_REPLY_PROBABILITY", self.random_reply_probability)
        _validate_probability("SUMMARY_INTERVENTION_RATIO", self.summary_intervention_ratio)
        _validate_probability("DELAYED_REPLY_PROBABILITY", self.delayed_reply_probability)
        _validate_probability("DELAYED_SUMMARY_RATIO", self.delayed_summary_ratio)
        _validate_probability("VOICE_REPLY_PROBABILITY", self.voice_reply_probability)
        _validate_probability("DELAYED_VOICE_PROBABILITY", self.delayed_voice_probability)

        if self.bark_threads <= 0:
            raise ValueError("BARK_THREADS debe ser mayor que 0.")
        if self.bark_timeout_seconds <= 0:
            raise ValueError("BARK_TIMEOUT_SECONDS debe ser mayor que 0.")
        if self.tts_max_chars < 20:
            raise ValueError("TTS_MAX_CHARS debe ser al menos 20.")

        _validate_non_negative("GROUP_COOLDOWN_SECONDS", self.group_cooldown_seconds)
        _validate_non_negative("DELAYED_REPLY_MIN_AGE_SECONDS", self.delayed_reply_min_age_seconds)
        _validate_non_negative("DELAYED_REPLY_MAX_AGE_SECONDS", self.delayed_reply_max_age_seconds)
        _validate_non_negative("DELAYED_REPLY_COOLDOWN_SECONDS", self.delayed_reply_cooldown_seconds)

        if self.delayed_reply_check_interval_seconds <= 0:
            raise ValueError("DELAYED_REPLY_CHECK_INTERVAL_SECONDS debe ser mayor que 0.")
        if self.delayed_reply_min_age_seconds > self.delayed_reply_max_age_seconds:
            raise ValueError(
                "DELAYED_REPLY_MIN_AGE_SECONDS no puede ser mayor que DELAYED_REPLY_MAX_AGE_SECONDS."
            )

    def apply_overrides_dict(self, overrides: Mapping[str, Any]) -> None:
        """Aplica overrides persistidos previamente tras validar su coherencia."""
        backup: dict[str, Any] = {}
        for attr, val in overrides.items():
            if hasattr(self, attr) and attr not in {"telegram_bot_token", "overrides_path", "env_path"}:
                backup[attr] = getattr(self, attr)
                setattr(self, attr, val)
        try:
            self.validate()
        except Exception:
            for attr, old_val in backup.items():
                setattr(self, attr, old_val)
            raise

    @classmethod
    def from_mapping(
        cls,
        env: Mapping[str, str],
        *,
        overrides_path: Path | None = None,
        env_path: Path | None = None,
        context_state_path: Path | None = None,
    ) -> BotConfig:
        def get(key: str, default: str = "") -> str:
            return env.get(key, default).strip()

        admin_raw = get("ADMIN_USER_ID")
        cfg = cls(
            telegram_bot_token=get("TELEGRAM_BOT_TOKEN"),
            allowed_chat_ids=_parse_int_set(get("ALLOWED_CHAT_IDS")),
            admin_user_id=int(admin_raw) if admin_raw else None,
            llama_base_url=get("LLAMA_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
            llm_timeout_seconds=float(get("LLM_TIMEOUT_SECONDS", "45")),
            max_tokens=int(get("MAX_TOKENS", "120")),
            temperature=float(get("TEMPERATURE", "0.8")),
            top_p=float(get("TOP_P", "0.9")),
            repeat_penalty=float(get("REPEAT_PENALTY", "1.15")),
            system_prompt=get("SYSTEM_PROMPT") or cls.system_prompt,
            summary_intervention_instruction=(
                get("SUMMARY_INTERVENTION_INSTRUCTION") or cls.summary_intervention_instruction
            ),
            delayed_reply_instruction=(
                get("DELAYED_REPLY_INSTRUCTION") or cls.delayed_reply_instruction
            ),
            max_context_messages=int(get("MAX_CONTEXT_MESSAGES", "15")),
            prompt_context_messages=int(get("PROMPT_CONTEXT_MESSAGES", "6")),
            max_message_chars=int(get("MAX_MESSAGE_CHARS", "280")),
            direct_reply_enabled=_parse_bool(get("DIRECT_REPLY_ENABLED"), True),
            keywords=_parse_keywords(get("KEYWORDS")),
            group_cooldown_seconds=int(get("GROUP_COOLDOWN_SECONDS", "15")),
            random_reply_probability=float(get("RANDOM_REPLY_PROBABILITY", "0.05")),
            summary_intervention_ratio=float(get("SUMMARY_INTERVENTION_RATIO", "0.40")),
            delayed_reply_enabled=_parse_bool(get("DELAYED_REPLY_ENABLED"), True),
            delayed_reply_check_interval_seconds=int(
                get("DELAYED_REPLY_CHECK_INTERVAL_SECONDS", "300")
            ),
            delayed_reply_probability=float(get("DELAYED_REPLY_PROBABILITY", "0.15")),
            delayed_reply_min_age_seconds=int(get("DELAYED_REPLY_MIN_AGE_SECONDS", "300")),
            delayed_reply_max_age_seconds=int(get("DELAYED_REPLY_MAX_AGE_SECONDS", "7200")),
            delayed_reply_cooldown_seconds=int(get("DELAYED_REPLY_COOLDOWN_SECONDS", "1800")),
            delayed_summary_ratio=float(get("DELAYED_SUMMARY_RATIO", "0.25")),
            notify_when_busy=_parse_bool(get("NOTIFY_WHEN_BUSY"), False),
            tts_enabled=_parse_bool(get("TTS_ENABLED"), True),
            bark_bin=get("BARK_BIN") or cls.bark_bin,
            bark_model_path=get("BARK_MODEL_PATH") or cls.bark_model_path,
            bark_threads=int(get("BARK_THREADS", "8")),
            bark_timeout_seconds=float(get("BARK_TIMEOUT_SECONDS", "180")),
            voice_reply_probability=float(get("VOICE_REPLY_PROBABILITY", "0.10")),
            delayed_voice_probability=float(get("DELAYED_VOICE_PROBABILITY", "0.35")),
            tts_max_chars=int(get("TTS_MAX_CHARS", "140")),
            tts_send_text_caption=_parse_bool(get("TTS_SEND_TEXT_CAPTION"), False),
            overrides_path=overrides_path,
            env_path=env_path,
            context_state_path=context_state_path,
        )
        cfg.validate()
        return cfg

    @classmethod
    def load(
        cls,
        env_path: Path | None = None,
        overrides_path: Path | None = None,
        context_state_path: Path | None = None,
    ) -> BotConfig:
        target_env = env_path or Path(".env")
        target_overrides = overrides_path or (target_env.parent / "runtime_overrides.json")
        target_state = context_state_path or (target_env.parent / "context_state.json")
        merged: dict[str, str] = {}
        merged.update(parse_env_file(target_env))
        merged.update(os.environ)
        cfg = cls.from_mapping(
            merged,
            overrides_path=target_overrides,
            env_path=target_env,
            context_state_path=target_state,
        )
        persisted = load_runtime_overrides(target_overrides)
        if persisted:
            cfg.apply_overrides_dict(persisted)
        return cfg
