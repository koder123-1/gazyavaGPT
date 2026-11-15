"""Обязательная подписка на канал @gazyavaGPT перед доступом к боту.

Проверка идёт через `getChatMember`, поэтому бот должен быть участником канала
(лучше — администратором). Если Telegram не даёт проверить подписку (бот не добавлен
в канал, канал закрыт), бот не запирает всех: доступ остаётся, а в лог пишется
предупреждение. Так поломка настройки не выключает бота целиком.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
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
from roles import has_admin_access, resolve_role
from store import Store

log = logging.getLogger("subscription_gate")
router = Router(name="subscription_gate")

CHANNEL = "@gazyavaGPT"
CHANNEL_URL = "https://t.me/gazyavaGPT"
CACHE_TTL = 45.0

SUBSCRIBED = "yes"
NOT_SUBSCRIBED = "no"
UNKNOWN = "unknown"

# user_id -> (результат, когда проверяли)
_cache: dict[int, tuple[str, float]] = {}
# Ошибку «бот не в канале» логируем один раз, чтобы не засорять лог.
_warned: set[str] = set()


def subscription_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "sub.join"), url=CHANNEL_URL)],
            [InlineKeyboardButton(text=t(lang, "sub.check"), callback_data="sub:check")],
        ]
    )


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
    bot: Bot, user_id: int, *, refresh: bool = False
) -> str:
    """SUBSCRIBED / NOT_SUBSCRIBED / UNKNOWN. Результат кешируется на минуту."""
    now = time.monotonic()
    cached = _cache.get(user_id)
    if not refresh and cached and now - cached[1] < CACHE_TTL:
        return cached[0]
    try:
        member = await bot.get_chat_member(CHANNEL, user_id)
    except TelegramAPIError as exc:
        message = str(exc)
        key = message[:120]
        if key not in _warned:
            _warned.add(key)
            log.warning(
                "Проверка подписки на %s недоступна: %s. "
                "Добавь бота в администраторы канала, иначе подписка не проверяется.",
                CHANNEL,
                exc,
            )
        _cache.pop(user_id, None)
        return UNKNOWN

    result = _status_of(member)
    _cache[user_id] = (result, now)
    if len(_cache) > 5000:
        cutoff = now - CACHE_TTL
        for user_id_key, (_, checked_at) in list(_cache.items()):
            if checked_at < cutoff:
                _cache.pop(user_id_key, None)
    return result


def reset_cache(user_id: int | None = None) -> None:
    """Сбросить кеш проверки — например, после ручной выдачи подписки."""
    if user_id is None:
        _cache.clear()
    else:
        _cache.pop(user_id, None)


async def gate_text(store: Store, settings: Settings, user_id: int) -> tuple[str, str]:
    lang = normalize_lang(await store.get_lang(user_id) or settings.default_lang)
    return lang, t(lang, "sub.required")


async def probe_channel(bot: Bot) -> bool:
    """Проверка, что бот видит участников канала. Без этого гейт не работает."""
    try:
        me = await bot.me()
        await bot.get_chat_member(CHANNEL, me.id)
        return True
    except TelegramAPIError as exc:
        log.warning(
            "Подписка на %s не проверяется: %s. Добавь бота в администраторы канала — "
            "иначе гейт подписки пропускает всех.",
            CHANNEL,
            exc,
        )
        return False


class SubscriptionMiddleware(BaseMiddleware):
    """Закрывает личный доступ к боту без подписки на канал.

    Не трогает: группы (модерация и ответы там работают как раньше), служебные
    платежи (`successful_payment`), владельца и админов бота, кнопку проверки.
    """

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
            if event.chat.type != "private" or user is None:
                return await handler(event, data)
            if event.successful_payment is not None:
                return await handler(event, data)
            if await self._exempt(user.id, settings, store):
                return await handler(event, data)
            await store.ensure_user(user.id, user.username, user.first_name)
            if await membership(bot, user.id) != NOT_SUBSCRIBED:
                return await handler(event, data)
            lang, text = await gate_text(store, settings, user.id)
            await event.answer(text, reply_markup=subscription_keyboard(lang))
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
            if await membership(bot, user.id) != NOT_SUBSCRIBED:
                return await handler(event, data)
            lang, text = await gate_text(store, settings, user.id)
            with_alert = True
            await event.answer(t(lang, "sub.not_yet"), show_alert=with_alert)
            try:
                await message.answer(text, reply_markup=subscription_keyboard(lang))
            except TelegramAPIError:
                pass
            return None

        return await handler(event, data)

    @staticmethod
    async def _exempt(user_id: int, settings: Settings, store: Store) -> bool:
        if settings.owner_id and user_id == settings.owner_id:
            return True
        if user_id in settings.admin_ids:
            return True
        return has_admin_access(await resolve_role(user_id, settings, store))


@router.callback_query(F.data == "sub:check")
async def check_subscription(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings
) -> None:
    user = call.from_user
    state = await membership(bot, user.id, refresh=True)
    lang = normalize_lang(await store.get_lang(user.id) or settings.default_lang)

    if state == UNKNOWN:
        await call.answer(t(lang, "sub.unavailable"), show_alert=True)
        return
    if state != SUBSCRIBED:
        if call.message is not None:
            try:
                await call.message.answer(
                    t(lang, "sub.required"), reply_markup=subscription_keyboard(lang)
                )
            except TelegramAPIError:
                pass
        await call.answer(t(lang, "sub.not_yet"), show_alert=True)
        return

    await call.answer(t(lang, "sub.ok"))
    if call.message is None:
        return
    from handlers import language_kb, send_welcome

    stored = await store.get_lang(user.id)
    if not stored:
        await call.message.answer(
            t(settings.default_lang, "lang.pick"), reply_markup=language_kb()
        )
    else:
        await send_welcome(
            call.message, store, settings, normalize_lang(stored), user=user
        )
