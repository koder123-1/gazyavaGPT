"""Ссылки на файлы «Сливов»: deep-link `/start leak_<id>` и кнопки «Поделиться».

Ссылку можно кинуть в любой чат. Человек открывает её, попадает в бота — и
бот сразу присылает этот файл с комментарием. Если перед ботом стоит гейт
подписки, файл запоминается и уходит после подтверждения подписки.
"""

from __future__ import annotations

import contextlib
from urllib.parse import urlencode

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from i18n import t
from store import Store

PAYLOAD_PREFIX = "leak_"
PENDING_PREFIX = "pending_leak:"


def parse_payload(payload: str) -> int:
    """`leak_12` -> 12, всё остальное -> 0."""
    raw = (payload or "").strip()
    if not raw.lower().startswith(PAYLOAD_PREFIX):
        return 0
    value = raw[len(PAYLOAD_PREFIX) :].strip()
    return int(value) if value.isdigit() else 0


def pending_key(user_id: int) -> str:
    return f"{PENDING_PREFIX}{user_id}"


async def remember_pending(store: Store, user_id: int, leak_id: int) -> None:
    """Запоминает файл, если до него не пустил гейт подписки."""
    if leak_id > 0:
        await store.set_setting(pending_key(user_id), str(leak_id))


async def take_pending(store: Store, user_id: int) -> int:
    key = pending_key(user_id)
    raw = await store.get_setting(key)
    if raw is None:
        return 0
    await store.delete_setting(key)
    return int(raw) if raw.isdigit() else 0


def deep_link(username: str, leak_id: int) -> str:
    name = (username or "").strip().lstrip("@")
    if not name or leak_id <= 0:
        return ""
    return f"https://t.me/{name}?start={PAYLOAD_PREFIX}{leak_id}"


def share_url(username: str, leak_id: int, title: str = "") -> str:
    """Ссылка для системного «Поделиться»: deep-link + подпись."""
    link = deep_link(username, leak_id)
    if not link:
        return ""
    params = {"url": link}
    if (title or "").strip():
        params["text"] = title.strip()[:200]
    return "https://t.me/share/url?" + urlencode(params)


def share_keyboard(
    username: str, leak_id: int, lang: str, title: str = ""
) -> InlineKeyboardMarkup | None:
    url = share_url(username, leak_id, title)
    if not url:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t(lang, "leaks.share"), url=url)]]
    )


async def deliver(bot: Bot, store: Store, chat_id: int, leak_id: int) -> bool:
    """Отправляет файл в чат. False — файла уже нет или Telegram не отдал его."""
    row = await store.get_leak(leak_id)
    if not row:
        return False
    title = str(row.get("title") or row.get("file_name") or "Файл").strip()
    comment = str(row.get("comment") or "").strip()
    caption = title + ("\n\n" + comment if comment else "")
    try:
        await bot.send_document(
            chat_id,
            str(row.get("file_id") or ""),
            caption=caption[:1024],
            parse_mode=None,
        )
    except TelegramAPIError:
        return False
    with contextlib.suppress(Exception):
        await store.bump_leak_downloads(leak_id)
    return True