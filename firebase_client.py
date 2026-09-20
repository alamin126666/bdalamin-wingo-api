"""Firebase Admin SDK wrapper for Realtime Database operations."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import firebase_admin
from firebase_admin import credentials, db

from config import Settings

logger = logging.getLogger(__name__)


class FirebaseClient:
    """Small, isolated client for the single collector database node."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._initialize_app()
        self._reference = db.reference(settings.collection_path)

    def _initialize_app(self) -> None:
        try:
            firebase_admin.get_app()
            return
        except ValueError:
            pass

        if self._settings.firebase_credentials_json:
            info = json.loads(self._settings.firebase_credentials_json)
            credential = credentials.Certificate(info)
        else:
            credential_path: Path = self._settings.firebase_credentials_file  # type: ignore[assignment]
            credential = credentials.Certificate(str(credential_path))

        firebase_admin.initialize_app(
            credential,
            {"databaseURL": self._settings.firebase_db_url},
        )
        logger.info("Firebase Admin SDK initialized")

    def read_records(self) -> list[dict[str, Any]]:
        """Return valid records in numeric-key order, newest first."""
        raw = self._reference.get()
        if not raw:
            return []

        if isinstance(raw, list):
            values = raw
        elif isinstance(raw, dict):
            def numeric_key(item: tuple[str, Any]) -> tuple[int, str]:
                key = str(item[0])
                return (int(key), key) if key.isdigit() else (10**12, key)

            values = [value for _, value in sorted(raw.items(), key=numeric_key)]
        else:
            logger.warning("Firebase collection contains unexpected data; treating it as empty")
            return []

        records: list[dict[str, Any]] = []
        for value in values:
            if isinstance(value, dict) and str(value.get("issueNumber", "")).strip():
                records.append(dict(value))
        return records

    def replace_records(self, records: list[dict[str, Any]]) -> None:
        """Replace the entire node in one set operation."""
        payload = {str(index): record for index, record in enumerate(records, start=1)}
        self._reference.set(payload)

    def count_records(self) -> int:
        return len(self.read_records())
