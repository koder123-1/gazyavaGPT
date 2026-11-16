"""Автопосты в канал: «задача дня» и «совет дня» по расписанию.

Админ выбирает канал, время (МСК) и тип контента в /admin → 📢 Канал →
🕘 Автопосты. Посты берутся из курируемого списка и меняются каждый день,
поэтому канал не превращается в спам одинаковыми сообщениями.

Публикация идёт фоновым циклом раз в 5 минут: если Render спал в нужный час,
бот догоняет в течение двух часов. Повтор за день невозможен — дата последней
публикации хранится в настройках.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Any

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from config import Settings
from roles import has_admin_access, resolve_role
from store import Store
from subscription import normalize_channel

log = logging.getLogger("autopost")
router = Router(name="autopost")

MSK = timezone(timedelta(hours=3))
KINDS = {"task": "📚 Задачи", "tip": "💡 Советы", "mix": "🎲 Микс"}
HOURS = (7, 8, 9, 10, 12, 15, 18, 20)
LOOP_INTERVAL = 300.0
CATCHUP_HOURS = 2

SETTING_KEYS = (
    "autopost_enabled",
    "autopost_channel",
    "autopost_hour",
    "autopost_kind",
    "autopost_last",
)

# --------------------------------------------------------------------------- контент
TASKS: list[dict[str, str]] = [
    {
        "tag": "математика",
        "body": "У Миши было 120 ₽. Он купил 3 ручки по 25 ₽ и блокнот за 30 ₽. "
        "Сколько денег у него осталось?",
        "answer": "15 ₽",
    },
    {
        "tag": "математика",
        "body": "Поезд прошёл 240 км за 3 часа. С какой средней скоростью он ехал?",
        "answer": "80 км/ч",
    },
    {
        "tag": "алгебра",
        "body": "Реши уравнение: 5x − 12 = 3x + 8.",
        "answer": "x = 10",
    },
    {
        "tag": "арифметика",
        "body": "Вычисли: 7 × 8 − 6 ÷ 2.",
        "answer": "53",
    },
    {
        "tag": "геометрия",
        "body": "Чему равна сумма углов треугольника?",
        "answer": "180°",
    },
    {
        "tag": "проценты",
        "body": "Найди 15% от 240.",
        "answer": "36",
    },
    {
        "tag": "дроби",
        "body": "В классе 28 учеников, 3/4 из них были на экскурсии. "
        "Сколько учеников было на экскурсии?",
        "answer": "21 ученик",
    },
    {
        "tag": "английский",
        "body": "Выбери правильную форму: She ___ (go) to school every day.",
        "answer": "goes",
    },
    {
        "tag": "геометрия",
        "body": "Площадь прямоугольника 48 см², одна сторона 6 см. Найди периметр.",
        "answer": "28 см",
    },
    {
        "tag": "логика",
        "body": "Сколько существует двузначных чисел, кратных 5?",
        "answer": "18",
    },
    {
        "tag": "физика",
        "body": "Автомобиль движется со скоростью 60 км/ч. Какой путь он пройдёт "
        "за 2 часа 30 минут?",
        "answer": "150 км",
    },
    {
        "tag": "русский язык",
        "body": "В каком слове ударение падает на второй слог: «звонИт», «тОрты», "
        "«красИвее»?",
        "answer": "звонИт",
    },
]

TIPS: list[dict[str, str]] = [
    {
        "tag": "память",
        "body": "Учи слова короткими подходами: 10 минут утром и 10 минут вечером "
        "работают лучше, чем час зубрёжки перед сном. Мозгу нужны повторения.",
    },
    {
        "tag": "учёба",
        "body": "Перед контрольной повторяй не всё подряд, а свои ошибки. "
        "Выпиши 5–7 мест, где ты ошибался, и разбери именно их.",
    },
    {
        "tag": "фокус",
        "body": "Правило 25/5: 25 минут работы без телефона, 5 минут отдыха. "
        "Четыре таких круга — и домашку можно закрывать.",
    },
    {
        "tag": "проверка",
        "body": "Проверяя решение, подставь ответ обратно в условие. Если сходится — "
        "ты почти наверняка не ошибся в знаках и арифметике.",
    },
    {
        "tag": "конспект",
        "body": "Конспект в три колонки: «вопрос», «формула», «пример». Так перед "
        "экзаменом ты повторяешь не текст, а структуру.",
    },
    {
        "tag": "английский",
        "body": "Учи английские слова в словосочетаниях: не «decision», а "
        "«make a decision». Так они сразу вспоминаются в речи.",
    },
    {
        "tag": "задачи",
        "body": "Если задача не решается, нарисуй схему. Даже простая картинка "
        "с числами часто показывает, какого шага не хватает.",
    },
    {
        "tag": "формулы",
        "body": "Не зубри формулы без вывода. Пойми, откуда берётся каждая — и "
        "через месяц ты вспомнишь её сам, а не будешь искать в шпаргалке.",
    },
]


# --------------------------------------------------------------------------- настройки
def _as_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    raw = value.strip().lower()
    if raw in {"1", "true", "yes", "on", "y", "t", "да", "так", "вкл"}:
        return True
    if raw in {"0", "false", "no", "off", "n", "f", "нет", "не", "выкл"}:
        return False
    return default


def _as_hour(value: str | None, default: int) -> int:
    try:
        hour = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return hour if 0 <= hour <= 23 else default


def _as_kind(value: str | None, default: str) -> str:
    candidate = (value or "").strip().lower()
    return candidate if candidate in KINDS else default


async def get_config(store: Store, settings: Settings) -> dict[str, Any]:
    overrides = await store.all_settings()
    if "autopost_channel" in overrides:
        channel = normalize_channel(overrides.get("autopost_channel"))
    else:
        channel = normalize_channel(settings.autopost_channel) or normalize_channel(
            settings.required_channel
        )
    return {
        "enabled": _as_bool(overrides.get("autopost_enabled"), settings.autopost_enabled),
        "channel": channel,
        "hour": _as_hour(overrides.get("autopost_hour"), settings.autopost_hour),
        "kind": _as_kind(overrides.get("autopost_kind"), settings.autopost_kind),
        "last": (overrides.get("autopost_last") or "").strip(),
    }


def _pool(kind: str) -> list[dict[str, str]]:
    if kind == "task":
        return TASKS
    if kind == "tip":
        return TIPS
    pool: list[dict[str, str]] = []
    for index in range(max(len(TASKS), len(TIPS))):
        if index < len(TASKS):
            pool.append(TASKS[index])
        if index < len(TIPS):
            pool.append(TIPS[index])
    return pool


def pick_post(kind: str, day: date) -> dict[str, str]:
    pool = _pool(kind)
    return pool[day.toordinal() % len(pool)]


def render_post(post: dict[str, str], day: date) -> str:
    is_task = bool(post.get("answer"))
    title = "Задача дня" if is_task else "Совет дня"
    emoji = "🧠" if is_task else "💡"
    tag = escape(str(post.get("tag") or ""))
    stamp = day.strftime("%d.%m.%Y")
    meta = f"{stamp} · {tag}" if tag else stamp
    lines = [
        f"{emoji} <b>{title}</b>",
        f"<i>{meta}</i>",
        "",
        f"<blockquote>{escape(str(post.get('body') or ''))}</blockquote>",
    ]
    if is_task:
        lines.extend(
            [
                "",
                f"<tg-spoiler><b>Ответ:</b> {escape(str(post['answer']))}</tg-spoiler>",
                "",
                "<i>Нужен разбор по шагам? Напиши боту — объясню.</i>",
            ]
        )
    else:
        lines.extend(["", "<i>Сохрани, чтобы не потерять.</i>"])
    return "\n".join(lines)


# --------------------------------------------------------------------------- публикация
_bot_username: str | None = None


async def _username(bot: Bot) -> str:
    global _bot_username
    if _bot_username is None:
        with contextlib.suppress(TelegramAPIError):
            _bot_username = (await bot.me()).username
    return _bot_username or ""


def _keyboard(username: str) -> InlineKeyboardMarkup | None:
    if not username:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🤖 Разобрать с ботом",
                    url=f"https://t.me/{username}?start=autopost",
                )
            ]
        ]
    )


async def publish(bot: Bot, store: Store, settings: Settings, *, force: bool = False) -> tuple[bool, str]:
    """Публикует один пост. Возвращает (успех, пояснение)."""
    config = await get_config(store, settings)
    target = config["channel"]
    if not target:
        return False, "Сначала выбери канал для автопостов."
    today = datetime.now(MSK).date()
    if not force and config["last"] == today.isoformat():
        return False, "Сегодня уже публиковали."

    post = pick_post(config["kind"], today)
    text = render_post(post, today)
    keyboard = _keyboard(await _username(bot))
    try:
        await bot.send_message(
            target, text, reply_markup=keyboard, disable_web_page_preview=True
        )
    except TelegramAPIError as exc:
        log.warning("Автопост в %s не опубликован: %s", target, exc)
        return False, f"Не удалось опубликовать: {exc}"
    await store.set_setting("autopost_last", today.isoformat())
    log.info("Автопост в %s: %s", target, post.get("tag"))
    return True, "Задача дня опубликована" if post.get("answer") else "Совет дня опубликован"


# --------------------------------------------------------------------------- цикл
_task: asyncio.Task | None = None


async def _loop(bot: Bot, store: Store, settings: Settings) -> None:
    while True:
        try:
            config = await get_config(store, settings)
            now = datetime.now(MSK)
            today = now.date().isoformat()
            if config["enabled"] and config["channel"] and config["last"] != today:
                delta = now.hour - config["hour"]
                if 0 <= delta < CATCHUP_HOURS:
                    ok, note = await publish(bot, store, settings)
                    if not ok:
                        log.warning("Автопост: %s", note)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — цикл не должен умирать
            log.exception("Ошибка фонового цикла автопостов")
        await asyncio.sleep(LOOP_INTERVAL)


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


# --------------------------------------------------------------------------- админка
async def _is_staff(user_id: int, settings: Settings, store: Store) -> bool:
    return has_admin_access(await resolve_role(user_id, settings, store))


async def _candidates(store: Store, settings: Settings, current: str) -> list[str]:
    channels: list[str] = []
    try:
        from admin import _managed_channels

        channels = list(await _managed_channels(store))
    except Exception:  # noqa: BLE001 — админка не должна падать из-за импорта
        log.exception("Не удалось прочитать список каналов")
    for raw in (current, settings.autopost_channel, settings.required_channel):
        channel = normalize_channel(raw)
        if channel and channel not in channels:
            channels.insert(0, channel)
    return channels[:8]


def _next_label(config: dict[str, Any], now: datetime) -> str:
    if config["last"] == now.date().isoformat():
        return "завтра"
    if now.hour < config["hour"]:
        return "сегодня"
    if now.hour - config["hour"] < CATCHUP_HOURS:
        return "в ближайшие минуты"
    return "завтра"


async def render_panel(
    store: Store, settings: Settings, channel: str | None = None
) -> tuple[str, InlineKeyboardMarkup]:
    config = await get_config(store, settings)
    if channel is not None:
        config["channel"] = channel
    now = datetime.now(MSK)
    channels = await _candidates(store, settings, config["channel"])
    status = "✅ включены" if config["enabled"] else "⏸ выключены"
    lines = [
        "🕘 <b>Автопосты в канал</b>\n",
        f"Статус: <b>{status}</b>",
        f"Канал: <b>{escape(config['channel']) if config['channel'] else 'не выбран'}</b>",
        f"Время: <b>{config['hour']:02d}:00 МСК</b>",
        f"Что постить: {KINDS[config['kind']]}",
        f"Следующий пост: <b>{_next_label(config, now)}</b>",
    ]
    if config["last"]:
        lines.append(f"Последний пост: {escape(config['last'])}")
    lines.extend(
        [
            "",
            "<i>Бот должен быть администратором канала с правом публикации. "
            "Пост выходит раз в день и только один раз.</i>",
        ]
    )
    if not channels:
        lines.append("\n⚠️ Канал не подключён: сначала добавь его в 📢 Канал.")

    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text=("⏸ Выключить" if config["enabled"] else "▶️ Включить"),
                callback_data="adm:auto:toggle",
            )
        ]
    ]
    hour_buttons = [
        InlineKeyboardButton(
            text=("🔹 " if hour == config["hour"] else "") + f"{hour:02d}:00",
            callback_data=f"adm:auto:hour:{hour}",
        )
        for hour in HOURS
    ]
    rows.append(hour_buttons[:4])
    rows.append(hour_buttons[4:])
    rows.append(
        [
            InlineKeyboardButton(
                text=("• " if kind == config["kind"] else "") + label,
                callback_data=f"adm:auto:kind:{kind}",
            )
            for kind, label in KINDS.items()
        ]
    )
    for index, item in enumerate(channels):
        rows.append(
            [
                InlineKeyboardButton(
                    text=("📢 " if item == config["channel"] else "") + item,
                    callback_data=f"adm:auto:ch:{index}",
                )
            ]
        )
    if not channels:
        rows.append([InlineKeyboardButton(text="➕ Подключить канал", callback_data="adm:ch:add")])
    rows.append(
        [InlineKeyboardButton(text="🚀 Опубликовать сейчас", callback_data="adm:auto:now")]
    )
    rows.append([InlineKeyboardButton(text="⬅️ К каналу", callback_data="adm:ch")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _show(
    call: CallbackQuery, store: Store, settings: Settings, channel: str | None = None
) -> None:
    text, keyboard = await render_panel(store, settings, channel)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=keyboard)


@router.callback_query(F.data == "adm:auto")
async def cb_panel(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    await _show(call, store, settings)
    await call.answer()


@router.callback_query(F.data == "adm:auto:toggle")
async def cb_toggle(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    config = await get_config(store, settings)
    await store.set_setting("autopost_enabled", "0" if config["enabled"] else "1")
    await _show(call, store, settings)
    await call.answer("Выключены" if config["enabled"] else "Включены")


@router.callback_query(F.data.startswith("adm:auto:hour:"))
async def cb_hour(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    try:
        hour = int((call.data or "").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        hour = -1
    if hour not in HOURS:
        await call.answer("Не понял время", show_alert=True)
        return
    await store.set_setting("autopost_hour", str(hour))
    await _show(call, store, settings)
    await call.answer(f"{hour:02d}:00 МСК")


@router.callback_query(F.data.startswith("adm:auto:kind:"))
async def cb_kind(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    kind = (call.data or "").rsplit(":", 1)[1]
    if kind not in KINDS:
        await call.answer("Не понял тип", show_alert=True)
        return
    await store.set_setting("autopost_kind", kind)
    await _show(call, store, settings)
    await call.answer(KINDS[kind])


@router.callback_query(F.data.startswith("adm:auto:ch:"))
async def cb_channel(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    config = await get_config(store, settings)
    channels = await _candidates(store, settings, config["channel"])
    try:
        index = int((call.data or "").rsplit(":", 1)[1])
        channel = channels[index]
    except (IndexError, ValueError):
        await call.answer("Канал не найден", show_alert=True)
        return
    await store.set_setting("autopost_channel", channel)
    await _show(call, store, settings)
    await call.answer(f"Канал: {channel}")


@router.callback_query(F.data == "adm:auto:now")
async def cb_now(call: CallbackQuery, bot: Bot, store: Store, settings: Settings) -> None:
    if not await _is_staff(call.from_user.id, settings, store):
        await call.answer("Нет доступа", show_alert=True)
        return
    ok, note = await publish(bot, store, settings, force=True)
    await _show(call, store, settings)
    await call.answer(note, show_alert=not ok)