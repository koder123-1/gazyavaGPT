"""Алерты админам в Telegram: ошибки ИИ, вебхука, БД и анти-рейд.

Получатель — `ALERT_CHAT_ID`, иначе `OWNER_ID`, иначе первый ID из `ADMIN_IDS`.
Повторные срабатывания одного и того же ключа внутри `ALERT_COOLDOWN` не
спамят: они копятся и уходят одним сообщением с пометкой «повторялось N раз».
"""

from __future__ import annotations

import asyncio
import logging
import time
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import Settings
from store import Store

log = logging.getLogger("alerts")

MAX_TEXT = 3000

_ICONS = {
    "ai": "🧠",
    "webhook": "🪝",
    "db": "🗄",
    "raid": "🛡",
    "error": "⚠️",
}

_TITLES = {
    "ai": "ИИ не отвечает",
    "webhook": "Ошибка запроса",
    "db": "База данных",
    "raid": "Анти-рейд",
    "error": "Ошибка обработчика",
}

_bot: Bot | None = None
_settings: Settings | None = None
_store: Store | None = None
_last: dict[str, float] = {}
_skipped: dict[str, int] = {}
_lock = asyncio.Lock()


def configure(bot: Bot, settings: Settings, store: Store) -> None:
    """Запоминает зависимости на старте: дальше notify можно звать откуда угодно."""
    global _bot, _settings, _store
    _bot = bot
    _settings = settings
    _store = store


def target_id(settings: Settings) -> int:
    if settings.alert_chat_id:
        return int(settings.alert_chat_id)
    if settings.owner_id:
        return int(settings.owner_id)
    ids = sorted(settings.admin_ids)
    return int(ids[0]) if ids else 0


def reset() -> None:
    """Для тестов: забыть историю и зависимости."""
    global _bot, _settings, _store
    _bot = _settings = _store = None
    _last.clear()
    _skipped.clear()


async def notify(
    kind: str,
    text: str,
    *,
    key: str = "",
    force: bool = False,
) -> bool:
    """Отправляет алерт админу. True — сообщение ушло."""
    settings, bot = _settings, _bot
    if settings is None or bot is None or not settings.alerts_enabled:
        return False
    target = target_id(settings)
    if not target:
        return False

    dedup = f"{kind}:{key or text[:80]}"
    now = time.monotonic()
    cooldown = max(30, int(settings.alert_cooldown))
    async with _lock:
        last = _last.get(dedup)
        if not force and last is not None and now - last < cooldown:
            _skipped[dedup] = _skipped.get(dedup, 0) + 1
            return False
        skipped = _skipped.pop(dedup, 0)
        _last[dedup] = now

    icon = _ICONS.get(kind, "🔔")
    title = _TITLES.get(kind, kind)
    body = f"{icon} <b>{escape(title)}</b>\n{escape(str(text).strip()[:MAX_TEXT])}"
    if skipped:
        body += f"\n\n<i>Повторялось ещё {skipped} раз(а).</i>"
    try:
        await bot.send_message(target, body, disable_web_page_preview=True)
    except TelegramAPIError as exc:
        log.warning("Алерт «%s» не доставлен: %s", kind, exc)
        return False
    return True


async def ai_failed(detail: str) -> None:
    await notify("ai", detail, key="ai-down")


async def web_failed(detail: str) -> None:
    await notify("webhook", detail, key=detail[:80])


async def db_down(detail: str = "") -> None:
    await notify("db", detail or "Проверка /health вернула ошибку БД.", key="db")