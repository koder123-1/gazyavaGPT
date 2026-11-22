"""Анти-рейд: всплеск входов временно закрывает чат и режет новичков.

Telegram не даёт боту «отключить приглашения» для чужих ссылок, поэтому защита
практичная: при N входах за окно бот снимает право писать у всех (админы
исключены правилами Telegram), высылает алерт админам и кикает новых
участников до конца блокировки. Через `RAID_LOCK_MINUTES` всё возвращается,
восстанавливаются прежние права чата (они сохраняются в БД, чтобы пережить
рестарт). Автоматику можно выключить: `/raid off` в чате.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from collections import defaultdict, deque

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, ChatPermissions, Message

import alerts
from config import Settings
from i18n import normalize_lang, t
from roles import has_admin_access, resolve_role
from store import Store

log = logging.getLogger("antiraid")
router = Router(name="antiraid")

RAID_KEY = "raid:"
SAVED_KEY = "raid_saved:"
JOINED = {"member"}
LEFT = {"left", "kicked"}

MUTE_ALL = ChatPermissions(
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

_recent: dict[int, deque[float]] = defaultdict(deque)


def _dump(perms: ChatPermissions | None) -> str:
    if perms is None:
        return "none"
    data = {
        key: value
        for key, value in perms.model_dump().items()
        if value is not None
    }
    return json.dumps(data, ensure_ascii=False)


def _load(raw: str | None) -> ChatPermissions:
    if not raw or raw == "none":
        return FULL
    try:
        data = json.loads(raw)
        return ChatPermissions(**data) if isinstance(data, dict) else FULL
    except (ValueError, TypeError):
        return FULL


def _chat_id(key: str) -> int:
    try:
        return int(key.split(":", 1)[1])
    except (IndexError, ValueError):
        return 0


async def raid_until(store: Store, chat_id: int) -> int:
    raw = await store.get_setting(f"{RAID_KEY}{chat_id}")
    if raw is None:
        return 0
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


async def engage(
    bot: Bot,
    store: Store,
    settings: Settings,
    chat_id: int,
    *,
    title: str = "",
    joined: int = 0,
    manual: bool = False,
) -> bool:
    """Закрывает чат. False — уже закрыт или нет прав."""
    now = int(time.time())
    if await raid_until(store, chat_id) > now:
        return False
    saved = "none"
    try:
        chat = await bot.get_chat(chat_id)
        if not title:
            title = str(getattr(chat, "title", "") or chat_id)
        saved = _dump(getattr(chat, "permissions", None))
    except TelegramAPIError:
        title = title or str(chat_id)
        saved = "none"
    try:
        await bot.set_chat_permissions(chat_id, MUTE_ALL)
    except TelegramAPIError as exc:
        log.warning("Анти-рейд: нет прав закрыть чат %s: %s", chat_id, exc)
        await alerts.notify(
            "raid",
            f"«{title}» ({chat_id}): не смог закрыть чат — {exc}. "
            "Дай боту право «Ограничивать участников».",
            key=f"raid-fail:{chat_id}",
        )
        return False

    until = now + max(1, int(settings.raid_lock_minutes)) * 60
    await store.set_setting(f"{RAID_KEY}{chat_id}", str(until))
    await store.set_setting(f"{SAVED_KEY}{chat_id}", saved)
    _recent.pop(chat_id, None)

    minutes = max(1, int(settings.raid_lock_minutes))
    lang = normalize_lang(settings.default_lang)
    with contextlib.suppress(TelegramAPIError):
        await bot.send_message(chat_id, t(lang, "raid.locked_chat", minutes=minutes))
    reason = (
        "закрыт вручную админом"
        if manual
        else f"всплеск входов: {joined} за {settings.raid_window} с"
    )
    await alerts.notify(
        "raid",
        f"«{title}» ({chat_id}) {reason}.\n"
        f"Чат закрыт на {minutes} мин, новые участники отсекаются. "
        f"Открыть: /raid off в чате.",
        key=f"raid-on:{chat_id}",
    )
    return True


async def stand_down(
    bot: Bot, store: Store, settings: Settings, chat_id: int, *, manual: bool = False
) -> bool:
    """Возвращает чату прежние права. False — блокировки не было."""
    if await raid_until(store, chat_id) == 0:
        return False
    saved = await store.get_setting(f"{SAVED_KEY}{chat_id}")
    perms = _load(saved)
    try:
        await bot.set_chat_permissions(chat_id, perms)
    except TelegramAPIError as exc:
        log.warning("Анти-рейд: не смог открыть чат %s: %s", chat_id, exc)
        return False
    await store.delete_setting(f"{RAID_KEY}{chat_id}")
    await store.delete_setting(f"{SAVED_KEY}{chat_id}")
    lang = normalize_lang(settings.default_lang)
    with contextlib.suppress(TelegramAPIError):
        await bot.send_message(chat_id, t(lang, "raid.unlocked_chat"))
    await alerts.notify(
        "raid",
        f"Чат {chat_id} снова открыт" + (" (вручную)." if manual else " по таймеру."),
        key=f"raid-off:{chat_id}",
        force=True,
    )
    return True


async def _kick(bot: Bot, chat_id: int, user_id: int) -> None:
    with contextlib.suppress(TelegramAPIError):
        await bot.ban_chat_member(chat_id, user_id)
    with contextlib.suppress(TelegramAPIError):
        await bot.unban_chat_member(chat_id, user_id, only_if_banned=True)


async def _is_allowed(bot: Bot, store: Store, settings: Settings, chat_id: int, user_id: int) -> bool:
    """Админ чата или сотрудник бота."""
    if has_admin_access(await resolve_role(user_id, settings, store)):
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
    except TelegramAPIError:
        return False
    return getattr(member, "status", "") in {"administrator", "creator"}


@router.chat_member(
    F.new_chat_member.status.in_(JOINED) & F.old_chat_member.status.in_(LEFT)
)
async def on_join(
    event: ChatMemberUpdated, bot: Bot, store: Store, settings: Settings
) -> None:
    if not settings.raid_enabled:
        return
    if event.chat.type not in {"group", "supergroup"}:
        return
    member = event.new_chat_member.user
    if member.is_bot:
        return
    chat_id = event.chat.id

    until = await raid_until(store, chat_id)
    if until:
        if until > time.time():
            if settings.raid_kick_new:
                await _kick(bot, chat_id, member.id)
            return
        await stand_down(bot, store, settings, chat_id)

    now = time.monotonic()
    bucket = _recent[chat_id]
    while bucket and now - bucket[0] > max(1, settings.raid_window):
        bucket.popleft()
    bucket.append(now)
    if len(bucket) < max(2, settings.raid_threshold):
        return
    joined = len(bucket)
    bucket.clear()
    await engage(
        bot,
        store,
        settings,
        chat_id,
        title=str(getattr(event.chat, "title", "") or ""),
        joined=joined,
    )


@router.message(Command("raid", "рейд"))
async def cmd_raid(
    message: Message, bot: Bot, store: Store, settings: Settings
) -> None:
    user = message.from_user
    lang = normalize_lang(settings.default_lang)
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer(t(lang, "raid.private"))
        return
    if user is None or not await _is_allowed(
        bot, store, settings, message.chat.id, user.id
    ):
        await message.answer(t(lang, "raid.admin_only"))
        return
    arg = (message.text or "").split(maxsplit=1)
    value = arg[1].strip().lower() if len(arg) > 1 else ""
    chat_id = message.chat.id

    if value in {"off", "выкл", "открыть", "відкрити", "адкрыць"}:
        if await stand_down(bot, store, settings, chat_id, manual=True):
            await message.answer(t(lang, "raid.disabled"))
        else:
            await message.answer(t(lang, "raid.status_off",
                threshold=settings.raid_threshold,
                window=settings.raid_window,
                minutes=settings.raid_lock_minutes,
            ))
        return

    if value in {"on", "вкл", "закрыть", "закрити", "закрыць"}:
        now = int(time.time())
        if await raid_until(store, chat_id) > now:
            minutes = max(1, (await raid_until(store, chat_id) - now) // 60 + 1)
            await message.answer(t(lang, "raid.status_on", minutes=minutes))
        elif await engage(bot, store, settings, chat_id, manual=True):
            await message.answer(
                t(lang, "raid.enabled", minutes=settings.raid_lock_minutes)
            )
        else:
            await message.answer(t(lang, "raid.failed"))
        return

    until = await raid_until(store, chat_id)
    if until > time.time():
        minutes = max(1, (until - int(time.time())) // 60 + 1)
        await message.answer(t(lang, "raid.status_on", minutes=minutes))
    else:
        await message.answer(
            t(
                lang,
                "raid.status_off",
                threshold=settings.raid_threshold,
                window=settings.raid_window,
                minutes=settings.raid_lock_minutes,
            )
        )


async def _tick(bot: Bot, store: Store, settings: Settings) -> int:
    now = time.time()
    rows = await store.settings_with_prefix(RAID_KEY)
    opened = 0
    for key, value in rows.items():
        chat_id = _chat_id(key)
        if not chat_id:
            await store.delete_setting(key)
            continue
        try:
            until = int(value)
        except (TypeError, ValueError):
            until = 0
        if until > now:
            continue
        if await stand_down(bot, store, settings, chat_id):
            opened += 1
    return opened


async def _loop(bot: Bot, store: Store, settings: Settings, interval: float = 30.0) -> None:
    while True:
        try:
            await _tick(bot, store, settings)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен умирать
            log.exception("Ошибка цикла анти-рейда")
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