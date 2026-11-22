from __future__ import annotations

import asyncio
import logging
import random
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Awaitable, Callable

from bot.config import BotConfig

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MD_RE = re.compile(r"[*_`~#>]+")
_SPACES_RE = re.compile(r"\s+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _clean_text(text: str) -> str:
    cleaned = _URL_RE.sub("", text)
    cleaned = _MD_RE.sub("", cleaned)
    return _SPACES_RE.sub(" ", cleaned).strip()


def _split_long_piece(piece: str, max_chars: int) -> list[str]:
    """Divide una frase larga en trozos <= max_chars respetando comas o espacios."""
    parts: list[str] = []
    remaining = piece.strip()
    while len(remaining) > max_chars:
        snippet = remaining[:max_chars]
        cut = -1
        for sep in (", ", "; ", ": ", " "):
            idx = snippet.rfind(sep)
            if idx >= max_chars // 3:
                cut = idx + (1 if sep != " " else 0)
                break
        if cut <= 0:
            cut = max_chars
        chunk = remaining[:cut].strip()
        if chunk:
            parts.append(chunk)
        remaining = remaining[cut:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def prepare_tts_text(text: str, max_chars: int = 220) -> str:
    """Limpia URLs y Markdown y acota la longitud total máxima para síntesis de voz."""
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned

    snippet = cleaned[:max_chars]
    for sep in (". ", "! ", "? "):
        idx = snippet.rfind(sep)
        if idx >= max_chars // 2:
            return snippet[: idx + 1].strip()

    space_idx = snippet.rfind(" ")
    if space_idx >= max_chars // 2:
        return snippet[:space_idx].rstrip(" ,;:") + "."
    return snippet.rstrip()


def split_tts_chunks(
    text: str,
    *,
    max_chars: int = 220,
    chunk_max_chars: int = 75,
    max_chunks: int = 3,
) -> list[str]:
    """
    Divide textos largos en fragmentos cortos (~75 chars) aptos para la ventana óptima de Bark,
    evitando timeouts y alucinaciones de 14 s por fragmento.
    """
    prepared = prepare_tts_text(text, max_chars=max_chars)
    if not prepared:
        return []
    if len(prepared) <= chunk_max_chars:
        return [prepared]

    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(prepared) if s.strip()]
    atomic_pieces: list[str] = []
    for sent in sentences:
        if len(sent) <= chunk_max_chars:
            atomic_pieces.append(sent)
        else:
            atomic_pieces.extend(_split_long_piece(sent, chunk_max_chars))

    chunks: list[str] = []
    current = ""
    for piece in atomic_pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= chunk_max_chars:
            current = f"{current} {piece}"
        else:
            chunks.append(current)
            current = piece
    if current:
        chunks.append(current)

    return chunks[:max_chunks]


class BarkCppTTS:
    """Sintetizador de voz local bajo demanda con bark.cpp (GGML) + chunking + ffmpeg Opus."""

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

    async def synthesize_ogg(
        self,
        text: str,
        *,
        on_progress: Callable[[], Awaitable[None]] | None = None,
    ) -> bytes:
        """
        Genera un audio .ogg Opus listo para Telegram send_voice.
        Si el texto es largo, lo divide en fragmentos cortos y concatena los .wav en un solo .ogg.
        """
        chunks = split_tts_chunks(
            text,
            max_chars=self.config.tts_max_chars,
            chunk_max_chars=self.config.tts_chunk_max_chars,
            max_chunks=self.config.tts_max_chunks,
        )
        if not chunks:
            raise ValueError("Texto vacío tras limpiar para síntesis de voz.")
        if not self.is_available():
            raise FileNotFoundError(
                "bark.cpp, el modelo GGML o ffmpeg no están disponibles en el sistema."
            )

        seed = random.randint(1, 2_000_000_000)
        t_total_start = time.monotonic()
        chunk_durations: list[float] = []

        with tempfile.TemporaryDirectory(prefix="bark_tts_") as tmpdir:
            tmp = Path(tmpdir)
            wav_files: list[Path] = []

            for idx, chunk in enumerate(chunks):
                if on_progress is not None:
                    try:
                        await on_progress()
                    except Exception:
                        pass

                wav_path = tmp / f"chunk_{idx}.wav"
                bark_cmd = [
                    str(self._bark_bin()),
                    "-m",
                    str(self._model_path()),
                    "-p",
                    chunk,
                    "-o",
                    str(wav_path),
                    "-t",
                    str(self.config.bark_threads),
                    "-s",
                    str(seed),
                ]
                t_chunk_start = time.monotonic()
                try:
                    rc, err = await self._run_process(
                        bark_cmd, timeout=self.config.bark_timeout_seconds
                    )
                except TimeoutError:
                    elapsed = time.monotonic() - t_chunk_start
                    if wav_files:
                        logger.warning(
                            "[TTS] timeout fragmento %d/%d (chars=%d, %.1fs); se envían %d previos",
                            idx + 1,
                            len(chunks),
                            len(chunk),
                            elapsed,
                            len(wav_files),
                        )
                        break
                    raise

                elapsed = time.monotonic() - t_chunk_start
                if rc != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
                    if wav_files:
                        logger.warning(
                            "[TTS] error fragmento %d/%d (rc=%d, chars=%d, %.1fs); se envían %d previos",
                            idx + 1,
                            len(chunks),
                            rc,
                            len(chunk),
                            elapsed,
                            len(wav_files),
                        )
                        break
                    raise RuntimeError(f"bark.cpp falló (rc={rc}, chars={len(chunk)}): {err[-300:]}")

                chunk_durations.append(elapsed)
                wav_files.append(wav_path)

            ogg_path = tmp / "out.ogg"
            if len(wav_files) == 1:
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-i",
                    str(wav_files[0]),
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
            else:
                list_file = tmp / "concat.txt"
                list_file.write_text(
                    "\n".join(f"file '{p.as_posix()}'" for p in wav_files) + "\n",
                    encoding="utf-8",
                )
                ffmpeg_cmd = [
                    "ffmpeg",
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_file),
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

            ogg_bytes = ogg_path.read_bytes()
            total_s = time.monotonic() - t_total_start
            times_str = ",".join(f"{d:.1f}s" for d in chunk_durations)
            logger.info(
                "[TTS] ok chunks=%d/%d chars=%d total=%.1fs times=[%s] ogg=%.1fKB seed=%d",
                len(wav_files),
                len(chunks),
                sum(len(c) for c in chunks[: len(wav_files)]),
                total_s,
                times_str,
                len(ogg_bytes) / 1024.0,
                seed,
            )
            return ogg_bytes
