from __future__ import annotations

import os
from pathlib import Path

from dutext.config import DATA_DIR

KEY_FILE = DATA_DIR / "deepseek_key.txt"


def get_api_key() -> str | None:
    env = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env:
        return env
    if KEY_FILE.exists():
        text = KEY_FILE.read_text(encoding="utf-8").strip()
        return text or None
    return None


def set_api_key(key: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip(), encoding="utf-8")


def key_is_set() -> bool:
    return bool(get_api_key())
