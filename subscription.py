"""Обязательная подписка на канал: проверка через getChatMember.

Канал задаётся в /admin → Настройки (`required_channel` и `required_channel_url`),
поэтому менять его можно без правки кода и без рестарта.

Проверка идёт через `getChatMember`, поэтому бот должен быть добавлен в канал или
группу (в канал — администратором, иначе Telegram не отдаёт список участников).
Если Telegram не даёт проверить (бот не добавлен), бот не запирает всех: доступ
остаётся, а в лог и владельцу уходит предупреждение.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from html import escape
from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from config import Settings
from i18n import normalize_lang, t
from moderation import ChatAdminCache
from roles import has_admin_access, resolve_role
from runtime import Runtime, load_runtime
from store import Store

log = logging.getLogger("subscription_gate")
router = Router(name="subscription_gate")

CACHE_TTL = 45.0
DISABLED_VALUES = {"", "0", "-", "off", "no", "none", "нет", "выкл"}

SUBSCRIBED = "yes"
NOT_SUBSCRIBED = "no"
UNKNOWN = "unknown"

# (канал, user_id) -> (результат, когда проверяли)
_cache: dict[tuple[str, int], tuple[str, float]] = {}
# Ошибку «бот не в канале» логируем один раз, чтобы не засорять лог.
_warned: set[str] = set()
# Предупреждения в группах: (chat_id, user_id) -> когда показывали.
_warned_in_group: dict[tuple[int, int], float] = {}
# Кеш «сотрудник бота»: resolve_role бьёт в БД, а в группе сообщений много.
_staff_cache: dict[int, tuple[bool, float]] = {}
STAFF_TTL = 300.0
# Кеш Runtime: не дёргать таблицу settings на каждое сообщение в группе.
_runtime_cache: tuple[float, Runtime] | None = None
RUNTIME_TTL = 45.0
GROUP_WARN_COOLDOWN = 90.0
GROUP_WARN_TTL = 25.0

# Какие сообщения считаются «написал участник». Служебные (вход, закреп,
# смена названия и т.п.) не трогаем: за них бот не должен наказывать.
GROUP_CONTENT_TYPES = {
    "text",
    "photo",
    "video",
    "document",
    "audio",
    "voice",
    "video_note",
    "animation",
    "sticker",
    "poll",
    "location",
    "contact",
    "dice",
}


async def runtime_cached(store: Store, settings: Settings) -> Runtime:
    """Настройки из БД с коротким кешем — их читают на каждое сообщение."""
    global _runtime_cache
    now = time.monotonic()
    if _runtime_cache is not None and now - _runtime_cache[0] < RUNTIME_TTL:
        return _runtime_cache[1]
    runtime = await load_runtime(store, settings)
    _runtime_cache = (now, runtime)
    return runtime


# --------------------------------------------------------------------------- канал
def normalize_channel(raw: str | None) -> str:
    """Приводит настройку к виду `@username` или `-100...`. Пусто — проверка выключена."""
    value = (raw or "").strip()
    if value.lower() in DISABLED_VALUES:
        return ""
    value = value.replace("https://", "").replace("http://", "")
    if value.lower().startswith("t.me/"):
        value = value[5:]
    value = value.strip().strip("/")
    if not value or value.startswith("+"):
        # Приватная ссылка-приглашение: Telegram не даёт проверить по ней подписку.
        return ""
    if value.lstrip("-").isdigit():
        return value
    value = value.lstrip("@").strip()
    if not value:
        return ""
    return "@" + value


def normalize_channel_url(raw: str | None, channel: str) -> str:
    """Ссылка для кнопки «Подписаться». Если пусто — собираем t.me по username."""
    value = (raw or "").strip()
    if not value:
        if channel and not channel.lstrip("-").isdigit():
            return f"https://t.me/{channel.lstrip('@')}"
        return ""
    if value.lower().startswith("t.me/"):
        value = "https://" + value
    elif not value.lower().startswith(("http://", "https://")):
        value = "https://" + value.lstrip("@")
    return value


def channel_display(channel: str) -> str:
    """Подпись канала для сообщений."""
    if not channel:
        return ""
    if channel.lstrip("-").isdigit():
        return "по ссылке ниже"
    return f"<b>@{channel.lstrip('@')}</b>"


async def current_channel(store: Store, settings: Settings) -> tuple[str, str]:
    """Действующие канал и ссылка: значение из БД поверх .env."""
    overrides = await store.all_settings()
    raw = overrides.get("required_channel")
    channel = normalize_channel(raw if raw is not None else settings.required_channel)
    raw_url = overrides.get("required_channel_url")
    url = normalize_channel_url(
        raw_url if raw_url is not None else settings.required_channel_url, channel
    )
    return channel, url


def subscription_keyboard(lang: str, url: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if url:
        rows.append([InlineKeyboardButton(text=t(lang, "sub.join"), url=url)])
    rows.append(
        [InlineKeyboardButton(text=t(lang, "sub.check"), callback_data="sub:check")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# --------------------------------------------------------------------------- проверка
def _status_of(member: object) -> str:
    status = getattr(member, "status", None)
    if status in {"member", "administrator", "creator"}:
        return SUBSCRIBED
    if status == "restricted":
        return SUBSCRIBED if getattr(member, "is_member", False) else NOT_SUBSCRIBED
    if status in {"left", "kicked"}:
        return NOT_SUBSCRIBED
    return UNKNOWN


async def membership(
    bot: Bot, channel: str, user_id: int, *, refresh: bool = False
) -> str:
    """SUBSCRIBED / NOT_SUBSCRIBED / UNKNOWN. Результат кешируется на минуту."""
    if not channel:
        return SUBSCRIBED  # проверка выключена
    now = time.monotonic()
    cached = _cache.get((channel, user_id))
    if not refresh and cached and now - cached[1] < CACHE_TTL:
        return cached[0]
    try:
        member = await bot.get_chat_member(channel, user_id)
    except TelegramAPIError as exc:
        key = str(exc)[:120]
        if key not in _warned:
            _warned.add(key)
            log.warning(
                "Проверка подписки на %s недоступна: %s. Добавь бота в администраторы "
                "канала (или участником группы), иначе подписка не проверяется.",
                channel,
                exc,
            )
        _cache.pop((channel, user_id), None)
        return UNKNOWN

    result = _status_of(member)
    _cache[(channel, user_id)] = (result, now)
    if len(_cache) > 5000:
        cutoff = now - CACHE_TTL
        for key, (_, checked_at) in list(_cache.items()):
            if checked_at < cutoff:
                _cache.pop(key, None)
    return result


async def probe_channel(bot: Bot, channel: str) -> bool:
    """Может ли бот вообще смотреть участников канала."""
    if not channel:
        return True
    try:
        me = await bot.me()
        await bot.get_chat_member(channel, me.id)
        return True
    except TelegramAPIError as exc:
        log.warning(
            "Подписка на %s не проверяется: %s. Добавь бота в администраторы канала — "
            "иначе гейт подписки пропускает всех.",
            channel,
            exc,
        )
        return False


async def channel_status(bot: Bot, channel: str) -> tuple[str, str]:
    """Для админки: (состояние, пояснение)."""
    if not channel:
        return "off", "проверка подписки выключена"
    try:
        me = await bot.me()
        member = await bot.get_chat_member(channel, me.id)
    except TelegramAPIError as exc:
        return "error", f"бот не может проверить: {exc}"
    status = getattr(member, "status", "?")
    titles = {
        "administrator": "бот админ канала — проверка работает",
        "creator": "бот владелец канала — проверка работает",
        "member": "бот участник — проверка работает, если Telegram отдаёт участников",
        "restricted": "бот ограничен в канале — проверь права",
    }
    state = "ok" if status in {"administrator", "creator", "member"} else "absent"
    return state, titles.get(status, f"статус бота: {status}")


def reset_cache(user_id: int | None = None) -> None:
    """Сбросить кеш проверки — после смены канала или ручной выдачи подписки."""
    global _runtime_cache
    _runtime_cache = None
    if user_id is None:
        _cache.clear()
        _warned_in_group.clear()
        _staff_cache.clear()
    else:
        for key in [key for key in _cache if key[1] == user_id]:
            _cache.pop(key, None)
        for key in [key for key in _warned_in_group if key[1] == user_id]:
            _warned_in_group.pop(key, None)
        _staff_cache.pop(user_id, None)


# --------------------------------------------------------------------------- middleware
class SubscriptionMiddleware(BaseMiddleware):
    """Закрывает доступ без подписки: личка и (по настройке) группы.

    В группе удаляет сообщение неподписанного и не чаще раза в 90 секунд
    показывает короткое предупреждение с кнопкой. Служебные сообщения, боты,
    анонимные админы, админы чата и сотрудники бота проходят без проверки.
    Если Telegram не даёт проверить подписку (UNKNOWN) — пропускаем: гейт не
    должен молча запирать весь чат.
    """

    def __init__(self) -> None:
        self.chat_admins = ChatAdminCache()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        settings: Settings = data["settings"]
        store: Store = data["store"]
        bot: Bot = data["bot"]

        if isinstance(event, Message):
            user = event.from_user
            if user is None:
                return await handler(event, data)
            if event.chat.type in {"group", "supergroup"}:
                return await self._group_gate(handler, event, data)
            if event.chat.type != "private":
                return await handler(event, data)
            if event.successful_payment is not None:
                return await handler(event, data)
            if await self._exempt(user.id, settings, store):
                return await handler(event, data)
            await store.ensure_user(user.id, user.username, user.first_name)
            channel, url = await current_channel(store, settings)
            if await membership(bot, channel, user.id) != NOT_SUBSCRIBED:
                return await handler(event, data)
            await self._send_gate(bot, event, store, settings, channel, url)
            return None

        if isinstance(event, CallbackQuery):
            user = event.from_user
            message = event.message
            if message is None or message.chat.type != "private":
                return await handler(event, data)
            if event.data == "sub:check":
                return await handler(event, data)
            if await self._exempt(user.id, settings, store):
                return await handler(event, data)
            await store.ensure_user(user.id, user.username, user.first_name)
            channel, url = await current_channel(store, settings)
            if await membership(bot, channel, user.id) != NOT_SUBSCRIBED:
                return await handler(event, data)
            lang = await self._lang(store, settings, user.id)
            try:
                await event.answer(t(lang, "sub.not_yet"), show_alert=True)
            except TelegramAPIError:
                pass
            try:
                await message.answer(
                    self._text(lang, channel), reply_markup=subscription_keyboard(lang, url)
                )
            except TelegramAPIError:
                pass
            return None

        return await handler(event, data)

    async def _group_gate(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        message: Message,
        data: dict[str, Any],
    ) -> Any:
        user = message.from_user
        if user is None or user.is_bot or message.sender_chat is not None:
            return await handler(message, data)
        if message.content_type not in GROUP_CONTENT_TYPES:
            return await handler(message, data)

        settings: Settings = data["settings"]
        store: Store = data["store"]
        bot: Bot = data["bot"]

        runtime = await runtime_cached(store, settings)
        if not runtime.group_gate:
            return await handler(message, data)
        channel = normalize_channel(runtime.required_channel)
        if not channel:
            return await handler(message, data)

        if await self._exempt(user.id, settings, store):
            return await handler(message, data)
        if await self.chat_admins.is_admin(bot, message.chat.id, user.id):
            return await handler(message, data)

        state = await membership(bot, channel, user.id)
        if state != NOT_SUBSCRIBED:
            return await handler(message, data)

        # Сообщение не должно дойти ни до ИИ, ни до модерации.
        with contextlib.suppress(TelegramAPIError):
            await message.delete()
        url = normalize_channel_url(runtime.required_channel_url, channel)
        await self._group_warning(bot, message, store, settings, channel, url)
        return None

    async def _group_warning(
        self,
        bot: Bot,
        message: Message,
        store: Store,
        settings: Settings,
        channel: str,
        url: str,
    ) -> None:
        user = message.from_user
        if user is None:
            return
        key = (message.chat.id, user.id)
        now = time.monotonic()
        last = _warned_in_group.get(key)
        if last is not None and now - last < GROUP_WARN_COOLDOWN:
            return
        _warned_in_group[key] = now
        if len(_warned_in_group) > 2000:
            cutoff = now - GROUP_WARN_COOLDOWN
            for stale, shown_at in list(_warned_in_group.items()):
                if shown_at < cutoff:
                    _warned_in_group.pop(stale, None)

        lang = await self._lang(store, settings, user.id)
        try:
            sent = await message.answer(
                t(
                    lang,
                    "gate.group",
                    name=escape(user.first_name or ""),
                    channel=channel_display(channel),
                ),
                reply_markup=subscription_keyboard(lang, url),
                disable_notification=True,
            )
        except TelegramAPIError:
            return
        asyncio.create_task(
            self._delete_later(bot, sent.chat.id, sent.message_id, GROUP_WARN_TTL)
        )

    @staticmethod
    async def _delete_later(bot: Bot, chat_id: int, message_id: int, delay: float) -> None:
        await asyncio.sleep(delay)
        with contextlib.suppress(TelegramAPIError):
            await bot.delete_message(chat_id, message_id)

    @staticmethod
    async def _lang(store: Store, settings: Settings, user_id: int) -> str:
        return normalize_lang(await store.get_lang(user_id) or settings.default_lang)

    def _text(self, lang: str, channel: str) -> str:
        return t(lang, "sub.required", channel=channel_display(channel))

    async def _send_gate(
        self,
        bot: Bot,
        message: Message,
        store: Store,
        settings: Settings,
        channel: str,
        url: str,
    ) -> None:
        user = message.from_user
        if user is None:
            return
        lang = await self._lang(store, settings, user.id)
        await message.answer(
            self._text(lang, channel), reply_markup=subscription_keyboard(lang, url)
        )

    @staticmethod
    async def _exempt(user_id: int, settings: Settings, store: Store) -> bool:
        if settings.owner_id and user_id == settings.owner_id:
            return True
        if user_id in settings.admin_ids:
            return True
        now = time.monotonic()
        cached = _staff_cache.get(user_id)
        if cached is not None and now - cached[1] < STAFF_TTL:
            return cached[0]
        value = has_admin_access(await resolve_role(user_id, settings, store))
        _staff_cache[user_id] = (value, now)
        return value


@router.callback_query(F.data == "sub:check")
async def check_subscription(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings
) -> None:
    user = call.from_user
    channel, url = await current_channel(store, settings)
    lang = normalize_lang(await store.get_lang(user.id) or settings.default_lang)

    if not channel:
        await call.answer(t(lang, "sub.disabled"), show_alert=True)
        return

    state = await membership(bot, channel, user.id, refresh=True)
    in_group = call.message is not None and call.message.chat.type != "private"
    if state == UNKNOWN:
        await call.answer(t(lang, "sub.unavailable"), show_alert=True)
        return
    if state != SUBSCRIBED:
        if call.message is not None and not in_group:
            try:
                await call.message.answer(
                    t(lang, "sub.required", channel=channel_display(channel)),
                    reply_markup=subscription_keyboard(lang, url),
                )
            except TelegramAPIError:
                pass
        await call.answer(t(lang, "sub.not_yet"), show_alert=True)
        return

    await call.answer(t(lang, "sub.ok"))
    if call.message is None or in_group:
        # В группе не заваливаем чат приветствием: подписка подтверждена —
        # человек просто пишет дальше, гейт его больше не трогает.
        return
    from handlers import language_kb, send_welcome

    stored = await store.get_lang(user.id)
    lang = normalize_lang(stored) if stored else normalize_lang(settings.default_lang)
    await send_welcome(call.message, store, settings, lang, user=user)
    if not stored:
        await call.message.answer(t(lang, "lang.pick"), reply_markup=language_kb(lang))