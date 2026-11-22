from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bot.config import BotConfig, parse_env_file


class TestConfig(unittest.TestCase):
    def test_valid_config_from_mapping(self) -> None:
        cfg = BotConfig.from_mapping(
            {
                "TELEGRAM_BOT_TOKEN": "123:abc",
                "ALLOWED_CHAT_IDS": "-1001, -1002, 555",
                "ADMIN_USER_ID": "555",
                "RANDOM_REPLY_PROBABILITY": "0.12",
                "MENTION_PROBABILITY": "0.65",
                "SUMMARY_INTERVENTION_RATIO": "0.5",
                "DELAYED_REPLY_ENABLED": "true",
                "DELAYED_REPLY_MIN_AGE_SECONDS": "60",
                "DELAYED_REPLY_MAX_AGE_SECONDS": "600",
                "KEYWORDS": "OnePlus, Bot, IA",
            }
        )
        self.assertEqual(cfg.allowed_chat_ids, {-1001, -1002, 555})
        self.assertEqual(cfg.admin_user_id, 555)
        self.assertAlmostEqual(cfg.random_reply_probability, 0.12)
        self.assertAlmostEqual(cfg.mention_probability, 0.65)
        self.assertEqual(cfg.keywords, ("oneplus", "bot", "ia"))

    def test_missing_token_raises(self) -> None:
        with self.assertRaises(ValueError):
            BotConfig.from_mapping({})

    def test_invalid_probability_raises(self) -> None:
        with self.assertRaises(ValueError):
            BotConfig.from_mapping(
                {
                    "TELEGRAM_BOT_TOKEN": "123:abc",
                    "RANDOM_REPLY_PROBABILITY": "1.5",
                }
            )

    def test_invalid_delayed_age_range_raises(self) -> None:
        with self.assertRaises(ValueError):
            BotConfig.from_mapping(
                {
                    "TELEGRAM_BOT_TOKEN": "123:abc",
                    "DELAYED_REPLY_MIN_AGE_SECONDS": "1000",
                    "DELAYED_REPLY_MAX_AGE_SECONDS": "500",
                }
            )

    def test_parse_env_file_ignores_comments_and_strips_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                '# comentario\nTELEGRAM_BOT_TOKEN="999:tok"\nRANDOM_REPLY_PROBABILITY=0.25\n',
                encoding="utf-8",
            )
            parsed = parse_env_file(env_file)
            self.assertEqual(parsed["TELEGRAM_BOT_TOKEN"], "999:tok")
            self.assertEqual(parsed["RANDOM_REPLY_PROBABILITY"], "0.25")

    def test_load_applies_persisted_runtime_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            overrides_file = Path(tmp) / "runtime_overrides.json"
            env_file.write_text(
                "TELEGRAM_BOT_TOKEN=999:tok\nRANDOM_REPLY_PROBABILITY=0.05\n",
                encoding="utf-8",
            )
            overrides_file.write_text(
                '{"random_reply_probability": 0.35, "delayed_reply_enabled": false}\n',
                encoding="utf-8",
            )
            cfg = BotConfig.load(env_path=env_file, overrides_path=overrides_file)
            self.assertAlmostEqual(cfg.random_reply_probability, 0.35)
            self.assertFalse(cfg.delayed_reply_enabled)


if __name__ == "__main__":
    unittest.main()
