"""Капча для новых участников: кнопка, мут до проверки и кик по таймауту.

Состояние живёт в настройках стора (`captcha:<chat>:<user>` = дедлайн в
unix-времени), поэтому переживает рестарт: цикл-обход добивает просроченных.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from html import escape
from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from config import Settings
from i18n import normalize_lang, t
from store import Store

log = logging.getLogger("captcha")
router = Router(name="captcha")

PREFIX = "captcha:"
OFF_PREFIX = "capoff:"
JOINED = {"member"}
LEFT = {"left", "kicked"}

MUTE = ChatPermissions(
    can_send_messages=False,
    can_send_audios=False,
    can_send_documents=False,
    can_send_photos=False,
    can_send_videos=False,
    can_send_video_notes=False,
    can_send_voice_notes=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
)

FULL = ChatPermissions(
    can_send_messages=True,
    can_send_audios=True,
    can_send_documents=True,
    can_send_photos=True,
    can_send_videos=True,
    can_send_video_notes=True,
    can_send_voice_notes=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
)

# Кто сейчас на капче: (chat_id, user_id). Нужно, чтобы не ходить в стор на
# каждое сообщение. После рестарта пусто — муты всё равно держит Telegram.
_pending: set[tuple[int, int]] = set()


def _key(chat_id: int, user_id: int) -> str:
    return f"{PREFIX}{chat_id}:{user_id}"


def _parse_key(key: str) -> tuple[int, int] | None:
    parts = key.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[1]), int(parts[2])
    except ValueError:
        return None


async def _is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError:
        return True  # не смогли проверить — лучше не мешать
    return getattr(member, "status", "") in {"administrator", "creator"}


async def _captcha_off(store: Store, chat_id: int) -> bool:
    return await store.get_setting(f"{OFF_PREFIX}{chat_id}") is not None


async def _can_restrict(bot: Bot, chat_id: int) -> bool:
    try:
        me = await bot.get_chat_member(chat_id, (await bot.me()).id)
    except TelegramAPIError:
        return False
    return bool(getattr(me, "can_restrict_members", False))


async def start_captcha(
    bot: Bot,
    store: Store,
    settings: Settings,
    chat_id: int,
    user_id: int,
    name: str,
) -> bool:
    """Мутит новичка и присылает кнопку. False — капча не поставлена."""
    if await store.get_setting(_key(chat_id, user_id)) is not None:
        return False
    timeout = max(30, int(settings.captcha_timeout))
    deadline = int(time.time()) + timeout
    try:
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=MUTE,
            until_date=deadline,
            use_independent_chat_permissions=True,
        )
    except TelegramAPIError as exc:
        log.warning("Капча: нет прав замутить %s в %s: %s", user_id, chat_id, exc)
        return False

    await store.set_setting(_key(chat_id, user_id), str(deadline))
    _pending.add((chat_id, user_id))

    lang = normalize_lang(settings.default_lang)
    minutes = max(1, timeout // 60)
    text = t(
        lang,
        "captcha.text",
        name=escape(name or "друг"),
        minutes=minutes,
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "captcha.button"),
                    callback_data=f"cap:{chat_id}:{user_id}",
                )
            ]
        ]
    )
    try:
        await bot.send_message(chat_id, text, reply_markup=keyboard)
    except TelegramAPIError:
        log.warning("Капча: не смог отправить сообщение в %s", chat_id)
    return True


async def _release(bot: Bot, chat_id: int, user_id: int) -> None:
    with contextlib.suppress(TelegramAPIError):
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            permissions=FULL,
            use_independent_chat_permissions=True,
        )


async def _kick(bot: Bot, chat_id: int, user_id: int) -> None:
    with contextlib.suppress(TelegramAPIError):
        await bot.ban_chat_member(chat_id, user_id)
    with contextlib.suppress(TelegramAPIError):
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)


@router.chat_member(
    F.new_chat_member.status.in_(JOINED) & F.old_chat_member.status.in_(LEFT)
)
async def on_join(event: ChatMemberUpdated, bot: Bot, store: Store, settings: Settings) -> None:
    if not settings.captcha_enabled:
        return
    if event.chat.type not in {"group", "supergroup"}:
        return
    member = event.new_chat_member.user
    if member.is_bot:
        return
    if await _captcha_off(store, event.chat.id):
        return
    if await _is_chat_admin(bot, event.chat.id, member.id):
        return
    if not await _can_restrict(bot, event.chat.id):
        log.info("Капча: в чате %s нет прав на ограничение", event.chat.id)
        return
    await start_captcha(
        bot,
        store,
        settings,
        event.chat.id,
        member.id,
        member.first_name or member.username or "друг",
    )


@router.chat_member(F.new_chat_member.status.in_(LEFT))
async def on_leave(event: ChatMemberUpdated, store: Store) -> None:
    user = event.new_chat_member.user
    _pending.discard((event.chat.id, user.id))
    with contextlib.suppress(Exception):
        await store.delete_setting(_key(event.chat.id, user.id))


@router.callback_query(F.data.startswith("cap:"))
async def on_captcha_click(call: CallbackQuery, bot: Bot, store: Store, settings: Settings) -> None:
    parts = (call.data or "").split(":")
    if len(parts) != 3:
        await call.answer()
        return
    try:
        chat_id, user_id = int(parts[1]), int(parts[2])
    except ValueError:
        await call.answer()
        return
    lang = normalize_lang(settings.default_lang)
    if call.from_user is None or call.from_user.id != user_id:
        await call.answer(t(lang, "captcha.not_yours"), show_alert=True)
        return
    key = _key(chat_id, user_id)
    if await store.get_setting(key) is None:
        await call.answer(t(lang, "captcha.already"))
        return
    await store.delete_setting(key)
    _pending.discard((chat_id, user_id))
    await _release(bot, chat_id, user_id)
    name = escape(call.from_user.first_name or "друг")
    with contextlib.suppress(TelegramAPIError):
        if isinstance(call.message, Message):
            await call.message.edit_text(t(lang, "captcha.ok", name=name))
    await call.answer(t(lang, "captcha.ok_short"))


@router.message(Command("captcha"))
async def cmd_captcha(message: Message, bot: Bot, store: Store, settings: Settings) -> None:
    lang = normalize_lang(settings.default_lang)
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer(t(lang, "captcha.private"))
        return
    user = message.from_user
    if user is None or not await _is_chat_admin(bot, message.chat.id, user.id):
        await message.answer(t(lang, "captcha.admin_only"))
        return
    arg = (message.text or "").split(maxsplit=1)
    value = arg[1].strip().lower() if len(arg) > 1 else ""
    if value in {"on", "вкл", "включить", "увімк", "уключыць"}:
        await store.delete_setting(f"{OFF_PREFIX}{message.chat.id}")
        await message.answer(t(lang, "captcha.enabled", minutes=max(1, settings.captcha_timeout // 60)))
    elif value in {"off", "выкл", "выключить", "выключиць"}:
        await store.set_setting(f"{OFF_PREFIX}{message.chat.id}", "1")
        await message.answer(t(lang, "captcha.disabled"))
    else:
        state = (
            t(lang, "captcha.state_off")
            if await _captcha_off(store, message.chat.id)
            else t(lang, "captcha.state_on", minutes=max(1, settings.captcha_timeout // 60))
        )
        await message.answer(
            t(lang, "captcha.status", state=state),
        )


class CaptchaMiddleware(BaseMiddleware):
    """Удаляет сообщения тех, кто ещё не прошёл капчу (если мут не сработал)."""

    async def __call__(
        self,
        handler: Any,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not _pending:
            return await handler(event, data)
        user = event.from_user
        if user is None:
            return await handler(event, data)
        if (event.chat.id, user.id) not in _pending:
            return await handler(event, data)
        with contextlib.suppress(TelegramAPIError):
            await event.delete()
        return None


async def sweep(bot: Bot, store: Store) -> int:
    """Кикает тех, кто не нажал кнопку вовремя. Возвращает число киков."""
    now = int(time.time())
    rows = await store.settings_with_prefix(PREFIX)
    kicked = 0
    for key, value in rows.items():
        parsed = _parse_key(key)
        if parsed is None:
            await store.delete_setting(key)
            continue
        chat_id, user_id = parsed
        try:
            deadline = int(value)
        except (TypeError, ValueError):
            deadline = 0
        if deadline and deadline > now:
            _pending.add((chat_id, user_id))
            continue
        _pending.discard((chat_id, user_id))
        await store.delete_setting(key)
        await _kick(bot, chat_id, user_id)
        kicked += 1
        log.info("Капча: кик %s из чата %s по таймауту", user_id, chat_id)
    return kicked


async def _loop(bot: Bot, store: Store, interval: float = 45.0) -> None:
    while True:
        try:
            await sweep(bot, store)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен умирать
            log.exception("Ошибка цикла капчи")
        await asyncio.sleep(interval)


_task: asyncio.Task | None = None


def start_loop(bot: Bot, store: Store) -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop(bot, store))


async def stop_loop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None