"""Telegram entry point for the BD ALAMIN WinGo Firebase Collector."""

from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any

from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message

from collector import Collector
from config import ConfigurationError, Settings, load_settings
from firebase_client import FirebaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
router = Router()

_settings: Settings
_collector: Collector
_firebase: FirebaseClient


def owner_only(handler):
    async def wrapped(message: Message, *args: Any, **kwargs: Any):
        if not message.from_user or message.from_user.id != _settings.owner_id:
            return
        return await handler(message, *args, **kwargs)

    return wrapped


@router.message(Command("start"))
@owner_only
async def start_command(message: Message) -> None:
    count = await asyncio.to_thread(_firebase.count_records)
    status = "𝗥𝗨𝗡𝗡𝗜𝗡𝗚 🟢" if _collector.is_running else "𝗢𝗙𝗙 🔴"
    await message.answer(
        f"💭 𝗦𝗘𝗥𝗩𝗘𝗥 : {status}\n\n"
        f"🔴 𝗔𝗟𝗟 𝗗𝗔𝗧𝗔 : {count}\n\n"
        "🐍 𝗠𝗔𝗗𝗘 𝗕𝗬 𝗕𝗗 𝗔𝗟𝗔𝗠𝗜𝗡 🐍"
    )


@router.message(Command("on"))
@owner_only
async def on_command(message: Message) -> None:
    started = await _collector.start()
    if started:
        await message.answer(
            "✅ 𝗖𝗢𝗟𝗟𝗘𝗖𝗧𝗢𝗥 : 𝗢𝗡\n\n"
            "💭 Fetching data on every Bangladesh minute (HH:MM:00)."
        )
    else:
        await message.answer("ℹ️ 𝗖𝗢𝗟𝗟𝗘𝗖𝗧𝗢𝗥 : 𝗔𝗟𝗥𝗘𝗔𝗗𝗬 𝗢𝗡")


@router.message(Command("off"))
@owner_only
async def off_command(message: Message) -> None:
    stopped = await _collector.stop()
    if stopped:
        await message.answer("🛑 𝗖𝗢𝗟𝗟𝗘𝗖𝗧𝗢𝗥 : 𝗢𝗙𝗙")
    else:
        await message.answer("ℹ️ 𝗖𝗢𝗟𝗟𝗘𝗖𝗧𝗢𝗥 : 𝗔𝗟𝗥𝗘𝗔𝗗𝗬 𝗢𝗙𝗙")


async def main() -> None:
    global _settings, _collector, _firebase
    _settings = load_settings()
    _firebase = FirebaseClient(_settings)
    _collector = Collector(_settings, _firebase)
    bot = Bot(token=_settings.bot_token)
    dispatcher = Dispatcher()
    dispatcher.include_router(router)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except NotImplementedError:
            pass

    logger.info("Telegram bot started")
    polling_task = asyncio.create_task(dispatcher.start_polling(bot), name="telegram-polling")
    stop_task = asyncio.create_task(stop_event.wait(), name="shutdown-wait")
    try:
        done, _ = await asyncio.wait(
            {polling_task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if polling_task in done:
            await polling_task
    finally:
        if not polling_task.done():
            polling_task.cancel()
            await asyncio.gather(polling_task, return_exceptions=True)
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
        await _collector.shutdown()
        await bot.session.close()
        logger.info("Telegram bot stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigurationError as exc:
        logger.critical("Configuration error: %s", exc)
        raise SystemExit(2) from exc
