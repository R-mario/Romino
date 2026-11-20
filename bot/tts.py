from __future__ import annotations

import asyncio
import logging
import re
import shutil
import tempfile
from pathlib import Path

from bot.config import BotConfig

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MD_RE = re.compile(r"[*_`~#>]+")
_SPACES_RE = re.compile(r"\s+")


def prepare_tts_text(text: str, max_chars: int = 140) -> str:
    """Limpia URLs y Markdown y acota longitud para que bark.cpp no tarde demasiado."""
    cleaned = _URL_RE.sub("", text)
    cleaned = _MD_RE.sub("", cleaned)
    cleaned = _SPACES_RE.sub(" ", cleaned).strip()
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    # Intentar cortar en el último límite de frase dentro del máximo
    snippet = cleaned[:max_chars]
    for sep in (". ", "! ", "? "):
        idx = snippet.rfind(sep)
        if idx >= max_chars // 2:
            return snippet[: idx + 1].strip()

    # Si no hay frase completa, cortar en el último espacio sin partir palabras
    space_idx = snippet.rfind(" ")
    if space_idx >= max_chars // 2:
        return snippet[:space_idx].rstrip(" ,;:") + "."
    return snippet.rstrip()


class BarkCppTTS:
    """Sintetizador de voz local bajo demanda usando bark.cpp (GGML) + ffmpeg (Opus OGG)."""

    def __init__(self, config: BotConfig) -> None:
        self.config = config

    def _bark_bin(self) -> Path:
        return Path(self.config.bark_bin).expanduser()

    def _model_path(self) -> Path:
        return Path(self.config.bark_model_path).expanduser()

    def is_available(self) -> bool:
        if not self.config.tts_enabled:
            return False
        return (
            self._bark_bin().is_file()
            and self._model_path().is_file()
            and shutil.which("ffmpeg") is not None
        )

    async def _run_process(self, cmd: list[str], timeout: float) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise TimeoutError(f"Proceso excedió el tiempo máximo ({timeout}s): {cmd[0]}")
        return (proc.returncode or 0, stderr.decode("utf-8", errors="replace").strip())

    async def synthesize_ogg(self, text: str) -> bytes:
        """Genera un audio .ogg Opus listo para Telegram send_voice y libera temporales."""
        prepared = prepare_tts_text(text, max_chars=self.config.tts_max_chars)
        if not prepared:
            raise ValueError("Texto vacío tras limpiar para síntesis de voz.")
        if not self.is_available():
            raise FileNotFoundError(
                "bark.cpp, el modelo GGML o ffmpeg no están disponibles en el sistema."
            )

        with tempfile.TemporaryDirectory(prefix="bark_tts_") as tmpdir:
            tmp = Path(tmpdir)
            wav_path = tmp / "out.wav"
            ogg_path = tmp / "out.ogg"

            bark_cmd = [
                str(self._bark_bin()),
                "-m",
                str(self._model_path()),
                "-p",
                prepared,
                "-o",
                str(wav_path),
                "-t",
                str(self.config.bark_threads),
            ]
            rc, err = await self._run_process(bark_cmd, timeout=self.config.bark_timeout_seconds)
            if rc != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
                raise RuntimeError(f"bark.cpp falló (rc={rc}): {err[-300:]}")

            ffmpeg_cmd = [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(wav_path),
                "-c:a",
                "libopus",
                "-b:a",
                "32k",
                "-vbr",
                "on",
                "-ac",
                "1",
                "-ar",
                "48000",
                str(ogg_path),
            ]
            rc_ff, err_ff = await self._run_process(ffmpeg_cmd, timeout=30.0)
            if rc_ff != 0 or not ogg_path.exists() or ogg_path.stat().st_size == 0:
                raise RuntimeError(f"ffmpeg falló al codificar Opus (rc={rc_ff}): {err_ff[-300:]}")

            return ogg_path.read_bytes()
