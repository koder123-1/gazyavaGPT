"""Команды управления группой: кик, бан, мут, предупреждения, админка, чистка.

Доступ: администраторы бота (роли) ИЛИ администраторы самого чата Telegram.
Бот не может быть «владельцем» группы по правилам Telegram, но с правами
администратора управляет чатом полностью: см. /group.
"""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from aiogram import BaseMiddleware, Bot, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import ChatMemberAdministrator, Message, TelegramObject

from config import Settings
from i18n import detect_lang, normalize_lang, t
from moderation import MUTE_PERMISSIONS, FULL_PERMISSIONS
from roles import has_admin_access, resolve_role
from store import Store

log = logging.getLogger("groupadmin")
router = Router(name="groupadmin")

RIGHTS_HUMAN = {
    "can_restrict_members": "ограничивать участников / restrict members",
    "can_delete_messages": "удалять сообщения / delete messages",
    "can_invite_users": "приглашать / invite users",
    "can_pin_messages": "закреплять / pin messages",
    "can_promote_members": "назначать админов / promote members",
}

# Telegram отвечает по-разному на типовые ошибки модерации. Пользователю
# показываем понятную фразу, а не сырой текст сервера.
_ERROR_KEYS = (
    ("invalid user_id", "group.target_channel"),
    ("user not found", "group.target_not_found"),
    ("participant", "group.target_not_found"),
    ("already an administrator", "group.already_admin"),
    ("chat owner", "group.owner_immutable"),
    ("not enough rights", "group.failed"),
    ("chat_admin_required", "group.failed"),
)


def _friendly_error(exc: Exception) -> str:
    text = str(exc).lower()
    for needle, key in _ERROR_KEYS:
        if needle in text:
            return key
    return "group.failed"

# Предупреждения живут в памяти: после рестарта счётчик начинается заново.
_strikes: dict[tuple[int, int], list[float]] = defaultdict(list)


def _lang(settings: Settings, message: Message) -> str:
    return normalize_lang(settings.default_lang) if message.chat.type != "private" else normalize_lang(
        detect_lang(message.text)
    )


def push_strike(chat_id: int, user_id: int, window: int = 24 * 3600) -> int:
    """Добавляет предупреждение и возвращает их количество."""
    now = time.monotonic()
    span = max(60, window or 24 * 3600)
    bucket = [ts for ts in _strikes[(chat_id, user_id)] if now - ts < span]
    bucket.append(now)
    _strikes[(chat_id, user_id)] = bucket
    return len(bucket)


def clear_strikes(chat_id: int, user_id: int) -> None:
    _strikes.pop((chat_id, user_id), None)


def strike_count(chat_id: int, user_id: int) -> int:
    return len(_strikes.get((chat_id, user_id), []))


async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError:
        return False
    return getattr(member, "status", None) in {"administrator", "creator"}


async def has_group_access(
    message: Message, bot: Bot, settings: Settings, store: Store
) -> bool:
    user = message.from_user
    if user is None:
        return False
    if has_admin_access(await resolve_role(user.id, settings, store)):
        return True
    return await is_chat_admin(bot, message.chat.id, user.id)


async def bot_rights(bot: Bot, chat_id: int) -> ChatMemberAdministrator | None:
    try:
        # Именно bot.id: chat_id — это ID чата (у супергруппы отрицательный),
        # а не пользователя. Раньше здесь стоял chat_id, и проверка прав
        # всегда падала с «не хватает прав администратора».
        member = await bot.get_chat_member(chat_id, bot.id)
    except TelegramAPIError:
        return None
    if isinstance(member, ChatMemberAdministrator):
        return member
    return None


async def _require_rights(
    message: Message, bot: Bot, lang: str, *rights: str
) -> bool:
    member = await bot_rights(bot, message.chat.id)
    if member is None:
        await message.reply(
            t(lang, "group.need_rights", rights=", ".join(RIGHTS_HUMAN[r] for r in rights))
        )
        return False
    missing = [RIGHTS_HUMAN[r] for r in rights if not getattr(member, r, False)]
    if missing:
        await message.reply(t(lang, "group.need_rights", rights=", ".join(missing)))
        return False
    return True


def _target_id(message: Message) -> str | None:
    reply = message.reply_to_message
    if reply is not None:
        if reply.sender_chat is not None:
            return str(reply.sender_chat.id)
        if reply.from_user is not None:
            return str(reply.from_user.id)
    parts = (message.text or "").split()
    if len(parts) < 2:
        return None
    # Ищем ID/упоминание среди аргументов: /mute 60 @user и /mute @user 60.
    for token in parts[1:]:
        raw = token.lstrip("@").strip()
        if token.startswith("@") and raw:
            return raw
        if raw.lstrip("-").isdigit():
            return raw
    return None


async def resolve_target(
    message: Message, bot: Bot, lang: str
) -> tuple[int, str] | None:
    """(id, имя) нарушителя из реплая или первого аргумента."""
    reply = message.reply_to_message
    if reply is not None:
        if reply.sender_chat is not None:
            return reply.sender_chat.id, reply.sender_chat.title or "канал"
        if reply.from_user is not None:
            return reply.from_user.id, reply.from_user.first_name or "участник"

    raw = _target_id(message)
    if not raw:
        await message.reply(t(lang, "group.need_reply"))
        return None
    if raw.lstrip("-").isdigit():
        return int(raw), f"id {raw}"
    # Telegram не умеет искать участника по @username в getChatMember:
    # просим реплай или числовой ID.
    await message.reply(t(lang, "group.no_username"))
    return None


def _minutes(message: Message, default: int) -> int:
    parts = (message.text or "").split()
    # /purge 20 — сколько последних сообщений удалить.
    for chunk in parts[1:]:
        if chunk.isdigit():
            return max(1, min(int(chunk), 100000))
    return max(1, default)


def _reason(message: Message) -> str:
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) == 3 and not parts[2].startswith("@"):
        return parts[2].strip()[:200]
    return ""


# --------------------------------------------------------------------------- длительности
# «1час», «30 мин», «2ч30м», «1 день», «90» (минуты) — всё это понимаем.
_DURATION_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*([A-Za-zА-Яа-яЁё]+)")
_BARE_MINUTES_RE = re.compile(r"(\d+(?:[.,]\d+)?)(?=\s|$)")
_UNIT_SECONDS = {
    "секунд": 1, "сек": 1, "с": 1, "second": 1, "sec": 1, "s": 1,
    "минут": 60, "мин": 60, "м": 60, "minute": 60, "min": 60, "m": 60,
    "часов": 3600, "час": 3600, "ч": 3600, "hour": 3600, "hr": 3600, "h": 3600,
    "дней": 86400, "день": 86400, "дня": 86400, "дн": 86400, "д": 86400, "сут": 86400,
    "day": 86400, "d": 86400,
    "недель": 604800, "неделя": 604800, "нед": 604800, "week": 604800, "w": 604800,
}
_UNIT_ORDER = sorted(_UNIT_SECONDS, key=len, reverse=True)


def _unit_seconds(unit: str) -> int | None:
    unit = unit.lower().strip(".,")
    for stem in _UNIT_ORDER:
        if unit.startswith(stem):
            return _UNIT_SECONDS[stem]
    return None


def parse_duration(raw: str, default_minutes: int) -> tuple[int, str]:
    """Разбирает начало строки как срок. Возвращает (секунды, причина)."""
    text = (raw or "").strip()
    default = max(60, int(default_minutes) * 60)
    if not text:
        return default, ""
    total = 0.0
    rest = text
    while rest:
        match = _DURATION_RE.match(rest)
        if match:
            seconds = _unit_seconds(match.group(2))
            if seconds is None:
                break
            total += float(match.group(1).replace(",", ".")) * seconds
            rest = rest[match.end():].lstrip(" ,")
            continue
        if total <= 0:
            bare = _BARE_MINUTES_RE.match(rest)
            if bare:
                total += float(bare.group(1).replace(",", ".")) * 60
                rest = rest[bare.end():].lstrip(" ,")
                continue
        break
    if total <= 0:
        return default, text
    seconds_total = int(max(10, min(total, 365 * 86400)))
    reason = rest.strip(" ,:-—").strip()
    return seconds_total, reason[:200]


def format_duration(seconds: int, lang: str = "ru") -> str:
    """«1 ч 30 мин», «2 дн.», «45 мин»."""
    seconds = max(0, int(seconds))
    labels = {
        "ru": {86400: "д", 3600: "ч", 60: "мин", 1: "с"},
        "uk": {86400: "д", 3600: "год", 60: "хв", 1: "с"},
        "be": {86400: "дзень", 3600: "г", 60: "хв", 1: "с"},
        "en": {86400: "d", 3600: "h", 60: "min", 1: "s"},
    }[lang] if lang in {"ru", "uk", "be", "en"} else {86400: "d", 3600: "h", 60: "min", 1: "s"}
    parts = []
    for size in (86400, 3600, 60, 1):
        if seconds >= size:
            value = seconds // size
            seconds -= value * size
            parts.append(f"{value} {labels[size]}")
    return " ".join(parts) or "0 мин"


def _command_args(message: Message) -> str:
    parts = (message.text or "").strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _args_without_target(message: Message) -> str:
    """Текст после команды без ID/упоминания цели."""
    args = _command_args(message)
    if message.reply_to_message is not None or not args:
        return args
    tokens = args.split()
    result = []
    removed = False
    for token in tokens:
        raw = token.lstrip("@")
        is_target = bool(token.startswith("@") and raw) or raw.lstrip("-").isdigit()
        if is_target and not removed:
            removed = True
            continue
        result.append(token)
    return " ".join(result)


# --------------------------------------------------------------------------- активные муты
# Нужны, чтобы удалять сообщения, даже если ограничение Telegram не сработало.
_muted: dict[tuple[int, int], float] = {}


def remember_mute(chat_id: int, user_id: int, seconds: int) -> None:
    now = time.monotonic()
    _muted[(chat_id, user_id)] = now + max(1, int(seconds))
    if len(_muted) > 2000:
        for key in [k for k, until in _muted.items() if until <= now]:
            _muted.pop(key, None)


def forget_mute(chat_id: int, user_id: int) -> None:
    _muted.pop((chat_id, user_id), None)


def mute_seconds_left(chat_id: int, user_id: int) -> int:
    until = _muted.get((chat_id, user_id))
    if not until:
        return 0
    left = until - time.monotonic()
    if left <= 0:
        _muted.pop((chat_id, user_id), None)
        return 0
    return int(left)


class MutedMiddleware(BaseMiddleware):
    """Удаляет всё, что пишет замьюченный, пока не истечёт срок."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)
        chat = event.chat
        user = event.from_user
        if (
            chat.type not in {"group", "supergroup"}
            or user is None
            or user.is_bot
            or mute_seconds_left(chat.id, user.id) <= 0
        ):
            return await handler(event, data)
        with contextlib.suppress(TelegramAPIError):
            await event.delete()
        return None


async def _delete_replied(message: Message, bot: Bot) -> None:
    """Удаляет сообщение нарушителя, на которое ответили командой."""
    replied = message.reply_to_message
    if replied is None:
        return
    with contextlib.suppress(TelegramAPIError):
        await bot.delete_message(message.chat.id, replied.message_id)


def _clean_reason(raw: str) -> str:
    return (raw or "").strip(" ,:-—").strip()[:200]


async def _deny_admin_target(message: Message, bot: Bot, target_id: int, lang: str) -> bool:
    """Не даём трогать админов чата: иначе бот воюет с командой."""
    if await is_chat_admin(bot, message.chat.id, target_id):
        await message.reply(t(lang, "group.only_admins"))
        return True
    if message.from_user and target_id == message.from_user.id:
        await message.reply(t(lang, "group.only_admins"))
        return True
    return False


# --------------------------------------------------------------------------- команды
@router.message(Command("group"))
async def cmd_group(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    if message.chat.type == "private":
        await message.reply(
            "🛡 Команды группы работают только в группе. Добавь меня в чат и дай права."
        )
        return
    if not await has_group_access(message, bot, settings, store):
        await message.reply(t(_lang(settings, message), "group.only_admins"))
        return
    lang = _lang(settings, message)
    member = await bot_rights(bot, message.chat.id)
    if member is None:
        await message.reply(
            t(
                lang,
                "group.need_rights",
                rights=", ".join(RIGHTS_HUMAN.values()),
            )
        )
        return
    missing = [RIGHTS_HUMAN[r] for r in RIGHTS_HUMAN if not getattr(member, r, False)]
    text = t(lang, "group.panel")
    if missing:
        text += "\n\n" + t(lang, "group.need_rights", rights=", ".join(missing))
    await message.reply(text)


async def _moderate(
    message: Message,
    bot: Bot,
    settings: Settings,
    store: Store,
    *,
    right: str,
    action: str,
) -> None:
    lang = _lang(settings, message)
    if message.chat.type == "private":
        await message.reply(t(lang, "err.private_only", username=settings.bot_name))
        return
    if not await has_group_access(message, bot, settings, store):
        await message.reply(t(lang, "group.only_admins"))
        return
    if not await _require_rights(message, bot, lang, right):
        return
    target = await resolve_target(message, bot, lang)
    if target is None:
        return
    target_id, name = target
    # Каналы и анонимные админы не бывают «участниками»: Telegram вернёт
    # invalid user_id. Для назначения/снятия админки нужен живой пользователь.
    if action in {"promote", "demote"} and target_id <= 0:
        await message.reply(t(lang, "group.target_channel"))
        return
    if await _deny_admin_target(message, bot, target_id, lang):
        return
    safe_name = escape(name)

    try:
        if action == "kick":
            until = datetime.now(timezone.utc) + timedelta(seconds=60)
            await bot.ban_chat_member(message.chat.id, target_id, until_date=until)
            clear_strikes(message.chat.id, target_id)
            forget_mute(message.chat.id, target_id)
            text = t(lang, "group.done_kick", name=safe_name)
            reason = _clean_reason(_args_without_target(message))
            if reason:
                text += t(lang, "group.with_reason", reason=escape(reason))
            await message.reply(text)
            await _delete_replied(message, bot)
        elif action == "ban":
            await bot.ban_chat_member(message.chat.id, target_id)
            await store.set_banned(target_id, True)
            clear_strikes(message.chat.id, target_id)
            forget_mute(message.chat.id, target_id)
            text = t(lang, "group.done_ban", name=safe_name)
            reason = _clean_reason(_args_without_target(message))
            if reason:
                text += t(lang, "group.with_reason", reason=escape(reason))
            await message.reply(text)
            await _delete_replied(message, bot)
        elif action == "unban":
            await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
            await store.set_banned(target_id, False)
            await message.reply(t(lang, "group.done_unban", name=safe_name))
        elif action == "mute":
            seconds, reason = parse_duration(
                _args_without_target(message), settings.mute_minutes
            )
            until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            await bot.restrict_chat_member(
                message.chat.id,
                target_id,
                permissions=MUTE_PERMISSIONS,
                until_date=until,
                use_independent_chat_permissions=True,
            )
            remember_mute(message.chat.id, target_id, seconds)
            text = t(
                lang, "group.muted", name=safe_name, duration=format_duration(seconds, lang)
            )
            if reason:
                text += t(lang, "group.muted_reason", reason=escape(reason))
            await message.reply(text)
            await _delete_replied(message, bot)
        elif action == "unmute":
            await bot.restrict_chat_member(
                message.chat.id,
                target_id,
                permissions=FULL_PERMISSIONS,
                use_independent_chat_permissions=True,
            )
            clear_strikes(message.chat.id, target_id)
            forget_mute(message.chat.id, target_id)
            await message.reply(t(lang, "group.done_unmute", name=safe_name))
        elif action == "warn":
            count = push_strike(
                message.chat.id, target_id, settings.strike_window
            )
            reason = _reason(message)
            text = f"⚠️ {safe_name}: {count}/{settings.strike_limit}"
            if reason:
                text += f" — {escape(reason)}"
            await message.reply(text)
            if settings.strike_limit > 0 and count >= settings.strike_limit:
                await _apply_strike_action(message, bot, settings, lang, target_id, safe_name)
        elif action == "promote":
            await bot.promote_chat_member(
                message.chat.id,
                target_id,
                can_delete_messages=True,
                can_restrict_members=True,
                can_invite_users=True,
                can_pin_messages=True,
                can_manage_video_chats=True,
                can_change_info=False,
                can_promote_members=False,
            )
            await message.reply(t(lang, "group.done_promote", name=safe_name))
        elif action == "demote":
            await bot.promote_chat_member(
                message.chat.id,
                target_id,
                can_delete_messages=False,
                can_restrict_members=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_manage_video_chats=False,
                can_change_info=False,
                can_promote_members=False,
            )
            await message.reply(t(lang, "group.done_demote", name=safe_name))
        elif action == "del":
            replied = message.reply_to_message
            if replied is None:
                await message.reply(t(lang, "group.need_reply"))
                return
            await bot.delete_message(message.chat.id, replied.message_id)
            with contextlib.suppress(TelegramAPIError):
                await message.delete()
    except TelegramAPIError as exc:
        log.warning("Модерация %s в %s не удалась: %s", action, message.chat.id, exc)
        await message.reply(t(lang, _friendly_error(exc)))


async def _apply_strike_action(
    message: Message, bot: Bot, settings: Settings, lang: str, target_id: int, name: str
) -> None:
    action = settings.antispam_action
    until = datetime.now(timezone.utc) + timedelta(minutes=max(1, settings.mute_minutes))
    try:
        if action == "mute":
            await bot.restrict_chat_member(
                message.chat.id,
                target_id,
                permissions=MUTE_PERMISSIONS,
                until_date=until,
                use_independent_chat_permissions=True,
            )
            remember_mute(message.chat.id, target_id, settings.mute_minutes * 60)
            await message.reply(
                t(lang, "group.done_mute", name=name, minutes=settings.mute_minutes)
            )
        elif action == "kick":
            await bot.ban_chat_member(
                message.chat.id, target_id, until_date=datetime.now(timezone.utc) + timedelta(seconds=60)
            )
            forget_mute(message.chat.id, target_id)
            await message.reply(t(lang, "group.done_kick", name=name))
        elif action == "ban":
            await bot.ban_chat_member(message.chat.id, target_id)
            forget_mute(message.chat.id, target_id)
            await message.reply(t(lang, "group.done_ban", name=name))
    except TelegramAPIError as exc:
        log.warning("Не смог применить наказание: %s", exc)
    finally:
        clear_strikes(message.chat.id, target_id)


@router.message(Command("kick"))
async def cmd_kick(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_restrict_members", action="kick"
    )


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_restrict_members", action="ban"
    )


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_restrict_members", action="unban"
    )


@router.message(Command("mute"))
async def cmd_mute(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_restrict_members", action="mute"
    )


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_restrict_members", action="unmute"
    )


@router.message(Command("warn"))
async def cmd_warn(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_restrict_members", action="warn"
    )


@router.message(Command("promote"))
async def cmd_promote(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_promote_members", action="promote"
    )


@router.message(Command("demote"))
async def cmd_demote(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_promote_members", action="demote"
    )


@router.message(Command("del", "delete"))
async def cmd_del(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    await _moderate(
        message, bot, settings, store, right="can_delete_messages", action="del"
    )


@router.message(Command("pin"))
async def cmd_pin(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    """Закрепляет сообщение, на которое ответили командой /pin."""
    lang = _lang(settings, message)
    if message.chat.type != "private":
        if not await has_group_access(message, bot, settings, store):
            await message.reply(t(lang, "group.only_admins"))
            return
        if not await _require_rights(message, bot, lang, "can_pin_messages"):
            return
    target = message.reply_to_message
    if target is None:
        await message.reply(t(lang, "pin.need_reply"))
        return
    silent = "тихо" in (message.text or "").lower() or "silent" in (message.text or "").lower()
    try:
        await bot.pin_chat_message(
            chat_id=message.chat.id,
            message_id=target.message_id,
            disable_notification=silent,
        )
        await message.reply(t(lang, "pin.done"))
    except TelegramAPIError as exc:
        log.warning("Не удалось закрепить сообщение: %s", exc)
        await message.reply(t(lang, "pin.failed"))


@router.message(Command("unpin"))
async def cmd_unpin(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    """Открепляет сообщение из реплая или последнее закреплённое."""
    lang = _lang(settings, message)
    if message.chat.type != "private":
        if not await has_group_access(message, bot, settings, store):
            await message.reply(t(lang, "group.only_admins"))
            return
        if not await _require_rights(message, bot, lang, "can_pin_messages"):
            return
    target = message.reply_to_message
    try:
        if target is not None:
            await bot.unpin_chat_message(
                chat_id=message.chat.id, message_id=target.message_id
            )
        else:
            await bot.unpin_chat_message(chat_id=message.chat.id)
        await message.reply(t(lang, "pin.unpinned"))
    except TelegramAPIError as exc:
        log.warning("Не удалось открепить сообщение: %s", exc)
        await message.reply(t(lang, "pin.failed"))


@router.message(Command("purge"))
async def cmd_purge(message: Message, bot: Bot, settings: Settings, store: Store) -> None:
    lang = _lang(settings, message)
    if message.chat.type == "private":
        await message.reply(t(lang, "err.private_only", username=settings.bot_name))
        return
    if not await has_group_access(message, bot, settings, store):
        await message.reply(t(lang, "group.only_admins"))
        return
    if not await _require_rights(message, bot, lang, "can_delete_messages"):
        return
    count = _minutes(message, 20)
    count = max(1, min(count, 100))
    ids = list(range(message.message_id - count, message.message_id + 1))
    deleted = 0
    for start in range(0, len(ids), 100):
        batch = ids[start : start + 100]
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_messages(message.chat.id, batch)
            deleted += len(batch)
    with contextlib.suppress(TelegramAPIError):
        notice = await message.reply(f"🧹 {deleted}")
        await bot.delete_message(message.chat.id, notice.message_id)


@router.message(Command("info", "whois"))
async def cmd_info(
    message: Message, bot: Bot, settings: Settings, store: Store
) -> None:
    lang = _lang(settings, message)
    if message.chat.type == "private":
        await message.reply(t(lang, "err.private_only", username=settings.bot_name))
        return
    if not await has_group_access(message, bot, settings, store):
        await message.reply(t(lang, "group.only_admins"))
        return
    target = await resolve_target(message, bot, lang)
    if target is None:
        return
    target_id, name = target
    role = await resolve_role(target_id, settings, store)
    banned = await store.is_banned(target_id)
    text = (
        f"👤 <b>{escape(name)}</b>\n"
        f"ID: <code>{target_id}</code>\n"
        f"⚠️ Предупреждений: {strike_count(message.chat.id, target_id)}/{settings.strike_limit}\n"
        f"🤖 Доступ к боту: {'закрыт' if banned else 'открыт'}\n"
        f"🎖 Роль: {role or '—'}"
    )
    await message.reply(text)