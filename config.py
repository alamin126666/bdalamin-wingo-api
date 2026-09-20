"""Application configuration loaded from environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

DEFAULT_SOURCE_API = (
    "https://draw.ar-lottery01.com/WinGo/WinGo_1M/GetHistoryIssuePage.json"
)
DEFAULT_COLLECTION_PATH = "WinGo/WinGo_1M/GetHistoryPage"


class ConfigurationError(ValueError):
    """Raised when required application configuration is invalid or missing."""


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(f"Missing required environment variable: {name}")
    return value


def _positive_int(name: str, default: int, *, maximum: int | None = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value <= 0 or (maximum is not None and value > maximum):
        limit = f" and <= {maximum}" if maximum is not None else ""
        raise ConfigurationError(f"{name} must be > 0{limit}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    owner_id: int
    firebase_db_url: str
    firebase_credentials_json: str | None
    firebase_credentials_file: Path | None
    source_api: str
    collection_path: str
    max_data: int
    interval: int
    request_timeout: int = 20


def load_settings() -> Settings:
    owner_raw = _required("OWNER_ID")
    try:
        owner_id = int(owner_raw)
    except ValueError as exc:
        raise ConfigurationError("OWNER_ID must be a numeric Telegram user ID") from exc
    if owner_id <= 0:
        raise ConfigurationError("OWNER_ID must be greater than zero")

    credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip() or None
    credentials_file_raw = os.getenv("FIREBASE_CREDENTIALS_FILE", "").strip()
    credentials_file = Path(credentials_file_raw) if credentials_file_raw else Path(
        "firebase-service-account.json"
    )
    if not credentials_json and not credentials_file.is_file():
        raise ConfigurationError(
            "Provide FIREBASE_CREDENTIALS_JSON or a local firebase-service-account.json file"
        )

    firebase_db_url = _required("FIREBASE_DB_URL").rstrip("/")
    if not (firebase_db_url.startswith("https://") or firebase_db_url.startswith("http://")):
        raise ConfigurationError("FIREBASE_DB_URL must be an http(s) URL")

    source_api = os.getenv("SOURCE_API", DEFAULT_SOURCE_API).strip()
    collection_path = os.getenv("COLLECTION_PATH", DEFAULT_COLLECTION_PATH).strip().strip("/")
    if not source_api:
        raise ConfigurationError("SOURCE_API cannot be empty")
    if not collection_path:
        raise ConfigurationError("COLLECTION_PATH cannot be empty")

    max_data = _positive_int("MAX_DATA", 1000, maximum=1000)
    interval = _positive_int("INTERVAL", 60)
    request_timeout = _positive_int("REQUEST_TIMEOUT", 20)

    # Validate the JSON at startup without logging its contents.
    if credentials_json:
        try:
            parsed: Any = json.loads(credentials_json)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("FIREBASE_CREDENTIALS_JSON is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ConfigurationError("FIREBASE_CREDENTIALS_JSON must contain a JSON object")
        for key in ("type", "project_id", "private_key", "client_email"):
            if not parsed.get(key):
                raise ConfigurationError(
                    f"FIREBASE_CREDENTIALS_JSON is missing service-account field: {key}"
                )

    return Settings(
        bot_token=_required("BOT_TOKEN"),
        owner_id=owner_id,
        firebase_db_url=firebase_db_url,
        firebase_credentials_json=credentials_json,
        firebase_credentials_file=credentials_file,
        source_api=source_api,
        collection_path=collection_path,
        max_data=max_data,
        interval=interval,
        request_timeout=request_timeout,
    )
