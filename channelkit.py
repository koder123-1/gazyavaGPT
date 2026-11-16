"""Расширенное управление каналом: карточка, история постов, отложенные посты,
опросы и отправка сообщений из чата в канал.

Идея: у админа должен быть не только «написать пост», но и полный набор
действий над уже опубликованным — закрепить, поправить, удалить, повторить.
Плюс отложенные публикации, чтобы не сидеть в нужное время у телефона.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

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

from roles import ROLE_ADMIN, RoleFilter
from store import Store

log = logging.getLogger("channelkit")
router = Router(name="channelkit")
router.message.filter(RoleFilter(ROLE_ADMIN))
router.callback_query.filter(RoleFilter(ROLE_ADMIN))

MSK = timezone(timedelta(hours=3))
POSTS_KEY = "channel_posts"
PLAN_KEY = "scheduled_posts"
STATS_KEY = "channel_stats"
MAX_POSTS = 12
MAX_PLAN = 40
LOOP_INTERVAL = 30.0
MAX_TRIES = 3


class Kit(StatesGroup):
    when = State()
    edit_text = State()
    poll = State()


# --------------------------------------------------------------------------- json-хранилище
def _as_dict(raw: str | None) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _as_list(raw: str | None) -> list[dict]:
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


async def _save(store: Store, key: str, value: Any) -> None:
    await store.set_setting(key, json.dumps(value, ensure_ascii=False))


# --------------------------------------------------------------------------- история постов
async def load_history(store: Store, channel: str) -> list[dict]:
    return list(_as_dict(await store.get_setting(POSTS_KEY)).get(channel) or [])[:MAX_POSTS]


async def record_post(
    store: Store,
    channel: str,
    message_id: int,
    text: str,
    photo: str | None = None,
    buttons: list[dict] | None = None,
) -> None:
    """Запоминает публикацию, чтобы её можно было закрепить, поправить или удалить."""
    data = _as_dict(await store.get_setting(POSTS_KEY))
    rows = [row for row in (data.get(channel) or []) if row.get("mid") != message_id]
    rows.insert(
        0,
        {
            "mid": int(message_id),
            "text": (text or "")[:2500],
            "photo": photo,
            "buttons": buttons or [],
            "ts": datetime.now(MSK).isoformat(timespec="seconds"),
            "pinned": False,
        },
    )
    data[channel] = rows[:MAX_POSTS]
    await _save(store, POSTS_KEY, data)


async def _update_history(store: Store, channel: str, message_id: int, **changes: Any) -> None:
    data = _as_dict(await store.get_setting(POSTS_KEY))
    rows = data.get(channel) or []
    for row in rows:
        if row.get("mid") == message_id:
            row.update(changes)
    data[channel] = rows[:MAX_POSTS]
    await _save(store, POSTS_KEY, data)


async def _drop_history(store: Store, channel: str, message_id: int) -> None:
    data = _as_dict(await store.get_setting(POSTS_KEY))
    data[channel] = [
        row for row in (data.get(channel) or []) if row.get("mid") != message_id
    ][:MAX_POSTS]
    await _save(store, POSTS_KEY, data)


# --------------------------------------------------------------------------- отложенные посты
async def load_plan(store: Store) -> list[dict]:
    return _as_list(await store.get_setting(PLAN_KEY))[:MAX_PLAN]


async def _save_plan(store: Store, rows: list[dict]) -> None:
    await _save(store, PLAN_KEY, rows[:MAX_PLAN])


async def add_plan(store: Store, entry: dict) -> None:
    rows = await load_plan(store)
    rows.append(entry)
    rows.sort(key=lambda item: str(item.get("at") or ""))
    await _save_plan(store, rows)


async def cancel_plan(store: Store, plan_id: str) -> bool:
    rows = await load_plan(store)
    left = [row for row in rows if str(row.get("id")) != plan_id]
    if len(left) == len(rows):
        return False
    await _save_plan(store, left)
    return True


def parse_when(raw: str, now: datetime | None = None) -> datetime | None:
    """Понимает «16.11 18:30», «16.11.2026 18:30», «16.11», «18:30»."""
    now = now or datetime.now(MSK)
    value = " ".join((raw or "").replace(",", ".").split())
    if not value:
        return None
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%y %H:%M", "%d.%m %H:%M", "%d.%m.%Y", "%d.%m"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        parsed = parsed.replace(tzinfo=MSK)
        if "%Y" not in fmt:
            parsed = parsed.replace(year=now.year)
        if "%H" not in fmt:
            parsed = parsed.replace(hour=9, minute=0)
        return parsed
    try:
        clock = datetime.strptime(value, "%H:%M")
    except ValueError:
        return None
    candidate = now.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


# --------------------------------------------------------------------------- публикация
def _post_kb(post: dict) -> InlineKeyboardMarkup | None:
    buttons = post.get("buttons") or []
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=str(item["text"]), url=str(item["url"]))]
            for item in buttons
        ]
    )


async def _discussion_markup(
    bot: Bot, channel: str, markup: InlineKeyboardMarkup | None
) -> InlineKeyboardMarkup | None:
    """Добавляет кнопку «Обсудить», если у канала есть привязанный чат с username."""
    with contextlib.suppress(TelegramAPIError):
        chat = await bot.get_chat(channel)
        linked = getattr(chat, "linked_chat_id", None)
        if not linked:
            return markup
        linked_chat = await bot.get_chat(linked)
        username = getattr(linked_chat, "username", None)
        if not username:
            return markup
        url = f"https://t.me/{username}"
        rows = list(markup.inline_keyboard) if markup else []
        if any(button.url == url for row in rows for button in row):
            return markup
        rows.append([InlineKeyboardButton(text="💬 Обсудить", url=url)])
        return InlineKeyboardMarkup(inline_keyboard=rows)
    return markup


async def publish_to_channel(
    bot: Bot,
    store: Store,
    channel: str,
    post: dict,
    *,
    discussion: bool = True,
) -> Message:
    """Публикует пост, добавляет кнопку обсуждения и пишет его в историю."""
    text = str(post.get("text") or post.get("caption") or "").strip()
    markup = _post_kb(post)
    if discussion:
        markup = await _discussion_markup(bot, channel, markup)
    photo = post.get("photo")
    if photo:
        sent = await bot.send_photo(
            channel,
            photo=photo,
            caption=text[:1024] or None,
            reply_markup=markup,
            parse_mode=None,
        )
    else:
        sent = await bot.send_message(
            channel, text, reply_markup=markup, parse_mode=None
        )
    await record_post(store, channel, sent.message_id, text, photo, post.get("buttons"))
    return sent


# --------------------------------------------------------------------------- канал
async def _channels(store: Store) -> list[str]:
    from admin import _managed_channels

    return list(await _managed_channels(store))


async def _resolve(store: Store, index: int) -> str | None:
    channels = await _channels(store)
    if 0 <= index < len(channels):
        return channels[index]
    return None


async def channel_index(store: Store, channel: str) -> int:
    channels = await _channels(store)
    return channels.index(channel) if channel in channels else 0


async def _chat_info(bot: Bot, channel: str):
    chat = await bot.get_chat(channel)
    member = await bot.get_chat_member(chat.id, bot.id)
    count = await bot.get_chat_member_count(chat.id)
    return chat, member, count


def _rights(member) -> dict[str, bool]:
    admin = str(getattr(member, "status", "")) in {"administrator", "creator", "owner"}

    def flag(name: str) -> bool:
        value = getattr(member, name, None)
        # В каналах Telegram не отдаёт can_pin_messages — закреп считаем рабочим.
        return admin if value is None else bool(value)

    return {
        "post": flag("can_post_messages"),
        "pin": flag("can_pin_messages"),
        "delete": flag("can_delete_messages"),
        "edit": flag("can_edit_messages"),
    }


async def _stats_delta(store: Store, channel: str, count: int) -> int | None:
    data = _as_dict(await store.get_setting(STATS_KEY))
    previous = data.get(channel) or {}
    old = previous.get("count")
    data[channel] = {"count": int(count), "ts": datetime.now(MSK).isoformat(timespec="seconds")}
    await _save(store, STATS_KEY, data)
    if isinstance(old, int):
        return int(count) - old
    return None


def _stamp(value: str) -> str:
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value or ""
    return moment.astimezone(MSK).strftime("%d.%m %H:%M")


async def render_card(
    bot: Bot, store: Store, index: int, note: str = ""
) -> tuple[str, InlineKeyboardMarkup]:
    channel = await _resolve(store, index)
    if channel is None:
        return "Канал не найден. Обнови список.", InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ К каналу", callback_data="adm:ch")]]
        )
    try:
        chat, member, count = await _chat_info(bot, channel)
    except TelegramAPIError as exc:
        log.warning("Карточка канала %s недоступна: %s", channel, exc)
        return (
            f"⚠️ Не удалось открыть {escape(channel)}.\n"
            "Проверь, что бот всё ещё администратор канала.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"adm:ck:card:{index}")],
                    [InlineKeyboardButton(text="⬅️ К каналу", callback_data="adm:ch")],
                ]
            ),
        )

    rights = _rights(member)
    delta = await _stats_delta(store, channel, count)
    history = await load_history(store, channel)
    plan = [row for row in await load_plan(store) if row.get("channel") == channel]
    username = getattr(chat, "username", None)
    title = getattr(chat, "title", None) or channel
    linked = getattr(chat, "linked_chat_id", None)
    pinned = getattr(chat, "pinned_message", None)

    def mark(ok: bool) -> str:
        return "✅" if ok else "❌"

    lines = [
        f"📊 <b>{escape(str(title))}</b>",
        "",
        f"🆔 <code>{chat.id}</code>"
        + (f" · 🔗 @{escape(username)}" if username else ""),
        f"👥 Подписчиков: <b>{count}</b>"
        + (f" ({delta:+d} с прошлой проверки)" if delta else ""),
        "",
        "<b>Права бота</b>",
        f"{mark(rights['post'])} публикация · {mark(rights['edit'])} правка · "
        f"{mark(rights['pin'])} закреп · {mark(rights['delete'])} удаление",
        f"💬 Обсуждение: {'есть' if linked else 'не привязано'}",
    ]
    if pinned is not None:
        lines.append(f"📌 Закреплён пост #{getattr(pinned, 'message_id', '?')}")
    else:
        lines.append("📌 Закрепа нет")
    lines += [
        "",
        f"📋 В истории: <b>{len(history)}</b> постов · 🕘 Отложено: <b>{len(plan)}</b>",
    ]
    if note:
        lines += ["", note]

    rows = [
        [
            InlineKeyboardButton(text="✍️ Новый пост", callback_data=f"adm:ch:pick:{index}"),
            InlineKeyboardButton(text="📋 История", callback_data=f"adm:ck:hist:{index}"),
        ],
        [
            InlineKeyboardButton(text="🕘 Отложенные", callback_data=f"adm:ck:plan:{index}"),
            InlineKeyboardButton(text="📊 Опрос", callback_data=f"adm:ck:poll:{index}"),
        ],
        [
            InlineKeyboardButton(text="📌 Закрепить последний", callback_data=f"adm:ck:pinlast:{index}"),
            InlineKeyboardButton(text="📌 Снять закреп", callback_data=f"adm:ck:unpin:{index}"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"adm:ck:card:{index}"),
            InlineKeyboardButton(text="🕘 Автопосты", callback_data="adm:auto"),
        ],
        [InlineKeyboardButton(text="⬅️ К каналу", callback_data="adm:ch")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _preview(text: str, limit: int = 70) -> str:
    flat = " ".join((text or "").split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


async def render_history(
    store: Store, channel: str, index: int, note: str = ""
) -> tuple[str, InlineKeyboardMarkup]:
    rows_data = await load_history(store, channel)
    lines = [f"📋 <b>История постов</b> · {escape(channel)}", ""]
    if not rows_data:
        lines.append("Пока пусто: опубликуй первый пост, и он появится здесь.")
    else:
        for number, row in enumerate(rows_data, start=1):
            pin = "📌 " if row.get("pinned") else ""
            photo = "🖼 " if row.get("photo") else ""
            lines.append(
                f"{number}. {pin}{photo}{_stamp(str(row.get('ts') or ''))} · "
                f"#{row.get('mid')}\n   {escape(_preview(str(row.get('text') or '')))}"
            )
    if note:
        lines += ["", note]
    lines += [
        "",
        "<i>Кнопки под списком действуют на пост с тем же номером.</i>",
    ]

    buttons: list[list[InlineKeyboardButton]] = []
    for number, row in enumerate(rows_data, start=1):
        mid = int(row.get("mid") or 0)
        pin_label = "📍" if row.get("pinned") else "📌"
        buttons.append(
            [
                InlineKeyboardButton(text=f"{pin_label}{number}", callback_data=f"adm:ck:pin:{index}:{mid}"),
                InlineKeyboardButton(text=f"✏️{number}", callback_data=f"adm:ck:edit:{index}:{mid}"),
                InlineKeyboardButton(text=f"🔁{number}", callback_data=f"adm:ck:rep:{index}:{mid}"),
                InlineKeyboardButton(text=f"🗑{number}", callback_data=f"adm:ck:del:{index}:{mid}"),
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"adm:ck:hist:{index}"),
            InlineKeyboardButton(text="⬅️ К каналу", callback_data=f"adm:ck:card:{index}"),
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_plan(
    store: Store, channel: str, index: int, note: str = ""
) -> tuple[str, InlineKeyboardMarkup]:
    rows_data = [row for row in await load_plan(store) if row.get("channel") == channel]
    lines = [f"🕘 <b>Отложенные посты</b> · {escape(channel)}", ""]
    if not rows_data:
        lines.append(
            "Ничего не запланировано. Открой пост, нажми «🕘 Отложить» и пришли время, "
            "например <code>16.11 18:30</code>."
        )
    else:
        for number, row in enumerate(rows_data, start=1):
            photo = "🖼 " if row.get("photo") else ""
            buttons = len(row.get("buttons") or [])
            lines.append(
                f"{number}. <b>{_stamp(str(row.get('at') or ''))} МСК</b> · "
                f"{photo}{escape(_preview(str(row.get('text') or '')))}\n"
                f"   кнопок: {buttons}"
            )
    if note:
        lines += ["", note]
    buttons = [
        [
            InlineKeyboardButton(
                text=f"❌ Отменить {number}",
                callback_data=f"adm:ck:unplan:{index}:{row.get('id')}",
            )
        ]
        for number, row in enumerate(rows_data, start=1)
    ]
    buttons.append(
        [
            InlineKeyboardButton(text="🔄 Обновить", callback_data=f"adm:ck:plan:{index}"),
            InlineKeyboardButton(text="⬅️ К каналу", callback_data=f"adm:ck:card:{index}"),
        ]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def _show(call: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=keyboard)


# --------------------------------------------------------------------------- роутер: карточка
@router.callback_query(F.data.startswith("adm:ck:card:"))
async def cb_card(call: CallbackQuery, bot: Bot, store: Store) -> None:
    index = _tail_int(call.data)
    text, keyboard = await render_card(bot, store, index)
    await _show(call, text, keyboard)
    await call.answer()


@router.callback_query(F.data.startswith("adm:ck:hist:"))
async def cb_history(call: CallbackQuery, store: Store) -> None:
    index = _tail_int(call.data)
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    text, keyboard = await render_history(store, channel, index)
    await _show(call, text, keyboard)
    await call.answer()


@router.callback_query(F.data.startswith("adm:ck:plan:"))
async def cb_plan(call: CallbackQuery, store: Store) -> None:
    index = _tail_int(call.data)
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    text, keyboard = await render_plan(store, channel, index)
    await _show(call, text, keyboard)
    await call.answer()


def _tail_int(data: str | None) -> int:
    try:
        return int(str(data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return -1


def _parts(data: str | None) -> list[str]:
    return str(data or "").split(":")


# --------------------------------------------------------------------------- закреп
@router.callback_query(F.data.startswith("adm:ck:pinlast:"))
async def cb_pin_last(call: CallbackQuery, bot: Bot, store: Store) -> None:
    index = _tail_int(call.data)
    channel = await _resolve(store, index)
    history = await load_history(store, channel) if channel else []
    if not channel or not history:
        await call.answer("В истории пока нет постов", show_alert=True)
        return
    mid = int(history[0]["mid"])
    try:
        await bot.pin_chat_message(channel, mid, disable_notification=True)
    except TelegramAPIError as exc:
        log.warning("Не удалось закрепить %s/#%s: %s", channel, mid, exc)
        await call.answer("Не получилось закрепить: проверь право «Закрепление сообщений».", show_alert=True)
        return
    await _update_history(store, channel, mid, pinned=True)
    text, keyboard = await render_card(bot, store, index, note=f"📌 Закреплён пост #{mid}.")
    await _show(call, text, keyboard)
    await call.answer("Закреплено")


@router.callback_query(F.data.startswith("adm:ck:unpin:"))
async def cb_unpin(call: CallbackQuery, bot: Bot, store: Store) -> None:
    index = _tail_int(call.data)
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    try:
        await bot.unpin_chat_message(channel)
    except TelegramAPIError as exc:
        log.warning("Не удалось снять закреп в %s: %s", channel, exc)
        await call.answer("Не получилось снять закреп.", show_alert=True)
        return
    for row in await load_history(store, channel):
        if row.get("pinned"):
            await _update_history(store, channel, int(row["mid"]), pinned=False)
    text, keyboard = await render_card(bot, store, index, note="📌 Закреп снят.")
    await _show(call, text, keyboard)
    await call.answer("Закреп снят")


@router.callback_query(F.data.startswith("adm:ck:pin:"))
async def cb_pin(call: CallbackQuery, bot: Bot, store: Store) -> None:
    parts = _parts(call.data)
    try:
        index, mid = int(parts[3]), int(parts[4])
    except (IndexError, ValueError):
        await call.answer("Неверный пост", show_alert=True)
        return
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    history = await load_history(store, channel)
    row = next((item for item in history if int(item.get("mid") or 0) == mid), None)
    if row is None:
        await call.answer("Пост уже не в истории", show_alert=True)
        return
    try:
        if row.get("pinned"):
            await bot.unpin_chat_message(channel)
            await _update_history(store, channel, mid, pinned=False)
            note = f"📍 Закреп с поста #{mid} снят."
        else:
            await bot.pin_chat_message(channel, mid, disable_notification=True)
            await _update_history(store, channel, mid, pinned=True)
            note = f"📌 Пост #{mid} закреплён."
    except TelegramAPIError as exc:
        log.warning("Закреп %s/#%s не удался: %s", channel, mid, exc)
        await call.answer("Не получилось: проверь право «Закрепление сообщений».", show_alert=True)
        return
    text, keyboard = await render_history(store, channel, index, note=note)
    await _show(call, text, keyboard)
    await call.answer("Готово")


# --------------------------------------------------------------------------- удаление и повтор
@router.callback_query(F.data.startswith("adm:ck:del:"))
async def cb_delete(call: CallbackQuery, bot: Bot, store: Store) -> None:
    parts = _parts(call.data)
    try:
        index, mid = int(parts[3]), int(parts[4])
    except (IndexError, ValueError):
        await call.answer("Неверный пост", show_alert=True)
        return
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    try:
        await bot.delete_message(channel, mid)
    except TelegramAPIError as exc:
        log.warning("Удаление %s/#%s не удалось: %s", channel, mid, exc)
        if "message to delete not found" not in str(exc).lower():
            await call.answer("Не удалось удалить: проверь право «Удаление сообщений».", show_alert=True)
            return
    await _drop_history(store, channel, mid)
    text, keyboard = await render_history(store, channel, index, note=f"🗑 Пост #{mid} удалён.")
    await _show(call, text, keyboard)
    await call.answer("Удалено")


@router.callback_query(F.data.startswith("adm:ck:rep:"))
async def cb_repost(call: CallbackQuery, bot: Bot, store: Store) -> None:
    parts = _parts(call.data)
    try:
        index, mid = int(parts[3]), int(parts[4])
    except (IndexError, ValueError):
        await call.answer("Неверный пост", show_alert=True)
        return
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    row = next(
        (item for item in await load_history(store, channel) if int(item.get("mid") or 0) == mid),
        None,
    )
    if row is None:
        await call.answer("Пост уже не в истории", show_alert=True)
        return
    try:
        sent = await publish_to_channel(
            bot,
            store,
            channel,
            {"text": row.get("text") or "", "photo": row.get("photo"), "buttons": row.get("buttons") or []},
        )
    except TelegramAPIError as exc:
        log.warning("Повтор поста в %s не удался: %s", channel, exc)
        await call.answer("Telegram не принял пост. Проверь права бота.", show_alert=True)
        return
    text, keyboard = await render_history(
        store, channel, index, note=f"🔁 Опубликовано заново: #{sent.message_id}."
    )
    await _show(call, text, keyboard)
    await call.answer("Опубликовано")


# --------------------------------------------------------------------------- правка поста
@router.callback_query(F.data.startswith("adm:ck:edit:"))
async def cb_edit(call: CallbackQuery, store: Store, state: FSMContext) -> None:
    parts = _parts(call.data)
    try:
        index, mid = int(parts[3]), int(parts[4])
    except (IndexError, ValueError):
        await call.answer("Неверный пост", show_alert=True)
        return
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    row = next(
        (item for item in await load_history(store, channel) if int(item.get("mid") or 0) == mid),
        None,
    )
    if row is None:
        await call.answer("Пост уже не в истории", show_alert=True)
        return
    await state.set_state(Kit.edit_text)
    await state.update_data(kit_channel=channel, kit_index=index, kit_mid=mid, kit_photo=row.get("photo"))
    current = _preview(str(row.get("text") or ""), 200)
    await _show(
        call,
        f"✏️ <b>Правка поста #{mid}</b>\n\nСейчас: <i>{escape(current)}</i>\n\n"
        "Пришли новый текст. /cancel — отмена.",
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"adm:ck:hist:{index}")]]
        ),
    )
    await state.set_state(Kit.edit_text)
    await call.answer()


@router.message(Kit.edit_text, F.text)
async def on_edit_text(message: Message, bot: Bot, store: Store, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пришли непустой текст.")
        return
    data = await state.get_data()
    channel = str(data.get("kit_channel") or "")
    index = int(data.get("kit_index") or 0)
    mid = int(data.get("kit_mid") or 0)
    if not channel or not mid:
        await state.clear()
        await message.answer("Не понял, какой пост править. Открой историю заново.")
        return
    try:
        if data.get("kit_photo"):
            await bot.edit_message_caption(
                channel, mid, caption=text[:1024], parse_mode=None
            )
        else:
            await bot.edit_message_text(text, chat_id=channel, message_id=mid, parse_mode=None)
    except TelegramAPIError as exc:
        log.warning("Правка %s/#%s не удалась: %s", channel, mid, exc)
        await message.answer(
            "Не удалось изменить пост. Проверь право «Редактирование сообщений» "
            "и что текст укладывается в лимит."
        )
        return
    await _update_history(store, channel, mid, text=text[:2500])
    await state.clear()
    panel, keyboard = await render_history(store, channel, index, note=f"✏️ Пост #{mid} обновлён.")
    await message.answer(panel, reply_markup=keyboard)


@router.message(Kit.edit_text)
async def on_edit_non_text(message: Message) -> None:
    await message.answer("Нужен текст. /cancel — отмена.")


# --------------------------------------------------------------------------- отложенная публикация
@router.callback_query(F.data == "adm:ck:later")
async def cb_later(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    post = data.get("channel_post") or {}
    channel = str(data.get("channel_target") or "")
    if not channel or (not (post.get("text") or post.get("caption")) and not post.get("photo")):
        await call.answer("Сначала добавь текст или фото поста", show_alert=True)
        return
    await state.set_state(Kit.when)
    await _show(
        call,
        "🕘 <b>Когда опубликовать?</b>\n\n"
        "Пришли дату и время по Москве: <code>16.11 18:30</code>, "
        "<code>16.11.2026 18:30</code> или только время <code>18:30</code>.\n"
        "Без времени — в 09:00. /cancel — отмена.",
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад к посту", callback_data="adm:ch:back")]]
        ),
    )
    await call.answer()


@router.message(Kit.when, F.text)
async def on_when(message: Message, state: FSMContext, store: Store) -> None:
    when = parse_when(message.text or "")
    now = datetime.now(MSK)
    if when is None:
        await message.answer(
            "Не понял время. Примеры: <code>16.11 18:30</code>, <code>18:30</code>, <code>16.11</code>."
        )
        return
    if when <= now:
        await message.answer(
            f"Это время уже прошло ({when.strftime('%d.%m %H:%M')} МСК). Пришли будущее время."
        )
        return
    data = await state.get_data()
    post = data.get("channel_post") or {}
    channel = str(data.get("channel_target") or "")
    if not channel:
        await state.clear()
        await message.answer("Канал потерялся. Открой пост заново из /admin → 📢 Канал.")
        return
    entry = {
        "id": f"{int(now.timestamp())}-{abs(hash((channel, when.isoformat()))) % 1000}",
        "channel": channel,
        "text": str(post.get("text") or ""),
        "photo": post.get("photo"),
        "buttons": post.get("buttons") or [],
        "at": when.isoformat(timespec="seconds"),
        "created_by": message.from_user.id if message.from_user else 0,
        "tries": 0,
    }
    await add_plan(store, entry)
    await state.clear()
    channels = await _channels(store)
    index = channels.index(channel) if channel in channels else 0
    text, keyboard = await render_plan(
        store,
        channel,
        index,
        note=f"✅ Запланировано на <b>{when.strftime('%d.%m %H:%M')} МСК</b>.",
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(Kit.when)
async def on_when_non_text(message: Message) -> None:
    await message.answer("Пришли дату и время текстом, например <code>16.11 18:30</code>.")


@router.callback_query(F.data.startswith("adm:ck:unplan:"))
async def cb_unplan(call: CallbackQuery, store: Store) -> None:
    parts = _parts(call.data)
    try:
        index = int(parts[3])
        plan_id = parts[4]
    except (IndexError, ValueError):
        await call.answer("Неверная запись", show_alert=True)
        return
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    if not await cancel_plan(store, plan_id):
        await call.answer("Уже отменено", show_alert=True)
        return
    text, keyboard = await render_plan(store, channel, index, note="🗑 Публикация отменена.")
    await _show(call, text, keyboard)
    await call.answer("Отменено")


# --------------------------------------------------------------------------- опрос
@router.callback_query(F.data.startswith("adm:ck:poll:"))
async def cb_poll(call: CallbackQuery, state: FSMContext, store: Store) -> None:
    index = _tail_int(call.data)
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    await state.set_state(Kit.poll)
    await state.update_data(kit_channel=channel, kit_index=index)
    await _show(
        call,
        f"📊 <b>Опрос в {escape(channel)}</b>\n\n"
        "Пришли одной строкой: <code>Вопрос | вариант 1 | вариант 2</code>\n"
        "От 2 до 10 вариантов. /cancel — отмена.",
        InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="⬅️ Отмена", callback_data=f"adm:ck:card:{index}")]]
        ),
    )
    await call.answer()


@router.message(Kit.poll, F.text)
async def on_poll(message: Message, bot: Bot, store: Store, state: FSMContext) -> None:
    parts = [part.strip() for part in (message.text or "").split("|") if part.strip()]
    if len(parts) < 3:
        await message.answer(
            "Нужно минимум два варианта: <code>Вопрос | вариант 1 | вариант 2</code>."
        )
        return
    question, options = parts[0], parts[1:]
    if len(question) > 255:
        await message.answer("Вопрос длиннее 255 символов — сократи.")
        return
    if len(options) > 10:
        await message.answer("В опросе не больше 10 вариантов.")
        return
    if any(len(option) > 100 for option in options):
        await message.answer("Каждый вариант — до 100 символов.")
        return
    data = await state.get_data()
    channel = str(data.get("kit_channel") or "")
    index = int(data.get("kit_index") or 0)
    if not channel:
        await state.clear()
        await message.answer("Канал потерялся. Начни заново из /admin → 📢 Канал.")
        return
    try:
        sent = await bot.send_poll(
            channel, question=question, options=options, is_anonymous=True
        )
    except TelegramAPIError as exc:
        log.warning("Опрос в %s не отправлен: %s", channel, exc)
        await message.answer("Telegram не принял опрос. Проверь права бота в канале.")
        return
    await record_post(store, channel, sent.message_id, f"📊 Опрос: {question}")
    await state.clear()
    text, keyboard = await render_card(
        bot, store, index, note=f"📊 Опрос #{sent.message_id} опубликован."
    )
    await message.answer(text, reply_markup=keyboard)


@router.message(Kit.poll)
async def on_poll_non_text(message: Message) -> None:
    await message.answer("Нужен текст: <code>Вопрос | вариант 1 | вариант 2</code>.")


# --------------------------------------------------------------------------- /topost
@router.message(Command("topost"))
async def cmd_topost(message: Message, store: Store, state: FSMContext) -> None:
    channels = await _channels(store)
    if not channels:
        await message.reply(
            "Сначала подключи канал: /admin → 📢 Канал → ➕ Подключить канал."
        )
        return
    source = message.reply_to_message
    if source is None:
        await message.reply(
            "📤 Ответь командой /topost на сообщение, которое нужно отправить в канал."
        )
        return
    await state.update_data(
        share_chat=message.chat.id,
        share_mid=source.message_id,
        share_text=(source.text or source.caption or "")[:2500],
        share_photo=(source.photo[-1].file_id if source.photo else None),
    )
    rows = [
        [InlineKeyboardButton(text=f"📢 {channel}", callback_data=f"adm:ck:share:{index}")]
        for index, channel in enumerate(channels)
    ]
    await message.reply(
        "📤 <b>Куда отправить?</b>\n\nСообщение скопируется в выбранный канал.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data.startswith("adm:ck:share:"))
async def cb_share(call: CallbackQuery, bot: Bot, store: Store, state: FSMContext) -> None:
    index = _tail_int(call.data)
    channel = await _resolve(store, index)
    if channel is None:
        await call.answer("Канал не найден", show_alert=True)
        return
    data = await state.get_data()
    chat_id = data.get("share_chat")
    mid = data.get("share_mid")
    if not chat_id or not mid:
        await call.answer("Сообщение не найдено — повтори /topost", show_alert=True)
        return
    try:
        sent = await bot.copy_message(channel, from_chat_id=int(chat_id), message_id=int(mid))
    except TelegramAPIError as exc:
        log.warning("Копирование в %s не удалось: %s", channel, exc)
        await call.answer("Не удалось отправить: проверь права бота.", show_alert=True)
        return
    await record_post(
        store,
        channel,
        sent.message_id,
        str(data.get("share_text") or ""),
        data.get("share_photo"),
    )
    await state.update_data(share_chat=None, share_mid=None)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(
            f"✅ Сообщение отправлено в {escape(channel)} (#{sent.message_id}).",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📋 История", callback_data=f"adm:ck:hist:{index}")],
                    [InlineKeyboardButton(text="⬅️ К каналу", callback_data="adm:ch")],
                ]
            ),
        )
    await call.answer("Отправлено")


# --------------------------------------------------------------------------- фоновый цикл
_task: asyncio.Task | None = None


async def run_due(bot: Bot, store: Store) -> int:
    """Публикует всё, чему пришло время. Возвращает число отправленных постов."""
    rows = await load_plan(store)
    if not rows:
        return 0
    now = datetime.now(MSK)
    keep: list[dict] = []
    sent_count = 0
    for row in rows:
        try:
            when = datetime.fromisoformat(str(row.get("at")))
        except (TypeError, ValueError):
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=MSK)
        if when > now:
            keep.append(row)
            continue
        try:
            sent = await publish_to_channel(
                bot,
                store,
                str(row.get("channel") or ""),
                {
                    "text": row.get("text") or "",
                    "photo": row.get("photo"),
                    "buttons": row.get("buttons") or [],
                },
            )
        except TelegramAPIError as exc:
            tries = int(row.get("tries") or 0) + 1
            log.warning("Отложенный пост в %s не ушёл (попытка %s): %s", row.get("channel"), tries, exc)
            if tries < MAX_TRIES:
                row["tries"] = tries
                keep.append(row)
            else:
                owner_id = int(row.get("created_by") or 0)
                if owner_id:
                    with contextlib.suppress(TelegramAPIError):
                        await bot.send_message(
                            owner_id,
                            f"⚠️ Отложенный пост в {row.get('channel')} не опубликован: {exc}",
                        )
            continue
        sent_count += 1
        owner_id = int(row.get("created_by") or 0)
        if owner_id:
            with contextlib.suppress(TelegramAPIError):
                await bot.send_message(
                    owner_id,
                    f"✅ Отложенный пост вышел в {row.get('channel')} (#{sent.message_id}).",
                )
    if sent_count or len(keep) != len(rows):
        await _save_plan(store, keep)
    return sent_count


async def _loop(bot: Bot, store: Store) -> None:
    while True:
        try:
            await run_due(bot, store)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен умирать
            log.exception("Ошибка цикла отложенных постов")
        await asyncio.sleep(LOOP_INTERVAL)


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