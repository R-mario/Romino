#!/usr/bin/env python3
"""Valida el token en .env mediante Telegram getMe sin exponer el token en salida."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bot.config import BotConfig


def main() -> int:
    cfg = BotConfig.load(REPO_ROOT / ".env")
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/getMe"
    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if not data.get("ok"):
        print("ERROR: Telegram rechazó el token.")
        return 1

    bot_info = data["result"]
    print(f"Bot ID:                    {bot_info.get('id')}")
    print(f"Username:                  @{bot_info.get('username')}")
    print(f"First name:                {bot_info.get('first_name')}")
    print(f"Can join groups:           {bot_info.get('can_join_groups')}")
    print(f"Read all group messages:   {bot_info.get('can_read_all_group_messages')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
