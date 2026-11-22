from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.config import BotConfig
from bot.tts import BarkCppTTS, prepare_tts_text, split_tts_chunks


class TestBarkCppTTS(unittest.IsolatedAsyncioTestCase):
    def test_prepare_tts_text_strips_urls_markdown_and_truncates(self) -> None:
        raw = "**Hola** mira esto https://example.com/abc. `Que tal` todo por el grupo hoy? Una frase extra muy larga que deberia recortarse."
        cleaned = prepare_tts_text(raw, max_chars=70)
        self.assertNotIn("https://", cleaned)
        self.assertNotIn("**", cleaned)
        self.assertNotIn("`", cleaned)
        self.assertLessEqual(len(cleaned), 70)
        self.assertTrue(cleaned.endswith("?"))

    def test_split_tts_chunks_splits_long_text_into_short_segments(self) -> None:
        long_text = (
            "Hoy hace un día increíble para salir a tomar algo por el centro. "
            "Si os parece bien nos vemos a las ocho en la plaza mayor. "
            "Luego podemos cenar pizza todos juntos y echar unas risas."
        )
        chunks = split_tts_chunks(long_text, max_chars=220, chunk_max_chars=75, max_chunks=3)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= 75 for c in chunks))

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
                bark_threads=8,
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
            self.assertIn("-s", captured_cmds[0])
            self.assertIn("libopus", captured_cmds[1])

    async def test_synthesize_ogg_multi_chunk_uses_ffmpeg_concat_and_handles_partial_timeout(self) -> None:
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
                tts_max_chars=220,
                tts_chunk_max_chars=50,
                tts_max_chunks=3,
            )
            tts = BarkCppTTS(cfg)
            captured_cmds: list[list[str]] = []
            bark_calls = 0

            async def fake_run(cmd: list[str], timeout: float) -> tuple[int, str]:
                nonlocal bark_calls
                captured_cmds.append(cmd)
                if cmd[0] == str(bark_bin):
                    bark_calls += 1
                    if bark_calls == 3:
                        raise TimeoutError("timeout en tercer fragmento")
                    out_idx = cmd.index("-o") + 1
                    Path(cmd[out_idx]).write_bytes(b"RIFF_CHUNK_WAV")
                elif cmd[0] == "ffmpeg":
                    Path(cmd[-1]).write_bytes(b"OggS_CONCAT_OPUS")
                return (0, "")

            text = (
                "Primera frase de prueba para el grupo. "
                "Segunda frase larga que debe ir aparte. "
                "Tercera frase que simula timeout."
            )
            with patch("shutil.which", return_value="/usr/bin/ffmpeg"), patch.object(
                tts, "_run_process", side_effect=fake_run
            ):
                ogg = await tts.synthesize_ogg(text)

            self.assertEqual(ogg, b"OggS_CONCAT_OPUS")
            # 3 intentos bark (2 ok + 1 timeout parcial) + 1 ffmpeg concat
            self.assertEqual(len(captured_cmds), 4)
            self.assertIn("concat", captured_cmds[-1])
            # Misma semilla en todos los fragmentos para mantener consistencia de voz
            seed_idx_1 = captured_cmds[0].index("-s") + 1
            seed_idx_2 = captured_cmds[1].index("-s") + 1
            self.assertEqual(captured_cmds[0][seed_idx_1], captured_cmds[1][seed_idx_2])


if __name__ == "__main__":
    unittest.main()
