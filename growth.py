"""Рост аудитории: приглашения по ссылке и награды обеим сторонам.

Ссылка вида `https://t.me/bot?start=ref_<id>` обрабатывается в трёх местах:
обычный `/start`, гейт подписки (когда сообщение перехвачено) и кнопка
«Проверить подписку». Поэтому логика вынесена сюда, а не в handlers.py.
"""

from __future__ import annotations

import contextlib
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from config import Settings
from i18n import normalize_lang, t
from store import Store
import gamification

log = logging.getLogger("growth")

# Сколько времени после создания аккаунта приглашение ещё считается новым.
REF_WINDOW_SECONDS = 24 * 3600
PENDING_PREFIX = "pending_ref:"


def pending_key(user_id: int) -> str:
    return f"{PENDING_PREFIX}{user_id}"


async def remember_pending(store: Store, user_id: int, referrer_id: int) -> None:
    """Запоминает пригласителя, если гейт подписки не пустил к /start."""
    if referrer_id <= 0 or referrer_id == user_id:
        return
    await store.set_setting(pending_key(user_id), str(referrer_id))


async def parse_ref(payload: str) -> int:
    """`ref_12345` -> 12345, всё остальное -> 0."""
    value = (payload or "").strip()
    if not value.lower().startswith("ref_"):
        return 0
    raw = value[4:].strip()
    return int(raw) if raw.isdigit() else 0


async def accept_referral(
    bot: Bot,
    store: Store,
    settings: Settings,
    invited_id: int,
    referrer_id: int,
    *,
    name: str | None = None,
) -> bool:
    """Начисляет награды, если приглашённый действительно новый."""
    if invited_id <= 0 or referrer_id <= 0 or invited_id == referrer_id:
        return False
    claimed = await store.claim_referral(
        referrer_id, invited_id, window_seconds=REF_WINDOW_SECONDS
    )
    if not claimed:
        # Повторная попытка уже ничего не даст: чистим метку, чтобы не копилась.
        await store.delete_setting(pending_key(invited_id))
        return False
    await store.add_bonus(referrer_id, settings.invite_reward)
    await store.add_bonus(invited_id, settings.invited_reward)
    await store.delete_setting(pending_key(invited_id))
    ref_lang = normalize_lang(await store.get_lang(referrer_id) or settings.default_lang)
    count = await store.referral_count(referrer_id)
    display = name or f"id {invited_id}"
    extra = ""
    try:
        events = await gamification.on_referral(
            store, referrer_id, ref_lang, invites=count
        )
        extra = gamification.format_events(events, ref_lang)
    except Exception:  # noqa: BLE001 — награда не должна ломать приглашение
        log.exception("Не удалось начислить XP за приглашение")
    try:
        invited_lang = normalize_lang(
            await store.get_lang(invited_id) or settings.default_lang
        )
        await gamification.on_referral_invited(store, invited_id, invited_lang)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось начислить XP приглашённому")
    text = t(
        ref_lang,
        "invite.joined",
        name=display,
        amount=settings.invite_reward,
        count=count,
    )
    if extra:
        text += "\n\n" + extra
    with contextlib.suppress(TelegramAPIError):
        await bot.send_message(referrer_id, text)
    log.info("Реферал: %s пригласил %s", referrer_id, invited_id)
    return True


async def process_pending(
    bot: Bot, store: Store, settings: Settings, user
) -> bool:
    """Забирает отложенное приглашение для пользователя, если оно есть."""
    raw = await store.get_setting(pending_key(user.id))
    if not raw:
        return False
    try:
        referrer_id = int(str(raw).strip())
    except (TypeError, ValueError):
        await store.delete_setting(pending_key(user.id))
        return False
    name = user.first_name or (f"@{user.username}" if user.username else None)
    return await accept_referral(
        bot, store, settings, user.id, referrer_id, name=name
    )