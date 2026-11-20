#!/usr/bin/env python3
"""Descarga en downloads/ los artefactos oficiales necesarios para el OnePlus 2:
- Google Android SDK platform-tools (adb + fastboot para Linux, sin sudo)
- Termux (arm64-v8a), Termux:Boot y Termux:API (todas de GitHub Releases, misma firma)
- Magisk (opcional, para root + ACC)
- TWRP Recovery para oneplus2 (dl.twrp.me/oneplus2)
- LineageOS 17.1 oficial firmado para oneplus2 (Internet Archive)
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_DIR = Path(__file__).resolve().parent.parent
DL_DIR = REPO_DIR / "downloads"
USER_AGENT = "oneplus2-llm-bot-downloader/1.0"


def _fetch_bytes(url: str, headers: dict[str, str] | None = None, timeout: int = 30) -> bytes:
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _fetch_json(url: str) -> Any:
    return json.loads(_fetch_bytes(url).decode("utf-8"))


def _download_file(
    url: str,
    dest: Path,
    *,
    headers: dict[str, str] | None = None,
    expected_sha1: str | None = None,
    min_bytes: int = 100_000,
) -> bool:
    if dest.exists() and dest.stat().st_size >= min_bytes:
        print(f"  [SKIP] Ya existe {dest.name} ({dest.stat().st_size / 1_048_576:.1f} MB)")
        return True

    print(f"  [GET]  {dest.name} <- {url}")
    req_headers = {"User-Agent": USER_AGENT}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)

    tmp = dest.with_suffix(dest.suffix + ".part")
    sha1 = hashlib.sha1()
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" in content_type.lower():
                print(f"  [WARN] Respuesta HTML inesperada para {dest.name} (posible página intermedia); omitido.")
                tmp.unlink(missing_ok=True)
                return False
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                sha1.update(chunk)
                total += len(chunk)
    except Exception as exc:
        print(f"  [ERR]  Error descargando {dest.name}: {exc}")
        tmp.unlink(missing_ok=True)
        return False

    if total < min_bytes:
        print(f"  [ERR]  Archivo demasiado pequeño ({total} bytes) para {dest.name}; descartado.")
        tmp.unlink(missing_ok=True)
        return False

    if expected_sha1 and sha1.hexdigest().lower() != expected_sha1.lower():
        print(
            f"  [ERR]  SHA1 no coincide para {dest.name}: "
            f"esperado {expected_sha1}, obtenido {sha1.hexdigest()}"
        )
        tmp.unlink(missing_ok=True)
        return False

    tmp.replace(dest)
    print(f"  [OK]   {dest.name} ({total / 1_048_576:.1f} MB)")
    return True


def download_platform_tools() -> bool:
    return _download_file(
        "https://dl.google.com/android/repository/platform-tools-latest-linux.zip",
        DL_DIR / "platform-tools-latest-linux.zip",
        min_bytes=1_000_000,
    )


def download_github_asset(repo: str, name_regex: str, rename_ext: str | None = None) -> bool:
    try:
        release = _fetch_json(f"https://api.github.com/repos/{repo}/releases/latest")
    except Exception as exc:
        print(f"  [ERR]  No se pudo consultar GitHub Releases de {repo}: {exc}")
        return False

    pattern = re.compile(name_regex, re.IGNORECASE)
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        if pattern.search(name):
            out_name = name
            if rename_ext and not out_name.endswith(rename_ext):
                out_name = Path(out_name).with_suffix(rename_ext).name
            return _download_file(asset["browser_download_url"], DL_DIR / out_name)

    print(f"  [ERR]  No se encontró asset en {repo} que coincida con {name_regex}")
    return False


def download_twrp() -> bool:
    index_url = "https://dl.twrp.me/oneplus2/"
    try:
        html = _fetch_bytes(index_url).decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"  [ERR]  No se pudo consultar {index_url}: {exc}")
        return False

    matches = re.findall(r'href="(/oneplus2/twrp-[^"]+-oneplus2\.img)\.html"', html)
    if not matches:
        print("  [WARN] No se encontraron enlaces directos en dl.twrp.me/oneplus2/.")
        return False

    rel_path = matches[0]
    filename = Path(rel_path).name
    direct_url = f"https://dl.twrp.me{rel_path}"
    referer = f"https://dl.twrp.me{rel_path}.html"
    return _download_file(
        direct_url,
        DL_DIR / filename,
        headers={"Referer": referer},
        min_bytes=5_000_000,
    )


def download_lineageos_17_1() -> bool:
    item_id = "lineage-17.1-20210605-nightly-oneplus2-signed_202108"
    meta_url = f"https://archive.org/metadata/{item_id}"
    try:
        meta = _fetch_json(meta_url)
    except Exception as exc:
        print(f"  [ERR]  No se pudo consultar metadatos de Archive.org ({item_id}): {exc}")
        return False

    for entry in meta.get("files", []):
        name = entry.get("name", "")
        if name.startswith("lineage-17.1") and name.endswith("oneplus2-signed.zip"):
            sha1 = entry.get("sha1")
            url = f"https://archive.org/download/{item_id}/{name}"
            return _download_file(
                url,
                DL_DIR / name,
                expected_sha1=sha1,
                min_bytes=200_000_000,
            )

    print(f"  [ERR]  No se encontró el ZIP firmado de LineageOS 17.1 en {item_id}.")
    return False


def main() -> int:
    DL_DIR.mkdir(parents=True, exist_ok=True)
    results = {
        "platform-tools (adb/fastboot)": download_platform_tools(),
        "Termux (arm64-v8a)": download_github_asset(
            "termux/termux-app", r"termux-app_.*github.*arm64-v8a\.apk$"
        ),
        "Termux:Boot": download_github_asset(
            "termux/termux-boot", r"termux-boot-app_.*github.*\.apk$"
        ),
        "Termux:API": download_github_asset(
            "termux/termux-api", r"termux-api-app_.*github.*\.apk$"
        ),
        "Magisk (opcional root/ACC)": download_github_asset(
            "topjohnwu/Magisk", r"^Magisk-v.*\.apk$", rename_ext=".zip"
        ),
        "ACC (control de carga Magisk)": download_github_asset(
            "VR-25/acc", r"^acc_.*\.zip$"
        ),
        "Modelo Qwen2.5-0.5B-Instruct (Q4_0)": _download_file(
            "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_0.gguf",
            DL_DIR / "qwen2.5-0.5b-instruct-q4_0.gguf",
            min_bytes=200_000_000,
        ),
        "TWRP oneplus2": download_twrp(),
        "LineageOS 17.1 oneplus2": download_lineageos_17_1(),
    }

    print("\n=== Resumen de descargas ===")
    ok_all = True
    for label, ok in results.items():
        status = "OK" if ok else "PENDIENTE"
        print(f"  [{status:9s}] {label}")
        if not ok:
            ok_all = False
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
