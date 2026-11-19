"""Админ-панель: статистика, пользователи, бан, рассылка, настройки."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import platform
import random
import re
import time
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
PANEL_STARTED = time.time()


router = Router(name="admin")
router.message.filter(RoleFilter(ROLE_ADMIN))
router.callback_query.filter(RoleFilter(ROLE_ADMIN))


class Panel(StatesGroup):
    broadcast = State()
    search = State()
    edit = State()
    grant = State()
    image_grant = State()
    role_user = State()
    channel_add = State()
    channel_text = State()
    channel_button = State()


# --------------------------------------------------------------------------- клавиатуры
def main_kb(role: str | None = ROLE_ADMIN) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="📊 Статистика", callback_data="adm:stats"),
            InlineKeyboardButton(text="👥 Пользователи", callback_data="adm:users:0"),
        ],
        [
            InlineKeyboardButton(text="📢 Канал", callback_data="adm:ch"),
            InlineKeyboardButton(text="🎉 Фишки", callback_data="adm:fun"),
        ],
        [
            InlineKeyboardButton(text="📢 Рассылка", callback_data="adm:bcast"),
            InlineKeyboardButton(text="⚙️ Настройки", callback_data="adm:settings"),
        ],
        [
            InlineKeyboardButton(text="🎫 Тикеты", callback_data="tick:list:0"),
            InlineKeyboardButton(text="⭐ Платежи", callback_data="adm:payments"),
        ],
        [
            InlineKeyboardButton(text="🔍 Найти по ID", callback_data="adm:find"),
            InlineKeyboardButton(text="🧪 Проверить ИИ", callback_data="adm:aitest"),
        ],
    ]
    if can_manage_roles(role):
        rows.append([InlineKeyboardButton(text="👑 Роли", callback_data="adm:roles")])
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
    if stats.get("grams"):
        lines.append(f"🪙 Получено GRAM: <b>{float(stats['grams']):.2f}</b>")
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
            elif row.get("kind") == "gram":
                what = f"🪙 +{row['requests']} за {float(row.get('gram') or 0):.2f} GRAM"
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
                        else (
                            f"↩️ #{row['id']} · 🪙 {row['requests']} зап. · {float(row.get('gram') or 0):.2f} GRAM"
                            if row.get("kind") == "gram"
                            else f"↩️ #{row['id']} · {row['requests']} зап. · {row['stars']} ⭐"
                        )
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
    total = (await store.stats())["users"]
    # Старая кнопка «➡️» могла уйти за конец списка — не показываем пустоту.
    offset = max(0, min(offset, max(0, total - PAGE)))
    rows = await store.list_users(offset, PAGE)
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
        f"🖼 Бонусных генераций картинок: <b>{card.get('image_credits', 0)}</b>\n"
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
            [
                InlineKeyboardButton(
                    text="🖼 Выдать генерации", callback_data=f"adm:ig:{user_id}"
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
    for item in model_catalog.CATALOG:
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
                    callback_data=f"adm:mdl:tg:{user_id}:{item.id}",
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
    store: Store, settings: Settings, bot: Bot | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    rt = await load_runtime(store, settings)
    overrides = await store.all_settings()

    def mark(key: str) -> str:
        return " ✏️" if key in overrides else ""

    from subscription import channel_status, channel_display

    gate_state, gate_note = (
        await channel_status(bot, rt.required_channel)
        if bot is not None
        else ("unknown", "—")
    )
    gate_icon = {"ok": "✅", "off": "⏸", "error": "⚠️"}.get(gate_state, "⚠️")
    channel_line = (
        f"📢 Подписка: {channel_display(rt.required_channel) or 'выключена'} "
        f"{gate_icon}{mark('required_channel')}\n"
        f"🔗 Ссылка: {escape(rt.required_channel_url) or '—'}{mark('required_channel_url')}\n"
        f"<i>{escape(gate_note)}</i>\n\n"
    )

    prompt = rt.system_prompt.replace("\n", " ")
    if len(prompt) > 140:
        prompt = prompt[:140] + "…"
    gate_line = (
        "🔐 Гейт в чатах: <b>"
        + ("включён" if rt.group_gate else "выключен")
        + "</b>"
        + mark("group_gate")
        + "\n\n"
    )
    text = (
        "⚙️ <b>Настройки</b>\n"
        "<i>Изменения применяются сразу, рестарт не нужен.</i>\n\n"
        f"📏 Лимит в день: <b>{rt.daily_limit if rt.daily_limit > 0 else 'безлимит'}</b>{mark('daily_limit')}\n"
        f"🧾 Глубина контекста: <b>{rt.max_context}</b>{mark('max_context')}\n"
        f"🧠 Модель: <code>{escape(rt.model)}</code>{mark('ai_model')}\n"
        f"🖼 Модель для фото: <code>{escape(rt.vision_model)}</code>{mark('ai_vision_model')}\n"
        f"📝 Промпт: <i>{escape(prompt)}</i>{mark('system_prompt')}\n\n"
        f"⭐ Тарифы: <code>{escape(','.join(f'{n}:{s}' for n, s in rt.star_packages))}</code>{mark('star_packages')}\n"
        f"💱 Курс: 1 ⭐ = <b>{rt.star_rate}</b> запросов{mark('star_rate')}\n\n"
        + channel_line
        + gate_line
        + "🛡 Защита: всегда включена — русский язык, анти-jailbreak, "
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
        [
            InlineKeyboardButton(
                text="✏️ Канал подписки", callback_data="adm:set:edit:required_channel"
            )
        ],
        [
            InlineKeyboardButton(
                text="✏️ Ссылка на канал", callback_data="adm:set:edit:required_channel_url"
            )
        ],
        [
            InlineKeyboardButton(
                text=("🔓 Выключить гейт в чатах" if rt.group_gate else "🔒 Включить гейт в чатах"),
                callback_data="adm:set:gate",
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
    "image_daily_limit": (
        "Сколько картинок в день пользователь может сгенерировать бесплатно.\n"
        "<code>0</code> — только выданные администратором генерации.\n"
        "Выданные генерации тратятся после бесплатных.\n\nПришли число:"
    ),
    "required_channel": (
        "Канал или группа, подписка на которую обязательна перед доступом к боту.\n\n"
        "Форматы: <code>@gazyavaGPT</code>, <code>https://t.me/gazyavaGPT</code> "
        "или ID вида <code>-1001234567890</code>.\n"
        "<b>Важно:</b> бот должен быть добавлен в канал администратором "
        "(или участником группы), иначе Telegram не даст проверить подписку.\n"
        "Чтобы выключить проверку, пришли <code>off</code>.\n\nПришли канал:"
    ),
    "required_channel_url": (
        "Ссылка, которая открывается кнопкой «Подписаться».\n"
        "Пример: <code>https://t.me/gazyavaGPT</code> или ссылка-приглашение "
        "<code>https://t.me/+AbCdEf</code>.\n"
        "Если оставить пустым, бот сам соберёт ссылку из @username.\n\nПришли ссылку:"
    ),
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
async def cb_grant_start(
    call: CallbackQuery, state: FSMContext, store: Store, settings: Settings
) -> None:
    user_id = int(call.data.rsplit(":", 1)[1])
    actor = call.from_user
    actor_id = actor.id if actor else 0
    actor_role = await resolve_role(actor_id, settings, store)
    target_role = await resolve_role(user_id, settings, store)
    if user_id == actor_id and actor_role != ROLE_OWNER:
        await call.answer("Себе запросы не начисляю — попроси другого админа.", show_alert=True)
        return
    if user_id != actor_id and rank(target_role) >= rank(actor_role):
        await call.answer("Нельзя менять баланс равного или старшего по роли", show_alert=True)
        return
    await state.set_state(Panel.grant)
    await state.update_data(grant_user_id=user_id)
    await call.message.edit_text(
        f"⭐ <b>Выдать запросы</b> пользователю <code>{user_id}</code>\n\n"
        "Пришли количество целым числом. Чтобы отозвать, укажи отрицательное число.\n"
        "Например: <code>50</code> или <code>-10</code>.\n/cancel — отмена.",
        reply_markup=back_kb("adm:main"),
    )
    await call.answer()


@router.message(Panel.grant, F.text, ~Command("cancel"))
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


@router.message(Panel.grant, ~Command("cancel"))
async def on_grant_non_text(message: Message) -> None:
    await message.answer("Пришли количество запросов числом или нажми /cancel.")


@router.callback_query(F.data.startswith("adm:ig:"))
async def cb_image_grant_start(
    call: CallbackQuery, state: FSMContext, store: Store, settings: Settings
) -> None:
    user_id = int(call.data.rsplit(":", 1)[1])
    actor = call.from_user
    actor_id = actor.id if actor else 0
    actor_role = await resolve_role(actor_id, settings, store)
    target_role = await resolve_role(user_id, settings, store)
    if user_id == actor_id and actor_role != ROLE_OWNER:
        await call.answer("Себе генерации не начисляю — попроси другого админа.", show_alert=True)
        return
    if user_id != actor_id and rank(target_role) >= rank(actor_role):
        await call.answer("Нельзя менять баланс равного или старшего по роли", show_alert=True)
        return
    await state.set_state(Panel.image_grant)
    await state.update_data(image_user_id=user_id)
    await call.message.edit_text(
        f"🖼 <b>Выдать генерации картинок</b> пользователю <code>{user_id}</code>\n\n"
        "Пришли количество целым числом. Чтобы отозвать, укажи отрицательное число.\n"
        "Например: <code>5</code> или <code>-1</code>.\n/cancel — отмена.",
        reply_markup=back_kb("adm:main"),
    )
    await call.answer()


@router.message(Panel.image_grant, F.text, ~Command("cancel"))
async def on_image_grant_amount(
    message: Message, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if not raw.lstrip("+-").isdigit():
        await message.answer("Пришли целое число, например <code>5</code> или <code>-1</code>.")
        return
    amount = int(raw)
    if amount == 0 or abs(amount) > 10_000:
        await message.answer("Число должно быть от -10000 до 10000, кроме нуля.")
        return
    data = await state.get_data()
    user_id = int(data.get("image_user_id", 0))
    if user_id <= 0 or not await store.user_card(user_id):
        await state.clear()
        await message.answer("Пользователь не найден. Открой карточку заново.")
        return
    balance = await store.add_image_credits(user_id, amount)
    await state.clear()
    await message.answer(
        f"✅ Изменение: {amount:+d} генераций картинок.\n"
        f"Баланс пользователя <code>{user_id}</code>: <b>{balance}</b>."
    )
    try:
        await bot.send_message(
            user_id,
            "🖼 Администратор "
            f"{'начислил' if amount > 0 else 'списал'} <b>{abs(amount)}</b> "
            "генераций картинок.\n"
            f"Твой запас генераций: <b>{balance}</b>.",
        )
    except TelegramAPIError:
        pass
    text, kb = await render_card(store, user_id, settings)
    await message.answer(text, reply_markup=kb)


@router.message(Panel.image_grant, ~Command("cancel"))
async def on_image_grant_non_text(message: Message) -> None:
    await message.answer("Пришли количество генераций числом или нажми /cancel.")


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
    is_gram = payment.get("kind") == "gram"
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
    elif is_gram:
        product = (
            f"🪙 <b>{payment['requests']}</b> запросов за "
            f"<b>{float(payment.get('gram') or 0):.2f}</b> GRAM"
        )
        effect = (
            "Автоматического возврата в блокчейне нет: GRAM придётся отправить вручную. "
            "Бот спишет начисленные запросы."
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
                        text="✅ Списать запросы" if is_gram else "✅ Вернуть звёзды",
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

    is_gram = payment.get("kind") == "gram"
    if is_gram:
        # On-chain возврат бот сделать не может: админ отправляет GRAM вручную,
        # а здесь только помечаем платёж и снимаем начисленные запросы.
        refunded = await store.mark_payment_refunded(payment_id)
        if not refunded:
            await call.answer("Платёж уже был возвращён", show_alert=True)
            return
        balance = await store.add_bonus(payment["user_id"], -int(payment["requests"]))
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(
                payment["user_id"],
                f"↩️ <b>Возврат GRAM</b>\n\n"
                f"Списано запросов: <b>{payment['requests']}</b>\n"
                f"Остаток бонусных запросов: <b>{balance}</b>.\n"
                "GRAM отправим на кошелёк, с которого была оплата.",
            )
        await call.answer("Запросы списаны, GRAM верните вручную ↩️")
        text, kb = await render_payments(store)
        with contextlib.suppress(TelegramAPIError):
            await call.message.edit_text(text, reply_markup=kb)
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
async def cb_users(
    call: CallbackQuery, store: Store, settings: Settings, state: FSMContext
) -> None:
    await state.clear()
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
    parts = call.data.split(":", 4)
    if len(parts) != 5:
        await call.answer("Кнопка устарела", show_alert=True)
        return
    user_id = int(parts[3])
    item = model_catalog.info(parts[4])
    if item is None or item.stars <= 0:
        await call.answer("Кнопка устарела — открой карточку заново", show_alert=True)
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
async def cb_reset_history(
    call: CallbackQuery, store: Store, settings: Settings
) -> None:
    user_id = int(call.data.rsplit(":", 1)[1])
    actor_id = call.from_user.id if call.from_user else 0
    actor_role = await resolve_role(actor_id, settings, store)
    target_role = await resolve_role(user_id, settings, store)
    if user_id != actor_id and rank(target_role) >= rank(actor_role):
        await call.answer("Нельзя чистить контекст равному или старшему", show_alert=True)
        return
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


@router.message(Panel.search, F.text, ~Command("cancel"))
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
async def cb_settings(call: CallbackQuery, bot: Bot, store: Store, settings: Settings) -> None:
    text, kb = await render_settings(store, settings, bot)
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
async def cb_set_cancel(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    await state.clear()
    text, kb = await render_settings(store, settings, bot)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:set:reset")
async def cb_set_reset(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    await state.clear()
    for key in EDITABLE:
        await store.delete_setting(key)
    # Гейт в группах и автопосты тоже возвращаем к значениям из env.
    await store.delete_setting("group_gate")
    for key in ("autopost_enabled", "autopost_channel", "autopost_hour", "autopost_kind"):
        await store.delete_setting(key)
    from subscription import reset_cache

    reset_cache()
    text, kb = await render_settings(store, settings, bot)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Вернул значения из env")


@router.callback_query(F.data == "adm:set:gate")
async def cb_set_gate(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    await state.clear()
    rt = await load_runtime(store, settings)
    await store.set_setting("group_gate", "off" if rt.group_gate else "on")
    from subscription import reset_cache

    reset_cache()
    text, kb = await render_settings(store, settings, bot)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer("Гейт в чатах выключен" if rt.group_gate else "Гейт в чатах включён")


@router.message(Panel.edit, F.text)
async def on_edit_value(
    message: Message, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    data = await state.get_data()
    key = data.get("edit_key")
    if key not in EDITABLE:
        await state.clear()
        await message.answer("Что-то пошло не так, открой /admin заново.")
        return

    value = (message.text or "").strip()

    if key in {"daily_limit", "max_context", "image_daily_limit"}:
        if not value.isdigit():
            await message.answer("Нужно целое число, например <code>30</code>. 0 — без ограничений.")
            return
        number = int(value)
        if key == "daily_limit" and number > 10000:
            await message.answer("Слишком много. Поставь до 10000.")
            return
        if key == "image_daily_limit" and number > 1000:
            await message.answer("Слишком много. Поставь до 1000 картинок в день.")
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
    elif key == "required_channel":
        from subscription import normalize_channel

        normalized = normalize_channel(value)
        if value.strip() and value.strip().lower() not in {"0", "-", "off", "no", "none", "нет", "выкл"} and not normalized:
            await message.answer(
                "Не понял канал. Пришли <code>@username</code>, "
                "ссылку <code>https://t.me/...</code> или ID <code>-100...</code>.\n"
                "Чтобы выключить проверку — <code>off</code>."
            )
            return
        value = normalized
    elif key == "required_channel_url":
        from subscription import normalize_channel_url

        if value and " " in value:
            await message.answer("В ссылке не должно быть пробелов. Пример: <code>https://t.me/gazyavaGPT</code>")
            return
        value = normalize_channel_url(value, "")
        if value and not value.lower().startswith(("http://", "https://")):
            await message.answer("Нужна ссылка вида <code>https://t.me/...</code>.")
            return
    else:  # system_prompt
        if len(value) < 10:
            await message.answer("Слишком коротко — минимум 10 символов.")
            return
        if len(value) > 4000:
            await message.answer("Слишком длинно — до 4000 символов.")
            return

    await store.set_setting(key, value)
    if key in {"required_channel", "required_channel_url"}:
        from subscription import reset_cache

        reset_cache()
    await state.clear()
    text, kb = await render_settings(store, settings, bot)
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


# --------------------------------------------------------------------------- фишки
FUN_GIFTS = (1, 3, 5, 10)
WHEEL_PRIZES = (1, 2, 3, 5, 7, 10)
FUN_FORTUNES = (
    "Сегодня отличный день, чтобы закрыть самый старый тикет 😉",
    "Если сомневаешься — посмотри логи. Там всегда честнее, чем в графике.",
    "Вселенная за тебя: сделай бэкап, пока она добрая.",
    "Твой бот сегодня особенно хорош. Не забудь сказать ему спасибо.",
    "Один маленький фикс сегодня лучше большого релиза в пятницу.",
    "Не всё то баг, что не работает с первого раза.",
    "Пользователи придут, запросы пойдут, звёзды зазвенят ✨",
    "Хороший админ — тот, кто вовремя нажимает «Обновить».",
    "Сегодня можно позволить себе один эксперимент. Только один 😄",
    "Правило трёх «П»: проверил, подождал, перезапустил.",
)


def _fun_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎲 Рулетка бонуса", callback_data="adm:fun:wheel"),
                InlineKeyboardButton(text="🎁 Бонус всем", callback_data="adm:fun:gift"),
            ],
            [
                InlineKeyboardButton(text="📈 Активность", callback_data="adm:fun:chart"),
                InlineKeyboardButton(text="🏆 Зал славы", callback_data="adm:fun:hall"),
            ],
            [
                InlineKeyboardButton(text="🩺 Диагностика", callback_data="adm:fun:diag"),
                InlineKeyboardButton(text="🔮 Предсказание", callback_data="adm:fun:fortune"),
            ],
            [InlineKeyboardButton(text="🎁 Розыгрыши", callback_data="adm:give")],
            [InlineKeyboardButton(text="🎆 Салют", callback_data="adm:fun:party")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:main")],
        ]
    )


def _fun_name(row: dict) -> str:
    username = row.get("username")
    if username:
        return "@" + escape(str(username))
    return escape(str(row.get("first_name") or row.get("user_id")))


async def render_fun(store: Store) -> tuple[str, InlineKeyboardMarkup]:
    stats = await store.stats()
    feedback = await store.feedback_stats()
    recipients = max(0, stats["users"] - stats["banned"])
    text = (
        "🎉 <b>Фишки админки</b>\n"
        "<i>Немного магии, чтобы панель не была скучной.</i>\n\n"
        f"👥 Получателей подарков: <b>{recipients}</b>\n"
        f"💬 Запросов сегодня: <b>{stats['requests_today']}</b>\n"
        f"👍/👎 за ответы: {feedback['up']} / {feedback['down']}\n\n"
        "🎲 <b>Рулетка</b> — случайному пользователю случайный бонус.\n"
        "🎁 <b>Бонус всем</b> — подарить запросы всем сразу.\n"
        "📈 <b>Активность</b> — график запросов за 7 дней.\n"
        "🏆 <b>Зал славы</b> — лучшие по запросам и покупкам.\n"
        "🩺 <b>Диагностика</b> — БД, ИИ, webhook и аптайм.\n"
        "🔮 <b>Предсказание</b> — что день грядущий нам готовит.\n"
        "🎁 <b>Розыгрыши</b> — призы, участники и победители в чатах.\n"
        "🎆 <b>Салют</b> — просто красиво."
    )
    return text, _fun_kb()


async def render_fun_gift(store: Store) -> tuple[str, InlineKeyboardMarkup]:
    stats = await store.stats()
    recipients = max(0, stats["users"] - stats["banned"])
    text = (
        "🎁 <b>Бонус всем</b>\n\n"
        f"Получателей: <b>{recipients}</b> (без забаненных).\n"
        "Нажми сумму — бонус выдастся сразу, без подтверждения.\n"
        "Забаненные пользователи подарок не получат."
    )
    buttons = [
        [
            InlineKeyboardButton(
                text=f"+{amount} всем", callback_data=f"adm:fun:gift:{amount}"
            )
            for amount in FUN_GIFTS[:2]
        ],
        [
            InlineKeyboardButton(
                text=f"+{amount} всем", callback_data=f"adm:fun:gift:{amount}"
            )
            for amount in FUN_GIFTS[2:]
        ],
        [InlineKeyboardButton(text="⬅️ К фишкам", callback_data="adm:fun")],
    ]
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


def _bar(value: int, maximum: int, width: int = 12) -> str:
    if value <= 0:
        return "·"
    filled = max(1, round(value / maximum * width)) if maximum > 0 else width
    return "█" * filled + "░" * max(0, width - filled)


async def render_activity(store: Store) -> tuple[str, InlineKeyboardMarkup]:
    rows = await store.activity_by_day(7)
    total = sum(int(row.get("total", 0)) for row in rows)
    best = max(rows, key=lambda row: int(row.get("total", 0))) if rows else None
    lines = ["📈 <b>Активность за 7 дней</b>\n"]
    if total <= 0:
        lines.append("Данных пока нет — как только пойдут запросы, график заполнится.")
    else:
        maximum = max(int(row.get("total", 0)) for row in rows) or 1
        chart = []
        for row in rows:
            day = row.get("day")
            label = day.strftime("%d.%m") if hasattr(day, "strftime") else str(day)
            mark = "👑" if best and row is best else "  "
            chart.append(f"{label}  {_bar(int(row.get('total', 0)), maximum)}  {int(row.get('total', 0)):>4} {mark}")
        lines.append("<pre>" + "\n".join(chart) + "</pre>")
        lines.append("")
        lines.append(f"Всего: <b>{total}</b> запросов · в среднем <b>{total / max(1, len(rows)):.1f}</b> в день")
    return "\n".join(lines), InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:fun:chart")],
            [InlineKeyboardButton(text="⬅️ К фишкам", callback_data="adm:fun")],
        ]
    )


async def render_hall(store: Store) -> tuple[str, InlineKeyboardMarkup]:
    top = await store.top_users(5)
    payers = await store.top_payers(5)
    feedback = await store.feedback_stats()
    medals = ("🥇", "🥈", "🥉", "4.", "5.")
    lines = ["🏆 <b>Зал славы</b>\n", "<b>💬 По запросам</b>"]
    if top:
        for index, row in enumerate(top):
            lines.append(f"{medals[index]} {_fun_name(row)} — <b>{row['total']}</b>")
    else:
        lines.append("Пока пусто.")
    lines.append("\n<b>⭐ По покупкам</b>")
    if payers:
        for index, row in enumerate(payers):
            lines.append(f"{medals[index]} {_fun_name(row)} — <b>{row['stars']}</b> ⭐")
    else:
        lines.append("Покупок пока не было.")
    lines.append(
        f"\n👍/👎 за ответы: <b>{feedback['up']}</b> / <b>{feedback['down']}</b>"
    )
    return "\n".join(lines), InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:fun:hall")],
            [InlineKeyboardButton(text="⬅️ К фишкам", callback_data="adm:fun")],
        ]
    )


def _uptime_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes = seconds // 60
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} м"
    return f"{minutes} м"


async def render_diag(
    bot: Bot, store: Store, settings: Settings, ai: AIClient
) -> tuple[str, InlineKeyboardMarkup]:
    from subscription import channel_display, channel_status

    started = time.perf_counter()
    db_ok = await store.ping()
    db_ms = (time.perf_counter() - started) * 1000
    rt = await load_runtime(store, settings)
    stats = await store.stats()
    tickets = await store.tickets_stats()

    db_line = f"✅ работает · {db_ms:.0f} мс" if db_ok else "❌ нет связи"
    ai_line = f"✅ <code>{escape(rt.model)}</code>" if ai.configured else "❌ ключ не задан"
    vision_line = f"✅ <code>{escape(rt.vision_model)}</code>"

    try:
        info = await bot.get_webhook_info()
        url = getattr(info, "url", "") or ""
        error = getattr(info, "last_error_message", None)
        pending = int(getattr(info, "pending_update_count", 0) or 0)
        if not url:
            webhook_line = "⚠️ не задан — бот работает через polling"
        elif error:
            webhook_line = f"⚠️ {escape(str(error)[:100])}"
        else:
            webhook_line = f"✅ {escape(url)} · в очереди {pending}"
    except Exception as exc:  # noqa: BLE001 — диагностика не должна падать
        webhook_line = f"⚠️ не проверить: {escape(str(exc)[:100])}"

    gate_state, gate_note = await channel_status(bot, rt.required_channel)
    gate_icon = {"ok": "✅", "off": "⏸", "error": "⚠️"}.get(gate_state, "⚠️")
    channel_line = (
        f"{gate_icon} {channel_display(rt.required_channel) or 'выключена'} · "
        f"<i>{escape(gate_note)}</i>"
    )

    text = (
        "🩺 <b>Диагностика</b>\n\n"
        f"🗄 БД: {db_line}\n"
        f"🧠 ИИ: {ai_line}\n"
        f"🖼 Фото: {vision_line}\n"
        f"🔗 Webhook: {webhook_line}\n"
        f"📢 Канал: {channel_line}\n\n"
        f"👥 Пользователей: <b>{stats['users']}</b> · 🚫 {stats['banned']}\n"
        f"🎫 Тикеты: {tickets['open']} открыто · {tickets['closed']} закрыто\n"
        f"💬 Запросов сегодня: <b>{stats['requests_today']}</b>\n"
        f"⏱ Аптайм панели: {_uptime_text(time.time() - PANEL_STARTED)}\n"
        f"🐍 Python {platform.python_version()}"
    )
    return text, InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:fun:diag")],
            [InlineKeyboardButton(text="⬅️ К фишкам", callback_data="adm:fun")],
        ]
    )


def render_fortune() -> tuple[str, InlineKeyboardMarkup]:
    text = (
        "🔮 <b>Предсказание дня</b>\n\n"
        f"<blockquote>{escape(random.choice(FUN_FORTUNES))}</blockquote>"
    )
    return text, InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔮 Ещё предсказание", callback_data="adm:fun:fortune")],
            [InlineKeyboardButton(text="⬅️ К фишкам", callback_data="adm:fun")],
        ]
    )


@router.message(Command("fun"))
async def cmd_fun(message: Message, store: Store) -> None:
    text, kb = await render_fun(store)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:fun")
async def cb_fun(call: CallbackQuery, store: Store) -> None:
    text, kb = await render_fun(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:fun:gift")
async def cb_fun_gift(call: CallbackQuery, store: Store) -> None:
    text, kb = await render_fun_gift(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data.startswith("adm:fun:gift:"))
async def cb_fun_gift_do(call: CallbackQuery, store: Store) -> None:
    try:
        amount = int(call.data.rsplit(":", 1)[1])
    except (AttributeError, IndexError, ValueError):
        await call.answer("Непонятная сумма", show_alert=True)
        return
    if amount not in FUN_GIFTS:
        await call.answer("Такой суммы нет", show_alert=True)
        return
    count = await store.add_bonus_all(amount)
    text = (
        "🎁 <b>Подарок разлетелся</b>\n\n"
        f"Каждому активному пользователю: <b>+{amount}</b> запросов.\n"
        f"Получателей: <b>{count}</b>.\n\n"
        "<i>Забаненные и удалённые не учитывались.</i>"
    )
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🎁 Ещё раз", callback_data="adm:fun:gift")],
                    [InlineKeyboardButton(text="⬅️ К фишкам", callback_data="adm:fun")],
                ]
            ),
        )
    await call.answer(f"Выдано {count} пользователям")


@router.callback_query(F.data == "adm:fun:wheel")
async def cb_fun_wheel(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings
) -> None:
    candidates = await store.user_ids(only_active=True)
    staff = set(settings.admin_ids) | set(await store.role_ids())
    if settings.owner_id:
        staff.add(settings.owner_id)
    regular = [uid for uid in candidates if uid not in staff]
    candidates = regular or candidates
    if not candidates:
        await call.answer("Пока нет пользователей — некого одаривать", show_alert=True)
        return
    winner = random.choice(candidates)
    amount = random.choice(WHEEL_PRIZES)
    balance = await store.add_bonus(winner, amount)
    card = await store.user_card(winner) or {"user_id": winner}
    name = _fun_name(card)
    with contextlib.suppress(TelegramAPIError):
        await call.message.answer_dice(emoji="🎰")
    with contextlib.suppress(TelegramAPIError):
        await bot.send_message(
            winner,
            f"🎉 <b>Рулетка бонуса!</b>\n\n"
            f"Тебе выпало <b>+{amount}</b> запросов.\n"
            f"Теперь у тебя <b>{balance}</b> бонусных запросов.",
        )
    text = (
        "🎲 <b>Рулетка бонуса</b>\n\n"
        f"Победитель: {name} (<code>{winner}</code>)\n"
        f"Приз: <b>+{amount}</b> запросов\n"
        f"Баланс: <b>{balance}</b>\n\n"
        "<i>Пользователь получил уведомление.</i>"
    )
    with contextlib.suppress(TelegramAPIError):
        await call.message.answer(
            text,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🎲 Ещё раз", callback_data="adm:fun:wheel")],
                    [InlineKeyboardButton(text="⬅️ К фишкам", callback_data="adm:fun")],
                ]
            ),
        )
    await call.answer("Крутим…")


@router.callback_query(F.data == "adm:fun:chart")
async def cb_fun_chart(call: CallbackQuery, store: Store) -> None:
    text, kb = await render_activity(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:fun:hall")
async def cb_fun_hall(call: CallbackQuery, store: Store) -> None:
    text, kb = await render_hall(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:fun:diag")
async def cb_fun_diag(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings, ai: AIClient
) -> None:
    text, kb = await render_diag(bot, store, settings, ai)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:fun:fortune")
async def cb_fun_fortune(call: CallbackQuery) -> None:
    text, kb = render_fortune()
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:fun:party")
async def cb_fun_party(call: CallbackQuery) -> None:
    with contextlib.suppress(TelegramAPIError):
        await call.message.answer_dice(emoji="🎲")
    with contextlib.suppress(TelegramAPIError):
        await call.message.answer(
            "🎆 <b>Салют в честь админа!</b>\n\n"
            "<i>Панель работает, запросы идут, тикеты закрываются.</i>"
        )
    await call.answer("🎉")


# --------------------------------------------------------------------------- канал
CHANNEL_SETTING = "managed_channels"
REQUIRED_CHANNEL_SETTING = "required_channel"
MAX_POST_BUTTONS = 10
MAX_CHANNELS = 8
_BUTTON_URL_RE = re.compile(r"^(?:https?://|tg://)\S+$", re.IGNORECASE)


def _stored_channels(raw: str | None) -> list[str]:
    """Разбирает сохранённый список каналов, поддерживая старый текстовый формат."""
    try:
        values = json.loads(raw or "[]")
    except (TypeError, ValueError):
        values = (raw or "").splitlines()
    if not isinstance(values, list):
        return []
    result = []
    for value in values:
        channel = str(value or "").strip()
        if channel and channel not in result:
            result.append(channel)
    return result[:MAX_CHANNELS]


async def _managed_channels(store: Store) -> list[str]:
    channels = _stored_channels(await store.get_setting(CHANNEL_SETTING))
    required = (await store.get_setting(REQUIRED_CHANNEL_SETTING) or "").strip()
    if required and required.lower() not in {"off", "none", "no", "0", "нет", "выкл"}:
        if required not in channels:
            channels.insert(0, required)
    return channels[:MAX_CHANNELS]


async def _verify_channel(bot: Bot, raw: str) -> tuple[str | None, str | None]:
    """Возвращает каноничный ID и ошибку; проверяет права публикации бота."""
    value = raw.strip()
    match = re.search(r"(?:https?://)?t\.me/([A-Za-z0-9_]+)", value, re.I)
    if match:
        value = "@" + match.group(1)
    elif not value.startswith("@") and not value.lstrip("-").isdigit():
        return None, "Пришли @username, ссылку https://t.me/username или числовой ID канала."
    try:
        chat = await bot.get_chat(value)
        member = await bot.get_chat_member(chat.id, bot.id)
    except TelegramAPIError:
        return None, "Не удалось открыть канал. Проверь username/ID и добавь бота администратором."
    status = getattr(member, "status", "")
    if status not in {"administrator", "creator", "owner"}:
        return None, "Бот не администратор этого канала. Выдай ему права администратора и попробуй снова."
    if getattr(chat, "type", "") != "channel":
        return None, "Это не канал. Укажи именно Telegram-канал."
    if status == "administrator" and getattr(member, "can_post_messages", True) is False:
        return None, "У бота нет права публиковать сообщения. Включи «Публикация сообщений»."
    username = getattr(chat, "username", None)
    return ("@" + username if username else str(chat.id)), None


def _channel_title(channel: str) -> str:
    return escape(channel)


def _post_kb(post: dict) -> InlineKeyboardMarkup | None:
    buttons = post.get("buttons") or []
    if not buttons:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=item["text"], url=item["url"])]
            for item in buttons
        ]
    )


def _post_text(post: dict) -> str:
    text = str(post.get("text") or "").strip()
    if text:
        return text
    return str(post.get("caption") or "").strip()


async def _deliver_post(bot: Bot, channel: str, post: dict, reply_markup=None):
    """Отправляет пост без parse_mode: админский текст не интерпретируется как HTML."""
    text = _post_text(post)
    markup = reply_markup if reply_markup is not None else _post_kb(post)
    photo = post.get("photo")
    if photo:
        return await bot.send_photo(
            channel, photo=photo, caption=text or None, reply_markup=markup, parse_mode=None
        )
    return await bot.send_message(channel, text, reply_markup=markup, parse_mode=None)


async def render_channels(store: Store) -> tuple[str, InlineKeyboardMarkup]:
    channels = await _managed_channels(store)
    required = (await store.get_setting(REQUIRED_CHANNEL_SETTING) or "").strip()
    lines = ["📢 <b>Управление каналом</b>", ""]
    if channels:
        lines.append("<b>Каналы, доступные для публикации:</b>")
        for index, channel in enumerate(channels):
            mark = " · проверка подписки" if channel == required else ""
            lines.append(f"{index + 1}. {_channel_title(channel)}{mark}")
    else:
        lines.append("Каналы пока не подключены.")
    lines += [
        "",
        "Подключи канал, где бот администратор, затем создавай посты с URL-кнопками.",
        "Пост можно сделать текстовым или с фото; кнопки задаются как <code>Текст | https://ссылка</code>.",
        "",
        "📊 Карточка канала: подписчики, права бота, закреп, история постов, "
        "отложенные публикации и опросы.",
        "📤 Отправить любое сообщение в канал: ответь на него командой /topost.",
    ]
    rows = []
    for index, channel in enumerate(channels):
        rows.append([
            InlineKeyboardButton(
                text=f"📊 {channel[:24]}", callback_data=f"adm:ck:card:{index}"
            ),
            InlineKeyboardButton(text="✍️", callback_data=f"adm:ch:pick:{index}"),
            InlineKeyboardButton(text="🗑", callback_data=f"adm:ch:rm:{index}"),
        ])
    if len(channels) < MAX_CHANNELS:
        rows.append([InlineKeyboardButton(text="➕ Подключить канал", callback_data="adm:ch:add")])
    rows.append([InlineKeyboardButton(text="🕘 Автопосты в канал", callback_data="adm:auto")])
    rows.append([InlineKeyboardButton(text="⬅️ В админку", callback_data="adm:main")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _compose_kb(post: dict | None = None) -> InlineKeyboardMarkup:
    buttons = (post or {}).get("buttons") or []
    rows = []
    for index, item in enumerate(buttons):
        rows.append([InlineKeyboardButton(
            text=f"🗑 {item['text'][:40]}", callback_data=f"adm:ch:del:{index}"
        )])
    rows.append([InlineKeyboardButton(text="🔘 Добавить URL-кнопку", callback_data="adm:ch:addbtn")])
    rows.append([
        InlineKeyboardButton(text="👀 Предпросмотр", callback_data="adm:ch:preview"),
        InlineKeyboardButton(text="🚀 Опубликовать", callback_data="adm:ch:publish"),
    ])
    rows.append([
        InlineKeyboardButton(text="🕘 Отложить публикацию", callback_data="adm:ck:later"),
    ])
    rows.append([
        InlineKeyboardButton(text="🗑 Удалить все кнопки", callback_data="adm:ch:delmenu"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="adm:ch:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _render_compose(post: dict, channel: str) -> str:
    body = _post_text(post)
    if len(body) > 700:
        body = body[:700] + "…"
    if not body:
        body = "<i>Текст пока не задан</i>"
    buttons = post.get("buttons") or []
    lines = [
        f"📝 <b>Новый пост для {_channel_title(channel)}</b>",
        "",
        f"📷 Фото: {'есть' if post.get('photo') else 'нет'}",
        "<b>Содержимое:</b>",
        escape(body),
        "",
        f"🔘 Кнопок: <b>{len(buttons)}/{MAX_POST_BUTTONS}</b>",
    ]
    for item in buttons:
        lines.append(f"• {escape(item['text'])} → <code>{escape(item['url'])}</code>")
    return "\n".join(lines)


async def _edit_compose(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    post = data.get("channel_post") or {}
    channel = str(data.get("channel_target") or "")
    await call.message.edit_text(_render_compose(post, channel), reply_markup=_compose_kb(post))


@router.message(Command("channel"))
async def cmd_channel(message: Message, store: Store, state: FSMContext) -> None:
    await state.clear()
    text, kb = await render_channels(store)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "adm:ch")
async def cb_channels(call: CallbackQuery, store: Store, state: FSMContext) -> None:
    await state.clear()
    text, kb = await render_channels(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "adm:ch:add")
async def cb_channel_add(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Panel.channel_add)
    await call.message.edit_text(
        "➕ <b>Подключить канал</b>\n\n"
        "Пришли @username, ссылку <code>https://t.me/username</code> или ID вида <code>-100…</code>.\n"
        "Бот проверит, что он администратор канала и может публиковать посты.\n/cancel — отмена.",
        reply_markup=back_kb("adm:ch"),
    )
    await call.answer()


@router.message(Panel.channel_add, F.text)
async def on_channel_add(message: Message, bot: Bot, store: Store, state: FSMContext) -> None:
    channel, error = await _verify_channel(bot, (message.text or "").strip())
    if error:
        await message.answer(error)
        return
    channels = _stored_channels(await store.get_setting(CHANNEL_SETTING))
    if channel not in channels:
        if len(channels) >= MAX_CHANNELS:
            await message.answer("Подключено максимальное число каналов. Удали один и попробуй снова.")
            return
        channels.append(channel)
        await store.set_setting(CHANNEL_SETTING, json.dumps(channels, ensure_ascii=False))
    await state.clear()
    text, kb = await render_channels(store)
    await message.answer(f"✅ Канал {escape(channel)} подключён.\n\n{text}", reply_markup=kb)


@router.callback_query(F.data.startswith("adm:ch:rm:"))
async def cb_channel_remove(call: CallbackQuery, store: Store) -> None:
    try:
        index = int(call.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await call.answer("Неверный канал", show_alert=True)
        return
    visible = await _managed_channels(store)
    if index < 0 or index >= len(visible):
        await call.answer("Канал уже удалён", show_alert=True)
        return
    removed = visible[index]
    required = (await store.get_setting(REQUIRED_CHANNEL_SETTING) or "").strip()
    if removed == required:
        await call.answer("Это канал обязательной подписки. Чтобы отвязать его, измени настройку в «Настройки».", show_alert=True)
        return
    channels = _stored_channels(await store.get_setting(CHANNEL_SETTING))
    channels = [channel for channel in channels if channel != removed]
    await store.set_setting(CHANNEL_SETTING, json.dumps(channels, ensure_ascii=False))
    text, kb = await render_channels(store)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(f"✅ Канал {escape(removed)} отвязан.\n\n{text}", reply_markup=kb)
    await call.answer("Канал отвязан")


@router.callback_query(F.data.startswith("adm:ch:pick:"))
async def cb_channel_pick(call: CallbackQuery, store: Store, state: FSMContext) -> None:
    try:
        index = int(call.data.rsplit(":", 1)[1])
        channels = await _managed_channels(store)
        channel = channels[index]
    except (IndexError, ValueError, AttributeError):
        await call.answer("Канал не найден", show_alert=True)
        return
    await state.clear()
    await state.update_data(channel_target=channel, channel_post={"text": "", "photo": None, "buttons": []})
    await state.set_state(Panel.channel_text)
    await call.message.edit_text(
        f"📝 <b>Пост в {escape(channel)}</b>\n\n"
        "Пришли текст поста или фото с подписью. Текст отправится без разбора HTML, чтобы символы не ломались.\n"
        "Затем можно добавить до 10 URL-кнопок.",
        reply_markup=back_kb("adm:ch"),
    )
    await call.answer()


@router.message(Panel.channel_text, F.text)
async def on_channel_post_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пост пустой — пришли текст или фото с подписью.")
        return
    data = await state.get_data()
    post = data.get("channel_post") or {"buttons": []}
    post.update(text=text, caption=text)
    await state.update_data(channel_post=post)
    await state.set_state(None)
    await message.answer(_render_compose(post, str(data.get("channel_target") or "")), reply_markup=_compose_kb(post))


@router.message(Panel.channel_text, F.photo)
async def on_channel_post_photo(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    caption = (message.caption or "").strip()
    data = await state.get_data()
    post = data.get("channel_post") or {"buttons": []}
    post.update(text=caption, caption=caption, photo=photo.file_id)
    await state.update_data(channel_post=post)
    await state.set_state(None)
    await message.answer(_render_compose(post, str(data.get("channel_target") or "")), reply_markup=_compose_kb(post))


@router.callback_query(F.data == "adm:ch:addbtn")
async def cb_channel_add_button(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if len((data.get("channel_post") or {}).get("buttons") or []) >= MAX_POST_BUTTONS:
        await call.answer("Можно добавить не больше 10 кнопок", show_alert=True)
        return
    await state.set_state(Panel.channel_button)
    await call.message.edit_text(
        "🔘 <b>Добавить кнопку</b>\n\nПришли в формате:\n<code>Текст кнопки | https://example.com</code>\n"
        "Допускаются ссылки http(s):// и tg://. Можно прислать несколько кнопок подряд — по одной в сообщении.\n"
        "/cancel — отмена добавления.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Готово", callback_data="adm:ch:back")]
            ]
        ),
    )
    await call.answer()


@router.message(Panel.channel_button, F.text)
async def on_channel_button(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if "|" not in raw:
        await message.answer("Нужен формат <code>Текст кнопки | https://example.com</code>.")
        return
    label, url = (part.strip() for part in raw.split("|", 1))
    if not label or len(label) > 64:
        await message.answer("Текст кнопки должен быть от 1 до 64 символов.")
        return
    if not _BUTTON_URL_RE.fullmatch(url):
        await message.answer("Ссылка должна начинаться с http://, https:// или tg:// и не содержать пробелов.")
        return
    data = await state.get_data()
    post = data.get("channel_post") or {"text": "", "photo": None, "buttons": []}
    buttons = post.setdefault("buttons", [])
    if len(buttons) >= MAX_POST_BUTTONS:
        await message.answer("У поста уже 10 кнопок — лимит достигнут.")
        return
    buttons.append({"text": label, "url": url})
    await state.update_data(channel_post=post)
    # Состояние не сбрасываем: можно сразу прислать следующую кнопку строкой.
    await message.answer(_render_compose(post, str(data.get("channel_target") or "")), reply_markup=_compose_kb(post))


@router.callback_query(F.data == "adm:ch:back")
async def cb_channel_compose_back(call: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(None)
    await _edit_compose(call, state)
    await call.answer()


@router.callback_query(F.data.startswith("adm:ch:del:"))
async def cb_channel_delete_button(call: CallbackQuery, state: FSMContext) -> None:
    try:
        index = int(call.data.rsplit(":", 1)[1])
    except (AttributeError, ValueError):
        await call.answer("Неверная кнопка", show_alert=True)
        return
    data = await state.get_data()
    post = data.get("channel_post") or {}
    buttons = post.get("buttons") or []
    if index < 0 or index >= len(buttons):
        await call.answer("Кнопка уже удалена", show_alert=True)
        return
    buttons.pop(index)
    post["buttons"] = buttons
    await state.update_data(channel_post=post)
    await _edit_compose(call, state)
    await call.answer("Кнопка удалена")


@router.callback_query(F.data == "adm:ch:delmenu")
async def cb_channel_delete_menu(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    post = data.get("channel_post") or {}
    post["buttons"] = []
    await state.update_data(channel_post=post)
    await _edit_compose(call, state)
    await call.answer("Кнопки удалены")


@router.callback_query(F.data == "adm:ch:preview")
async def cb_channel_preview(call: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    post = data.get("channel_post") or {}
    channel = str(data.get("channel_target") or "")
    if not _post_text(post) and not post.get("photo"):
        await call.answer("Сначала добавь текст или фото", show_alert=True)
        return
    try:
        if post.get("photo"):
            await call.bot.send_photo(
                call.message.chat.id,
                photo=post["photo"],
                caption=_post_text(post) or None,
                reply_markup=_post_kb(post),
                parse_mode=None,
            )
        else:
            await call.message.answer(_post_text(post), reply_markup=_post_kb(post), parse_mode=None)
    except TelegramAPIError:
        await call.answer("Не удалось показать предпросмотр", show_alert=True)
        return
    await call.answer(f"Предпросмотр · публикация в {channel}")


@router.callback_query(F.data == "adm:ch:publish")
async def cb_channel_publish(
    call: CallbackQuery, bot: Bot, store: Store, state: FSMContext
) -> None:
    data = await state.get_data()
    post = data.get("channel_post") or {}
    channel = str(data.get("channel_target") or "")
    if not channel or (not _post_text(post) and not post.get("photo")):
        await call.answer("Не хватает канала или содержимого поста", show_alert=True)
        return
    try:
        import channelkit

        sent = await channelkit.publish_to_channel(bot, store, channel, post)
        index = await channelkit.channel_index(store, channel)
    except TelegramAPIError as exc:
        await call.answer("Telegram не принял пост. Проверь права бота и длину текста.", show_alert=True)
        log.warning("Channel post failed for %s: %s", channel, exc)
        return
    await state.clear()
    await call.message.edit_text(
        f"✅ Пост #{sent.message_id} опубликован в {escape(channel)}.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Карточка канала", callback_data=f"adm:ck:card:{index}")],
                [InlineKeyboardButton(text="📋 История постов", callback_data=f"adm:ck:hist:{index}")],
                [InlineKeyboardButton(text="⬅️ К каналу", callback_data="adm:ch")],
            ]
        ),
    )
    await call.answer("Опубликовано")


@router.callback_query(F.data == "adm:ch:cancel")
async def cb_channel_cancel(call: CallbackQuery, state: FSMContext, store: Store) -> None:
    await state.clear()
    text, kb = await render_channels(store)
    await call.message.edit_text("🗑 Черновик удалён.\n\n" + text, reply_markup=kb)
    await call.answer("Отменено")


@router.message(Panel.channel_add)
async def on_channel_add_non_text(message: Message) -> None:
    await message.answer("Пришли @username, t.me-ссылку или ID канала текстом. /cancel — отмена.")


@router.message(Panel.channel_text)
async def on_channel_post_non_text(message: Message) -> None:
    await message.answer("Пришли текстовый пост или фото с подписью.")


@router.message(Panel.channel_button)
async def on_channel_button_non_text(message: Message) -> None:
    await message.answer("Кнопка добавляется текстом: <code>Текст | https://example.com</code>.")


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