"""Розыгрыши в чатах: несколько одновременных, с подписью и таймером.

Создаются из группы командой `/giveaway` (админ чата или сотрудник бота),
а также управляются из /admin → 🎉 Фишки → 🎁 Розыгрыши. Участники жмут
кнопку «🎉 Участвовать»; бот хранит участников в БД, поэтому розыгрыш
переживает рестарт и завершается фоновым циклом (или лениво — при нажатии).

Правила простые:
• один человек — одна заявка;
• если включён «только подписчики», проверяем канал из настроек;
• победителей выбирает `random.sample`, результат публикуется в чат;
• победителям бот пишет в личку (если они его запускали).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
from datetime import UTC, datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config import Settings
from groupadmin import is_chat_admin
from i18n import normalize_lang, t
from roles import has_admin_access, resolve_role
from store import Store
from subscription import (
    NOT_SUBSCRIBED,
    channel_display,
    current_channel,
    membership,
)

log = logging.getLogger("giveaways")
router = Router(name="giveaways")

MAX_PRIZE = 120
MAX_ACTIVE_PER_CHAT = 5

DURATIONS = ((10, "10 минут"), (60, "1 час"), (360, "6 часов"), (1440, "24 часа"), (4320, "3 дня"))
WINNER_CHOICES = (1, 3, 5, 10)


class GiveawayFlow(StatesGroup):
    prize = State()
    winners = State()
    duration = State()
    need_sub = State()


# --------------------------------------------------------------------------- утилиты
async def _lang(store: Store, settings: Settings, user_id: int) -> str:
    return normalize_lang(await store.get_lang(user_id) or settings.default_lang)


def _fmt_time(when: datetime | None) -> str:
    if when is None:
        return "—"
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.strftime("%d.%m %H:%M UTC")


def _mention(row: dict) -> str:
    user_id = row.get("user_id") or 0
    name = row.get("first_name") or row.get("username") or str(user_id)
    return f'<a href="tg://user?id={int(user_id)}">{escape(str(name))}</a>'


def _id_from(data: str | None) -> int | None:
    try:
        return int((data or "").rsplit(":", 1)[1])
    except (IndexError, TypeError, ValueError):
        return None


async def _can_manage(message: Message, bot: Bot, settings: Settings, store: Store) -> bool:
    user = message.from_user
    if user is None:
        return False
    if has_admin_access(await resolve_role(user.id, settings, store)):
        return True
    if message.chat.type in {"group", "supergroup"}:
        return await is_chat_admin(bot, message.chat.id, user.id)
    return False


async def _is_staff(user_id: int, settings: Settings, store: Store) -> bool:
    return has_admin_access(await resolve_role(user_id, settings, store))


# --------------------------------------------------------------------------- рендер
async def render_admin(store: Store) -> tuple[str, InlineKeyboardMarkup]:
    stats = await store.giveaways_stats()
    active = await store.active_giveaways()
    lines = [t("ru", "give.admin_list", active=stats["active"], finished=stats["finished"]).strip()]
    rows: list[list[InlineKeyboardButton]] = []
    if not active:
        lines.append(t("ru", "give.admin_empty"))
        lines.append("")
        lines.append(t("ru", "give.private_hint"))
    else:
        for giveaway in active[:10]:
            lines.append(
                t(
                    "ru",
                    "give.admin_line",
                    id=giveaway["id"],
                    prize=escape(str(giveaway["prize"])),
                    n=giveaway.get("entries", 0),
                    until=_fmt_time(giveaway.get("ends_at")),
                )
            )
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{t('ru', 'give.finish_btn')} #{giveaway['id']}",
                        callback_data=f"adm:give:finish:{giveaway['id']}",
                    ),
                    InlineKeyboardButton(
                        text=f"❌ #{giveaway['id']}",
                        callback_data=f"adm:give:cancel:{giveaway['id']}",
                    ),
                ]
            )
        lines.append("")
        lines.append(t("ru", "give.private_hint"))
    rows.append(
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:give")]
    )
    rows.append([InlineKeyboardButton(text="⬅️ К фишкам", callback_data="adm:fun")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _durations_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=label, callback_data=f"give:dur:{minutes}")
        for minutes, label in DURATIONS
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons[:3],
            buttons[3:],
            [InlineKeyboardButton(text=t("ru", "give.cancel"), callback_data="give:flow_cancel")],
        ]
    )


def _winners_kb() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(text=str(count), callback_data=f"give:win:{count}")
        for count in WINNER_CHOICES
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            buttons,
            [InlineKeyboardButton(text=t("ru", "give.cancel"), callback_data="give:flow_cancel")],
        ]
    )


def _need_sub_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("ru", "give.yes"), callback_data="give:sub:1"),
                InlineKeyboardButton(text=t("ru", "give.no"), callback_data="give:sub:0"),
            ],
            [InlineKeyboardButton(text=t("ru", "give.cancel"), callback_data="give:flow_cancel")],
        ]
    )


# --------------------------------------------------------------------------- создание
@router.message(Command("giveaway", "giveaways", "розыгрыш"))
async def cmd_giveaway(
    message: Message, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await _lang(store, settings, user.id)
    if not await _can_manage(message, bot, settings, store):
        await message.reply(t(lang, "give.no_rights"))
        return
    if message.chat.type not in {"group", "supergroup"}:
        text, kb = await render_admin(store)
        await message.answer(text, reply_markup=kb)
        return

    active = await store.active_giveaways(chat_id=message.chat.id)
    if len(active) >= MAX_ACTIVE_PER_CHAT:
        await message.reply(
            f"⚠️ В этом чате уже {len(active)} активных розыгрышей. "
            "Дождись завершения или отмени лишние в /admin → 🎉 Фишки → 🎁 Розыгрыши."
        )
        return

    await state.clear()
    await state.set_state(GiveawayFlow.prize)
    await state.update_data(chat_id=message.chat.id, admin_lang=lang)
    await message.answer(
        t(lang, "give.ask_prize"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t(lang, "give.cancel"), callback_data="give:flow_cancel")]
            ]
        ),
    )


@router.message(GiveawayFlow.prize, F.text, ~F.text.startswith("/"))
async def on_prize(message: Message, store: Store, settings: Settings, state: FSMContext) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await _lang(store, settings, user.id)
    prize = " ".join((message.text or "").split())
    if not 2 <= len(prize) <= MAX_PRIZE:
        await message.answer(t(lang, "give.bad_prize"))
        return
    await state.update_data(prize=prize)
    await state.set_state(GiveawayFlow.winners)
    await message.answer(t(lang, "give.ask_winners"), reply_markup=_winners_kb())


@router.message(GiveawayFlow.prize)
async def on_prize_bad(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await _lang(store, settings, user.id)
    await message.answer(t(lang, "give.bad_prize"))


@router.callback_query(F.data.startswith("give:win:"))
async def cb_winners(call: CallbackQuery, store: Store, settings: Settings, state: FSMContext) -> None:
    current = await state.get_state()
    if current != GiveawayFlow.winners.state:
        await call.answer(t("ru", "give.over"), show_alert=True)
        return
    count = _id_from(call.data)
    if count not in WINNER_CHOICES:
        await call.answer("Не понял число", show_alert=True)
        return
    await state.update_data(winners=count)
    await state.set_state(GiveawayFlow.duration)
    lang = await _lang(store, settings, call.from_user.id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(t(lang, "give.ask_duration"), reply_markup=_durations_kb())
    await call.answer()


@router.callback_query(F.data.startswith("give:dur:"))
async def cb_duration(call: CallbackQuery, store: Store, settings: Settings, state: FSMContext) -> None:
    current = await state.get_state()
    if current != GiveawayFlow.duration.state:
        await call.answer(t("ru", "give.over"), show_alert=True)
        return
    minutes = _id_from(call.data)
    if minutes is None or minutes <= 0:
        await call.answer("Не понял время", show_alert=True)
        return
    await state.update_data(duration=minutes)
    await state.set_state(GiveawayFlow.need_sub)
    lang = await _lang(store, settings, call.from_user.id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(t(lang, "give.ask_sub"), reply_markup=_need_sub_kb())
    await call.answer()


@router.callback_query(F.data.startswith("give:sub:"))
async def cb_need_sub(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    current = await state.get_state()
    if current != GiveawayFlow.need_sub.state:
        await call.answer(t("ru", "give.over"), show_alert=True)
        return
    need_sub = (call.data or "").endswith("1")
    data = await state.get_data()
    await state.clear()

    chat_id = int(data.get("chat_id") or 0)
    prize = str(data.get("prize") or "").strip()
    winners = int(data.get("winners") or 1)
    minutes = int(data.get("duration") or 60)
    lang = normalize_lang(str(data.get("admin_lang") or "ru"))
    user = call.from_user

    if not chat_id or not prize:
        await call.answer("Сессия создания истекла, начни заново /giveaway", show_alert=True)
        return

    channel, url = await current_channel(store, settings)
    giveaway_id = await store.create_giveaway(
        chat_id=chat_id,
        prize=prize,
        winners=winners,
        need_sub=need_sub and bool(channel),
        duration_minutes=minutes,
        created_by=user.id,
        lang=lang,
    )
    giveaway = await store.get_giveaway(giveaway_id)
    if giveaway is None:
        await call.answer(t(lang, "give.not_found"), show_alert=True)
        return

    condition = (
        t(lang, "give.condition_sub", channel=channel_display(channel))
        if giveaway["need_sub"]
        else t(lang, "give.condition_free")
    )
    text = t(
        lang,
        "give.post",
        prize=escape(prize),
        winners=giveaway["winners"],
        until=_fmt_time(giveaway.get("ends_at")),
        condition=condition,
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "give.join_btn"), callback_data=f"give:join:{giveaway_id}"
                )
            ]
        ]
    )
    try:
        post = await bot.send_message(chat_id, text, reply_markup=keyboard)
    except TelegramAPIError as exc:
        await store.cancel_giveaway(giveaway_id)
        log.warning("Розыгрыш %s не опубликован: %s", giveaway_id, exc)
        await call.answer("Не смог написать в чат. Проверь права бота.", show_alert=True)
        return
    await store.set_giveaway_message(giveaway_id, post.message_id)

    created = t(lang, "give.created")
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(
            f"{created}\n\n🎁 <b>{escape(prize)}</b> · #{giveaway_id}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=t("ru", "give.finish_btn"),
                            callback_data=f"adm:give:finish:{giveaway_id}",
                        ),
                        InlineKeyboardButton(
                            text=t("ru", "give.cancel_btn"),
                            callback_data=f"adm:give:cancel:{giveaway_id}",
                        ),
                    ]
                ]
            ),
        )
    await call.answer(t(lang, "give.created"))


@router.callback_query(F.data == "give:flow_cancel")
async def cb_flow_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(t("ru", "give.cancelled"))
    await call.answer()


# --------------------------------------------------------------------------- участие
@router.callback_query(F.data.startswith("give:join:"))
async def cb_join(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings
) -> None:
    giveaway_id = _id_from(call.data)
    user = call.from_user
    lang = await _lang(store, settings, user.id)
    if giveaway_id is None:
        await call.answer(t(lang, "give.not_found"), show_alert=True)
        return

    giveaway = await store.get_giveaway(giveaway_id)
    if giveaway is None:
        await call.answer(t(lang, "give.not_found"), show_alert=True)
        return
    if call.message is not None and call.message.chat.id != giveaway["chat_id"]:
        # Кнопку могли переслать в другой чат — участвовать можно только там,
        # где розыгрыш опубликован.
        await call.answer(t(lang, "give.not_found"), show_alert=True)
        return
    if giveaway["status"] != "active":
        await call.answer(t(lang, "give.over"), show_alert=True)
        return

    ends_at = giveaway.get("ends_at")
    if isinstance(ends_at, datetime):
        if ends_at.tzinfo is None:
            ends_at = ends_at.replace(tzinfo=UTC)
        if ends_at <= datetime.now(UTC):
            # Фоновый цикл мог спать (free Render) — завершаем сейчас.
            await finalize_giveaway(bot, store, giveaway)
            await call.answer(t(lang, "give.over"), show_alert=True)
            return

    if giveaway.get("need_sub"):
        channel, _ = await current_channel(store, settings)
        if channel:
            state = await membership(bot, channel, user.id)
            if state == NOT_SUBSCRIBED:
                await call.answer(
                    t(lang, "give.need_sub", channel=channel_display(channel)), show_alert=True
                )
                return

    added = await store.join_giveaway(
        giveaway_id, user.id, user.username, user.first_name
    )
    if not added:
        await call.answer(t(lang, "give.already"), show_alert=True)
        return
    count = await store.giveaway_entries_count(giveaway_id)
    await call.answer(t(lang, "give.joined", n=count), show_alert=True)


# --------------------------------------------------------------------------- завершение
def _result_text(giveaway: dict, entries: list[dict], winners: list[dict]) -> str:
    lang = normalize_lang(str(giveaway.get("lang") or "ru"))
    prize = escape(str(giveaway.get("prize") or ""))
    if not entries:
        return t(lang, "give.no_entries", prize=prize)
    lines = "\n".join(f"{index}. {_mention(row)}" for index, row in enumerate(winners, 1))
    return t(lang, "give.result", prize=prize, n=len(entries), winners=lines)


async def finalize_giveaway(bot: Bot, store: Store, giveaway: dict) -> bool:
    """Выбрать победителей и опубликовать результат. Идемпотентно."""
    giveaway_id = int(giveaway["id"])
    entries = await store.giveaway_entries(giveaway_id)
    winners: list[dict] = []
    if entries:
        count = min(max(1, int(giveaway.get("winners") or 1)), len(entries))
        winners = random.sample(entries, count)
    result = _result_text(giveaway, entries, winners)
    if not await store.finish_giveaway(giveaway_id, result):
        return False

    lang = normalize_lang(str(giveaway.get("lang") or "ru"))
    prize = escape(str(giveaway.get("prize") or ""))
    message_id = giveaway.get("message_id")
    if message_id:
        with contextlib.suppress(TelegramAPIError):
            await bot.edit_message_text(
                chat_id=giveaway["chat_id"],
                message_id=int(message_id),
                text=t(lang, "give.finished_short", prize=prize),
            )
    with contextlib.suppress(TelegramAPIError):
        await bot.send_message(giveaway["chat_id"], result)
    for winner in winners:
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(
                int(winner["user_id"]), t(lang, "give.win_dm", prize=prize)
            )
    log.info("Розыгрыш %s завершён: участников %s", giveaway_id, len(entries))
    return True


async def cancel_giveaway(bot: Bot, store: Store, giveaway: dict) -> bool:
    if not await store.cancel_giveaway(int(giveaway["id"])):
        return False
    lang = normalize_lang(str(giveaway.get("lang") or "ru"))
    message_id = giveaway.get("message_id")
    if message_id:
        with contextlib.suppress(TelegramAPIError):
            await bot.edit_message_text(
                chat_id=giveaway["chat_id"],
                message_id=int(message_id),
                text=t(lang, "give.cancelled"),
            )
    return True


# --------------------------------------------------------------------------- фоновый цикл
_task: asyncio.Task | None = None


async def _loop(bot: Bot, store: Store, interval: float = 20.0) -> None:
    while True:
        try:
            for giveaway in await store.due_giveaways():
                await finalize_giveaway(bot, store, giveaway)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен умирать
            log.exception("Ошибка фонового цикла розыгрышей")
        await asyncio.sleep(interval)


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


# --------------------------------------------------------------------------- админка
@router.callback_query(F.data == "adm:give")
async def cb_admin_list(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    text, kb = await render_admin(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:give:finish:"))
async def cb_admin_finish(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings
) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    giveaway_id = _id_from(call.data)
    giveaway = await store.get_giveaway(giveaway_id) if giveaway_id else None
    if giveaway is None:
        await call.answer(t("ru", "give.not_found"), show_alert=True)
        return
    finished = await finalize_giveaway(bot, store, giveaway)
    text, kb = await render_admin(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Завершён" if finished else t("ru", "give.over"))


@router.callback_query(F.data.startswith("adm:give:cancel:"))
async def cb_admin_cancel(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings
) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    giveaway_id = _id_from(call.data)
    giveaway = await store.get_giveaway(giveaway_id) if giveaway_id else None
    if giveaway is None:
        await call.answer(t("ru", "give.not_found"), show_alert=True)
        return
    cancelled = await cancel_giveaway(bot, store, giveaway)
    text, kb = await render_admin(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer(t("ru", "give.cancelled") if cancelled else t("ru", "give.over"))