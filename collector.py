"""WinGo source API collector and bounded Firebase persistence."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from config import Settings
from firebase_client import FirebaseClient

logger = logging.getLogger(__name__)
BANGLADESH_TZ = ZoneInfo("Asia/Dhaka")
SOURCE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "Chrome/120.0 Mobile Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": "https://draw.ar-lottery01.com/",
}


class Collector:
    """Fetch, validate, de-duplicate, order, and persist lottery results."""

    def __init__(self, settings: Settings, firebase: FirebaseClient) -> None:
        self.settings = settings
        self.firebase = firebase
        self._task: asyncio.Task[None] | None = None
        self._state_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self) -> bool:
        """Start exactly one loop. Return False if it was already running."""
        async with self._state_lock:
            if self.is_running:
                return False
            self._task = asyncio.create_task(self._run(), name="wingo-collector")
            logger.info("Collector started")
            return True

    async def stop(self) -> bool:
        """Cancel only the collector task; Telegram polling remains alive."""
        async with self._state_lock:
            task = self._task
            if task is None or task.done():
                self._task = None
                return False
            task.cancel()
            self._task = None

        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.info("Collector stopped")
        return True

    async def shutdown(self) -> None:
        await self.stop()

    async def _run(self) -> None:
        timeout = aiohttp.ClientTimeout(total=self.settings.request_timeout)
        try:
            async with aiohttp.ClientSession(
                timeout=timeout, headers=SOURCE_HEADERS
            ) as session:
                while True:
                    await self.collect_once(session)
                    # Align to Bangladesh wall-clock minute boundaries
                    # (12:34:00, 12:35:00, ...), rather than sleeping 60
                    # seconds from the /on command or previous fetch time.
                    now = datetime.now(BANGLADESH_TZ)
                    next_minute = now.replace(second=0, microsecond=0) + timedelta(
                        minutes=1
                    )
                    delay = max(0.0, (next_minute - now).total_seconds())
                    logger.info(
                        "Next Bangladesh minute fetch at %s (in %.2f seconds)",
                        next_minute.strftime("%Y-%m-%d %H:%M:%S %Z"),
                        delay,
                    )
                    await asyncio.sleep(delay)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A single unexpected cycle must not take down the bot process.
            logger.exception("Collector loop stopped after an unexpected error")

    async def collect_once(self, session: aiohttp.ClientSession) -> bool:
        """Run one safe fetch/process/write cycle. Return whether it succeeded."""
        logger.info("Fetching source API")
        try:
            async with session.get(self.settings.source_api) as response:
                logger.info("Source API HTTP %s", response.status)
                response.raise_for_status()
                payload = await response.json(content_type=None)
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            logger.error("Source API timeout")
            return False
        except aiohttp.ClientResponseError as exc:
            logger.error("Source API HTTP error: %s", exc.status)
            return False
        except (aiohttp.ClientError, ValueError) as exc:
            logger.error("Source API request/JSON error: %s", exc)
            return False

        source_records = self._parse_payload(payload)
        if source_records is None:
            logger.error("Source API response has an invalid structure")
            return False
        logger.info("Received %d source records", len(source_records))

        # Firebase Admin SDK calls are synchronous, so keep them off the event loop.
        try:
            async with self._write_lock:
                existing = await asyncio.to_thread(self.firebase.read_records)
                merged, new_issues = self._merge(existing, source_records)
                if new_issues:
                    await asyncio.to_thread(self.firebase.replace_records, merged)
                    for issue in new_issues:
                        logger.info("New issue saved: %s", issue)
                for issue in self._duplicate_issues(existing, source_records):
                    logger.info("Duplicate issue skipped: %s", issue)
                logger.info("Firebase total: %d", len(merged))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Firebase write failed")
            return False
        return True

    @staticmethod
    def _parse_payload(payload: Any) -> list[dict[str, Any]] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        items = data.get("list") if isinstance(data, dict) else None
        if not isinstance(items, list):
            return None

        parsed: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            issue = str(item.get("issueNumber", "")).strip()
            if not issue or issue in seen:
                continue
            if "number" not in item or "color" not in item or "premium" not in item or "sum" not in item:
                logger.warning("Skipping incomplete source record: %s", issue or "unknown")
                continue
            seen.add(issue)
            parsed.append(
                {
                    "issueNumber": issue,
                    "number": str(item["number"]),
                    "color": str(item["color"]),
                    "premium": str(item["premium"]),
                    "sum": item["sum"],
                }
            )
        return parsed

    def _merge(
        self,
        existing: list[dict[str, Any]],
        incoming: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        by_issue: dict[str, dict[str, Any]] = {}
        for record in existing:
            issue = str(record.get("issueNumber", "")).strip()
            if issue and issue not in by_issue:
                by_issue[issue] = dict(record)

        new_issues: list[str] = []
        saved_at = datetime.now(timezone.utc).isoformat()
        for record in incoming:
            issue = record["issueNumber"]
            if issue not in by_issue:
                by_issue[issue] = {**record, "savedAt": saved_at}
                new_issues.append(issue)

        def newest_key(record: dict[str, Any]) -> tuple[int, int | str]:
            issue = str(record.get("issueNumber", ""))
            if issue.isdigit():
                return (1, int(issue))
            return (0, issue)

        ordered = sorted(
            by_issue.values(),
            key=newest_key,
            reverse=True,
        )[: self.settings.max_data]
        return ordered, new_issues

    @staticmethod
    def _duplicate_issues(
        existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
    ) -> list[str]:
        existing_issues = {str(record.get("issueNumber", "")) for record in existing}
        return [record["issueNumber"] for record in incoming if record["issueNumber"] in existing_issues]
