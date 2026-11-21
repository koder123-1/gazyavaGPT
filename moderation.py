"""Модерация: приветствие новых участников, правила чата и антифлуд."""

from __future__ import annotations

import contextlib
import logging
import re
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

from aiogram import BaseMiddleware, Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import (
    ChatMemberUpdated,
    ChatPermissions,
    Message,
    TelegramObject,
)

from config import Settings
from i18n import normalize_lang, t
from roles import has_admin_access, resolve_role
from store import Store

log = logging.getLogger("moderation")
router = Router(name="moderation")

JOINED_STATUSES = {"member", "restricted"}
LEFT_STATUSES = {"left", "kicked"}

MUTE_PERMISSIONS = ChatPermissions(
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

FULL_PERMISSIONS = ChatPermissions(
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


def render_template(template: str, *, name: str = "", settings: Settings | None = None) -> str:
    """Подставляет {name}, {bot} и {mute} без str.format (в тексте могут быть другие скобки)."""
    text = template
    if name:
        text = text.replace("{name}", escape(name))
    if settings is not None:
        text = text.replace("{bot}", escape(settings.bot_name))
        text = text.replace("{mute}", str(settings.mute_minutes))
    return text


# --------------------------------------------------------------------------- приветствие
@router.chat_member(
    F.new_chat_member.status.in_(JOINED_STATUSES)
    & F.old_chat_member.status.in_(LEFT_STATUSES)
)
async def on_member_joined(event: ChatMemberUpdated, bot: Bot, settings: Settings) -> None:
    member = event.new_chat_member.user
    if member.is_bot:
        return
    if event.chat.type not in {"group", "supergroup"}:
        return
    if not settings.welcome_text.strip():
        return

    text = render_template(
        settings.welcome_text,
        name=member.first_name or member.username or "друг",
        settings=settings,
    )
    try:
        await bot.send_message(event.chat.id, text)
    except TelegramAPIError:
        log.warning("Не смог отправить приветствие в чат %s", event.chat.id)


# --------------------------------------------------------------------------- правила
@router.message(Command("rules"))
async def cmd_rules(message: Message, settings: Settings) -> None:
    await message.answer(render_template(settings.rules_text, settings=settings))


MAT_OFF_PREFIX = "mat:"


async def _antimat_off(store: Store, chat_id: int) -> bool:
    return await store.get_setting(f"{MAT_OFF_PREFIX}{chat_id}") is not None


@router.message(Command("antimat", "антимат"))
async def cmd_antimat(
    message: Message, bot: Bot, store: Store, settings: Settings
) -> None:
    """Включение и выключение антимата для конкретного чата."""
    lang = normalize_lang(settings.default_lang)
    if message.chat.type not in {"group", "supergroup"}:
        await message.answer(t(lang, "antimat.private"))
        return
    user = message.from_user
    if user is None:
        return
    try:
        member = await bot.get_chat_member(message.chat.id, user.id)
    except TelegramAPIError:
        member = None
    if member is None or getattr(member, "status", "") not in {"administrator", "creator"}:
        await message.answer(t(lang, "antimat.admin_only"))
        return
    arg = (message.text or "").split(maxsplit=1)
    value = arg[1].strip().lower() if len(arg) > 1 else ""
    key = f"{MAT_OFF_PREFIX}{message.chat.id}"
    if value in {"on", "вкл", "включить", "увімк", "уключыць"}:
        await store.delete_setting(key)
        await message.answer(t(lang, "antimat.enabled"))
    elif value in {"off", "выкл", "выключить", "выключиць"}:
        await store.set_setting(key, "1")
        await message.answer(t(lang, "antimat.disabled"))
    else:
        state = (
            t(lang, "antimat.state_off")
            if await _antimat_off(store, message.chat.id)
            else t(lang, "antimat.state_on")
        )
        await message.answer(t(lang, "antimat.status", state=state))


# --------------------------------------------------------------------------- антифлуд
class ChatAdminCache:
    """Помнит, кто админ чата: Telegram нельзя дёргать на каждое сообщение."""

    def __init__(self, ttl: float = 300.0) -> None:
        self.ttl = ttl
        self._cache: dict[tuple[int, int], tuple[bool, float]] = {}

    async def is_admin(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        """True для администратора и владельца чата: их модерация не трогает."""
        key = (chat_id, user_id)
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[1] < self.ttl:
            return cached[0]
        try:
            member = await bot.get_chat_member(chat_id, user_id)
            status = getattr(member, "status", None)
            value = status in {"administrator", "creator"}
        except TelegramAPIError:
            # Не смогли узнать статус: не кэшируем и не наказываем вслепую.
            return False
        self._cache[key] = (value, now)
        return value


class FloodGuard:
    """Считает сообщения в скользящем окне по паре (чат, пользователь)."""

    def __init__(self, limit: int, window: int) -> None:
        self.limit = max(1, limit)
        self.window = max(1, window)
        self._events: dict[tuple[int, int], deque[float]] = defaultdict(deque)

    def hit(self, chat_id: int, user_id: int) -> bool:
        """True, если лимит превышен и сообщение нужно отбить."""
        now = time.monotonic()
        bucket = self._events[(chat_id, user_id)]
        while bucket and now - bucket[0] > self.window:
            bucket.popleft()
        bucket.append(now)
        if len(bucket) > self.limit:
            # Сбрасываем окно, чтобы мут не продлевался каждым следующим сообщением.
            bucket.clear()
            self._maybe_cleanup()
            return True
        return False

    def forget(self, chat_id: int, user_id: int) -> None:
        self._events.pop((chat_id, user_id), None)

    def _maybe_cleanup(self) -> None:
        if len(self._events) < 1000:
            return
        now = time.monotonic()
        stale = [key for key, bucket in self._events.items() if not bucket or now - bucket[-1] > self.window * 4]
        for key in stale:
            self._events.pop(key, None)


class FloodMiddleware(BaseMiddleware):
    """Мутит флудеров в группах. В личке и для админов не работает."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.guard = FloodGuard(settings.flood_limit, settings.flood_window)
        self.chat_admins = ChatAdminCache()

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
            or user.id in self.settings.admin_ids
            or self.settings.flood_limit <= 0
        ):
            return await handler(event, data)

        store = data.get("store")
        if store is not None and has_admin_access(
            await resolve_role(user.id, self.settings, store)
        ):
            return await handler(event, data)

        bot: Bot | None = data.get("bot")
        if bot is None:
            return await handler(event, data)
        # Владельца и админов чата не мутим: Telegram всё равно не даст,
        # а удалять их сообщения — ошибка.
        if await self.chat_admins.is_admin(bot, chat.id, user.id):
            return await handler(event, data)

        if not self.guard.hit(chat.id, user.id):
            return await handler(event, data)

        with contextlib.suppress(TelegramAPIError):
            await event.delete()

        muted = False
        if self.settings.mute_minutes > 0:
            until = datetime.now(timezone.utc) + timedelta(minutes=self.settings.mute_minutes)
            try:
                await bot.restrict_chat_member(
                    chat.id,
                    user.id,
                    permissions=MUTE_PERMISSIONS,
                    until_date=until,
                    use_independent_chat_permissions=True,
                )
                from groupadmin import remember_mute

                remember_mute(chat.id, user.id, self.settings.mute_minutes * 60)
                muted = True
            except TelegramAPIError as exc:
                # Бот не админ или не хватает прав — просто чистим сообщение.
                log.warning("Не смог замутить %s в чате %s: %s", user.id, chat.id, exc)

        log.info(
            "Антифлуд: %s в чате %s (>%s сообщений за %s с), мут=%s",
            user.id,
            chat.id,
            self.settings.flood_limit,
            self.settings.flood_window,
            muted,
        )

        notice = (
            t(
                normalize_lang(self.settings.default_lang),
                "group.flood",
                name=escape(user.first_name or "участник"),
                minutes=self.settings.mute_minutes,
            )
            if muted
            else t(
                normalize_lang(self.settings.default_lang),
                "group.flood_nomute",
                name=escape(user.first_name or "участник"),
            )
        )
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(chat.id, notice, disable_notification=True)
        return None


# --------------------------------------------------------------------------- фильтры спама
_LINK_RE = re.compile(
    r"(?:https?://|www\.|t\.me/|telegram\.me/|wa\.me/|discord\.gg/|youtu\.be/)",
    re.IGNORECASE,
)
_MENTION_RE = re.compile(r"@[A-Za-z0-9_]{4,}")

# «Антимат»: текст схлопываем в буквы, чтобы ловить х*у*й и xуй, и ищем корни.
_LEET_MAP = str.maketrans(
    {"@": "а", "0": "о", "3": "з", "$": "с", "4": "ч", "1": "и", "ё": "е", "€": "е"}
)
_NON_WORD_RE = re.compile(r"[^a-zа-я]+")


def normalize_mat_text(text: str) -> str:
    """Нижний регистр, leet-замены и удаление всего, кроме букв."""
    return _NON_WORD_RE.sub("", text.lower().translate(_LEET_MAP))


def contains_mat(text: str, words: tuple[str, ...]) -> bool:
    if not words:
        return False
    flat = normalize_mat_text(text)
    return any(word in flat for word in words)


class SpamGuard:
    """Повторы, капс и массовые упоминания — то, что не ловится счётчиком частоты."""

    def __init__(self, window: int = 600) -> None:
        self.window = window
        self._recent: dict[tuple[int, int], deque[tuple[str, float]]] = defaultdict(deque)

    def duplicate(self, chat_id: int, user_id: int, text: str) -> bool:
        now = time.monotonic()
        bucket = self._recent[(chat_id, user_id)]
        while bucket and now - bucket[0][1] > self.window:
            bucket.popleft()
        normalized = " ".join(text.lower().split())
        bucket.append((normalized, now))
        return sum(1 for item, _ in bucket if item == normalized) >= 3

    @staticmethod
    def caps(text: str) -> bool:
        letters = [ch for ch in text if ch.isalpha()]
        if len(letters) < 15:
            return False
        upper = sum(1 for ch in letters if ch.isupper())
        return upper / len(letters) > 0.75


class SpamMiddleware(BaseMiddleware):
    """Удаляет спам и ссылки, выдаёт предупреждения и наказывает по страйкам."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.guard = SpamGuard()
        self.chat_admins = ChatAdminCache()

    async def _is_chat_admin(self, bot: Bot, chat_id: int, user_id: int) -> bool:
        return await self.chat_admins.is_admin(bot, chat_id, user_id)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not self.settings.antispam_enabled:
            return await handler(event, data)

        chat = event.chat
        user = event.from_user
        if (
            chat.type not in {"group", "supergroup"}
            or user is None
            or user.is_bot
            or event.sender_chat is not None
        ):
            return await handler(event, data)

        text = event.text or event.caption or ""
        if not text or text.startswith("/"):
            return await handler(event, data)

        store = data.get("store")
        if store is not None and has_admin_access(
            await resolve_role(user.id, self.settings, store)
        ):
            return await handler(event, data)
        if user.id in self.settings.admin_ids:
            return await handler(event, data)

        bot: Bot | None = data.get("bot")
        if bot is None:
            return await handler(event, data)
        if await self._is_chat_admin(bot, chat.id, user.id):
            return await handler(event, data)

        reason = None
        if self.settings.antispam_links and _LINK_RE.search(text):
            reason = "group.reason_links"
        elif (
            self.settings.antimat_enabled
            and contains_mat(text, self.settings.antimat_words)
            and (store is None or not await _antimat_off(store, chat.id))
        ):
            reason = "group.reason_mat"
        elif (
            self.settings.antispam_mentions > 0
            and len(_MENTION_RE.findall(text)) >= self.settings.antispam_mentions
        ):
            reason = "group.reason_mentions"
        elif self.settings.antispam_duplicates and self.guard.duplicate(chat.id, user.id, text):
            reason = "group.reason_duplicate"
        elif self.settings.antispam_caps and self.guard.caps(text):
            reason = "group.reason_caps"

        if reason is None:
            return await handler(event, data)

        with contextlib.suppress(TelegramAPIError):
            await event.delete()

        from groupadmin import push_strike

        strikes = push_strike(chat.id, user.id, self.settings.strike_window)
        lang = normalize_lang(self.settings.default_lang)
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(
                chat.id,
                t(
                    lang,
                    "group.spam_deleted",
                    name=escape(user.first_name or "участник"),
                    reason=t(lang, reason),
                ),
                disable_notification=True,
            )

        if self.settings.strike_limit > 0 and strikes >= self.settings.strike_limit:
            from groupadmin import _apply_strike_action

            await _apply_strike_action(
                event, bot, self.settings, lang, user.id, escape(user.first_name or "участник")
            )
        return None


class PrivateOnlyMiddleware(BaseMiddleware):
    """В группах молчит на команды, которым место только в личке."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.chat.type in {"group", "supergroup"}:
            text = (event.text or "").strip()
            if text.startswith("/"):
                command = text[1:].split()[0].split("@")[0].lower()
                if command in self.settings.private_only_commands:
                    log.info(
                        "Команда /%s в группе %s проигнорирована", command, event.chat.id
                    )
                    return None
        return await handler(event, data)