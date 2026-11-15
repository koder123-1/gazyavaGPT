"""Админ-панель: статистика, пользователи, бан, рассылка, настройки."""

from __future__ import annotations

import asyncio
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

from config import Settings, parse_packages
from ai import AIClient, AIError
import models as model_catalog
from roles import (
    ASSIGNABLE,
    ROLE_ADMIN,
    ROLE_OWNER,
    RoleFilter,
    can_assign,
    can_manage_roles,
    rank,
    resolve_role,
    role_title,
)
from runtime import EDITABLE, load_runtime
from store import Store

log = logging.getLogger("admin")
PAGE = 5


router = Router(name="admin")
router.message.filter(RoleFilter(ROLE_ADMIN))
router.callback_query.filter(RoleFilter(ROLE_ADMIN))


class Panel(StatesGroup):
    broadcast = State()
    search = State()
    edit = State()
    grant = State()
    role_user = State()


# --------------------------------------------------------------------------- клавиатуры
def main_kb(role: str | None = ROLE_ADMIN) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users:0"),
        ],
        [
            InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:bcast"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="adm:settings"),
        ],
        [
            InlineKeyboardButton(text="🎫 Тикеты", callback_data="tick:list:0"),
            InlineKeyboardButton(text="⭐ Платежи", callback_data="adm:payments"),
        ],
    ]
    if can_manage_roles(role):
        rows.append([InlineKeyboardButton(text="👑 Роли", callback_data="adm:roles")])
    rows.append([InlineKeyboardButton(text="🔍 Найти по ID", callback_data="adm:find")])
    rows.append([InlineKeyboardButton(text="🧪 Проверить ИИ", callback_data="adm:aitest")])
    rows.append([InlineKeyboardButton(text="❌ Закрыть", callback_data="adm:close")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_kb(target: str = "adm:main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=target)]]
    )


# --------------------------------------------------------------------------- рендер
async def render_main(
    store: Store, settings: Settings, role: str | None = ROLE_ADMIN
) -> tuple[str, InlineKeyboardMarkup]:
    stats = await store.stats()
    tickets = await store.tickets_stats()
    rt = await load_runtime(store, settings)
    text = (
        "🛠 <b>Админ-панель</b>\n"
        f"Твоя роль: {role_title(role)}\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b> (забанено {stats['banned']})\n"
        f"💬 Сегодня: <b>{stats['requests_today']}</b> запросов от {stats['active_today']} чел.\n"
        f"🎫 Открытых тикетов: <b>{tickets['open']}</b>\n"
        f"🧠 Модель: <code>{escape(rt.model)}</code>\n"
        f"📏 Лимит: {rt.daily_limit if rt.daily_limit > 0 else 'безлимит'}"
    )
    return text, main_kb(role)


async def render_stats(store: Store, settings: Settings) -> tuple[str, InlineKeyboardMarkup]:
    stats = await store.stats()
    top = await store.top_users(5)
    feedback = await store.feedback_stats()
    pay = await store.payments_stats()
    tickets = await store.tickets_stats()
    rt = await load_runtime(store, settings)
    lines = [
        "📊 <b>Статистика</b>\n",
        f"👥 Пользователей: <b>{stats['users']}</b>",
        f"🚫 Забанено: {stats['banned']}",
        f"🔥 Активных сегодня: {stats['active_today']}",
        f"💬 Запросов сегодня: <b>{stats['requests_today']}</b>",
        f"🗂 Сообщений в истории: {stats['messages_total']}",
        f"🎫 Тикеты: открыто {tickets['open']} · закрыто {tickets['closed']}",
        "",
        f"👍/👎 Оценки ответов: {feedback['up']} / {feedback['down']} (оценено {feedback['total']})",
        f"⭐ Продажи: {pay['count']} платежей · {pay['stars']} ⭐ · {pay['requests']} запросов",
        "",
        f"🧠 Модель: <code>{escape(rt.model)}</code>",
        f"📏 Лимит в день: {rt.daily_limit if rt.daily_limit > 0 else 'безлимит'}",
        f"🧾 Контекст: {rt.max_context} сообщений",
    ]
    if top:
        lines.append("\n<b>Топ по запросам</b>")
        for i, row in enumerate(top, 1):
            name = f"@{row['username']}" if row.get("username") else str(row["user_id"])
            lines.append(f"{i}. {escape(name)} — {row['total']}")
    return "\n".join(lines), InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:stats")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")],
        ]
    )


def _user_line(row: dict) -> str:
    name = f"@{row['username']}" if row.get("username") else (row.get("first_name") or "без имени")
    flag = "🚫 " if row.get("banned") else ""
    return f"{flag}{escape(str(name))} — <code>{row['user_id']}</code> · {row.get('used_today', 0)}"


async def render_payments(store: Store) -> tuple[str, InlineKeyboardMarkup]:
    stats = await store.payments_stats()
    rows = await store.recent_payments(10)
    lines = [
        "⭐ <b>Платежи</b>\n",
        f"Всего покупок: <b>{stats['count']}</b>",
        f"Получено звёзд: <b>{stats['stars']}</b>",
        f"Продано запросов: <b>{stats['requests']}</b>",
    ]
    if stats.get("subs"):
        lines.append(f"💎 Куплено подписок: <b>{stats['subs']}</b>")
    if stats.get("models"):
        lines.append(f"🧠 Открыто моделей: <b>{stats['models']}</b>")
    if stats.get("refunded"):
        lines.append(f"↩️ Возвращено платежей: {stats['refunded']}")
    if rows:
        lines.append("\n<b>Последние</b>")
        for row in rows:
            name = f"@{row['username']}" if row.get("username") else str(row["user_id"])
            when = row.get("created_at")
            stamp = when.strftime("%d.%m %H:%M") if hasattr(when, "strftime") else ""
            refunded = " ↩️" if row.get("refunded_at") else ""
            if row.get("kind") == "sub":
                what = f"💎 подписка за {row['stars']} ⭐"
            elif row.get("kind") == "model":
                what = f"🧠 {escape(model_catalog.title(row.get('model')))} за {row['stars']} ⭐"
            else:
                what = f"+{row['requests']} за {row['stars']} ⭐"
            lines.append(f"{what} — {escape(name)} {stamp}{refunded}".rstrip())
    else:
        lines.append("\nПокупок пока не было.")

    buttons = [
        [
            InlineKeyboardButton(
                text=(
                    f"↩️ #{row['id']} · 💎 подписка · {row['stars']} ⭐"
                    if row.get("kind") == "sub"
                    else (
                        f"↩️ #{row['id']} · 🧠 {model_catalog.title(row.get('model'))} · {row['stars']} ⭐"
                        if row.get("kind") == "model"
                        else f"↩️ #{row['id']} · {row['requests']} зап. · {row['stars']} ⭐"
                    )
                ),
                callback_data=f"adm:refund:ask:{row['id']}",
            )
        ]
        for row in rows
        if not row.get("refunded_at")
    ]
    buttons.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:payments")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_users(
    store: Store, offset: int, settings: Settings
) -> tuple[str, InlineKeyboardMarkup]:
    rt = await load_runtime(store, settings)
    rows = await store.list_users(offset, PAGE)
    total = (await store.stats())["users"]
    if not rows:
        return (
            "👥 Пользователей пока нет.",
            back_kb(),
        )

    lines = [f"👥 <b>Пользователи</b> ({offset + 1}–{offset + len(rows)} из {total})\n"]
    lines += [_user_line(r) for r in rows]

    buttons = [
        [InlineKeyboardButton(text=f"👤 {r['user_id']}", callback_data=f"adm:user:{r['user_id']}")]
        for r in rows
    ]
    nav = []
    if offset > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️", callback_data=f"adm:users:{max(0, offset - PAGE)}"
            )
        )
    if offset + PAGE < total:
        nav.append(
            InlineKeyboardButton(text="➡️", callback_data=f"adm:users:{offset + PAGE}")
        )
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_card(
    store: Store, user_id: int, settings: Settings
) -> tuple[str, InlineKeyboardMarkup]:
    card = await store.user_card(user_id)
    if not card:
        return "Пользователь не найден в базе.", back_kb("adm:users:0")

    rt = await load_runtime(store, settings)
    role = await resolve_role(card["user_id"], settings, store)
    name = f"@{card['username']}" if card.get("username") else (card.get("first_name") or "без имени")
    status = "🚫 забанен" if card.get("banned") else "✅ активен"
    limit = "безлимит" if rt.daily_limit <= 0 else rt.daily_limit
    sub_until = await store.get_subscription(card["user_id"])
    sub_line = f"💎 Подписка: до <b>{sub_until:%d.%m.%Y}</b>\n" if sub_until else ""
    chosen = await store.get_model(card["user_id"])
    model_line = (
        f"🧠 Модель: <b>{escape(model_catalog.title(chosen))}</b>\n" if chosen else ""
    )
    text = (
        f"👤 <b>{escape(str(name))}</b>\n"
        f"ID: <code>{card['user_id']}</code>\n"
        f"Роль: {role_title(role) if role else 'обычный пользователь'}\n"
        f"Статус: {status}\n\n"
        f"Сегодня: {card.get('used_today', 0)} из {limit}\n"
        f"Бонусных запросов: <b>{card.get('bonus_requests', 0)}</b>\n"
        f"{sub_line}"
        f"{model_line}"
        f"Всего запросов: {card.get('total_requests', 0)}\n"
        f"Сообщений в истории: {card.get('history_len', 0)}"
    )
    ban_text = "✅ Разбанить" if card.get("banned") else "🚫 Забанить"
    action = "unban" if card.get("banned") else "ban"
    return text, InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=ban_text, callback_data=f"adm:{action}:{user_id}")],
            [
                InlineKeyboardButton(
                    text="🧹 Сбросить контекст", callback_data=f"adm:reset:{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧠 Модели", callback_data=f"adm:u:models:{user_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="⭐ Выдать запросы", callback_data=f"adm:grant:{user_id}"
                )
            ],
            [InlineKeyboardButton(text="⬅️ К списку", callback_data="adm:users:0")],
        ]
    )


async def render_model_access(
    store: Store, user_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    granted = set(await store.list_model_access(user_id))
    chosen = await store.get_model(user_id)
    lines = [
        "🧠 <b>Модели пользователя</b>",
        f"ID: <code>{user_id}</code>\n",
        "Отмеченные модели доступны без оплаты. Бесплатная есть у всех.\n",
    ]
    buttons: list[list[InlineKeyboardButton]] = []
    for index, item in enumerate(model_catalog.CATALOG):
        if item.stars <= 0:
            has = True
        else:
            has = item.id in granted
        mark = "✅" if has else "⬜"
        price = "бесплатно" if item.stars <= 0 else f"{item.stars} ⭐"
        suffix = " · выбрана" if item.id == chosen else ""
        lines.append(f"{mark} {escape(item.title)} — {price}{suffix}")
        if item.stars <= 0:
            continue
        action = "забрать" if has else "выдать"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{mark} {item.title} · {price} — {action}",
                    callback_data=f"adm:mdl:tg:{user_id}:{index}",
                )
            ]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                text="🔄 Сбросить выбранную модель",
                callback_data=f"adm:mdl:reset:{user_id}",
            )
        ]
    )
    buttons.append(
        [InlineKeyboardButton(text="⬅️ К карточке", callback_data=f"adm:user:{user_id}")]
    )
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_settings(
    store: Store, settings: Settings
) -> tuple[str, InlineKeyboardMarkup]:
    rt = await load_runtime(store, settings)
    overrides = await store.all_settings()

    def mark(key: str) -> str:
        return " ✏️" if key in overrides else ""

    prompt = rt.system_prompt.replace("\n", " ")
    if len(prompt) > 140:
        prompt = prompt[:140] + "…"
    text = (
        "⚙️ <b>Настройки</b>\n"
        "<i>Изменения применяются сразу, рестарт не нужен.</i>\n\n"
        f"📏 Лимит в день: <b>{rt.daily_limit if rt.daily_limit > 0 else 'безлимит'}</b>{mark('daily_limit')}\n"
        f"🧾 Глубина контекста: <b>{rt.max_context}</b>{mark('max_context')}\n"
        f"🧠 Модель: <code>{escape(rt.model)}</code>{mark('ai_model')}\n"
        f"🖼 Модель для фото: <code>{escape(rt.vision_model)}</code>{mark('ai_vision_model')}\n"
        f"📝 Промпт: <i>{escape(prompt)}</i>{mark('system_prompt')}\n\n"
        f"⭐ Тарифы: <code>{escape(','.join(f'{n}:{s}' for n, s in rt.star_packages))}</code>{mark('star_packages')}\n"
        f"💱 Курс свободной суммы: 1 ⭐ = <b>{rt.star_rate}</b> запросов{mark('star_rate')}\n"
        "🛡 Защита: всегда включена — русский язык, анти-jailbreak, "
        "скрытие внутренних правил (изменить нельзя)."
    )
    buttons = [
        [
            InlineKeyboardButton(text="✏️ Лимит", callback_data="adm:set:edit:daily_limit"),
            InlineKeyboardButton(text="✏️ Контекст", callback_data="adm:set:edit:max_context"),
        ],
        [
            InlineKeyboardButton(text="✏️ Модель", callback_data="adm:set:edit:ai_model"),
            InlineKeyboardButton(text="✏️ Модель фото", callback_data="adm:set:edit:ai_vision_model"),
        ],
        [InlineKeyboardButton(text="✏️ Промпт", callback_data="adm:set:edit:system_prompt")],
        [
            InlineKeyboardButton(
                text="✏️ Тарифы Stars", callback_data="adm:set:edit:star_packages"
            )
        ],
        [
            InlineKeyboardButton(
                text="✏️ Курс за звезду", callback_data="adm:set:edit:star_rate"
            )
        ],
    ]
    if overrides:
        buttons.append(
            [InlineKeyboardButton(text="♻️ Вернуть значения из env", callback_data="adm:set:reset")]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_roles(
    store: Store, settings: Settings, actor_role: str | None
) -> tuple[str, InlineKeyboardMarkup]:
    rows = await store.list_roles()
    lines = [
        "👑 <b>Роли</b>\n",
        "👑 <b>Владелец</b> — полный доступ, задаётся только через <code>OWNER_ID</code>.",
        "👑 <b>Гл. админ</b> — почти всё, что владелец: админка, роли, платежи, тикеты.",
        "🛡 <b>Админ</b> — админка, пользователи, рассылка, настройки, платежи.",
        "🎫 <b>Саппорт</b> — только тикеты поддержки.\n",
    ]
    if settings.owner_id:
        lines.append(f"👑 Владелец: <code>{settings.owner_id}</code>")
    else:
        lines.append("👑 Владелец: <b>не задан</b> — добавь <code>OWNER_ID</code> в env.")

    buttons: list[list[InlineKeyboardButton]] = []
    if rows:
        lines.append("\n<b>Назначенные роли</b>")
        for row in rows:
            name = row.get("username") or row.get("first_name") or str(row["user_id"])
            lines.append(
                f"• {role_title(row['role'])} — {escape(str(name))} "
                f"(<code>{row['user_id']}</code>)"
            )
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"👤 {name} · {role_title(row['role'])}",
                        callback_data=f"adm:role:{row['user_id']}",
                    )
                ]
            )
    else:
        lines.append("\nРолей из бота пока нет: работают только владелец и <code>ADMIN_IDS</code>.")

    db_ids = {row["user_id"] for row in rows}
    env_admins = sorted(set(settings.admin_ids) - db_ids - {settings.owner_id})
    if env_admins:
        lines.append("\n<b>Админы из ADMIN_IDS</b> (роль в БД не задана)")
        for user_id in env_admins:
            lines.append(f"• 🛡 Админ — <code>{user_id}</code>")
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"👤 {user_id} · из env",
                        callback_data=f"adm:role:{user_id}",
                    )
                ]
            )

    if can_manage_roles(actor_role):
        buttons.append(
            [InlineKeyboardButton(text="➕ Выдать роль по ID", callback_data="adm:roles:add")]
        )
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


async def render_role_card(
    store: Store,
    settings: Settings,
    actor_role: str | None,
    actor_id: int,
    target_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    card = await store.user_card(target_id)
    stored = await store.get_role(target_id)
    current = await resolve_role(target_id, settings, store)
    name = "без имени"
    if card:
        name = card.get("username") or card.get("first_name") or str(target_id)

    if settings.owner_id and target_id == settings.owner_id:
        source = "OWNER_ID — не меняется из бота"
    elif stored:
        source = "роль в БД"
        if target_id in settings.admin_ids:
            source += " (перекрывает ADMIN_IDS)"
    elif target_id in settings.admin_ids:
        source = "ADMIN_IDS из env — снимается только в настройках Render"
    else:
        source = "роль не назначена"

    lines = [
        "👤 <b>Роль пользователя</b>\n",
        f"Имя: {escape(str(name))}",
        f"ID: <code>{target_id}</code>",
        f"Сейчас: {role_title(current) if current else 'обычный пользователь'}",
        f"Источник: {source}",
    ]
    if not card:
        lines.append("\n<i>Пользователь ещё не писал боту — уведомление может не дойти.</i>")

    buttons: list[list[InlineKeyboardButton]] = []
    for role in ASSIGNABLE:
        allowed, _ = can_assign(
            actor_role=actor_role,
            actor_id=actor_id,
            target_id=target_id,
            target_role=current,
            new_role=role,
            settings=settings,
        )
        mark = " ✅" if current == role else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{role_title(role)}{mark}",
                    callback_data=f"adm:role:set:{target_id}:{role}"
                    if allowed
                    else "adm:role:deny",
                )
            ]
        )
    if stored:
        allowed, _ = can_assign(
            actor_role=actor_role,
            actor_id=actor_id,
            target_id=target_id,
            target_role=current,
            new_role=None,
            settings=settings,
        )
        if allowed:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="❌ Снять роль",
                        callback_data=f"adm:role:clear:{target_id}",
                    )
                ]
            )
    lines.append(
        "\n<i>Гл. админа и владельца меняет только владелец. Свою роль менять нельзя.</i>"
    )
    buttons.append([InlineKeyboardButton(text="⬅️ К ролям", callback_data="adm:roles")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


HINTS = {
    "daily_limit": "Сколько сообщений в день разрешено одному пользователю. 0 — без ограничений.\n\nПришли число:",
    "max_context": "Сколько последних сообщений держать в контексте диалога. 0 — без памяти.\n\nПришли число:",
    "ai_model": "Имя модели провайдера.\nПримеры: <code>openrouter/free</code>, <code>google/gemma-4-31b-it:free</code>, <code>gemini-3.8-flash</code>.\n\nПришли название:",
    "ai_vision_model": "Модель, которая читает изображения.\nПримеры: <code>openrouter/free</code>, <code>inclusionai/ling-3.2-flash:free</code>, <code>nvidia/nemotron-3.5-super-vl:free</code>.\nЕсли модель занята, бот сам пробует резервные.\n\nПришли название:",
    "system_prompt": "Новый системный промпт — характер и правила ассистента.\n\nПришли текст:",
    "star_packages": "Тарифы в формате <code>запросы:звёзды</code> через запятую.\nПример: <code>30:3,60:6,100:10</code>\n\nПришли тарифы:",
    "star_rate": "Сколько запросов давать за 1 звезду, когда пользователь вводит свою сумму.\nПример: <code>10</code>\n\nПришли число:",
}


# --------------------------------------------------------------------------- вход
@router.message(Command("admin", "panel"))
async def cmd_admin(message: Message, store: Store, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    if user:
        await store.ensure_user(user.id, user.username, user.first_name)
    role = await resolve_role(user.id, settings, store) if user else None
    text, kb = await render_main(store, settings, role)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:main")
async def cb_main(call: CallbackQuery, store: Store, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    role = (
        await resolve_role(call.from_user.id, settings, store) if call.from_user else None
    )
    text, kb = await render_main(store, settings, role)
    await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:close")
async def cb_close(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Панель закрыта. Открыть снова: /admin")
    await call.answer()


@router.callback_query(F.data.startswith("adm:grant:"))
async def cb_grant_start(call: CallbackQuery, state: FSMContext) -> None:
    user_id = int(call.data.rsplit(":", 1)[1])
    await state.set_state(Panel.grant)
    await state.update_data(grant_user_id=user_id)
    await call.message.edit_text(
        f"⭐ <b>Выдать запросы</b> пользователю <code>{user_id}</code>\n\n"
        "Пришли количество целым числом. Чтобы отозвать, укажи отрицательное число.\n"
        "Например: <code>50</code> или <code>-10</code>.\n/cancel — отмена.",
        reply_markup=back_kb("adm:main"),
    )
    await call.answer()


@router.message(Panel.grant, F.text)
async def on_grant_amount(
    message: Message, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("+-").isdigit():
        await message.answer("Пришли целое число, например <code>50</code> или <code>-10</code>.")
        return
    amount = int(raw)
    if amount == 0 or abs(amount) > 100_000:
        await message.answer("Число должно быть от -100000 до 100000, кроме нуля.")
        return
    data = await state.get_data()
    user_id = int(data.get("grant_user_id", 0))
    if user_id <= 0 or not await store.user_card(user_id):
        await state.clear()
        await message.answer("Пользователь не найден. Открой карточку заново.")
        return
    balance = await store.add_bonus(user_id, amount)
    await state.clear()
    await message.answer(
        f"✅ Изменение: {amount:+d} запросов.\n"
        f"Баланс пользователя <code>{user_id}</code>: <b>{balance}</b>."
    )
    try:
        await bot.send_message(
            user_id,
            f"⭐ Администратор {'начислил' if amount > 0 else 'списал'} "
            f"<b>{abs(amount)}</b> запросов.\n"
            f"Твой запас бонусных запросов: <b>{balance}</b>.",
        )
    except TelegramAPIError:
        pass
    text, kb = await render_card(store, user_id, settings)
    await message.answer(text, reply_markup=kb)


@router.message(Panel.grant)
async def on_grant_non_text(message: Message) -> None:
    await message.answer("Пришли количество запросов числом или нажми /cancel.")


# --------------------------------------------------------------------------- статистика
@router.message(Command("stats"))
async def cmd_stats(message: Message, store: Store, settings: Settings) -> None:
    text, kb = await render_stats(store, settings)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:stats")
async def cb_stats(call: CallbackQuery, store: Store, settings: Settings) -> None:
    text, kb = await render_stats(store, settings)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Обновлено")


@router.callback_query(F.data == "adm:aitest")
async def cb_ai_test(
    call: CallbackQuery, ai: AIClient, store: Store, settings: Settings
) -> None:
    """Быстрая проверка: отвечает ли ИИ и сколько это занимает."""
    runtime = await load_runtime(store, settings)
    loop = asyncio.get_running_loop()
    started = loop.time()
    try:
        answer = await ai.reply([], "Ответь одним словом: работает?")
        elapsed = loop.time() - started
        text = (
            "🧪 <b>ИИ отвечает</b>\n"
            f"Модель: <code>{escape(runtime.model)}</code>\n"
            f"Ответ: {escape(answer[:200])}\n"
            f"Время: <b>{elapsed:.1f} с</b>"
        )
    except AIError as exc:
        elapsed = loop.time() - started
        text = (
            "⚠️ <b>ИИ не ответил</b>\n"
            f"Модель: <code>{escape(runtime.model)}</code>\n"
            f"Ошибка: {escape(str(exc))}\n"
            f"Время: <b>{elapsed:.1f} с</b>"
        )
    except Exception:  # noqa: BLE001
        log.exception("Тест ИИ из админки упал")
        text = "⚠️ Тест упал неожиданно. Подробности в логах."
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=back_kb("adm:main"))
    await call.answer("Проверил")


@router.callback_query(F.data == "adm:payments")
async def cb_payments(call: CallbackQuery, store: Store) -> None:
    text, kb = await render_payments(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:refund:ask:"))
async def cb_refund_ask(call: CallbackQuery, store: Store) -> None:
    payment_id = int(call.data.rsplit(":", 1)[1])
    payment = await store.get_payment(payment_id)
    if not payment:
        await call.answer("Платёж не найден", show_alert=True)
        return
    if payment.get("refunded_at"):
        await call.answer("Этот платёж уже возвращён", show_alert=True)
        return

    user_id = payment["user_id"]
    card = await store.user_card(user_id) or {}
    name = f"@{card['username']}" if card.get("username") else str(user_id)
    is_sub = payment.get("kind") == "sub"
    is_model = payment.get("kind") == "model"
    if is_sub:
        product = (
            f"💎 подписка на ИИ за <b>{payment['stars']}</b> ⭐ "
            f"({payment['requests']} дн.)"
        )
        effect = "Telegram вернёт звёзды, а срок подписки сократится на эти дни."
    elif is_model:
        product = (
            f"🧠 модель {escape(model_catalog.title(payment.get('model')))} "
            f"за <b>{payment['stars']}</b> ⭐"
        )
        effect = (
            "Telegram вернёт звёзды пользователю, а доступ к модели закроется. "
            "Если она была выбрана, бот вернётся к общей модели."
        )
    else:
        product = f"<b>{payment['requests']}</b> запросов за <b>{payment['stars']}</b> ⭐"
        effect = (
            "Telegram вернёт звёзды пользователю, а с его бонусного баланса спишутся "
            "эти запросы."
        )
    await call.message.edit_text(
        f"↩️ <b>Вернуть звёзды?</b>\n\n"
        f"Платёж: <code>#{payment_id}</code>\n"
        f"Пользователь: {escape(str(name))} (<code>{user_id}</code>)\n"
        f"Покупка: {product}\n\n"
        f"{effect} Действие нельзя отменить.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Вернуть звёзды",
                        callback_data=f"adm:refund:do:{payment_id}",
                    )
                ],
                [InlineKeyboardButton(text="⬅️ Отмена", callback_data="adm:payments")],
            ]
        ),
    )
    await call.answer()


@router.callback_query(F.data.startswith("adm:refund:do:"))
async def cb_refund_do(call: CallbackQuery, bot: Bot, store: Store) -> None:
    payment_id = int(call.data.rsplit(":", 1)[1])
    payment = await store.get_payment(payment_id)
    if not payment:
        await call.answer("Платёж не найден", show_alert=True)
        return
    if payment.get("refunded_at"):
        await call.answer("Этот платёж уже возвращён", show_alert=True)
        return

    try:
        ok = await bot.refund_star_payment(
            user_id=payment["user_id"],
            telegram_payment_charge_id=payment["charge_id"],
        )
    except TelegramAPIError as exc:
        await call.answer(f"Telegram отказал: {exc.message}", show_alert=True)
        return
    if not ok:
        await call.answer("Telegram не подтвердил возврат", show_alert=True)
        return

    refunded = await store.mark_payment_refunded(payment_id)
    if not refunded:
        await call.answer("Платёж уже был возвращён", show_alert=True)
    else:
        if payment.get("kind") == "model":
            model_id = payment.get("model")
            if model_id:
                await store.revoke_model(payment["user_id"], model_id)
                if await store.get_model(payment["user_id"]) == model_id:
                    await store.set_model(payment["user_id"], None)
            title = model_catalog.title(model_id)
            try:
                await bot.send_message(
                    payment["user_id"],
                    f"↩️ <b>Возврат выполнен</b>\n\n"
                    f"Звёзды за модель {escape(title)} ({payment['stars']} ⭐) "
                    "возвращены Telegram.\n"
                    "Доступ к модели закрыт. Выбрать другую — /model.",
                )
            except TelegramAPIError:
                pass
        elif payment.get("kind") == "sub":
            days = int(payment["requests"] or 0)
            left = await store.trim_subscription(payment["user_id"], days)
            tail = (
                f"Остаток подписки: до <b>{left:%d.%m.%Y}</b>."
                if left
                else "Подписка отменена."
            )
            try:
                await bot.send_message(
                    payment["user_id"],
                    f"↩️ <b>Возврат выполнен</b>\n\n"
                    f"Звёзды за подписку ({payment['stars']} ⭐) возвращены Telegram.\n"
                    f"Снято дней: <b>{days}</b>. {tail}",
                )
            except TelegramAPIError:
                pass
        else:
            balance = await store.add_bonus(payment["user_id"], -int(payment["requests"]))
            try:
                await bot.send_message(
                    payment["user_id"],
                    f"↩️ <b>Возврат выполнен</b>\n\n"
                    f"Звёзды за покупку ({payment['stars']} ⭐) возвращены Telegram.\n"
                    f"Списано запросов: <b>{payment['requests']}</b>\n"
                    f"Остаток бонусных запросов: <b>{balance}</b>.",
                )
            except TelegramAPIError:
                pass
        await call.answer("Возврат выполнен ↩️")

    text, kb = await render_payments(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)


# --------------------------------------------------------------------------- пользователи
@router.callback_query(F.data.startswith("adm:users:"))
async def cb_users(call: CallbackQuery, store: Store, settings: Settings) -> None:
    offset = int(call.data.rsplit(":", 1)[1])
    text, kb = await render_users(store, offset, settings)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:user:"))
async def cb_user(call: CallbackQuery, store: Store, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    user_id = int(call.data.rsplit(":", 1)[1])
    text, kb = await render_card(store, user_id, settings)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:u:models:"))
async def cb_model_access(call: CallbackQuery, store: Store) -> None:
    user_id = int(call.data.rsplit(":", 1)[1])
    text, kb = await render_model_access(store, user_id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:mdl:tg:"))
async def cb_model_toggle(call: CallbackQuery, store: Store) -> None:
    parts = call.data.split(":")
    if len(parts) != 5:
        await call.answer("Кнопка устарела", show_alert=True)
        return
    user_id, index = int(parts[3]), int(parts[4])
    item = model_catalog.by_index(index)
    if item is None or item.stars <= 0:
        await call.answer("Эта модель бесплатна для всех", show_alert=True)
        return
    if await store.has_model_access(user_id, item.id):
        await store.revoke_model(user_id, item.id)
        if await store.get_model(user_id) == item.id:
            await store.set_model(user_id, None)
        note = f"🚫 Забрал: {item.title}"
    else:
        actor_id = call.from_user.id if call.from_user else 0
        await store.grant_model(user_id, item.id, granted_by=actor_id)
        note = f"✅ Выдал: {item.title}"
    text, kb = await render_model_access(store, user_id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer(note)


@router.callback_query(F.data.startswith("adm:mdl:reset:"))
async def cb_model_reset(call: CallbackQuery, store: Store) -> None:
    user_id = int(call.data.rsplit(":", 1)[1])
    await store.set_model(user_id, None)
    text, kb = await render_model_access(store, user_id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Модель сброшена на общую")


@router.callback_query(F.data.startswith("adm:ban:"))
@router.callback_query(F.data.startswith("adm:unban:"))
async def cb_ban(call: CallbackQuery, store: Store, settings: Settings) -> None:
    action, raw_id = call.data.split(":")[1], call.data.split(":")[2]
    user_id = int(raw_id)
    banned = action == "ban"

    actor_id = call.from_user.id if call.from_user else 0
    if user_id == actor_id:
        await call.answer("Себя забанить нельзя 🙂", show_alert=True)
        return
    actor_role = await resolve_role(actor_id, settings, store)
    target_role = await resolve_role(user_id, settings, store)
    if settings.owner_id and user_id == settings.owner_id:
        await call.answer("Владельца забанить нельзя 👑", show_alert=True)
        return
    if rank(target_role) >= rank(actor_role):
        await call.answer("Нельзя забанить равного или старшего по роли", show_alert=True)
        return

    changed = await store.set_banned(user_id, banned)
    if not changed:
        await call.answer("Пользователь не найден", show_alert=True)
        return

    text, kb = await render_card(store, user_id, settings)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Забанен 🚫" if banned else "Разбанен ✅")


@router.callback_query(F.data.startswith("adm:reset:"))
async def cb_reset_history(call: CallbackQuery, store: Store, settings: Settings) -> None:
    user_id = int(call.data.rsplit(":", 1)[1])
    await store.reset(user_id)
    text, kb = await render_card(store, user_id, settings)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Контекст очищен 🧹")


@router.message(Command("ban", "unban"))
async def cmd_ban(message: Message, store: Store, settings: Settings) -> None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Использование: <code>/ban 123456789</code>")
        return
    user_id = int(parts[1])
    actor_id = message.from_user.id if message.from_user else 0
    actor_role = await resolve_role(actor_id, settings, store)
    target_role = await resolve_role(user_id, settings, store)
    if settings.owner_id and user_id == settings.owner_id:
        await message.answer("Владельца забанить нельзя 👑")
        return
    if rank(target_role) >= rank(actor_role):
        await message.answer("Нельзя забанить равного или старшего по роли.")
        return
    banned = parts[0].lstrip("/").split("@")[0] == "ban"
    changed = await store.set_banned(user_id, banned)
    if not changed:
        await message.answer("Такого пользователя нет в базе — он ещё не писал боту.")
        return
    await message.answer(f"Пользователь <code>{user_id}</code> {'забанен 🚫' if banned else 'разбанен ✅'}")


@router.callback_query(F.data == "adm:find")
async def cb_find(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Panel.search)
    await call.message.edit_text(
        "🔍 Пришли Telegram ID пользователя (число).",
        reply_markup=back_kb("adm:main"),
    )
    await call.answer()


@router.message(Panel.search, F.text)
async def on_search(message: Message, store: Store, settings: Settings, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("-").isdigit():
        await message.answer("Нужен числовой ID. Например: <code>123456789</code>")
        return
    await state.clear()
    text, kb = await render_card(store, int(raw), settings)
    await message.answer(text, reply_markup=kb)


# --------------------------------------------------------------------------- рассылка
@router.callback_query(F.data == "adm:bcast")
async def cb_bcast(call: CallbackQuery, state: FSMContext, store: Store) -> None:
    ids = await store.user_ids(only_active=True)
    await state.set_state(Panel.broadcast)
    await call.message.edit_text(
        f"📢 <b>Рассылка</b>\nПолучателей: <b>{len(ids)}</b>\n\n"
        "Пришли текст сообщения. Забаненные будут пропущены.\n/cancel — отмена.",
        reply_markup=back_kb("adm:main"),
    )
    await call.answer()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


@router.message(Panel.broadcast, F.text)
async def on_bcast_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Текст пустой, пришли ещё раз.")
        return
    await state.update_data(bcast_text=text)
    preview = text if len(text) < 500 else text[:500] + "…"
    await message.answer(
        f"📢 <b>Проверь текст</b>\n\n{escape(preview)}\n\n"
        "Отправляем всем активным пользователям?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Отправить", callback_data="adm:bcast:go"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="adm:bcast:no"),
                ]
            ]
        ),
    )


@router.callback_query(F.data == "adm:bcast:no")
async def cb_bcast_cancel(call: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await call.message.edit_text("Рассылка отменена.")
    await call.answer()


@router.callback_query(F.data == "adm:bcast:go")
async def cb_bcast_go(
    call: CallbackQuery, bot: Bot, store: Store, state: FSMContext
) -> None:
    data = await state.get_data()
    text = (data.get("bcast_text") or "").strip()
    await state.clear()
    if not text:
        await call.answer("Текст потерян, начни заново", show_alert=True)
        return

    await call.message.edit_text("📣 Рассылка запущена…")
    await call.answer()
    asyncio.create_task(run_broadcast(bot, store, call.message.chat.id, call.message.message_id, text))


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext, store: Store) -> None:
    ids = await store.user_ids(only_active=True)
    await state.set_state(Panel.broadcast)
    await message.answer(
        f"📢 Получателей: <b>{len(ids)}</b>\nПришли текст рассылки или /cancel."
    )


async def run_broadcast(bot: Bot, store: Store, chat_id: int, message_id: int, text: str) -> None:
    ids = await store.user_ids(only_active=True)
    sent = failed = 0
    for index, uid in enumerate(ids, start=1):
        try:
            await bot.send_message(uid, text, parse_mode=None)
            sent += 1
        except TelegramAPIError:
            failed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        if index % 25 == 0:
            with contextlib.suppress(TelegramAPIError):
                await bot.edit_message_text(
                    text=f"📣 Отправлено {index} из {len(ids)}…",
                    chat_id=chat_id,
                    message_id=message_id,
                )
        await asyncio.sleep(0.05)

    with contextlib.suppress(TelegramAPIError):
        await bot.edit_message_text(
            text=f"📣 <b>Готово</b>\nДоставлено: {sent}\nНе доставлено: {failed}",
            chat_id=chat_id,
            message_id=message_id,
        )


# --------------------------------------------------------------------------- настройки
@router.callback_query(F.data == "adm:settings")
async def cb_settings(call: CallbackQuery, store: Store, settings: Settings) -> None:
    text, kb = await render_settings(store, settings)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:set:edit:"))
async def cb_set_edit(call: CallbackQuery, state: FSMContext) -> None:
    key = call.data.rsplit(":", 1)[1]
    if key not in EDITABLE:
        await call.answer("Неизвестная настройка", show_alert=True)
        return
    await state.set_state(Panel.edit)
    await state.update_data(edit_key=key)
    await call.message.edit_text(
        f"⚙️ <b>{escape(EDITABLE[key])}</b>\n\n{HINTS.get(key, '')}",
        reply_markup=back_kb("adm:set:cancel"),
    )
    await call.answer()


@router.callback_query(F.data == "adm:set:cancel")
async def cb_set_cancel(call: CallbackQuery, store: Store, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    text, kb = await render_settings(store, settings)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:set:reset")
async def cb_set_reset(call: CallbackQuery, store: Store, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    for key in EDITABLE:
        await store.delete_setting(key)
    text, kb = await render_settings(store, settings)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Вернул значения из env")


@router.message(Panel.edit, F.text)
async def on_edit_value(
    message: Message, store: Store, settings: Settings, state: FSMContext
) -> None:
    data = await state.get_data()
    key = data.get("edit_key")
    if key not in EDITABLE:
        await state.clear()
        await message.answer("Что-то пошло не так, открой /admin заново.")
        return

    value = (message.text or "").strip()

    if key in {"daily_limit", "max_context"}:
        if not value.isdigit():
            await message.answer("Нужно целое число, например <code>30</code>. 0 — без ограничений.")
            return
        number = int(value)
        if key == "daily_limit" and number > 10000:
            await message.answer("Слишком много. Поставь до 10000.")
            return
        if key == "max_context" and number > 100:
            await message.answer("Слишком много. Поставь до 100.")
            return
    elif key in {"ai_model", "ai_vision_model"}:
        if not value or len(value) > 120 or " " in value:
            await message.answer("Имя модели — одно слово без пробелов, например <code>openrouter/free</code>.")
            return
    elif key == "star_rate":
        if not value.isdigit():
            await message.answer("Нужно целое число, например <code>2</code>.")
            return
        number = int(value)
        if not 1 <= number <= 1000:
            await message.answer("Поставь от 1 до 1000 запросов за звезду.")
            return
        value = str(number)
    elif key == "star_packages":
        try:
            parsed = parse_packages(value, ())
        except ValueError as exc:
            await message.answer(
                f"Не получилось разобрать тарифы: {escape(str(exc))}.\n"
                "Пример: <code>30:3,60:6,100:10</code>"
            )
            return
        value = ",".join(f"{requests}:{stars}" for requests, stars in parsed)
    else:  # system_prompt
        if len(value) < 10:
            await message.answer("Слишком коротко — минимум 10 символов.")
            return
        if len(value) > 4000:
            await message.answer("Слишком длинно — до 4000 символов.")
            return

    await store.set_setting(key, value)
    await state.clear()
    text, kb = await render_settings(store, settings)
    await message.answer("✅ Сохранено.")
    await message.answer(text, reply_markup=kb)


# --------------------------------------------------------------------------- роли
async def _notify_role(bot: Bot, user_id: int, text: str) -> bool:
    try:
        await bot.send_message(user_id, text)
        return True
    except TelegramAPIError:
        return False


@router.callback_query(F.data == "adm:roles")
async def cb_roles(call: CallbackQuery, store: Store, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    if call.from_user is None:
        return
    actor_role = await resolve_role(call.from_user.id, settings, store)
    if not can_manage_roles(actor_role):
        await call.answer("Управлять ролями могут только владелец и гл. админ", show_alert=True)
        return
    text, kb = await render_roles(store, settings, actor_role)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:roles:add")
async def cb_roles_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Panel.role_user)
    await state.update_data(role_return="adm:roles")
    await call.message.edit_text(
        "➕ <b>Выдать роль</b>\n\n"
        "Пришли Telegram ID пользователя числом. Он должен хотя бы раз написать боту, "
        "иначе уведомление не дойдёт.\n/cancel — отмена.",
        reply_markup=back_kb("adm:roles"),
    )
    await call.answer()


@router.message(Panel.role_user, F.text)
async def on_role_user(
    message: Message, store: Store, settings: Settings, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        await message.answer("Отменено.")
        return
    if not raw.isdigit():
        await message.answer("Нужен числовой ID, например <code>123456789</code>.")
        return
    target_id = int(raw)
    await state.clear()
    actor = message.from_user
    actor_role = await resolve_role(actor.id, settings, store) if actor else None
    if not can_manage_roles(actor_role):
        await message.answer("Управлять ролями могут только владелец и гл. админ.")
        return
    text, kb = await render_role_card(store, settings, actor_role, actor.id if actor else 0, target_id)
    await message.answer(text, reply_markup=kb)


@router.message(Panel.role_user)
async def on_role_user_non_text(message: Message) -> None:
    await message.answer("Нужен числовой ID или /cancel.")


@router.callback_query(F.data == "adm:role:deny")
async def cb_role_deny(call: CallbackQuery) -> None:
    await call.answer("Эту роль тебе менять нельзя", show_alert=True)


@router.callback_query(F.data.startswith("adm:role:set:"))
async def cb_role_set(call: CallbackQuery, bot: Bot, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    parts = (call.data or "").split(":")
    if len(parts) != 5:
        await call.answer("Некорректная команда", show_alert=True)
        return
    try:
        target_id = int(parts[3])
    except ValueError:
        await call.answer("Некорректный ID", show_alert=True)
        return
    new_role = parts[4]

    actor_role = await resolve_role(call.from_user.id, settings, store)
    current = await resolve_role(target_id, settings, store)
    allowed, reason = can_assign(
        actor_role=actor_role,
        actor_id=call.from_user.id,
        target_id=target_id,
        target_role=current,
        new_role=new_role,
        settings=settings,
    )
    if not allowed:
        await call.answer(reason, show_alert=True)
        return
    if await store.get_role(target_id) == new_role:
        await call.answer("Уже эта роль", show_alert=True)
        return

    await store.set_role(target_id, new_role, call.from_user.id)
    if new_role == "support":
        hint = "Теперь тебе доступны обращения пользователей: /tickets"
    else:
        hint = "Теперь тебе доступна админка: /admin"
    delivered = await _notify_role(
        bot, target_id, f"🎖 <b>Тебе выдана роль</b>\n\n{role_title(new_role)}\n{hint}"
    )
    text, kb = await render_role_card(
        store, settings, actor_role, call.from_user.id, target_id
    )
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Роль выдана ✅" if delivered else "Роль выдана (уведомление не дошло)")


@router.callback_query(F.data.startswith("adm:role:clear:"))
async def cb_role_clear(call: CallbackQuery, bot: Bot, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    try:
        target_id = int((call.data or "").rsplit(":", 1)[1])
    except ValueError:
        await call.answer("Некорректный ID", show_alert=True)
        return
    actor_role = await resolve_role(call.from_user.id, settings, store)
    current = await resolve_role(target_id, settings, store)
    allowed, reason = can_assign(
        actor_role=actor_role,
        actor_id=call.from_user.id,
        target_id=target_id,
        target_role=current,
        new_role=None,
        settings=settings,
    )
    if not allowed:
        await call.answer(reason, show_alert=True)
        return

    await store.delete_role(target_id)
    extra = (
        " Доступ из ADMIN_IDS остался — снимите ID в настройках Render."
        if target_id in settings.admin_ids
        else ""
    )
    delivered = await _notify_role(
        bot,
        target_id,
        "🎖 <b>Роль снята</b>\n\nЕсли это ошибка — напиши владельцу сообщества." + extra,
    )
    text, kb = await render_role_card(
        store, settings, actor_role, call.from_user.id, target_id
    )
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Роль снята" + ("" if delivered else " (уведомление не дошло)"))


@router.callback_query(F.data.startswith("adm:role:"))
async def cb_role_card(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    raw = (call.data or "").rsplit(":", 1)[1]
    if not raw.isdigit():
        await call.answer("Некорректный ID", show_alert=True)
        return
    actor_role = await resolve_role(call.from_user.id, settings, store)
    if not can_manage_roles(actor_role):
        await call.answer("Управлять ролями могут только владелец и гл. админ", show_alert=True)
        return
    text, kb = await render_role_card(
        store, settings, actor_role, call.from_user.id, int(raw)
    )
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


# --------------------------------------------------------------------------- fallback
@router.message(Panel.broadcast)
async def on_bcast_non_text(message: Message) -> None:
    await message.answer("Нужен текст. Пришли сообщение словами или /cancel.")


@router.message(Panel.edit)
async def on_edit_non_text(message: Message) -> None:
    await message.answer("Нужен текст. Пришли значение сообщением или нажми «Назад».")


@router.message(Panel.search)
async def on_search_non_text(message: Message) -> None:
    await message.answer("Нужен числовой ID.")