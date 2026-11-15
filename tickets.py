"""Тикеты поддержки: пользователь описывает проблему, саппорт отвечает и закрывает."""

from __future__ import annotations

import contextlib
import logging
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
from payments import render_support
from roles import (
    StaffFilter,
    has_admin_access,
    is_staff,
    resolve_role,
    staff_ids,
)
from store import Store

log = logging.getLogger("tickets")
router = Router(name="tickets")

MAX_TICKET_CHARS = 2000
MIN_TICKET_CHARS = 5
LIST_PAGE = 8
VIEW_MESSAGES = 12
VIEW_LIMIT = 3600

TOPICS: dict[str, tuple[str, str]] = {
    "payment": ("💳 Оплата", "Оплата и звёзды"),
    "answer": ("🧠 Ответ ИИ", "Ошибка в ответе ИИ"),
    "access": ("🚫 Доступ", "Доступ и блокировки"),
    "other": ("💬 Другое", "Другое"),
}

STATUS = {"open": "🟢 открыто", "closed": "⚪ закрыто"}


class TicketFlow(StatesGroup):
    message = State()
    reply = State()
    user_reply = State()


# --------------------------------------------------------------------------- утилиты
def topic_title(topic: str) -> str:
    return TOPICS.get(topic, TOPICS["other"])[1]


def status_text(status: str) -> str:
    return STATUS.get(status, status)


def display_name(row: dict) -> str:
    if row.get("username"):
        return f"@{row['username']}"
    return row.get("first_name") or str(row.get("user_id") or "")


def fmt_time(when) -> str:
    return when.strftime("%d.%m %H:%M") if hasattr(when, "strftime") else ""


def parse_ticket_id(data: str | None) -> int:
    try:
        return int((data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return 0


def _topic_rows() -> list[list[InlineKeyboardButton]]:
    return [
        [InlineKeyboardButton(text=label, callback_data=f"tick:new:{key}")]
        for key, (label, _) in TOPICS.items()
    ]


async def support_menu(store: Store, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    open_ticket = await store.user_open_ticket(user_id)
    text = (
        "🆘 <b>Поддержка</b>\n\n"
        "Опиши проблему — саппорт ответит здесь же, в личке.\n"
        "• оплата и звёзды;\n"
        "• ошибка или странный ответ ИИ;\n"
        "• доступ, бан, лимиты;\n"
        "• любой другой вопрос.\n\n"
        "Если по оплате — укажи дату покупки и сколько звёзд списалось. "
        "Одно обращение на одну проблему: лучше дополнить старое, чем создавать новое."
    )
    rows = _topic_rows()
    if open_ticket:
        text += (
            f"\n\n🟢 У тебя есть открытое обращение <b>#{open_ticket['id']}</b> "
            f"({escape(topic_title(open_ticket['topic']))})."
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"✍️ Ответить в #{open_ticket['id']}",
                    callback_data=f"tick:userreply:{open_ticket['id']}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="📨 Мои обращения", callback_data="tick:mine")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def render_my_tickets(store: Store, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    rows = await store.user_tickets(user_id, 10)
    if not rows:
        return (
            "📨 <b>Мои обращения</b>\n\nТы ещё не писал в поддержку.",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Написать в поддержку", callback_data="tick:menu")]
                ]
            ),
        )
    lines = ["📨 <b>Мои обращения</b>\n"]
    buttons = []
    for row in rows:
        topic = escape(topic_title(row["topic"]))
        lines.append(
            f"#{row['id']} · {topic} · {status_text(row['status'])} · {fmt_time(row['updated_at'])}"
        )
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"📨 #{row['id']} · {topic_title(row['topic'])}",
                    callback_data=f"tick:view:{row['id']}",
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton(text="🆘 Новое обращение", callback_data="tick:menu")]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_ticket(
    store: Store, ticket_id: int, *, staff: bool
) -> tuple[str, InlineKeyboardMarkup] | None:
    ticket = await store.get_ticket(ticket_id)
    if not ticket:
        return None
    messages = await store.ticket_messages(ticket_id, VIEW_MESSAGES)

    header = (
        f"🎫 <b>Обращение #{ticket['id']}</b> · {status_text(ticket['status'])}\n"
        f"Тема: <b>{escape(topic_title(ticket['topic']))}</b>\n"
        f"Автор: {escape(display_name(ticket))} (<code>{ticket['user_id']}</code>)\n"
        f"Создано: {fmt_time(ticket['created_at'])} · обновлено: {fmt_time(ticket['updated_at'])}"
    )

    blocks = []
    for message in messages:
        who = "🛡 <b>Поддержка</b>" if message["from_staff"] else "👤 <b>Автор</b>"
        body = message["text"]
        if len(body) > 700:
            body = body[:700] + "…"
        blocks.append(f"{who} · {fmt_time(message['created_at'])}\n{escape(body)}")

    text = header
    tail: list[str] = []
    for block in reversed(blocks):
        candidate = "\n\n" + block
        if len(text) + len(candidate) + sum(len(b) + 2 for b in tail) > VIEW_LIMIT:
            break
        tail.insert(0, block)
    if len(tail) < len(blocks):
        text += "\n\n<i>…показаны последние сообщения</i>"
    if tail:
        text += "\n\n" + "\n\n".join(tail)
    else:
        text += "\n\nСообщений пока нет."

    buttons: list[list[InlineKeyboardButton]] = []
    if staff:
        if ticket["status"] == "open":
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="✍️ Ответить", callback_data=f"tick:reply:{ticket_id}"
                    ),
                    InlineKeyboardButton(
                        text="✅ Закрыть", callback_data=f"tick:close:{ticket_id}"
                    ),
                ]
            )
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🔄 Обновить", callback_data=f"tick:refresh:{ticket_id}"
                )
            ]
        )
        buttons.append(
            [InlineKeyboardButton(text="⬅️ К списку", callback_data="tick:list:0")]
        )
    else:
        if ticket["status"] == "open":
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="✍️ Ответить", callback_data=f"tick:userreply:{ticket_id}"
                    )
                ]
            )
        buttons.append(
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="tick:menu")]
        )
        buttons.append(
            [InlineKeyboardButton(text="📨 Мои обращения", callback_data="tick:mine")]
        )
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_ticket_list(
    store: Store, offset: int, *, admin: bool = False
) -> tuple[str, InlineKeyboardMarkup]:
    stats = await store.tickets_stats()
    rows = await store.open_tickets(LIST_PAGE, offset)
    lines = [
        "🎫 <b>Тикеты поддержки</b>\n",
        f"Открытых: <b>{stats['open']}</b> · закрытых: {stats['closed']} · всего {stats['total']}",
    ]
    buttons: list[list[InlineKeyboardButton]] = []
    if rows:
        lines.append("")
        for row in rows:
            topic = escape(topic_title(row["topic"]))
            lines.append(
                f"#{row['id']} · {topic} · {escape(display_name(row))} "
                f"(<code>{row['user_id']}</code>) · {fmt_time(row['updated_at'])}"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"🎫 #{row['id']} · {topic_title(row['topic'])}",
                        callback_data=f"tick:view:{row['id']}",
                    )
                ]
            )
        nav = []
        if offset > 0:
            nav.append(
                InlineKeyboardButton(
                    text="⬅️", callback_data=f"tick:list:{max(0, offset - LIST_PAGE)}"
                )
            )
        if offset + LIST_PAGE < stats["open"]:
            nav.append(
                InlineKeyboardButton(
                    text="➡️", callback_data=f"tick:list:{offset + LIST_PAGE}"
                )
            )
        if nav:
            buttons.append(nav)
    else:
        lines.append("\nОткрытых обращений нет — все вопросы закрыты ✅")

    buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"tick:list:{offset}")])
    if admin:
        buttons.append([InlineKeyboardButton(text="🛠 Админка", callback_data="adm:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def _notify_staff(
    bot: Bot,
    store: Store,
    settings: Settings,
    ticket: dict,
    body: str,
    *,
    fresh: bool,
) -> None:
    title = "🆕 <b>Новое обращение</b>" if fresh else "💬 <b>Новое сообщение в обращении</b>"
    header = (
        f"{title} #{ticket['id']}\n"
        f"Тема: {escape(topic_title(ticket['topic']))}\n"
        f"От: {escape(display_name(ticket))} (<code>{ticket['user_id']}</code>)"
    )
    preview = body if len(body) <= 900 else body[:900] + "…"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🎫 Открыть #{ticket['id']}",
                    callback_data=f"tick:view:{ticket['id']}",
                )
            ]
        ]
    )
    for staff_id in await staff_ids(store, settings):
        if staff_id == ticket["user_id"]:
            continue
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(
                staff_id, f"{header}\n\n{escape(preview)}", reply_markup=kb
            )


async def _ask_problem(
    target: Message, state: FSMContext, store: Store, topic: str, user_id: int
) -> None:
    open_ticket = await store.user_open_ticket(user_id)
    note = (
        f"\n\n🟢 Сообщение добавится в открытое обращение <b>#{open_ticket['id']}</b>."
        if open_ticket
        else ""
    )
    await state.set_state(TicketFlow.message)
    await state.update_data(topic=topic)
    await target.answer(
        f"{TOPICS[topic][0]} — <b>{escape(topic_title(topic))}</b>\n\n"
        "Опиши проблему <b>одним сообщением</b>: что случилось и что уже пробовал.\n"
        "Если про оплату — дата покупки и сколько звёзд списалось.\n"
        f"Длина — от {MIN_TICKET_CHARS} до {MAX_TICKET_CHARS} символов.{note}\n\n"
        "/cancel — отмена."
    )


# --------------------------------------------------------------------------- вход
@router.message(Command("support"))
async def cmd_support(message: Message, store: Store) -> None:
    user = message.from_user
    if user is None:
        return
    if message.chat.type != "private":
        await message.reply("Поддержка — в личке: /support")
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    text, kb = await support_menu(store, user.id)
    await message.answer(text, reply_markup=kb)


@router.message(Command("paysupport"))
async def cmd_paysupport(message: Message, settings: Settings) -> None:
    if message.chat.type != "private":
        await message.reply("Поддержка по оплате — в личке: /paysupport")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎫 Написать в поддержку", callback_data="tick:new:payment"
                )
            ],
            [InlineKeyboardButton(text="📨 Мои обращения", callback_data="tick:mine")],
        ]
    )
    await message.answer(render_support(settings), reply_markup=kb)


@router.callback_query(F.data == "pay:support")
async def cb_pay_support(
    call: CallbackQuery, store: Store, state: FSMContext
) -> None:
    if call.from_user is None or call.message is None:
        return
    if call.message.chat.type != "private":
        await call.answer("Напиши мне в личку /paysupport", show_alert=True)
        return
    await store.ensure_user(call.from_user.id, call.from_user.username, call.from_user.first_name)
    await _ask_problem(call.message, state, store, "payment", call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "tick:menu")
async def cb_menu(call: CallbackQuery, store: Store) -> None:
    if call.from_user is None:
        return
    text, kb = await support_menu(store, call.from_user.id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "tick:mine")
async def cb_mine(call: CallbackQuery, store: Store) -> None:
    if call.from_user is None:
        return
    text, kb = await render_my_tickets(store, call.from_user.id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("tick:new:"))
async def cb_new(
    call: CallbackQuery, store: Store, settings: Settings, state: FSMContext
) -> None:
    if call.from_user is None or call.message is None:
        return
    topic = (call.data or "").rsplit(":", 1)[-1]
    if topic not in TOPICS:
        await call.answer("Неизвестная тема", show_alert=True)
        return
    if call.message.chat.type != "private":
        await call.answer("Напиши мне в личку /support", show_alert=True)
        return
    await store.ensure_user(call.from_user.id, call.from_user.username, call.from_user.first_name)
    await _ask_problem(call.message, state, store, topic, call.from_user.id)
    await call.answer()


# --------------------------------------------------------------------------- сообщение пользователя
@router.message(TicketFlow.message, F.text)
async def on_ticket_text(
    message: Message, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("Отменено.")
        return
    if len(text) < MIN_TICKET_CHARS:
        await message.answer(
            f"Слишком коротко. Опиши проблему подробнее — минимум {MIN_TICKET_CHARS} символов."
        )
        return
    if len(text) > MAX_TICKET_CHARS:
        await message.answer(
            f"Слишком длинно: до {MAX_TICKET_CHARS} символов. Сократи, пожалуйста."
        )
        return

    data = await state.get_data()
    topic = data.get("topic", "other")
    user = message.from_user
    if user is None:
        await state.clear()
        return

    existing = await store.user_open_ticket(user.id)
    if existing:
        await store.append_ticket_message(existing["id"], user.id, text, False)
        ticket = await store.get_ticket(existing["id"]) or existing
        fresh = False
    else:
        ticket_id = await store.create_ticket(user.id, topic, text)
        ticket = await store.get_ticket(ticket_id) or {
            "id": ticket_id,
            "topic": topic,
            "user_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
        }
        fresh = True

    await state.clear()
    if fresh:
        await message.answer(
            f"✅ <b>Обращение #{ticket['id']} создано</b>\n\n"
            "Саппорт увидит его и ответит здесь, в личке. "
            "Дополнить можно кнопкой «✍️ Ответить» в ответе поддержки или через /support."
        )
    else:
        await message.answer(
            f"✅ Добавил в обращение <b>#{ticket['id']}</b>. Ответ придёт сюда."
        )
    await _notify_staff(bot, store, settings, ticket, text, fresh=fresh)


@router.message(TicketFlow.message)
async def on_ticket_non_text(message: Message) -> None:
    await message.answer("Нужен текст. Опиши проблему сообщением или /cancel.")


# --------------------------------------------------------------------------- ответ пользователя
@router.callback_query(F.data.startswith("tick:userreply:"))
async def cb_user_reply(
    call: CallbackQuery, store: Store, state: FSMContext
) -> None:
    if call.from_user is None:
        return
    ticket_id = parse_ticket_id(call.data)
    ticket = await store.get_ticket(ticket_id)
    if not ticket:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    if ticket["user_id"] != call.from_user.id:
        await call.answer("Это чужое обращение", show_alert=True)
        return
    if ticket["status"] != "open":
        await call.answer("Обращение закрыто — создай новое через /support", show_alert=True)
        return
    await state.set_state(TicketFlow.user_reply)
    await state.update_data(ticket_id=ticket_id)
    await call.message.answer(
        f"✍️ Напиши сообщение в обращение <b>#{ticket_id}</b> одним текстом.\n"
        "/cancel — отмена."
    )
    await call.answer()


@router.message(TicketFlow.user_reply, F.text)
async def on_user_reply(
    message: Message, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("Отменено.")
        return
    if not text or len(text) > MAX_TICKET_CHARS:
        await message.answer(f"Нужен текст до {MAX_TICKET_CHARS} символов.")
        return
    user = message.from_user
    data = await state.get_data()
    ticket_id = int(data.get("ticket_id", 0))
    ticket = await store.get_ticket(ticket_id)
    if user is None or not ticket or ticket["user_id"] != user.id:
        await state.clear()
        await message.answer("Обращение не найдено. Открой /support.")
        return
    if ticket["status"] != "open":
        await state.clear()
        await message.answer("Обращение уже закрыто. Создай новое через /support.")
        return

    await store.append_ticket_message(ticket_id, user.id, text, False)
    await state.clear()
    await message.answer(f"✅ Добавил в обращение <b>#{ticket_id}</b>. Ответ придёт сюда.")
    await _notify_staff(bot, store, settings, ticket, text, fresh=False)


@router.message(TicketFlow.user_reply)
async def on_user_reply_non_text(message: Message) -> None:
    await message.answer("Нужен текст. Напиши сообщение или /cancel.")


# --------------------------------------------------------------------------- панель staff
@router.message(Command("tickets"))
async def cmd_tickets(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    if message.chat.type != "private":
        await message.reply("Тикеты — в личке: /tickets")
        return
    role = await resolve_role(user.id, settings, store)
    if is_staff(role):
        text, kb = await render_ticket_list(store, 0, admin=has_admin_access(role))
    else:
        text, kb = await render_my_tickets(store, user.id)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data.startswith("tick:list:"), StaffFilter())
async def cb_list(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    offset = parse_ticket_id(call.data)
    role = await resolve_role(call.from_user.id, settings, store)
    text, kb = await render_ticket_list(
        store, max(0, offset), admin=has_admin_access(role)
    )
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("tick:view:"))
async def cb_view(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    ticket_id = parse_ticket_id(call.data)
    ticket = await store.get_ticket(ticket_id)
    if not ticket:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    role = await resolve_role(call.from_user.id, settings, store)
    if not is_staff(role) and ticket["user_id"] != call.from_user.id:
        await call.answer("Это чужое обращение", show_alert=True)
        return
    rendered = await render_ticket(store, ticket_id, staff=is_staff(role))
    if rendered is None:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    text, kb = rendered
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("tick:refresh:"), StaffFilter())
async def cb_refresh(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    rendered = await render_ticket(store, parse_ticket_id(call.data), staff=True)
    if rendered is None:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    text, kb = rendered
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Обновлено")


@router.callback_query(F.data.startswith("tick:close:"), StaffFilter())
async def cb_close(call: CallbackQuery, bot: Bot, store: Store) -> None:
    if call.from_user is None:
        return
    ticket_id = parse_ticket_id(call.data)
    ticket = await store.get_ticket(ticket_id)
    if not ticket:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    if not await store.close_ticket(ticket_id, call.from_user.id):
        await call.answer("Обращение уже закрыто", show_alert=True)
        return

    with contextlib.suppress(TelegramAPIError):
        await bot.send_message(
            ticket["user_id"],
            f"✅ <b>Обращение #{ticket_id} закрыто</b>\n\n"
            "Если проблема вернётся — создай новое обращение через /support.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🆘 Поддержка", callback_data="tick:menu")]
                ]
            ),
        )

    rendered = await render_ticket(store, ticket_id, staff=True)
    if rendered is not None:
        text, kb = rendered
        with contextlib.suppress(TelegramAPIError):
            await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Обращение закрыто ✅")


@router.callback_query(F.data.startswith("tick:reply:"), StaffFilter())
async def cb_reply(
    call: CallbackQuery, store: Store, state: FSMContext
) -> None:
    ticket_id = parse_ticket_id(call.data)
    ticket = await store.get_ticket(ticket_id)
    if not ticket:
        await call.answer("Обращение не найдено", show_alert=True)
        return
    if ticket["status"] != "open":
        await call.answer("Обращение уже закрыто", show_alert=True)
        return
    await state.set_state(TicketFlow.reply)
    await state.update_data(ticket_id=ticket_id)
    await call.message.answer(
        f"✍️ <b>Ответ в обращение #{ticket_id}</b>\n"
        f"Пользователь: {escape(display_name(ticket))} (<code>{ticket['user_id']}</code>)\n\n"
        "Пришли текст ответа — он уйдёт пользователю в личку.\n/cancel — отмена."
    )
    await call.answer()


@router.message(TicketFlow.reply, F.text)
async def on_staff_reply(
    message: Message, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    author = message.from_user
    if author is None:
        return
    role = await resolve_role(author.id, settings, store)
    if not is_staff(role):
        await state.clear()
        await message.answer("Ответить в обращение может только саппорт.")
        return

    text = (message.text or "").strip()
    if text.startswith("/"):
        await state.clear()
        await message.answer("Отменено.")
        return
    if not text:
        await message.answer("Пустой ответ не отправлю. Пришли текст.")
        return
    if len(text) > MAX_TICKET_CHARS:
        await message.answer(f"Слишком длинно: до {MAX_TICKET_CHARS} символов.")
        return

    data = await state.get_data()
    ticket_id = int(data.get("ticket_id", 0))
    ticket = await store.get_ticket(ticket_id)
    if not ticket:
        await state.clear()
        await message.answer("Обращение не найдено.")
        return
    if ticket["status"] != "open":
        await state.clear()
        await message.answer("Обращение уже закрыто — ответить нельзя.")
        return

    author = message.from_user
    if author is None:
        return
    await store.append_ticket_message(ticket_id, author.id, text, True)
    await state.clear()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✍️ Ответить", callback_data=f"tick:userreply:{ticket_id}"
                )
            ],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="tick:menu")],
        ]
    )
    delivered = True
    try:
        await bot.send_message(
            ticket["user_id"],
            f"💬 <b>Ответ поддержки</b> · обращение #{ticket_id}\n\n{escape(text)}",
            reply_markup=kb,
        )
    except TelegramAPIError:
        delivered = False

    note = "Пользователь получил ответ в личку." if delivered else (
        "⚠️ Не смог доставить: пользователь не писал боту или закрыл личку."
    )
    await message.answer(f"✅ Ответ добавлен в #{ticket_id}. {note}")
    rendered = await render_ticket(store, ticket_id, staff=True)
    if rendered is not None:
        text, kb = rendered
        await message.answer(text, reply_markup=kb)


@router.message(TicketFlow.reply)
async def on_staff_reply_non_text(message: Message) -> None:
    await message.answer("Нужен текст ответа или /cancel.")


@router.callback_query(
    F.data.startswith(("tick:list:", "tick:reply:", "tick:close:", "tick:refresh:"))
)
async def cb_staff_only(call: CallbackQuery) -> None:
    """Сюда попадают только те, кто не прошёл StaffFilter."""
    await call.answer("Это действие доступно только поддержке", show_alert=True)