"""Напоминания и таймеры.

Хранятся в таблице settings под ключом `rem:<user_id>`, поэтому переживают
перезапуск Render. Фоновый цикл раз в 20 секунд проверяет сроки и пишет в тот
чат, где напоминание создали (личка, группа или канал).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import Message

from config import Settings
from i18n import normalize_lang, t
from store import Store

log = logging.getLogger("reminders")
router = Router(name="reminders")

REMINDER_PREFIX = "rem:"
MAX_PER_USER = 10
MAX_AHEAD = timedelta(days=365)
TICK_SECONDS = 20.0

_UNIT_SECONDS = {
    "с": 1,
    "сек": 1,
    "секунда": 1,
    "секунды": 1,
    "секунд": 1,
    "s": 1,
    "м": 60,
    "мин": 60,
    "минута": 60,
    "минуты": 60,
    "минут": 60,
    "m": 60,
    "min": 60,
    "minute": 60,
    "minutes": 60,
    "ч": 3600,
    "час": 3600,
    "часа": 3600,
    "часов": 3600,
    "h": 3600,
    "hour": 3600,
    "hours": 3600,
    "д": 86400,
    "дн": 86400,
    "день": 86400,
    "дня": 86400,
    "дней": 86400,
    "d": 86400,
    "day": 86400,
    "days": 86400,
}
_DURATION_PART = re.compile(
    r"(\d+)\s*"
    r"(секунда|секунды|секунд|сек|с|минута|минуты|минут|мин|м|"
    r"часов|часа|час|ч|день|дня|дней|дн|д|"
    r"minutes|minute|min|hours|hour|days|day|s|m|h|d)",
    re.IGNORECASE,
)
_LEADING_NUMBER = re.compile(r"^(\d+)(?:\s+|$)")


def _key(user_id: int) -> str:
    return f"{REMINDER_PREFIX}{user_id}"


def parse_duration(text: str) -> tuple[int, str] | None:
    """`10м выпить воды` -> (600, 'выпить воды'). Без единицы число = минуты."""
    raw = (text or "").strip()
    if not raw:
        return None
    total = 0
    position = 0
    found = False
    for match in _DURATION_PART.finditer(raw):
        # Между частями «1ч30м» допускаем только пробелы.
        if raw[position : match.start()].strip():
            break
        total += int(match.group(1)) * _UNIT_SECONDS[match.group(2).lower()]
        position = match.end()
        found = True
    if not found:
        match = _LEADING_NUMBER.match(raw)
        if not match:
            return None
        total = int(match.group(1)) * 60
        position = match.end()
    if total <= 0:
        return None
    total = max(5, min(total, int(MAX_AHEAD.total_seconds())))
    return total, raw[position:].strip()


def human_duration(seconds: int) -> str:
    """Компактно и без локализации: «2 д 3 ч», «15 мин», «40 с»."""
    seconds = max(1, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if minutes:
        parts.append(f"{minutes} мин")
    if secs and not days and not hours:
        parts.append(f"{secs} с")
    return " ".join(parts) or "0 с"


def _parse_items(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    items: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            due = datetime.fromisoformat(str(row["due"]))
        except (KeyError, TypeError, ValueError):
            continue
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        items.append(
            {
                "id": int(row.get("id") or 0),
                "chat_id": int(row.get("chat_id") or 0),
                "text": str(row.get("text") or "")[:500],
                "due": due.isoformat(),
                "kind": str(row.get("kind") or "remind"),
                "attempts": int(row.get("attempts") or 0),
            }
        )
    return items


async def _load(store: Store, user_id: int) -> list[dict]:
    return _parse_items(await store.get_setting(_key(user_id)))


async def _save(store: Store, user_id: int, items: list[dict]) -> None:
    if not items:
        await store.delete_setting(_key(user_id))
        return
    await store.set_setting(
        _key(user_id), json.dumps(items, ensure_ascii=False, separators=(",", ":"))
    )


async def _lang(store: Store, settings: Settings, user_id: int) -> str:
    return normalize_lang(await store.get_lang(user_id) or settings.default_lang)


async def add_reminder(
    store: Store,
    settings: Settings,
    *,
    user_id: int,
    chat_id: int,
    text: str,
    seconds: int,
    kind: str = "remind",
) -> dict | None:
    """Добавляет напоминание. None — если у пользователя уже 10 штук."""
    items = await _load(store, user_id)
    if len(items) >= MAX_PER_USER:
        return None
    next_id = max((item["id"] for item in items), default=0) + 1
    due = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    item = {
        "id": next_id,
        "chat_id": chat_id,
        "text": (text or "").strip()[:500],
        "due": due.isoformat(),
        "kind": kind,
        "attempts": 0,
    }
    items.append(item)
    await _save(store, user_id, items)
    return item


async def _deliver(
    bot: Bot, store: Store, settings: Settings, item: dict, user_id: int
) -> bool:
    lang = await _lang(store, settings, user_id)
    name = ""
    with contextlib.suppress(Exception):
        card = await store.user_card(user_id)
        if card:
            name = escape(str(card.get("first_name") or card.get("username") or ""))
    if item["kind"] == "timer":
        text = t(lang, "rem.timer_fired", text=escape(item["text"]))
    else:
        text = t(lang, "rem.fired", text=escape(item["text"]), name=name)
    try:
        await bot.send_message(item["chat_id"], text, parse_mode="HTML")
    except TelegramAPIError:
        log.warning(
            "Напоминание %s не доставлено в %s", item.get("id"), item.get("chat_id")
        )
        return False
    return True


async def _tick(bot: Bot, store: Store, settings: Settings) -> int:
    """Один проход: отправляет всё, что уже наступило. Возвращает число отправок."""
    sent = 0
    try:
        mapping = await store.all_settings()
    except Exception:  # noqa: BLE001 — база может моргнуть
        log.exception("Не удалось прочитать напоминания")
        return 0
    now = datetime.now(timezone.utc)
    for key, raw in list(mapping.items()):
        if not key.startswith(REMINDER_PREFIX):
            continue
        suffix = key[len(REMINDER_PREFIX) :]
        if not suffix.lstrip("-").isdigit():
            continue
        user_id = int(suffix)
        items = _parse_items(raw)
        if not items:
            continue
        keep: list[dict] = []
        changed = False
        for item in items:
            due = datetime.fromisoformat(item["due"])
            if due > now:
                keep.append(item)
                continue
            changed = True
            if await _deliver(bot, store, settings, item, user_id):
                sent += 1
                continue
            # Две попытки на сетевые сбои, потом выбрасываем.
            item["attempts"] = int(item.get("attempts") or 0) + 1
            if item["attempts"] < 3:
                item["due"] = (
                    datetime.now(timezone.utc) + timedelta(minutes=1)
                ).isoformat()
                keep.append(item)
        if changed:
            await _save(store, user_id, keep)
    return sent


async def _loop(
    bot: Bot, store: Store, settings: Settings, interval: float = TICK_SECONDS
) -> None:
    while True:
        try:
            await _tick(bot, store, settings)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен умирать
            log.exception("Ошибка цикла напоминаний")
        await asyncio.sleep(interval)


_task: asyncio.Task | None = None


def start_loop(bot: Bot, store: Store, settings: Settings) -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(bot, store, settings))


async def stop_loop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None


# --------------------------------------------------------------------------- команды
async def _reply_private_hint(message: Message, lang: str, settings: Settings) -> None:
    me = await message.bot.me()
    await message.reply(
        t(lang, "tool.private", username=me.username or settings.bot_name)
    )


def _command_user(message: Message) -> int:
    # В канале автора нет: храним напоминания канала под его chat_id.
    return message.from_user.id if message.from_user else message.chat.id


@router.message(Command("remind", "напомни", "напоминание"))
async def cmd_remind(message: Message, store: Store, settings: Settings) -> None:
    user_id = _command_user(message)
    lang = await _lang(store, settings, user_id)
    raw = (message.text or "").split(maxsplit=1)
    payload = raw[1].strip() if len(raw) > 1 else ""
    parsed = parse_duration(payload)
    if parsed is None:
        await message.reply(t(lang, "rem.help"))
        return
    seconds, text = parsed
    if not text:
        text = t(lang, "rem.default_text")
    item = await add_reminder(
        store,
        settings,
        user_id=user_id,
        chat_id=message.chat.id,
        text=text,
        seconds=seconds,
    )
    if item is None:
        await message.reply(t(lang, "rem.full", limit=MAX_PER_USER))
        return
    await message.reply(
        t(
            lang,
            "rem.set",
            when=human_duration(seconds),
            text=escape(text),
            id=item["id"],
        ),
        parse_mode="HTML",
    )


@router.message(Command("reminders", "напоминания"))
async def cmd_reminders(message: Message, store: Store, settings: Settings) -> None:
    user_id = _command_user(message)
    lang = await _lang(store, settings, user_id)
    items = await _load(store, user_id)
    if not items:
        await message.reply(t(lang, "rem.empty"))
        return
    now = datetime.now(timezone.utc)
    items.sort(key=lambda item: item["due"])
    lines = []
    for item in items:
        due = datetime.fromisoformat(item["due"])
        left = max(1, int((due - now).total_seconds()))
        icon = "⏳" if item["kind"] == "timer" else "🔔"
        lines.append(
            f"{icon} <b>{item['id']}.</b> {escape(item['text'])} — "
            + t(lang, "rem.in_time", when=human_duration(left))
        )
    await message.reply(
        t(lang, "rem.list", count=len(items), items="\n".join(lines)),
        parse_mode="HTML",
    )


@router.message(Command("unremind", "отмени", "убери"))
async def cmd_unremind(message: Message, store: Store, settings: Settings) -> None:
    user_id = _command_user(message)
    lang = await _lang(store, settings, user_id)
    raw = (message.text or "").split(maxsplit=1)
    arg = raw[1].strip() if len(raw) > 1 else ""
    items = await _load(store, user_id)
    if not arg:
        await message.reply(t(lang, "rem.unremind_help"))
        return
    try:
        target = int(arg)
    except ValueError:
        await message.reply(t(lang, "rem.unremind_help"))
        return
    keep = [item for item in items if item["id"] != target]
    if len(keep) == len(items):
        await message.reply(t(lang, "rem.not_found", id=target))
        return
    await _save(store, user_id, keep)
    await message.reply(t(lang, "rem.removed", id=target))


@router.message(Command("timer", "таймер"))
async def cmd_timer(message: Message, store: Store, settings: Settings) -> None:
    user_id = _command_user(message)
    lang = await _lang(store, settings, user_id)
    raw = (message.text or "").split(maxsplit=1)
    payload = raw[1].strip() if len(raw) > 1 else ""

    if payload.lower() in {"stop", "стоп", "off", "выкл"}:
        items = await _load(store, user_id)
        keep = [
            item
            for item in items
            if not (
                item["kind"] == "timer" and item["chat_id"] == message.chat.id
            )
        ]
        removed = len(items) - len(keep)
        await _save(store, user_id, keep)
        await message.reply(t(lang, "rem.timer_stopped", count=removed))
        return

    if not payload:
        seconds, text = 25 * 60, t(lang, "rem.timer_default")
    else:
        parsed = parse_duration(payload)
        if parsed is None:
            await message.reply(t(lang, "timer.help"))
            return
        seconds, text = parsed
        if not text:
            text = t(lang, "rem.timer_default")
    item = await add_reminder(
        store,
        settings,
        user_id=user_id,
        chat_id=message.chat.id,
        text=text,
        seconds=seconds,
        kind="timer",
    )
    if item is None:
        await message.reply(t(lang, "rem.full", limit=MAX_PER_USER))
        return
    await message.reply(
        t(
            lang,
            "rem.timer_set",
            when=human_duration(seconds),
            text=escape(text),
        ),
        parse_mode="HTML",
    )


# В каналах напоминание просто пишет в канал — этим пользуются админы.
for _handler, _commands in (
    (cmd_remind, ("remind", "напомни", "напоминание")),
    (cmd_reminders, ("reminders", "напоминания")),
    (cmd_unremind, ("unremind", "отмени", "убери")),
    (cmd_timer, ("timer", "таймер")),
):
    router.channel_post(Command(*_commands))(_handler)