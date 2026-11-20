from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.config import BotConfig
from bot.tts import BarkCppTTS, prepare_tts_text


class TestBarkCppTTS(unittest.IsolatedAsyncioTestCase):
    def test_prepare_tts_text_strips_urls_markdown_and_truncates(self) -> None:
        raw = "**Hola** mira esto https://example.com/abc. `Que tal` todo por el grupo hoy? Una frase extra muy larga que deberia recortarse."
        cleaned = prepare_tts_text(raw, max_chars=70)
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("`", cleaned)
        self.assertLessEqual(len(cleaned), 70)
        self.assertTrue(cleaned.endswith("?"))

    def test_is_available_checks_binary_model_and_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bark_bin = Path(tmp) / "main"
            model_file = Path(tmp) / "bark.bin"
            bark_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            model_file.write_bytes(b"ggml")

            cfg = BotConfig(
                telegram_bot_token="123:abc",
                tts_enabled=True,
                bark_bin=str(bark_bin),
                bark_model_path=str(model_file),
            )
            tts = BarkCppTTS(cfg)
            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                self.assertTrue(tts.is_available())
            with patch("shutil.which", return_value=None):
                self.assertFalse(tts.is_available())

            cfg.tts_enabled = False
            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                self.assertFalse(tts.is_available())

    async def test_synthesize_ogg_invokes_bark_and_ffmpeg(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bark_bin = Path(tmp) / "main"
            model_file = Path(tmp) / "bark.bin"
            bark_bin.write_text("#!/bin/sh\n", encoding="utf-8")
            model_file.write_bytes(b"ggml")

            cfg = BotConfig(
                telegram_bot_token="123:abc",
                tts_enabled=True,
                bark_bin=str(bark_bin),
                bark_model_path=str(model_file),
                bark_threads=4,
            )
            tts = BarkCppTTS(cfg)
            captured_cmds: list[list[str]] = []

            async def fake_run(cmd: list[str], timeout: float) -> tuple[int, str]:
                captured_cmds.append(cmd)
                if cmd[0] == str(bark_bin):
                    out_idx = cmd.index("-o") + 1
                    Path(cmd[out_idx]).write_bytes(b"RIFF_FAKE_WAV")
                elif cmd[0] == "ffmpeg":
                    Path(cmd[-1]).write_bytes(b"OggS_FAKE_OPUS")
                return (0, "")

            with patch("shutil.which", return_value="/usr/bin/ffmpeg"), patch.object(
                tts, "_run_process", side_effect=fake_run
            ):
                ogg = await tts.synthesize_ogg("Hola grupo, esto es Bark.")

            self.assertEqual(ogg, b"OggS_FAKE_OPUS")
            self.assertEqual(len(captured_cmds), 2)
            self.assertIn("-m", captured_cmds[0])
            self.assertIn("-p", captured_cmds[0])
            self.assertIn("libopus", captured_cmds[1])


if __name__ == "__main__":
    unittest.main()
