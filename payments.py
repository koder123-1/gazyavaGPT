"""Пополнение запросов за Telegram Stars (XTR): наборы, своя сумма, условия, поддержка."""

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
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import Settings
import models as model_catalog
from roles import ROLE_ADMIN, staff_ids
from runtime import Runtime, load_runtime
from store import Store

log = logging.getLogger("payments")
router = Router(name="payments")

PAYLOAD_PREFIX = "buy"
SUB_PREFIX = "sub"
MODEL_PREFIX = "model"
MIN_STARS = 1
MAX_STARS = 10_000
# Что показываем в профиле подписчику. Отвечает всё равно DeepSeek —
# подписка меняет только оформление профиля.
SUBSCRIPTION_MODELS = "GPT-6 · Claude · Gemini · Grok · Kimi"


class Purchase(StatesGroup):
    custom_stars = State()


# --------------------------------------------------------------------------- расчёты
def parse_payload(payload: str) -> tuple[int, int] | None:
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != PAYLOAD_PREFIX:
        return None
    try:
        requests, stars = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not (0 < requests <= 10_000_000 and 0 < stars <= 1_000_000):
        return None
    return requests, stars


def requests_for_stars(stars: int, runtime: Runtime) -> int:
    return max(1, stars * max(1, runtime.star_rate))


def parse_sub_payload(payload: str) -> tuple[int, int] | None:
    """payload подписки: sub:<дней>:<звёзд>."""
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != SUB_PREFIX:
        return None
    try:
        days, stars = int(parts[1]), int(parts[2])
    except ValueError:
        return None
    if not (0 < days <= 3650 and 0 < stars <= 1_000_000):
        return None
    return days, stars


def parse_model_payload(payload: str) -> tuple[str, int] | None:
    """payload модели: model:<id>:<звёзд>."""
    parts = (payload or "").split(":")
    if len(parts) != 3 or parts[0] != MODEL_PREFIX:
        return None
    model_id, raw_stars = parts[1], parts[2]
    if not model_catalog.info(model_id):
        return None
    try:
        stars = int(raw_stars)
    except ValueError:
        return None
    if stars <= 0 or stars != model_catalog.stars(model_id):
        return None
    return model_id, stars


def is_valid_offer(runtime: Runtime, requests: int, stars: int) -> bool:
    """Набор из настроек или свободная сумма по действующему курсу."""
    if (requests, stars) in runtime.star_packages:
        return True
    return (
        MIN_STARS <= stars <= MAX_STARS
        and requests == requests_for_stars(stars, runtime)
    )


# --------------------------------------------------------------------------- тексты
def render_terms(settings: Settings, runtime: Runtime) -> str:
    return (
        settings.terms_text.replace("{bot}", escape(settings.bot_name))
        .replace("{rate}", str(runtime.star_rate))
    )


def render_support(settings: Settings) -> str:
    contact = f" {escape(settings.support_contact)}" if settings.support_contact else ""
    return settings.support_text.replace("{contact}", contact)


def buy_kb(runtime: Runtime, settings: Settings) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{requests} запросов — {stars} ⭐",
                callback_data=f"pay:buy:{requests}:{stars}",
            )
        ]
        for requests, stars in runtime.star_packages
    ]
    rows.append(
        [
            InlineKeyboardButton(
                text=f"💎 Подписка на ИИ — {settings.subscription_stars} ⭐",
                callback_data="pay:sub",
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="✏️ Своё количество звёзд", callback_data="pay:custom")]
    )
    rows.append(
        [
            InlineKeyboardButton(text="📄 Условия", callback_data="pay:terms"),
            InlineKeyboardButton(text="✉️ Поддержка", callback_data="pay:support"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_buy(
    store: Store, settings: Settings, user_id: int
) -> tuple[str, InlineKeyboardMarkup]:
    runtime = await load_runtime(store, settings)
    bonus = await store.bonus_requests(user_id)
    packages = "\n".join(
        f"• <b>{requests}</b> запросов — <b>{stars}</b> ⭐"
        for requests, stars in runtime.star_packages
    )
    text = (
        "⭐ <b>Пополнение запросов</b>\n\n"
        f"Твой запас: <b>{bonus}</b> дополнительных запросов.\n\n"
        "Готовые наборы (выгоднее):\n"
        f"{packages}\n\n"
        f"Или своя сумма: <b>1 ⭐ = {runtime.star_rate} запросов</b> "
        f"(от {MIN_STARS} до {MAX_STARS} ⭐).\n\n"
        "Купленные запросы не сгорают и тратятся только после дневного лимита. "
        "Оплата проходит внутри Telegram — карта не нужна.\n\n"
        f"💎 <b>Подписка на популярные ИИ</b> — {settings.subscription_stars} ⭐ "
        f"на {settings.subscription_days} дн.\n"
        f"В профиле появится значок подписки: {SUBSCRIPTION_MODELS}.\n"
        "<i>Отвечать бот будет на DeepSeek — подписка меняет оформление профиля.</i>\n\n"
        "<i>Оплачивая, ты принимаешь условия покупки.</i>"
    )
    return text, buy_kb(runtime, settings)


async def send_stars_invoice(
    bot: Bot, chat_id: int, requests: int, stars: int, settings: Settings
) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"{requests} запросов к {settings.bot_name}",
        description=(
            f"{requests} дополнительных запросов за {stars} ⭐. "
            "Не сгорают, тратятся после дневного лимита."
        ),
        payload=f"{PAYLOAD_PREFIX}:{requests}:{stars}",
        currency="XTR",
        prices=[LabeledPrice(label=f"{requests} запросов", amount=stars)],
        provider_token="",
    )


async def send_subscription_invoice(bot: Bot, chat_id: int, settings: Settings) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"Подписка на популярные ИИ · {settings.subscription_days} дн.",
        description=(
            f"Значок подписки в профиле: {SUBSCRIPTION_MODELS}. "
            "Отвечает DeepSeek — подписка меняет только оформление профиля."
        ),
        payload=f"{SUB_PREFIX}:{settings.subscription_days}:{settings.subscription_stars}",
        currency="XTR",
        prices=[
            LabeledPrice(label="Подписка на ИИ", amount=settings.subscription_stars)
        ],
        provider_token="",
    )


async def send_model_invoice(
    bot: Bot, chat_id: int, item: model_catalog.ModelInfo, settings: Settings
) -> None:
    await bot.send_invoice(
        chat_id=chat_id,
        title=f"Модель {item.title} в {settings.bot_name}",
        description=(
            f"Разовое открытие модели {item.title} за {item.stars} ⭐. "
            "После оплаты она сразу станет активной — без подписки и без доплат за запросы."
        ),
        payload=f"{MODEL_PREFIX}:{item.id}:{item.stars}",
        currency="XTR",
        prices=[LabeledPrice(label=item.title, amount=item.stars)],
        provider_token="",
    )


# --------------------------------------------------------------------------- меню
@router.message(Command("buy"))
async def cmd_buy(message: Message, bot: Bot, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    await store.ensure_user(user.id, user.username, user.first_name)

    if not settings.payments_enabled:
        await message.reply("Пополнение сейчас отключено. Дневной лимит обновится в полночь по UTC.")
        return

    text, kb = await render_buy(store, settings, user.id)
    if message.chat.type == "private":
        await message.answer(text, reply_markup=kb)
        return
    try:
        await bot.send_message(user.id, text, reply_markup=kb)
        await message.reply("💌 Меню пополнения отправил тебе в личку.")
    except TelegramAPIError:
        await message.reply("Напиши мне в личку /buy — там покажу тарифы 🙂")


@router.callback_query(F.data == "pay:menu")
async def cb_menu(call: CallbackQuery, bot: Bot, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    text, kb = await render_buy(store, settings, call.from_user.id)
    try:
        await bot.send_message(call.from_user.id, text, reply_markup=kb)
    except TelegramAPIError:
        await call.answer("Напиши боту в личку /buy", show_alert=True)
        return
    await call.answer("Отправил в личку 💌")


@router.callback_query(F.data == "pay:back")
async def cb_back(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    text, kb = await render_buy(store, settings, call.from_user.id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(text, reply_markup=kb)
    await call.answer()


@router.callback_query(F.data == "pay:terms")
async def cb_terms(call: CallbackQuery, store: Store, settings: Settings) -> None:
    runtime = await load_runtime(store, settings)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ К покупке", callback_data="pay:back")]]
    )
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(render_terms(settings, runtime), reply_markup=kb)
    await call.answer()


@router.message(Command("terms"))
async def cmd_terms(message: Message, store: Store, settings: Settings) -> None:
    runtime = await load_runtime(store, settings)
    await message.answer(render_terms(settings, runtime))


@router.callback_query(F.data == "pay:sub")
async def cb_sub(call: CallbackQuery, bot: Bot, settings: Settings) -> None:
    if call.from_user is None:
        return
    if not settings.payments_enabled:
        await call.answer("Оплата сейчас отключена", show_alert=True)
        return
    await call.answer()
    try:
        await send_subscription_invoice(bot, call.from_user.id, settings)
    except TelegramAPIError as exc:
        log.warning("Не удалось выставить счёт на подписку %s: %s", call.from_user.id, exc)
        await call.answer("Не смог выставить счёт. Напиши мне в личку /buy", show_alert=True)


# --------------------------------------------------------------------------- наборы
@router.callback_query(F.data.startswith("pay:buy:"))
async def cb_buy(call: CallbackQuery, bot: Bot, store: Store, settings: Settings) -> None:
    if call.from_user is None or call.data is None:
        return
    if not settings.payments_enabled:
        await call.answer("Пополнение сейчас отключено", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) != 4:
        await call.answer("Неизвестный тариф", show_alert=True)
        return
    try:
        requests, stars = int(parts[2]), int(parts[3])
    except ValueError:
        await call.answer("Неизвестный тариф", show_alert=True)
        return

    runtime = await load_runtime(store, settings)
    if (requests, stars) not in runtime.star_packages:
        await call.answer("Тариф изменился — открой /buy заново", show_alert=True)
        return

    await call.answer()
    try:
        await send_stars_invoice(bot, call.from_user.id, requests, stars, settings)
    except TelegramAPIError as exc:
        log.warning("Не удалось выставить счёт %s: %s", call.from_user.id, exc)
        await call.answer("Не смог выставить счёт. Напиши мне в личку /buy", show_alert=True)


# --------------------------------------------------------------------------- своя сумма
@router.callback_query(F.data == "pay:custom")
async def cb_custom(call: CallbackQuery, store: Store, settings: Settings, state: FSMContext) -> None:
    if call.from_user is None:
        return
    if not settings.payments_enabled:
        await call.answer("Пополнение сейчас отключено", show_alert=True)
        return
    if call.message.chat.type != "private":
        await call.answer("Свою сумму удобнее выбрать в личке: /buy", show_alert=True)
        return

    runtime = await load_runtime(store, settings)
    await state.set_state(Purchase.custom_stars)
    await call.message.answer(
        "✏️ <b>Своё количество звёзд</b>\n\n"
        f"Сколько звёзд потратить? От <b>{MIN_STARS}</b> до <b>{MAX_STARS}</b>.\n"
        f"Курс: 1 ⭐ = {runtime.star_rate} запросов.\n\n"
        "Пришли число звёзд, например <code>40</code>."
    )
    await call.answer()


@router.message(Purchase.custom_stars, F.text)
async def on_custom_stars(
    message: Message, bot: Bot, store: Store, settings: Settings, state: FSMContext
) -> None:
    raw = (message.text or "").strip()
    if raw.startswith("/"):
        await state.clear()
        await message.answer("Отменено.")
        return
    if not raw.isdigit():
        await message.answer(
            f"Нужно целое число звёзд от {MIN_STARS} до {MAX_STARS}, например <code>40</code>."
        )
        return

    stars = int(raw)
    if not MIN_STARS <= stars <= MAX_STARS:
        await message.answer(
            f"Можно от {MIN_STARS} до {MAX_STARS} ⭐ за одну покупку."
        )
        return

    runtime = await load_runtime(store, settings)
    requests = requests_for_stars(stars, runtime)
    await state.clear()
    try:
        await send_stars_invoice(bot, message.chat.id, requests, stars, settings)
    except TelegramAPIError as exc:
        log.warning("Не удалось выставить счёт на %s звёзд: %s", stars, exc)
        await message.answer("Не смог выставить счёт. Попробуй ещё раз через /buy.")


@router.message(Purchase.custom_stars)
async def on_custom_non_text(message: Message) -> None:
    await message.answer("Пришли число звёзд, например <code>40</code>, или /cancel.")


# --------------------------------------------------------------------------- оплата
@router.pre_checkout_query()
async def on_pre_checkout(
    query: PreCheckoutQuery, store: Store, settings: Settings
) -> None:
    parsed = parse_payload(query.invoice_payload)
    sub = parse_sub_payload(query.invoice_payload)
    model = parse_model_payload(query.invoice_payload)
    valid = False
    if model and query.currency == "XTR":
        _, stars = model
        valid = query.total_amount == stars
    elif sub and query.currency == "XTR":
        days, stars = sub
        valid = (
            days == settings.subscription_days
            and stars == settings.subscription_stars
            and query.total_amount == stars
        )
    elif parsed and query.currency == "XTR":
        runtime = await load_runtime(store, settings)
        requests, stars = parsed
        valid = is_valid_offer(runtime, requests, stars) and query.total_amount == stars
    await query.answer(
        ok=valid,
        error_message=None if valid else "Тариф изменился. Открой /buy и выбери пакет заново.",
    )


@router.message(F.successful_payment)
async def on_paid(message: Message, bot: Bot, store: Store, settings: Settings) -> None:
    user = message.from_user
    payment = message.successful_payment
    if user is None or payment is None:
        return

    model = parse_model_payload(payment.invoice_payload)
    if model:
        model_id, _ = model
        await store.ensure_user(user.id, user.username, user.first_name)
        credited = await store.record_payment(
            user.id,
            0,
            payment.total_amount,
            payment.telegram_payment_charge_id,
            kind="model",
            model=model_id,
        )
        title = model_catalog.title(model_id)
        if credited:
            await store.grant_model(user.id, model_id)
            await store.set_model(user.id, model_id)
            log.info(
                "Оплата Stars: %s открыл модель %s за %s звёзд",
                user.id,
                model_id,
                payment.total_amount,
            )
            await message.answer(
                f"🧠 <b>Модель открыта!</b>\n\n"
                f"Теперь отвечает: <b>{escape(title)}</b>\n"
                f"Оплата разовая — модель останется у тебя.\n\n"
                "Сменить модель — /model. Вопросы по оплате — /paysupport."
            )
            await notify_admins(
                bot,
                f"🧠 <b>Покупка модели</b>\n"
                f"Пользователь: {escape(user.full_name)} (<code>{user.id}</code>)\n"
                f"Модель: {escape(title)} за {payment.total_amount} ⭐",
                store,
                settings,
            )
        else:
            await message.answer("✅ Эта оплата уже учтена. Модель уже открыта — /model.")
        return

    sub = parse_sub_payload(payment.invoice_payload)
    if sub:
        days, _ = sub
        await store.ensure_user(user.id, user.username, user.first_name)
        credited = await store.record_payment(
            user.id,
            days,
            payment.total_amount,
            payment.telegram_payment_charge_id,
            kind="sub",
        )
        if credited:
            until = await store.activate_subscription(user.id, days)
            log.info(
                "Оплата Stars: %s купил подписку на %s дней за %s звёзд",
                user.id,
                days,
                payment.total_amount,
            )
            await message.answer(
                f"💎 <b>Подписка активна!</b>\n\n"
                f"Действует до: <b>{until:%d.%m.%Y}</b>\n"
                f"В профиле: {SUBSCRIPTION_MODELS}\n"
                "Отвечает: DeepSeek.\n\n"
                "Посмотреть профиль — /me, продлить — /buy."
            )
            await notify_admins(
                bot,
                f"💎 <b>Подписка</b>\n"
                f"Пользователь: {escape(user.full_name)} (<code>{user.id}</code>)\n"
                f"Срок: {days} дн. за {payment.total_amount} ⭐",
                store,
                settings,
            )
        else:
            await message.answer("✅ Эта оплата уже учтена. Подписка продлена не была.")
        return

    parsed = parse_payload(payment.invoice_payload)
    if not parsed:
        log.warning("Оплата с неизвестным payload: %r", payment.invoice_payload)
        await message.answer("Оплата прошла, но тариф не распознан. Напиши администратору через /paysupport.")
        return

    requests, _ = parsed
    stars = payment.total_amount
    await store.ensure_user(user.id, user.username, user.first_name)
    credited = await store.record_payment(
        user.id, requests, stars, payment.telegram_payment_charge_id
    )
    balance = await store.bonus_requests(user.id)

    if credited:
        log.info("Оплата Stars: %s купил %s запросов за %s звёзд", user.id, requests, stars)
        await message.answer(
            f"✅ <b>Оплата получена!</b>\n\n"
            f"Начислено: <b>+{requests}</b> запросов\n"
            f"Твой запас: <b>{balance}</b>\n\n"
            "Спасибо за поддержку! Запросы тратятся после дневного лимита.\n"
            "Вопросы по оплате — /paysupport."
        )
        await notify_admins(
            bot,
            f"💰 <b>Покупка</b>\n"
            f"Пользователь: {escape(user.full_name)} (<code>{user.id}</code>)\n"
            f"Пакет: {requests} запросов за {stars} ⭐",
            store,
            settings,
        )
    else:
        await message.answer(
            f"✅ Эта оплата уже учтена. Твой запас: <b>{balance}</b> запросов."
        )


async def notify_admins(bot: Bot, text: str, store: Store, settings: Settings) -> None:
    for admin_id in await staff_ids(store, settings, min_role=ROLE_ADMIN):
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(admin_id, text)