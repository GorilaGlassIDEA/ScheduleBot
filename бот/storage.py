"""Простое хранилище настроек пользователей в JSON-файле."""

from __future__ import annotations

import json
from pathlib import Path

from scheduler import Settings

DATA_FILE = Path(__file__).parent / "data" / "users.json"


def _load_all() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {}


def _save_all(data: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_settings(user_id: int) -> Settings:
    user = _load_all().get(str(user_id), {})
    return Settings.from_dict(user.get("settings", {}))


def save_settings(user_id: int, settings: Settings) -> None:
    data = _load_all()
    data.setdefault(str(user_id), {})["settings"] = settings.to_dict()
    _save_all(data)


def get_last_input(user_id: int) -> str | None:
    return _load_all().get(str(user_id), {}).get("last_input")


def save_last_input(user_id: int, text: str) -> None:
    data = _load_all()
    data.setdefault(str(user_id), {})["last_input"] = text
    _save_all(data)
