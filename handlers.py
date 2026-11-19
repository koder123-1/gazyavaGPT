"""Хендлеры: диалог с ИИ, квоты, кнопки под ответом, меню, режим проверки."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import io
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape, unescape
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    User,
    WebAppInfo,
)

import files
import debugmode
import growth
import media
import models as model_catalog
from ai import AIClient, AIError
from config import Settings
from formatting import humanize_answer, split_big_code, to_telegram_html
from guards import JAILBREAK_REFUSAL, looks_like_jailbreak
from i18n import (
    LANGS,
    LANG_FLAGS,
    LANG_NAMES,
    detect_lang,
    normalize_lang,
    t,
)
from images import (
    ImageClient,
    ImageError,
    ImageNoCredits,
    ImageRateLimited,
    ImageUnsupported,
)
from payments import send_model_invoice
from roles import has_admin_access, is_staff, resolve_role, role_title
from runtime import Runtime, load_runtime
from store import Store
from styles import (
    STYLE_KEYS,
    normalize_style,
    style_hint,
)
from subjects import detect_subject, subject_hint, subject_title

log = logging.getLogger("handlers")
router = Router()

MAX_INPUT_CHARS = 6000
CHUNK = 3000
# Telegram: 4096 символов на сообщение. Оставляем запас под теги и экранирование.
HTML_LIMIT = 3800
IMAGE_MAX_BYTES = 8 * 1024 * 1024

# Язык блока кода → расширение файла.
CODE_EXT = {
    "python": "py",
    "py": "py",
    "html": "html",
    "htm": "html",
    "css": "css",
    "js": "js",
    "javascript": "js",
    "typescript": "ts",
    "ts": "ts",
    "json": "json",
    "sql": "sql",
    "bash": "sh",
    "sh": "sh",
    "shell": "sh",
}

IMAGE_PROMPT = (
    "Посмотри на изображение. Если это учебное задание (задача, пример, упражнение) — "
    "реши его по шагам и объясни решение. Если это текст или конспект — кратко перескажи "
    "суть и помоги с ним. Если это таблица, график или схема — опиши, что на них видно."
)

CHECK_INSTRUCTION = (
    "Проверь решение пользователя ниже. Не решай задачу заново: найди, где ошибка, "
    "объясни, почему это ошибка, и покажи правильный шаг. Если решение верное — "
    "подтверди и скажи, что можно улучшить. Кратко и по шагам."
)

MODIFIERS = {
    "simple": "Объясни это же проще: короче, без сложных формулировок, с бытовым примером.",
    "deep": "Объясни это подробнее: распиши каждый шаг и добавь пример.",
    "practice": "Дай одну похожую задачу для тренировки, без решения и подсказок. "
    "В конце попроси прислать ответ.",
}

class Check(StatesGroup):
    awaiting = State()


class Imagine(StatesGroup):
    awaiting = State()


class Promo(StatesGroup):
    awaiting = State()


# --------------------------------------------------------------------------- утилиты
async def is_admin(user_id: int, settings: Settings, store: Store) -> bool:
    return has_admin_access(await resolve_role(user_id, settings, store))


def strip_bot_mention(text: str, username: str | None) -> str:
    if not username:
        return text.strip()
    return re.sub(rf"@{re.escape(username)}\b", "", text, flags=re.IGNORECASE).strip()


async def user_lang(store: Store, settings: Settings, user_id: int) -> str:
    stored = await store.get_lang(user_id)
    return normalize_lang(stored or settings.default_lang)


# --------------------------------------------------------------------------- выбор модели
def model_title(model_id: str | None) -> str:
    return model_catalog.title(model_id)


def available_models(settings: Settings, runtime: Runtime) -> list[str]:
    """Все модели каталога, которые вообще можно выбрать."""
    return model_catalog.ids()


async def owned_models(
    store: Store, settings: Settings, user_id: int, *, staff: bool = False
) -> set[str]:
    """Какие модели пользователь уже открыл: бесплатные, купленные и выданные админом."""
    owned = {item.id for item in model_catalog.CATALOG if item.stars <= 0}
    owned.update(await store.list_model_access(user_id))
    if staff:
        owned.update(model_catalog.ids())
    return owned


async def user_model(
    store: Store, settings: Settings, runtime: Runtime, user_id: int
) -> str:
    chosen = await store.get_model(user_id)
    if chosen and model_catalog.info(chosen):
        if model_catalog.is_free(chosen) or await store.has_model_access(user_id, chosen):
            return chosen
        # Доступ отозвали (например, вернули звёзды) — возвращаем модель по умолчанию.
        await store.set_model(user_id, None)
    return runtime.model or model_catalog.DEFAULT_MODEL


def model_price(item: model_catalog.ModelInfo, lang: str) -> str:
    if item.stars <= 0:
        return t(lang, "model.free")
    return t(lang, "model.price", stars=item.stars)


def model_kb(
    models: list[str] | None, current: str, lang: str, owned: set[str] | None = None
) -> InlineKeyboardMarkup:
    owned = owned or {m.id for m in model_catalog.CATALOG if m.stars <= 0}
    rows: list[list[InlineKeyboardButton]] = []
    for item in model_catalog.CATALOG:
        mark = "✅ " if item.id == current else ""
        price = model_price(item, lang)
        if item.stars > 0 and item.id not in owned:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"🔒 {item.title} · {price}",
                        callback_data=f"mdl:buy:{item.id}",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{mark}{item.title} · {price}",
                        callback_data=f"mdl:set:{item.id}",
                    )
                ]
            )
    rows.append(
        [InlineKeyboardButton(text=t(lang, "model.auto"), callback_data="mdl:auto")]
    )
    rows.append(
        [InlineKeyboardButton(text=t(lang, "menu.home"), callback_data="menu:home")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_model_menu(
    message: Message, store: Store, settings: Settings, lang: str, user_id: int
) -> None:
    runtime = await load_runtime(store, settings)
    current = await user_model(store, settings, runtime, user_id)
    role = await resolve_role(user_id, settings, store)
    owned = await owned_models(store, settings, user_id, staff=has_admin_access(role))
    await message.answer(
        t(lang, "model.title", current=escape(model_title(current))),
        reply_markup=model_kb(None, current, lang, owned),
    )


MENU_KEYS = (
    "menu.model",
    "menu.styles",
    "menu.check",
    "menu.imagine",
    "menu.buy",
    "menu.donate",
    "menu.support",
    "menu.tickets",
    "menu.files",
    "menu.bonus",
    "menu.promo",
    "menu.invite",
    "menu.lang",
    "menu.help",
    "menu.reset",
    "menu.terms",
    "menu.admin",
)


def styles_kb(current: str, lang: str) -> InlineKeyboardMarkup:
    """Выбор стиля: текущий помечен галочкой."""
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if key == current else "") + t(lang, f"styles.{key}"),
                callback_data=f"sty:{key}",
            )
        ]
        for key in STYLE_KEYS
    ]
    rows.append([InlineKeyboardButton(text=t(lang, "menu.home"), callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def render_styles(
    store: Store, user_id: int, lang: str
) -> tuple[str, InlineKeyboardMarkup]:
    current = normalize_style(await store.get_style(user_id))
    lines = [
        t(lang, "styles.title"),
        "",
        t(lang, "styles.current", value=t(lang, f"styles.{current}")),
        "",
    ]
    for key in STYLE_KEYS:
        mark = "✅ " if key == current else ""
        lines.append(
            f"{mark}<b>{t(lang, f'styles.{key}')}</b> — {t(lang, f'styles.{key}.desc')}"
        )
    lines += ["", t(lang, "styles.hint")]
    return "\n".join(lines), styles_kb(current, lang)


async def send_styles(
    message: Message, store: Store, settings: Settings, lang: str, user_id: int
) -> None:
    text, kb = await render_styles(store, user_id, lang)
    await message.answer(text, reply_markup=kb)


@router.message(Command("style", "styles"))
async def cmd_style(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    lang = await user_lang(store, settings, user.id)
    await send_styles(message, store, settings, lang, user.id)


@router.callback_query(F.data.startswith("sty:"))
async def cb_style(call: CallbackQuery, store: Store, settings: Settings) -> None:
    user = call.from_user
    if user is None or call.data is None:
        return
    lang = await user_lang(store, settings, user.id)
    action = call.data.split(":", 1)[1]

    if action != "menu":
        if action not in STYLE_KEYS:
            await call.answer(t(lang, "fb.stale"), show_alert=True)
            return
        await store.set_style(user.id, None if action == "auto" else action)

    text, kb = await render_styles(store, user.id, lang)
    if isinstance(call.message, Message):
        with contextlib.suppress(TelegramAPIError):
            await call.message.edit_text(text, reply_markup=kb)
    if action == "menu":
        await call.answer()
    else:
        await call.answer(t(lang, "styles.saved", value=t(lang, f"styles.{action}")))


def menu_label_map() -> dict[str, str]:
    """Подписи кнопок главного меню → ключ действия."""
    return {t(lang, key): key for lang in LANGS for key in MENU_KEYS}


def _button_row(lang: str, *keys: str) -> list[KeyboardButton]:
    return [KeyboardButton(text=t(lang, key)) for key in keys]


def main_menu_kb(
    lang: str, *, staff: bool = False, payments: bool = True, support: bool = False
) -> ReplyKeyboardMarkup:
    """Постоянная клавиатура: почти всё меню под рукой, команды помнить не надо."""
    rows = [
        _button_row(lang, "menu.model", "menu.styles"),
        _button_row(lang, "menu.check", "menu.imagine"),
    ]
    if payments:
        rows.append(_button_row(lang, "menu.buy", "menu.support"))
    else:
        rows.append(_button_row(lang, "menu.support"))
    if support:
        rows.append(_button_row(lang, "menu.donate"))
    rows.append(_button_row(lang, "menu.tickets", "menu.files"))
    rows.append(_button_row(lang, "menu.promo", "menu.bonus", "menu.invite"))
    rows.append(_button_row(lang, "menu.lang", "menu.help"))
    if payments:
        rows.append(_button_row(lang, "menu.terms", "menu.reset"))
    else:
        rows.append(_button_row(lang, "menu.reset"))
    if staff:
        rows.append(_button_row(lang, "menu.admin"))
    return ReplyKeyboardMarkup(
        keyboard=rows, resize_keyboard=True, is_persistent=True
    )


def menu_inline(
    lang: str, *, staff: bool = False, payments: bool = True, support: bool = False
) -> InlineKeyboardMarkup:
    """Меню кнопками — компактная копия постоянной клавиатуры."""
    rows = [
        [
            InlineKeyboardButton(text=t(lang, "menu.model"), callback_data="mdl:menu"),
            InlineKeyboardButton(text=t(lang, "menu.styles"), callback_data="sty:menu"),
        ],
        [
            InlineKeyboardButton(text=t(lang, "menu.check"), callback_data="menu:act:check"),
            InlineKeyboardButton(text=t(lang, "menu.imagine"), callback_data="menu:act:imagine"),
        ],
    ]
    if payments:
        rows.append(
            [
                InlineKeyboardButton(text=t(lang, "menu.buy"), callback_data="pay:menu"),
                InlineKeyboardButton(text=t(lang, "menu.support"), callback_data="tick:menu"),
            ]
        )
    else:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "menu.support"), callback_data="tick:menu")]
        )
    if support:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "menu.donate"), callback_data="menu:donate"
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text=t(lang, "menu.tickets"), callback_data="menu:act:tickets"
            ),
            InlineKeyboardButton(text=t(lang, "menu.files"), callback_data="menu:act:files"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text=t(lang, "menu.promo"), callback_data="menu:act:promo"),
            InlineKeyboardButton(text=t(lang, "menu.bonus"), callback_data="menu:act:bonus"),
            InlineKeyboardButton(text=t(lang, "menu.invite"), callback_data="menu:act:invite"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text=t(lang, "menu.lang"), callback_data="lang:menu"),
            InlineKeyboardButton(text=t(lang, "menu.help"), callback_data="menu:act:help"),
        ]
    )
    if payments:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "menu.terms"), callback_data="menu:act:terms"
                ),
                InlineKeyboardButton(
                    text=t(lang, "menu.reset"), callback_data="menu:act:reset"
                ),
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "menu.reset"), callback_data="menu:act:reset"
                )
            ]
        )
    if staff:
        rows.append(
            [InlineKeyboardButton(text=t(lang, "menu.admin"), callback_data="menu:act:admin")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def donate_view(settings: Settings, lang: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Текст с адресом для доната GRAM и кнопка запуска Mini App."""
    text = t(lang, "donate.text", wallet=escape(settings.support_wallet))
    url = ""
    if settings.use_webhook:
        with contextlib.suppress(Exception):
            from miniapp import webapp_url

            url = webapp_url(settings)
    keyboard = None
    if url:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "donate.open"), web_app=WebAppInfo(url=url)
                    )
                ]
            ]
        )
    return text, keyboard


def language_kb(current: str | None = None) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for code in LANGS:
        mark = "✅ " if code == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{mark}{LANG_FLAGS[code]} {LANG_NAMES[code]}",
                callback_data=f"lg:{code}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _alias_patterns(settings: Settings) -> list[re.Pattern[str]]:
    patterns = []
    for alias in settings.aliases:
        alias = alias.strip()
        if not alias:
            continue
        patterns.append(re.compile(rf"(?<![\w@]){re.escape(alias)}(?![\w])", re.IGNORECASE))
    return patterns


async def addressed_text(message: Message, bot: Bot, settings: Settings) -> str | None:
    """Текст, если к боту обратились. В личке — всегда, в группе — реплай,
    @username, «газява / газик / газировка» и другие прозвища из настроек."""
    text = (message.text or message.caption or "").strip()
    if message.chat.type == "private":
        return text

    replied = message.reply_to_message
    if replied and replied.from_user and replied.from_user.id == bot.id:
        return text

    me = await bot.me()
    stripped = text
    hit = False
    if me.username:
        pattern = re.compile(rf"@{re.escape(me.username)}\b", re.IGNORECASE)
        if pattern.search(stripped):
            hit = True
            stripped = pattern.sub("", stripped)
    for pattern in _alias_patterns(settings):
        if pattern.search(stripped):
            hit = True
            stripped = pattern.sub("", stripped)
    if not hit:
        return None
    cleaned = re.sub(r"\s{2,}", " ", stripped).strip()
    # После прозвища часто остаётся запятая: «газик, реши…» -> «реши…».
    return re.sub(r"^[\s,.;:!?—–-]+", "", cleaned).strip()


def split_text(text: str, limit: int = CHUNK) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    buffer = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if buffer:
                chunks.append(buffer)
                buffer = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(buffer) + len(line) > limit:
            chunks.append(buffer)
            buffer = ""
        buffer += line
    if buffer.strip():
        chunks.append(buffer)
    return [chunk for chunk in chunks if chunk.strip()]


def readable_answer(text: str, *, code: bool = False) -> str:
    """Приводит ответ модели к читаемому тексту; пустой результат не пропускает."""
    cleaned = humanize_answer(text, code=code).strip()
    return cleaned or (text or "").strip()


@asynccontextmanager
async def keep_typing(bot: Bot, chat_id: int) -> AsyncIterator[None]:
    stop = asyncio.Event()

    async def worker() -> None:
        while not stop.is_set():
            with contextlib.suppress(Exception):
                await bot.send_chat_action(chat_id, ChatAction.TYPING)
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=4.5)

    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


def _tg_len(text: str) -> int:
    """Telegram считает длину в UTF-16: эмодзи 📌 весит 2, а не 1."""
    return len(text.encode("utf-16-le")) // 2


def html_parts(
    chunk: str, limit: int = HTML_LIMIT, *, code: bool = False
) -> list[tuple[str, str]]:
    """(html, plain) куски: HTML не должен вылезти за лимит Telegram.

    Экранирование (< -> &lt;) и теги удлиняют текст, поэтому кусок, который
    в plain-виде влезал, в HTML может не влезть. Тогда дробим ещё мельче.
    """
    html = to_telegram_html(chunk, code=code)
    if _tg_len(html) <= limit:
        return [(html, chunk)]
    # Пропорционально ужимаем plain-кусок под HTML-лимит.
    smaller = max(100, len(chunk) * limit // max(1, _tg_len(html)) - 1)
    pieces = split_text(chunk, max(100, smaller))
    if len(pieces) <= 1:
        pieces = [chunk[i : i + max(100, smaller)] for i in range(0, len(chunk), max(100, smaller))]
    result: list[tuple[str, str]] = []
    for piece in pieces:
        result.extend(html_parts(piece, limit, code=code))
    return result


async def send_answer(
    message: Message,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
    *,
    code: bool = False,
) -> None:
    """Отправляет решение HTML-блоками; при ошибке разметки — обычным текстом."""
    parts: list[tuple[str, str]] = []
    for chunk in split_text(text):
        parts.extend(html_parts(chunk, code=code))
    for index, (html, plain) in enumerate(parts):
        markup = keyboard if index == len(parts) - 1 else None
        try:
            await message.reply(html, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest:
            # Битая разметка — шлём обычным текстом. Если не вышло и это,
            # значит исходное сообщение удалили: отвечаем без reply.
            try:
                await message.reply(plain, parse_mode=None, reply_markup=markup)
            except TelegramBadRequest:
                with contextlib.suppress(TelegramAPIError):
                    await message.answer(plain, parse_mode=None, reply_markup=markup)


def cabinet_webapp_kb(settings: Settings, lang: str, exchange_id: int = 0) -> InlineKeyboardMarkup | None:
    """Кнопка «📱 Открыть в приложении» под ответом ИИ — открывает Mini App с этим ответом."""
    if not settings.use_webhook:
        return None
    url = settings.base_url.rstrip("/") + "/app"
    if exchange_id:
        url += "?answer=" + str(exchange_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "app.after"),
                    web_app=WebAppInfo(url=url),
                )
            ]
        ]
    )


def answer_kb(
    exchange_id: int, voted: str | None = None, lang: str = "ru"
) -> InlineKeyboardMarkup:
    if voted == "up":
        first = [
            InlineKeyboardButton(text=t(lang, "btn.thanks_up"), callback_data="fb:noop:0")
        ]
    elif voted == "down":
        first = [
            InlineKeyboardButton(text=t(lang, "btn.thanks_down"), callback_data="fb:noop:0")
        ]
    else:
        first = [
            InlineKeyboardButton(text="👍", callback_data=f"fb:up:{exchange_id}"),
            InlineKeyboardButton(text="👎", callback_data=f"fb:down:{exchange_id}"),
        ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            first,
            [
                InlineKeyboardButton(
                    text=t(lang, "btn.simple"), callback_data=f"fb:simple:{exchange_id}"
                ),
                InlineKeyboardButton(
                    text=t(lang, "btn.deep"), callback_data=f"fb:deep:{exchange_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "btn.check"), callback_data=f"fb:check:{exchange_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=t(lang, "btn.practice"), callback_data=f"fb:practice:{exchange_id}"
                )
            ],
        ]
    )


async def load_image(
    message: Message, bot: Bot, lang: str = "ru"
) -> tuple[bytes | None, str, str | None]:
    """Возвращает (данные, mime, текст ошибки)."""
    mime = "image/jpeg"
    file = None
    if message.photo:
        file = message.photo[-1]
    elif message.document is not None:
        document = message.document
        mime = (document.mime_type or "").lower()
        if not mime.startswith("image/") and not files.is_image_document(
            document.file_name, document.mime_type
        ):
            return None, mime, t(lang, "image.not_image")
        if (document.file_size or 0) > IMAGE_MAX_BYTES:
            return None, mime, t(lang, "image.too_big")
        file = document

    if file is None:
        return None, mime, t(lang, "image.no_image")

    if (file.file_size or 0) > IMAGE_MAX_BYTES:
        return None, mime, t(lang, "image.too_big")

    buffer = io.BytesIO()
    try:
        await bot.download(file, destination=buffer)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось скачать изображение из Telegram")
        return None, mime, t(lang, "image.download_failed")

    data = buffer.getvalue()
    if not data:
        return None, mime, t(lang, "image.empty_file")
    return data, mime, None


# --------------------------------------------------------------------------- картинки
DRAW_RE = re.compile(
    r"(?i)^\s*(?:"
    r"нарисуй(?:\s+мне)?|нарисуйте|"
    r"(?:создай|создайте|сделай|сделайте|создать|сделать|"
    r"хочу(?:\s+(?:создать|сделать|сгенерировать))?|"
    r"можешь\s+(?:создать|сделать|сгенерировать))"
    r"(?:\s+(?:мне|пожалуйста))?\s+(?:а\s+)?"
    r"(?:фото(?:графию)?|фотку|картинк\w*|изображени\w*|рисунок|портрет|"
    r"picture|image|photo)"
    r"|сгенерируй(?:те)?(?:\s+(?:мне|пожалуйста))?"
    r"(?:\s+(?:фото(?:графию)?|фотку|картинк\w*|изображени\w*|рисунок|портрет))?"
    r"|draw|generate(?:\s+an?\s+(?:image|picture|photo))?|imagine|paint)"
    r"\b[:,]?\s*"
)
EDIT_RE = re.compile(
    r"(?i)\b(измени|изменить|изменение|перерисуй|переделай|фотошоп\w*|отредактир\w*|"
    r"замени|убери|добавь|change|edit|redraw|replace|remove|add)\b"
)


def image_filename(data: bytes) -> str:
    """Telegram лучше показывает фото, если расширение совпадает с форматом."""
    if data.startswith(b"\xff\xd8"):
        return "gazyava.jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "gazyava.webp"
    return "gazyava.png"


# Промпты последних картинок: кнопка «Ещё вариант» хранит только токен,
# а не весь текст в callback_data (у неё лимит 64 байта).
_image_prompts: dict[str, str] = {}
_IMAGE_MEMORY = 500


def remember_prompt(prompt: str) -> str:
    token = uuid.uuid4().hex[:12]
    _image_prompts[token] = prompt
    while len(_image_prompts) > _IMAGE_MEMORY:
        _image_prompts.pop(next(iter(_image_prompts)), None)
    return token


def image_more_kb(prompt: str, lang: str) -> InlineKeyboardMarkup:
    token = remember_prompt(prompt)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "img.more"), callback_data=f"img:more:{token}"
                )
            ]
        ]
    )


async def send_generated(
    message: Message,
    images: ImageClient,
    settings: Settings,
    lang: str,
    prompt: str,
    *,
    store: Store | None = None,
    actor: User | None = None,
    source: bytes | None = None,
    mime: str = "image/png",
) -> None:
    """Генерирует или редактирует картинку и отправляет её в чат."""
    prompt = prompt.strip()
    if not prompt:
        await message.reply(t(lang, "img.need_prompt"))
        return
    if not images.configured:
        await message.reply(t(lang, "img.not_configured"))
        return

    user = actor or message.from_user
    runtime = await load_runtime(store, settings) if store else None
    limit = runtime.image_daily_limit if runtime else 0
    spend: str | None = None
    charged = False
    if store is not None and user is not None:
        await store.ensure_user(user.id, user.username, user.first_name)
        admin = await is_admin(user.id, settings, store)
        if not admin:
            # Резерв до генерации: два одновременных запроса не получат
            # бесплатную картинку по одному и тому же остатку лимита.
            spend = await store.spend_image(user.id, limit)
            if spend is None:
                await message.reply(
                    t(lang, "img.quota_exhausted", limit=limit),
                    reply_markup=image_more_kb(prompt, lang),
                )
                return
            charged = True

    status = await message.reply(t(lang, "img.generating"))
    markup = image_more_kb(prompt, lang) if source is None else None
    delivered = False
    try:
        if source is not None:
            data = await images.edit(source, mime, prompt)
        else:
            data = await images.generate(prompt)
        if not data:
            raise ImageError("empty")
        await message.reply_photo(
            photo=BufferedInputFile(data, filename=image_filename(data)),
            caption=t(lang, "img.done", prompt=escape(prompt[:500])),
            parse_mode="HTML",
            reply_markup=markup,
        )
        delivered = True
    except ImageUnsupported:
        await message.reply(t(lang, "img.edit_unsupported"))
    except ImageNoCredits:
        await message.reply(t(lang, "img.no_credits"), reply_markup=markup)
    except ImageRateLimited as exc:
        await message.reply(
            t(lang, "img.rate_limited", seconds=exc.seconds), reply_markup=markup
        )
    except ImageError as exc:
        log.warning("Не удалось получить картинку: %s", exc)
        await message.reply(t(lang, "img.failed"), reply_markup=markup)
    except Exception:  # noqa: BLE001
        log.exception("Ошибка генерации картинки")
        await message.reply(t(lang, "img.failed"), reply_markup=markup)
    finally:
        if charged and not delivered and spend and user is not None and store is not None:
            with contextlib.suppress(Exception):
                await store.refund_image(user.id, spend)
        with contextlib.suppress(Exception):
            await status.delete()


@router.message(Command("imagine", "draw", "art"))
async def cmd_imagine(
    message: Message,
    store: Store,
    settings: Settings,
    images: ImageClient,
) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    parts = (message.text or "").split(maxsplit=1)
    prompt = parts[1].strip() if len(parts) > 1 else ""
    await send_generated(message, images, settings, lang, prompt, store=store)


@router.message(
    Imagine.awaiting,
    F.text,
    ~F.text.startswith("/"),
    ~F.text.in_(set(menu_label_map())),
)
async def on_imagine_prompt(
    message: Message,
    store: Store,
    settings: Settings,
    images: ImageClient,
    state: FSMContext,
) -> None:
    """Кнопка «🖌 Картинка»: следующее сообщение — описание картинки."""
    await state.clear()
    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang
    await send_generated(
        message, images, settings, lang, (message.text or "").strip(), store=store
    )


@router.message(Command("edit"))
async def cmd_edit(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    await message.reply(t(lang, "img.edit_hint"))


@router.callback_query(F.data.startswith("img:more:"))
async def cb_image_more(
    call: CallbackQuery, store: Store, settings: Settings, images: ImageClient
) -> None:
    token = call.data.rsplit(":", 1)[1]
    prompt = _image_prompts.get(token)
    lang = await user_lang(store, settings, call.from_user.id)
    if not prompt:
        await call.answer(t(lang, "img.old_request"), show_alert=True)
        return
    await call.answer(t(lang, "img.more_generating"))
    if call.message is None:
        return
    await send_generated(
        call.message, images, settings, lang, prompt, store=store, actor=call.from_user
    )


# --------------------------------------------------------------------------- ядро
async def answer_with_ai(
    message: Message,
    *,
    bot: Bot,
    store: Store,
    settings: Settings,
    ai: AIClient,
    question: str,
    image: bytes | None = None,
    image_mime: str = "image/jpeg",
    kind: str = "answer",
    instruction: str | None = None,
    max_chars: int = MAX_INPUT_CHARS,
    use_history: bool = True,
    deliver: bool = True,
    store_question: str | None = None,
    task_lang: str | None = None,
) -> str | None:
    """Ответ ИИ. При deliver=False ответ не отправляется, а возвращается."""
    question = question.strip()
    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else normalize_lang(
        settings.default_lang
    )

    if not question:
        await message.reply(t(lang, "err.empty_question"))
        return

    if user is None:
        await message.reply(t(lang, "err.no_user"))
        return

    await store.ensure_user(user.id, user.username, user.first_name)
    admin = await is_admin(user.id, settings, store)

    if not admin and await store.is_banned(user.id):
        await message.reply(t(lang, "err.banned"))
        return

    if looks_like_jailbreak(question):
        log.info("Jailbreak-паттерн от %s: %r", user.id, question[:120])
        await message.reply(JAILBREAK_REFUSAL)
        return

    runtime: Runtime = await load_runtime(store, settings)

    if not admin and runtime.daily_limit > 0:
        left = await store.remaining(user.id, runtime.daily_limit)
        if left <= 0:
            kb = None
            if settings.payments_enabled:
                kb = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=t(lang, "btn.buy"), callback_data="pay:menu"
                            )
                        ]
                    ]
                )
            text = t(lang, "limit.exhausted", limit=runtime.daily_limit)
            if settings.payments_enabled:
                text += t(lang, "limit.buy_hint")
            await message.reply(text, reply_markup=kb)
            return

    if len(question) > max_chars:
        question = question[:max_chars]
        if max_chars == MAX_INPUT_CHARS:
            await message.reply(t(lang, "err.truncated", limit=MAX_INPUT_CHARS))

    payload_text = f"{instruction}\n\n---\n{question}" if instruction else question

    # «Сделай PDF с планом», «создай .py файл» — просим ИИ контент и отдаём файлом.
    out_fmt = (
        files.detect_output_format(question)
        if deliver
        and (
            files.wants_new_file(question)
            or files.is_empty_file_request(question)
        )
        else None
    )

    # «Сделай пустой файл html» — не тратим ИИ: отдаём ровно пустой файл
    # с коротким именем, а не страницу-заготовку с именем «gazyavaGPT-код».
    if out_fmt and deliver and files.is_empty_file_request(question):
        await send_file(
            message,
            "",
            out_fmt,
            lang,
            name=files.suggest_filename(question, out_fmt),
            empty=True,
        )
        return ""

    # Роутер предметов: смотрит на задание и подмешивает правила нужного предмета.
    # В кодерском стиле предметный блок не нужен: там свои правила оформления.
    style_key = normalize_style(await store.get_style(user.id))
    style_note = style_hint(style_key)
    subject_key = detect_subject(payload_text, has_image=image is not None)
    subject_note = None if style_key == "code" else subject_hint(subject_key)
    if subject_note:
        log.info("Предмет задания для %s: %s", user.id, subject_title(subject_key))

    if out_fmt:
        if out_fmt in {"py", "html", "css", "js"}:
            payload_text += (
                f"\n\n[Верни только код для файла .{out_fmt} в одном блоке "
                "без пояснений и без фраз «вот файл».]"
            )
        else:
            payload_text += (
                "\n\n[Верни готовое содержимое документа: заголовки, списки и шаги. "
                "Без вступлений и без упоминания файлов.]"
            )

    history = []
    if use_history and runtime.max_context > 0:
        history = await store.history(user.id, runtime.max_context)

    if out_fmt and files.is_pure_file_request(question):
        last = next(
            (item for item in reversed(history) if item.get("role") == "assistant"),
            None,
        )
        if last and (last.get("content") or "").strip():
            # Пользователь просит только переоформить прошлый ответ — не тратим ИИ.
            await send_file(
                message,
                last["content"],
                out_fmt,
                lang,
                name=files.suggest_filename(question, out_fmt),
            )
            return last["content"]

    chosen_model = await user_model(store, settings, runtime, user.id)

    # Резервируем запрос до обращения к ИИ: два параллельных сообщения не должны
    # оба пройти по последнему бесплатному лимиту и по одному бонусу.
    #
    # Считаем расход всегда — иначе у админов и владельца статистика остаётся
    # пустой («Сколько запросов» = 0), хотя они пользуются ботом. Лимит при этом
    # действует только на обычных пользователей: `daily_limit=0` в `try_consume`
    # означает «записать расход, но не ограничивать».
    limit_for_user = 0 if admin else runtime.daily_limit
    reserved: str | None = await store.try_consume(user.id, limit_for_user)
    if reserved is None:
        kb = None
        if settings.payments_enabled:
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=t(lang, "btn.buy"), callback_data="pay:menu"
                        )
                    ]
                ]
            )
        text = t(lang, "limit.exhausted", limit=runtime.daily_limit)
        if settings.payments_enabled:
            text += t(lang, "limit.buy_hint")
        await message.reply(text, reply_markup=kb)
        return

    # «Режим отладки»: заскриптованный спектакль с внутренними шагами.
    # Показываем только при реальной отправке ответа, не для служебных вызовов.
    show = (
        await debugmode.begin(
            message,
            store=store,
            user_id=user.id,
            lang=lang,
            system_prompt=runtime.system_prompt,
            subject=subject_title(subject_key),
            photo=image is not None,
        )
        if deliver
        else None
    )

    try:
        async with keep_typing(bot, message.chat.id):
            answer = await ai.reply(
                history,
                payload_text,
                model=chosen_model,
                system_prompt=runtime.system_prompt,
                image=image,
                image_mime=image_mime,
                vision_model=runtime.vision_model,
                subject_note=subject_note,
                style_note=style_note,
                lang=lang,
                task_lang=task_lang or detect_lang(question),
            )
    except AIError as exc:
        if show:
            await show.finish(ok=False)
        if reserved:
            await store.refund_consume(user.id, reserved)
        await message.reply(t(lang, "err.ai", message=escape(str(exc))))
        return
    except Exception:  # noqa: BLE001
        if show:
            await show.finish(ok=False)
        if reserved:
            await store.refund_consume(user.id, reserved)
        log.exception("Неожиданная ошибка при запросе к ИИ")
        await message.reply(t(lang, "err.generic"))
        return

    # Крупный код отдаём файлом: для этого сохраняем fences при чистке ответа.
    # В кодерском стиле код сохраняется всегда, даже если он короткий.
    _, big_blocks = split_big_code(answer)
    code_view = (
        style_key == "code"
        or bool(big_blocks)
        or out_fmt in {"py", "html", "css", "js"}
    )
    answer = readable_answer(answer, code=code_view)
    if not answer:
        if show:
            await show.finish(ok=False)
        if reserved:
            await store.refund_consume(user.id, reserved)
        log.warning("Модель вернула только рассуждения, ответ не отправлен")
        await message.reply(t(lang, "err.retry"))
        return

    if show:
        await show.finish(ok=True)
    label = store_question or question
    await store.add_exchange(
        user.id,
        label,
        answer,
        keep=max(2, runtime.max_context * 2) if runtime.max_context else 2,
    )
    exchange_id = await store.add_exchange_record(user.id, label, answer, kind)
    if out_fmt:
        await send_file(
            message,
            answer,
            out_fmt,
            lang,
            name=files.suggest_filename(question, out_fmt),
        )
    elif deliver:
        # Под ответом не показываем кнопок оценок или вариантов — только кнопку
        # «📊 Кабинет», если Mini App включён, чтобы пользователь сразу видел
        # статистику (остаток, историю, инструменты).
        await deliver_answer(
            message,
            answer,
            code=code_view,
            lang=lang,
            keyboard=cabinet_webapp_kb(settings, lang, exchange_id),
        )
    return answer


# --------------------------------------------------------------------------- команды
async def send_welcome(
    message: Message,
    store: Store,
    settings: Settings,
    lang: str,
    user: User | None = None,
) -> None:
    user = user or message.from_user
    runtime = await load_runtime(store, settings)
    role = await resolve_role(user.id, settings, store) if user else None
    admin_access = has_admin_access(role)
    if admin_access:
        limit = t(lang, "start.limit_staff", role=role_title(role))
    elif runtime.daily_limit <= 0:
        limit = t(lang, "start.limit_unlimited")
    else:
        limit = t(lang, "start.limit_daily", limit=runtime.daily_limit)

    if admin_access:
        extra = t(lang, "start.admin_extra", role=role_title(role))
    elif is_staff(role):
        extra = t(lang, "start.support_extra", role=role_title(role))
    else:
        extra = ""

    text = t(lang, "start.body", bot=escape(settings.bot_name)) + limit + extra
    await message.answer(
        text,
        reply_markup=main_menu_kb(
            lang,
            staff=has_admin_access(role),
            payments=settings.payments_enabled,
            support=settings.support_ready,
        ),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    await store.ensure_user(user.id, user.username, user.first_name)

    if message.chat.type != "private":
        me = await message.bot.me()
        await message.answer(
            t(
                normalize_lang(await store.get_lang(user.id) or settings.default_lang),
                "err.private_only",
                username=me.username or settings.bot_name,
            )
        )
        return

    stored = await store.get_lang(user.id)
    lang = normalize_lang(stored) if stored else normalize_lang(settings.default_lang)
    referred = await _accept_referral(message, store, settings, lang)
    # Меню показываем сразу, даже если язык ещё не выбран: иначе новый
    # пользователь видит только выбор языка и не находит кнопки.
    await send_welcome(message, store, settings, lang)
    if referred:
        await message.answer(
            t(lang, "invite.welcome", amount=settings.invited_reward)
        )
    if not stored:
        await message.answer(t(lang, "lang.pick"), reply_markup=language_kb(lang))


@router.message(Command("app", "кабинет", "cabinet"))
async def cmd_app(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    if message.chat.type != "private":
        me = await message.bot.me()
        await message.answer(
            t(lang, "app.private", username=me.username or settings.bot_name)
        )
        return
    if not settings.use_webhook:
        await message.answer(t(lang, "app.disabled"))
        return
    url = f"{settings.base_url.rstrip('/')}/app"
    await message.answer(
        t(lang, "app.open"),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "app.button"), web_app=WebAppInfo(url=url)
                    )
                ]
            ]
        ),
    )


async def _accept_referral(
    message: Message, store: Store, settings: Settings, lang: str
) -> bool:
    """Разбирает deep-link /start ref_<id> и награждает за приглашение."""
    user = message.from_user
    if user is None:
        return False
    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    referrer_id = await growth.parse_ref(payload) if payload else 0
    name = user.first_name or (f"@{user.username}" if user.username else None)
    if referrer_id:
        if referrer_id == user.id:
            return False
        return await growth.accept_referral(
            message.bot,
            store,
            settings,
            user.id,
            referrer_id,
            name=name,
        )
    return await growth.process_pending(message.bot, store, settings, user)


@router.message(Command("bonus", "бонус"))
async def cmd_bonus(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    if message.chat.type != "private":
        me = await message.bot.me()
        await message.answer(
            t(lang, "bonus.private", username=me.username or settings.bot_name)
        )
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    text, _, _ = await bonus_view(store, settings, user.id, lang)
    await message.answer(text)


async def bonus_view(
    store: Store, settings: Settings, user_id: int, lang: str
) -> tuple[str, bool, int]:
    """Текст про бонус дня + признак «только что получен» и сумма."""
    result = await store.daily_bonus(user_id, settings.bonus_base, settings.bonus_max)
    runtime = await load_runtime(store, settings)
    left = await store.remaining(user_id, runtime.daily_limit)
    if result["claimed"]:
        text = t(
            lang,
            "bonus.ok",
            amount=result["amount"],
            streak=result["streak"],
            left=left,
            top=settings.bonus_max,
        )
    else:
        text = t(lang, "bonus.already", streak=result["streak"], left=left)
    return text, bool(result["claimed"]), int(result["amount"])


async def redeem_promo(
    message: Message,
    store: Store,
    lang: str,
    user_id: int,
    raw: str,
) -> None:
    """Активирует код и сообщает результат. Возвращает текст через message.answer."""
    code = (raw or "").strip().upper()
    if not code:
        await message.answer(t(lang, "promo.ask"))
        return
    result = await store.redeem_promo(code, user_id)
    status = str(result.get("status") or "not_found")
    if status != "ok":
        key = {
            "used": "promo.used",
            "expired": "promo.expired",
            "exhausted": "promo.exhausted",
            "inactive": "promo.inactive",
        }.get(status, "promo.not_found")
        await message.answer(t(lang, key))
        return
    promo = result.get("promo") or {}
    requests = int(promo.get("requests") or 0)
    images = int(promo.get("image_credits") or 0)
    balance = await store.bonus_requests(user_id)
    image_balance = await store.image_credits(user_id)
    kwargs = {
        "code": escape(code),
        "requests": requests,
        "images": images,
        "balance": balance,
        "image_balance": image_balance,
    }
    if requests and images:
        text = t(lang, "promo.ok_both", **kwargs)
    elif requests:
        text = t(lang, "promo.ok_requests", **kwargs)
    else:
        text = t(lang, "promo.ok_images", **kwargs)
    await message.answer(text)


@router.message(Command("promo", "промокод"))
async def cmd_promo(
    message: Message, store: Store, settings: Settings, state: FSMContext
) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    if message.chat.type != "private":
        me = await message.bot.me()
        await message.answer(
            t(lang, "promo.private", username=me.username or settings.bot_name)
        )
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    parts = (message.text or "").split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ""
    if code:
        await state.clear()
        await redeem_promo(message, store, lang, user.id, code)
        return
    await state.set_state(Promo.awaiting)
    await message.answer(t(lang, "promo.ask"))


@router.message(
    Promo.awaiting, F.text, ~F.text.startswith("/"), ~F.text.in_(set(menu_label_map()))
)
async def on_promo_code(
    message: Message, store: Store, settings: Settings, state: FSMContext
) -> None:
    await state.clear()
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    await redeem_promo(
        message, store, lang, user.id, (message.text or "").strip()
    )


@router.message(Promo.awaiting)
async def on_promo_non_text(message: Message) -> None:
    await message.answer("Пришли промокод текстом или нажми /cancel.")


@router.message(Command("invite", "пригласить", "реф", "ref"))
async def cmd_invite(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    me = await message.bot.me()
    if message.chat.type != "private":
        await message.answer(
            t(lang, "invite.private", username=me.username or settings.bot_name)
        )
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    text, keyboard = await invite_view(
        store, settings, user.id, lang, me.username or settings.bot_name
    )
    await message.answer(text, reply_markup=keyboard)


async def invite_view(
    store: Store, settings: Settings, user_id: int, lang: str, bot_username: str
) -> tuple[str, InlineKeyboardMarkup]:
    link = f"https://t.me/{bot_username}?start=ref_{user_id}"
    count = await store.referral_count(user_id)
    bonus = await store.bonus_requests(user_id)
    share = (
        "https://t.me/share/url?url="
        + quote(link, safe="")
        + "&text="
        + quote(t(lang, "invite.share_text", bot=settings.bot_name), safe="")
    )
    text = t(
        lang,
        "invite.card",
        link=escape(link),
        count=count,
        reward=settings.invite_reward,
        friend=settings.invited_reward,
        bonus=bonus,
    )
    return text, InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "invite.share"), url=share)],
            [
                InlineKeyboardButton(
                    text=t(lang, "menu.bonus"), callback_data="bonus:claim"
                )
            ],
        ]
    )


@router.callback_query(F.data == "bonus:claim")
async def cb_bonus_claim(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    lang = await user_lang(store, settings, call.from_user.id)
    await store.ensure_user(
        call.from_user.id, call.from_user.username, call.from_user.first_name
    )
    text, claimed, amount = await bonus_view(
        store, settings, call.from_user.id, lang
    )
    with contextlib.suppress(TelegramAPIError):
        await call.message.answer(text)
    await call.answer(
        t(lang, "bonus.ok_short", amount=amount)
        if claimed
        else t(lang, "bonus.already_short")
    )


@router.callback_query(F.data.startswith("lg:"))
async def cb_lang(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None or call.data is None:
        return
    code = normalize_lang(call.data.split(":", 1)[1], settings.default_lang)
    await store.set_lang(call.from_user.id, code)
    if isinstance(call.message, Message):
        with contextlib.suppress(TelegramAPIError):
            await call.message.edit_text(t(code, "lang.saved", name=LANG_NAMES[code]))
    await call.answer()
    if isinstance(call.message, Message):
        await send_welcome(call.message, store, settings, code, user=call.from_user)


@router.callback_query(F.data == "lang:menu")
async def cb_lang_menu(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    lang = await user_lang(store, settings, call.from_user.id)
    if isinstance(call.message, Message):
        with contextlib.suppress(TelegramAPIError):
            await call.message.edit_text(
                t(lang, "lang.pick"), reply_markup=language_kb(lang)
            )
    await call.answer()


@router.message(Command("lang"))
async def cmd_lang(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    if message.chat.type != "private":
        me = await message.bot.me()
        await message.answer(
            t(lang, "err.private_only", username=me.username or settings.bot_name)
        )
        return
    await message.answer(t(lang, "lang.pick"), reply_markup=language_kb(lang))


@router.message(Command("model", "llm"))
async def cmd_model(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    if message.chat.type != "private":
        me = await message.bot.me()
        await message.answer(
            t(lang, "err.private_only", username=me.username or settings.bot_name)
        )
        return
    await send_model_menu(message, store, settings, lang, user.id)


@router.callback_query(F.data.startswith("mdl:"))
async def cb_model(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings
) -> None:
    if call.from_user is None or call.data is None:
        return
    lang = await user_lang(store, settings, call.from_user.id)
    runtime = await load_runtime(store, settings)
    parts = call.data.split(":", 2)
    action = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""

    if action == "menu":
        if call.message:
            await send_model_menu(call.message, store, settings, lang, call.from_user.id)
        await call.answer()
        return

    if action == "auto":
        await store.set_model(call.from_user.id, None)
        current = runtime.model or model_catalog.DEFAULT_MODEL
    elif action == "buy":
        item = model_catalog.info(value)
        if item is None or item.stars <= 0:
            await call.answer(t(lang, "model.stale"), show_alert=True)
            return
        if not settings.payments_enabled:
            await call.answer(t(lang, "model.buy_disabled"), show_alert=True)
            return
        try:
            await send_model_invoice(bot, call.from_user.id, item, settings)
        except TelegramAPIError as exc:
            log.warning("Не удалось выставить счёт на модель %s: %s", value, exc)
            await call.answer(t(lang, "model.invoice"), show_alert=True)
            return
        await call.answer()
        return
    elif action == "set":
        item = model_catalog.info(value)
        if item is None:
            await call.answer(t(lang, "model.stale"), show_alert=True)
            return
        role = await resolve_role(call.from_user.id, settings, store)
        owned = await owned_models(
            store, settings, call.from_user.id, staff=has_admin_access(role)
        )
        if item.id not in owned:
            await call.answer(
                t(lang, "model.not_owned", stars=item.stars), show_alert=True
            )
            return
        await store.set_model(call.from_user.id, item.id)
        current = item.id
    else:
        await call.answer(t(lang, "model.stale"), show_alert=True)
        return

    role = await resolve_role(call.from_user.id, settings, store)
    owned = await owned_models(
        store, settings, call.from_user.id, staff=has_admin_access(role)
    )
    models = available_models(settings, runtime)
    if isinstance(call.message, Message):
        with contextlib.suppress(TelegramAPIError):
            await call.message.edit_text(
                t(lang, "model.title", current=escape(model_title(current))),
                reply_markup=model_kb(models, current, lang, owned),
            )
    await call.answer(t(lang, "model.saved", name=model_title(current)))


async def help_text(store: Store, settings: Settings, lang: str, user_id: int | None) -> str:
    runtime = await load_runtime(store, settings)
    role = await resolve_role(user_id, settings, store) if user_id else None
    current_model = (
        await user_model(store, settings, runtime, user_id) if user_id else runtime.model
    )
    if has_admin_access(role):
        staff_note = t(lang, "start.admin_extra", role=role_title(role))
    elif is_staff(role):
        staff_note = t(lang, "start.support_extra", role=role_title(role))
    else:
        staff_note = ""
    return (
        t(lang, "help.body")
        + t(lang, "help.tools")
        + t(lang, "help.support")
        + t(lang, "help.tail", model=escape(model_title(current_model)), lang=LANG_NAMES[normalize_lang(lang)])
        + staff_note
    )


@router.message(Command("help"))
async def cmd_help(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang
    role = await resolve_role(user.id, settings, store) if user else None
    await message.answer(
        await help_text(store, settings, lang, user.id if user else None),
        reply_markup=(
            main_menu_kb(
                lang,
                staff=has_admin_access(role),
                payments=settings.payments_enabled,
                support=settings.support_ready,
            )
            if message.chat.type == "private"
            else None
        ),
    )


@router.message(Command("debug", "dbg"))
async def cmd_debug(message: Message, store: Store, settings: Settings) -> None:
    """Секретная команда: включает «режим отладки» только в личке.

    Это спектакль, а не настоящий обход фильтров: бот просто меняет текст
    одного сообщения по шагам. Команда намеренно не попадает в меню команд.
    """
    user = message.from_user
    if user is None or message.chat.type != "private":
        return
    lang = await user_lang(store, settings, user.id)
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    if arg.lower() in {"off", "0", "выкл", "стоп", "stop", "disable"}:
        await debugmode.set_enabled(store, user.id, False)
        await message.answer(t(lang, "dbg.off"))
        return

    expected = debugmode.secret(settings.debug_command_secret)
    if not arg or not hmac.compare_digest(
        arg.encode("utf-8"), expected.encode("utf-8")
    ):
        await message.answer(t(lang, "dbg.denied"))
        return

    await debugmode.set_enabled(store, user.id, True)
    await message.answer(
        t(lang, "dbg.on", cmd="/debug off"),
        parse_mode="HTML",
    )


@router.message(Command("files", "file"))
async def cmd_files(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang
    await message.answer(
        t(
            lang,
            "file.help",
            mb=settings.file_max_mb,
            pages=settings.file_max_pdf_pages,
        )
    )


@router.message(Command("ai"))
async def cmd_ai(message: Message, bot: Bot, store: Store, settings: Settings, ai: AIClient) -> None:
    parts = (message.text or "").split(maxsplit=1)
    question = parts[1] if len(parts) > 1 else ""
    await answer_with_ai(
        message, bot=bot, store=store, settings=settings, ai=ai, question=question
    )


@router.message(Command("reset"))
async def cmd_reset(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if user:
        await store.reset(user.id)
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang
    await message.answer(t(lang, "reset.done"))


@router.message(Command("me"))
async def cmd_me(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    if not user:
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    lang = await user_lang(store, settings, user.id)
    runtime = await load_runtime(store, settings)
    current_model = await user_model(store, settings, runtime, user.id)
    bonus = await store.bonus_requests(user.id)
    role = await resolve_role(user.id, settings, store)
    if has_admin_access(role):
        limit_text = t(lang, "me.limit_staff", role=role_title(role))
    elif runtime.daily_limit <= 0:
        limit_text = t(lang, "me.limit_unlimited")
    else:
        left = await store.remaining(user.id, runtime.daily_limit)
        daily_left = max(0, left - bonus)
        limit_text = t(lang, "me.limit_left", left=daily_left, total=runtime.daily_limit)

    banned = await store.is_banned(user.id)
    style_key = normalize_style(await store.get_style(user.id))
    note = t(lang, "me.banned_note") if banned else ""
    rows = []
    if settings.payments_enabled:
        rows.append([InlineKeyboardButton(text=t(lang, "btn.buy"), callback_data="pay:menu")])
    if settings.support_ready:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "menu.donate"), callback_data="menu:donate"
                )
            ]
        )
    if is_staff(role):
        rows.append([InlineKeyboardButton(text=t(lang, "btn.tickets"), callback_data="tick:list:0")])
    rows.append([InlineKeyboardButton(text=t(lang, "btn.support"), callback_data="tick:menu")])
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn.model"), callback_data="mdl:menu")]
    )
    rows.append(
        [InlineKeyboardButton(text=t(lang, "btn.lang"), callback_data="lang:menu")]
    )
    role_line = t(lang, "me.role_line", role=role_title(role)) if role else ""
    streak = await store.bonus_streak(user.id)
    invites = await store.referral_count(user.id)
    growth_line = (
        t(lang, "me.growth_line", streak=streak, invites=invites)
        if streak or invites
        else ""
    )
    await message.answer(
        t(
            lang,
            "me.body",
            user_id=user.id,
            role_line=role_line,
            sub_line=growth_line,
            limit=limit_text,
            bonus=bonus,
            style=t(lang, f"styles.{style_key}"),
            model=escape(model_title(current_model)),
            note=note,
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


# --------------------------------------------------------------------------- режим проверки
@router.message(Command("check"))
async def cmd_check(message: Message, store: Store, settings: Settings, state: FSMContext) -> None:
    await state.set_state(Check.awaiting)
    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang
    await message.answer(t(lang, "check.hint"))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, store: Store, settings: Settings, state: FSMContext) -> None:
    await state.clear()
    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang
    await message.answer(t(lang, "cancel.done"))


@router.message(Check.awaiting, ~F.text.startswith("/"), ~F.text.in_(set(menu_label_map())))
async def on_check_input(
    message: Message, bot: Bot, store: Store, settings: Settings, ai: AIClient, state: FSMContext
) -> None:
    await state.clear()
    # Состояние проверки выставлено явно (кнопка или /check), поэтому в группе
    # не требуем упоминания: следующее сообщение этого ученика — его решение.
    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang

    image = None
    mime = "image/jpeg"
    if message.document is not None and not files.is_image_document(
        message.document.file_name, message.document.mime_type
    ):
        # В режиме проверки прислали документ с решением — читаем его как файл,
        # а не отвечаем «это не картинка».
        await handle_document(
            message,
            bot=bot,
            store=store,
            settings=settings,
            ai=ai,
            instruction=CHECK_INSTRUCTION,
        )
        return
    if message.photo or message.document:
        image, mime, error = await load_image(message, bot, lang)
        if error:
            await message.reply(error)
            return

    question = (message.text or message.caption or "").strip()
    if not question and image is None:
        await message.reply(t(lang, "check.need_solution"))
        return

    await answer_with_ai(
        message,
        bot=bot,
        store=store,
        settings=settings,
        ai=ai,
        question=question or "Проверь решение на изображении.",
        image=image,
        image_mime=mime,
        kind="check",
        instruction=CHECK_INSTRUCTION,
    )


# --------------------------------------------------------------------------- файлы
SEND_LIMIT_BYTES = 45 * 1024 * 1024


async def send_file(
    message: Message,
    text: str,
    fmt: str,
    lang: str,
    *,
    name: str | None = None,
    empty: bool = False,
) -> None:
    """Собирает файл с ответом и отправляет его в чат."""
    fmt = fmt.lower()
    try:
        if empty:
            data, filename = files.build_empty(fmt, name)
        else:
            data, filename = await asyncio.to_thread(
                files.build_output, text, fmt, name
            )
    except files.FileError:
        if fmt == "pdf":
            try:
                data, filename = await asyncio.to_thread(files.build_output, text, "docx")
            except files.FileError:
                await send_answer(message, text)
                return
            await message.reply(t(lang, "file.pdf_unavailable"))
        else:
            await message.reply(t(lang, "file.build_failed", fmt=fmt.upper()))
            await send_answer(message, text)
            return
    except Exception:  # noqa: BLE001 — сборщик файла не должен терять ответ
        log.exception("Сборка файла %s не удалась", fmt)
        await message.reply(t(lang, "file.build_failed", fmt=fmt.upper()))
        await send_answer(message, text)
        return

    if len(data) > SEND_LIMIT_BYTES:
        await message.reply(t(lang, "file.build_failed", fmt=fmt.upper()))
        await send_answer(message, text)
        return

    try:
        await message.answer_document(
            BufferedInputFile(data, filename=filename),
            caption=t(lang, "file.caption", name=escape(filename)),
        )
    except TelegramAPIError:
        # Telegram не любит совсем пустые документы: шлём один перевод строки.
        if not data:
            try:
                await message.answer_document(
                    BufferedInputFile(b"\n", filename=filename),
                    caption=t(lang, "file.caption", name=escape(filename)),
                )
                return
            except TelegramAPIError:
                pass
        log.exception("Не удалось отправить файл %s — отдаю текстом", filename)
        if text.strip():
            await send_answer(message, text)
        else:
            await message.reply(t(lang, "file.empty"))


async def send_code_file(
    message: Message,
    code: str,
    language: str,
    index: int,
    lang: str,
    name: str | None = None,
) -> bool:
    """Отправляет большой блок кода отдельным файлом. True, если получилось."""
    if name is None:
        name = code_file_name(language, index)
    data = (code.rstrip() + "\n").encode("utf-8")
    if len(data) > SEND_LIMIT_BYTES:
        return False
    lines = len(code.splitlines())
    try:
        await message.answer_document(
            BufferedInputFile(data, filename=name),
            caption=t(lang, "code.file_caption", name=name, lines=lines),
        )
    except TelegramAPIError:
        log.exception("Не удалось отправить код файлом %s", name)
        return False
    return True


def code_file_name(language: str, index: int) -> str:
    """Понятное имя файла: main.py, index.html, styles.css и т.д."""
    ext = CODE_EXT.get((language or "").strip().lower(), "txt")
    default = files.CODE_DEFAULT_NAMES.get(ext)
    return default or f"gazyavaGPT-{index}.{ext}"


def code_file_entries(blocks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Имена файлов для архива: одинаковые расширения не затирают друг друга."""
    entries: list[tuple[str, str]] = []
    used: dict[str, int] = {}
    for index, (language, source) in enumerate(blocks, 1):
        name = code_file_name(language, index)
        if name in used:
            used[name] += 1
            stem, dot, ext = name.partition(".")
            name = f"{stem}-{used[name]}{dot}{ext}"
        else:
            used[name] = 1
        entries.append((name, source))
    return entries


async def send_code_archive(
    message: Message, blocks: list[tuple[str, str]], lang: str
) -> int:
    """Складывает несколько файлов проекта в один архив. 0 — не получилось."""
    entries = code_file_entries(blocks)
    try:
        data = await asyncio.to_thread(files.build_zip, entries)
    except Exception:  # noqa: BLE001 — архив не должен терять ответ
        log.exception("Не удалось собрать архив с кодом")
        return 0
    if len(data) > SEND_LIMIT_BYTES:
        return 0
    name = "gazyavaGPT-project.zip"
    lines = sum(len(source.splitlines()) for _, source in blocks)
    try:
        await message.answer_document(
            BufferedInputFile(data, filename=name),
            caption=t(
                lang,
                "code.zip_caption",
                files=len(entries),
                lines=lines,
                names=", ".join(name for name, _ in entries[:6]),
            ),
        )
    except TelegramAPIError:
        log.exception("Не удалось отправить архив %s", name)
        return 0
    return len(blocks)


async def deliver_answer(
    message: Message,
    text: str,
    *,
    code: bool,
    lang: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    """Отправляет ответ: большой код — файлами или проектом в ZIP."""
    rest, blocks = split_big_code(text)
    sent_blocks = 0
    if len(blocks) >= 2:
        sent_blocks = await send_code_archive(message, blocks, lang)
    if not sent_blocks:
        for index, (language, source) in enumerate(blocks, 1):
            if await send_code_file(message, source, language, index, lang):
                sent_blocks += 1
    if rest.strip():
        await send_answer(message, rest, keyboard=keyboard, code=code)
    elif blocks and not sent_blocks:
        # Ни файл, ни текст не ушли — лучше показать код сообщением, чем молчать.
        await send_answer(message, text, keyboard=keyboard, code=code)


async def echo_document(
    message: Message,
    doc,
    name: str,
    lang: str,
) -> None:
    """Отправляет присланный файл обратно — по file_id, без скачивания.

    Так работают файлы любого формата: бот не тратит трафик и место, а
    Telegram сам отдаёт файл из своего хранилища. Файл >50 МБ бот отправить
    не может — просим сжать, разбить или прислать ссылку.
    """
    size = int(getattr(doc, "file_size", 0) or 0)
    if size > files.TELEGRAM_SEND_LIMIT:
        await message.reply(t(lang, "file.send_too_big"))
        return
    try:
        await message.answer_document(
            doc.file_id, caption=t(lang, "file.echoed", name=escape(name))
        )
    except TelegramAPIError:
        log.exception("Не удалось вернуть файл %s", name)
        await message.reply(t(lang, "file.download_failed"))


async def handle_document(
    message: Message,
    *,
    bot: Bot,
    store: Store,
    settings: Settings,
    ai: AIClient,
    document=None,
    instruction: str | None = None,
) -> None:
    """Читает документ, отдаёт текст ИИ и при просьбе собирает файл."""
    user = message.from_user
    lang = (
        await user_lang(store, settings, user.id)
        if user
        else normalize_lang(settings.default_lang)
    )

    doc = document or message.document
    if doc is None and message.reply_to_message is not None:
        doc = message.reply_to_message.document
    if doc is None:
        return

    name = files.sanitize_name(doc.file_name or "file", "")
    ext = files.extension(name, doc.mime_type)
    task = (instruction or "").strip()
    supported = files.is_supported(name, doc.mime_type)

    if not supported:
        if not files.is_image_document(name, doc.mime_type):
            await message.reply(t(lang, "file.unsupported", ext=escape(ext or "?")))
        # Неподдерживаемый формат всё равно принимаем и возвращаем владельцу.
        await echo_document(message, doc, name, lang)
        return

    # Любой файл без задания возвращаем обратно — без скачивания, по file_id.
    # Но «пришли файл в pdf» — это конвертация, а не эхо.
    if not task or (
        files.wants_echo(task)
        and files.detect_output_format(task, generic=False) is None
        and not files.edit_instruction(task)
    ):
        await echo_document(message, doc, name, lang)
        return

    download_limit = min(
        settings.file_max_mb * 1024 * 1024, files.TELEGRAM_DOWNLOAD_LIMIT
    )
    if (doc.file_size or 0) > download_limit:
        await message.reply(
            t(lang, "file.too_big", mb=download_limit // (1024 * 1024))
        )
        return

    status = await message.reply(t(lang, "file.reading"))
    try:
        # Bot API: first obtain file_path, then download bytes into memory.
        remote = await bot.get_file(doc.file_id)
        buffer = io.BytesIO()
        if getattr(remote, "file_path", None):
            await bot.download_file(remote.file_path, destination=buffer)
        else:
            # Compatibility with Bot mocks/custom sessions; regular Bot API
            # returns file_path and always takes the explicit get_file path above.
            await bot.download(doc, destination=buffer)
        data = buffer.getvalue()
        if len(data) > files.TELEGRAM_DOWNLOAD_LIMIT:
            await message.reply(t(lang, "file.too_big", mb=20))
            return
    except (TelegramAPIError, TelegramNetworkError, OSError, TimeoutError):
        log.exception("Не удалось скачать файл %s", name)
        await message.reply(t(lang, "file.download_failed"))
        return
    finally:
        with contextlib.suppress(Exception):
            await status.delete()

    try:
        text = await asyncio.to_thread(
            files.extract_text,
            data,
            name,
            doc.mime_type,
            settings.file_max_pdf_pages,
        )
    except files.FileError as exc:
        await message.reply(t(lang, exc.key, **exc.kwargs))
        return

    text = files.clip_text(text, settings.file_max_chars)
    if not text.strip():
        await message.reply(t(lang, "file.empty"))
        return

    task = (instruction or "").strip()
    source_fmt = files.FORMAT_BY_EXT.get(ext)
    requested = (
        files.detect_output_format(task)
        if task and files.wants_document_output(task)
        else None
    )
    editing = bool(task) and files.edit_instruction(task)
    fmt = requested or (source_fmt if editing else None)
    if fmt:
        if fmt == "xlsx":
            task += (
                "\nВерни ТОЛЬКО содержимое таблицы: одна строка на строку Excel, "
                "столбцы разделяй символом |. Не добавляй Markdown-таблицу, "
                "пояснения или кодовый блок."
            )
        elif fmt == "pptx":
            task += (
                "\nВерни результат как текст слайдов: каждый слайд начинай "
                "с '# Заголовок', пункты — отдельными строками."
            )
        else:
            task += "\nВерни только содержимое файла, без пояснений."
    if not task:
        task = t(lang, "file.default_task")

    wrapper = f"{task}\n\nСодержимое файла «{name}»:\n---\n{text}\n---"
    answer = await answer_with_ai(
        message,
        bot=bot,
        store=store,
        settings=settings,
        ai=ai,
        question=wrapper,
        max_chars=settings.file_max_chars + 2000,
        use_history=False,
        deliver=fmt is None,
        store_question=f"[файл] {name}: {task[:180]}",
        task_lang=detect_lang(task),
    )

    if answer and fmt:
        if editing and (requested is None or requested == source_fmt):
            out_name = files.edited_filename(name, fmt)
        elif source_fmt:
            # Конвертация присланного файла: сохраняем имя, меняем расширение.
            out_name = files.retarget_filename(name, fmt)
        else:
            out_name = files.suggest_filename(instruction or name, fmt)
        await send_file(message, answer, fmt, lang, name=out_name)


# --------------------------------------------------------------------------- картинки (фото)
@router.message(F.photo | F.document)
async def on_image(
    message: Message,
    bot: Bot,
    store: Store,
    settings: Settings,
    ai: AIClient,
    images: ImageClient,
    state: FSMContext,
) -> None:
    if await state.get_state() == Imagine.awaiting.state:
        # Ждали текст-описание картинки, а прислали фото — режим ввода сбрасываем,
        # иначе следующее обычное сообщение уедет в генерацию.
        await state.clear()
    caption = await addressed_text(message, bot, settings)
    if caption is None:
        return

    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang

    # Файл без подписи возвращаем как есть — включая картинки-документы.
    if message.document is not None and not caption.strip():
        await handle_document(
            message,
            bot=bot,
            store=store,
            settings=settings,
            ai=ai,
            instruction="",
        )
        return

    # «нарисуй …» / «сделай фото …» с любым вложением — это генерация картинки,
    # а не чтение документа: просьба нарисовать важнее вложенного файла.
    if caption:
        draw_match = DRAW_RE.match(caption)
        if draw_match:
            await send_generated(
                message,
                images,
                settings,
                lang,
                caption[draw_match.end() :].strip(),
                store=store,
            )
            return

    if message.document is not None and not files.is_image_document(
        message.document.file_name, message.document.mime_type
    ):
        await handle_document(
            message,
            bot=bot,
            store=store,
            settings=settings,
            ai=ai,
            instruction=caption,
        )
        return

    data, mime, error = await load_image(message, bot, lang)
    if error:
        await message.reply(error)
        return
    assert data is not None

    if caption and EDIT_RE.search(caption):
        await send_generated(
            message, images, settings, lang, caption, source=data, mime=mime, store=store
        )
        return

    check_mode = bool(
        re.search(r"провер|правильн|найди ошибк|\bcheck\b", caption or "", re.IGNORECASE)
    )
    question = caption or IMAGE_PROMPT

    debug_on = await debugmode.enabled(store, user.id) if user else False
    status = None if debug_on else await message.reply(t(lang, "image.checking"))
    try:
        await answer_with_ai(
            message,
            bot=bot,
            store=store,
            settings=settings,
            ai=ai,
            question=question,
            image=data,
            image_mime=mime,
            kind="check" if check_mode else "answer",
            instruction=CHECK_INSTRUCTION if check_mode else None,
        )
    finally:
        if status is not None:
            with contextlib.suppress(Exception):
                await status.delete()


# --------------------------------------------------------------------------- картинки (фото)
VIDEO_PROMPT = "Разбери, что происходит на видео: опиши события, текст и главное."
STICKER_PROMPT = "Опиши этот стикер: что на нём и какое настроение он передаёт."
VIDEO_INSTRUCTION = (
    "Пользователь прислал видео. Тебе передали несколько кадров, склеенных в сетку. "
    "Разбери, что происходит: события по порядку, люди и предметы, надписи на экране. "
    "Если кадров мало, честно скажи, что видно не всё."
)
STICKER_INSTRUCTION = (
    "Пользователь прислал стикер. Если передано несколько кадров, это анимированный "
    "стикер: опиши, что происходит по ходу анимации. Если кадр один — опиши, что на нём "
    "изображено, и объясни смысл или настроение."
)


async def _download_bytes(bot: Bot, file, limit: int) -> tuple[bytes | None, str | None]:
    """Скачивает файл Telegram в память с проверкой размера."""
    if file is None:
        return None, "empty"
    if (getattr(file, "file_size", 0) or 0) > limit:
        return None, "too_big"
    buffer = io.BytesIO()
    try:
        await bot.download(file, destination=buffer)
    except Exception:  # noqa: BLE001
        log.exception("Не удалось скачать медиа из Telegram")
        return None, "download"
    data = buffer.getvalue()
    return (data, None) if data else (None, "empty")


@router.message(F.video | F.video_note | F.animation)
async def on_video(
    message: Message,
    bot: Bot,
    store: Store,
    settings: Settings,
    ai: AIClient,
    state: FSMContext,
) -> None:
    if await state.get_state() == Imagine.awaiting.state:
        await state.clear()
    text = await addressed_text(message, bot, settings)
    if text is None:
        return
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)

    video = message.video or message.animation or message.video_note
    limit = media.VIDEO_MAX_BYTES
    debug_on = await debugmode.enabled(store, user.id)
    status = None if debug_on else await message.reply(t(lang, "media.video_reading"))

    async def drop_status() -> None:
        if status is not None:
            with contextlib.suppress(Exception):
                await status.delete()

    try:
        data, error = await _download_bytes(bot, video, limit)
        if error == "too_big":
            await drop_status()
            await message.reply(t(lang, "media.too_big", mb=limit // (1024 * 1024)))
            return
        if error or not data:
            await drop_status()
            await message.reply(t(lang, "media.video_failed"))
            return

        frames = await asyncio.to_thread(media.video_frames, data)
        image = await asyncio.to_thread(media.contact_sheet, frames) if frames else b""
        mime = "image/jpeg"
        if not image:
            thumb = getattr(video, "thumbnail", None)
            thumb_data, _ = await _download_bytes(bot, thumb, 5 * 1024 * 1024)
            image = thumb_data or b""

        if not image:
            await drop_status()
            await message.reply(t(lang, "media.video_failed"))
            return

        duration = int(getattr(video, "duration", 0) or 0)
        hint = f" Длительность: {duration} с." if duration else ""
        question = text.strip() or VIDEO_PROMPT
        await drop_status()
        await answer_with_ai(
            message,
            bot=bot,
            store=store,
            settings=settings,
            ai=ai,
            question=question + hint,
            image=image,
            image_mime=mime,
            instruction=VIDEO_INSTRUCTION,
            store_question=f"[видео] {question[:160]}",
        )
    finally:
        await drop_status()


@router.message(F.sticker)
async def on_sticker(
    message: Message,
    bot: Bot,
    store: Store,
    settings: Settings,
    ai: AIClient,
    state: FSMContext,
) -> None:
    if await state.get_state() == Imagine.awaiting.state:
        await state.clear()
    text = await addressed_text(message, bot, settings)
    if text is None:
        return
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    sticker = message.sticker
    animated = bool(getattr(sticker, "is_animated", False))
    is_video = bool(getattr(sticker, "is_video", False))

    data: bytes | None = None
    note = ""
    if is_video:
        # .webm: достаём несколько кадров, чтобы увидеть движение.
        raw, error = await _download_bytes(bot, sticker, 5 * 1024 * 1024)
        if error == "too_big":
            await message.reply(t(lang, "media.too_big", mb=5))
            return
        if raw:
            frames = await asyncio.to_thread(media.sticker_video_frames, raw, 4)
            if frames:
                data = await asyncio.to_thread(media.contact_sheet, frames)
        if not data:
            thumb_data, _ = await _download_bytes(
                bot, getattr(sticker, "thumbnail", None), 5 * 1024 * 1024
            )
            data = (
                await asyncio.to_thread(media.sticker_image, thumb_data)
                if thumb_data
                else None
            )
        note = " Тебе передали несколько кадров анимированного стикера."
    elif animated:
        # .tgs — Lottie: рендерим кадры, а если пакета нет — берём превью.
        raw, error = await _download_bytes(bot, sticker, 5 * 1024 * 1024)
        if error == "too_big":
            await message.reply(t(lang, "media.too_big", mb=5))
            return
        if raw:
            frames = await asyncio.to_thread(media.tgs_frames, raw, 3)
            if len(frames) > 1:
                data = await asyncio.to_thread(media.contact_sheet, frames)
            elif frames:
                data = await asyncio.to_thread(media.sticker_image, frames[0])
            if not data:
                embedded = await asyncio.to_thread(media.tgs_text, raw)
                if embedded:
                    note += f" Текст на стикере: «{embedded}»."
        if not data:
            thumb_data, _ = await _download_bytes(
                bot, getattr(sticker, "thumbnail", None), 5 * 1024 * 1024
            )
            data = (
                await asyncio.to_thread(media.sticker_image, thumb_data)
                if thumb_data
                else None
            )
        if data:
            note += " Это кадры анимированного стикера."
    else:
        raw, error = await _download_bytes(bot, sticker, 5 * 1024 * 1024)
        if error == "too_big":
            await message.reply(t(lang, "media.too_big", mb=5))
            return
        data = await asyncio.to_thread(media.sticker_image, raw) if raw else None

    if not data:
        await message.reply(t(lang, "media.sticker_failed"))
        return

    emoji = getattr(sticker, "emoji", None)
    question = text.strip() or STICKER_PROMPT
    if emoji:
        question += f" Эмодзи стикера: {emoji}."
    question += note
    await answer_with_ai(
        message,
        bot=bot,
        store=store,
        settings=settings,
        ai=ai,
        question=question,
        image=data,
        image_mime="image/jpeg",
        instruction=STICKER_INSTRUCTION,
        store_question=f"[стикер] {question[:160]}",
    )


# --------------------------------------------------------------------------- кнопки под ответом
@router.callback_query(F.data.startswith("fb:"))
async def cb_feedback(
    call: CallbackQuery, bot: Bot, store: Store, settings: Settings, ai: AIClient, state: FSMContext
) -> None:
    if call.from_user is None or call.data is None:
        return

    _, action, raw_id = call.data.split(":")
    lang = await user_lang(store, settings, call.from_user.id)
    if action == "noop":
        await call.answer(t(lang, "fb.already"))
        return

    if not isinstance(call.message, Message):
        # Сообщение с кнопками удалено — отвечать некуда.
        await call.answer(t(lang, "fb.gone"), show_alert=True)
        return

    exchange = await store.get_exchange(int(raw_id))
    if not exchange:
        await call.answer(t(lang, "fb.gone"), show_alert=True)
        return

    owner = exchange["user_id"]
    if call.from_user.id != owner and not await is_admin(
        call.from_user.id, settings, store
    ):
        await call.answer(t(lang, "fb.not_yours"), show_alert=True)
        return

    if action in {"up", "down"}:
        await store.set_vote(exchange["id"], action)
        with contextlib.suppress(TelegramAPIError):
            await call.message.edit_reply_markup(
                reply_markup=answer_kb(exchange["id"], voted=action, lang=lang)
            )
        await call.answer(t(lang, "fb.saved_up" if action == "up" else "fb.saved_down"))
        return

    if action == "check":
        await state.set_state(Check.awaiting)
        await call.answer()
        await call.message.answer(t(lang, "check.prompt"))
        return

    modifier = MODIFIERS.get(action)
    if not modifier:
        await call.answer(t(lang, "fb.stale"))
        return

    await call.answer(t(lang, "fb.working"))
    runtime = await load_runtime(store, settings)
    style_key = normalize_style(await store.get_style(owner))
    history = [
        {"role": "user", "content": exchange["question"]},
        {"role": "assistant", "content": exchange["answer"]},
    ]
    chosen_model = await user_model(store, settings, runtime, owner)

    try:
        async with keep_typing(bot, call.message.chat.id):
            answer = await ai.reply(
                history,
                modifier,
                model=chosen_model,
                system_prompt=runtime.system_prompt,
                vision_model=runtime.vision_model,
                style_note=style_hint(style_key),
                lang=lang,
                task_lang=detect_lang(exchange["question"]),
            )
    except AIError as exc:
        await call.message.answer(t(lang, "err.ai", message=escape(str(exc))))
        return
    except Exception:  # noqa: BLE001
        log.exception("Ошибка при повторном объяснении")
        await call.message.answer(t(lang, "err.retry"))
        return

    _, big_blocks = split_big_code(answer)
    code_view = style_key == "code" or bool(big_blocks)
    answer = readable_answer(answer, code=code_view)
    if not answer:
        await call.message.answer(t(lang, "err.retry"))
        return
    await store.add_exchange_record(owner, exchange["question"], answer, action)
    await deliver_answer(call.message, answer, code=code_view, lang=lang)


# --------------------------------------------------------------------------- главное меню
@router.message(F.text.in_(set(menu_label_map())))
async def on_menu_button(
    message: Message,
    bot: Bot,
    store: Store,
    settings: Settings,
    images: ImageClient,
    state: FSMContext,
) -> None:
    """Кнопки постоянной клавиатуры: работают вместо команд."""
    if message.chat.type != "private":
        return
    user = message.from_user
    if user is None:
        return
    action = menu_label_map().get((message.text or "").strip())
    if action is None:
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    lang = await user_lang(store, settings, user.id)
    role = await resolve_role(user.id, settings, store)
    await state.clear()

    if action == "menu.model":
        await send_model_menu(message, store, settings, lang, user.id)
    elif action == "menu.styles":
        await send_styles(message, store, settings, lang, user.id)
    elif action == "menu.check":
        await state.set_state(Check.awaiting)
        await message.answer(t(lang, "check.hint"))
    elif action == "menu.imagine":
        await state.set_state(Imagine.awaiting)
        await message.answer(t(lang, "img.ask_prompt"))
    elif action == "menu.buy":
        if not settings.payments_enabled:
            await message.answer(t(lang, "pay.disabled"))
            return
        from payments import render_buy

        text, kb = await render_buy(store, settings, user.id)
        await message.answer(text, reply_markup=kb)
    elif action == "menu.donate":
        text, kb = donate_view(settings, lang)
        await message.answer(text, reply_markup=kb, disable_web_page_preview=True)
    elif action == "menu.support":
        from tickets import support_menu

        text, kb = await support_menu(store, user.id)
        await message.answer(text, reply_markup=kb)
    elif action == "menu.tickets":
        from tickets import render_my_tickets, render_ticket_list

        if is_staff(role):
            text, kb = await render_ticket_list(
                store, 0, admin=has_admin_access(role)
            )
        else:
            text, kb = await render_my_tickets(store, user.id)
        await message.answer(text, reply_markup=kb)
    elif action == "menu.files":
        await message.answer(
            t(
                lang,
                "file.help",
                mb=settings.file_max_mb,
                pages=settings.file_max_pdf_pages,
            )
        )
    elif action == "menu.bonus":
        await cmd_bonus(message, store, settings)
    elif action == "menu.promo":
        await cmd_promo(message, store, settings, state)
    elif action == "menu.invite":
        await cmd_invite(message, store, settings)
    elif action == "menu.lang":
        await message.answer(t(lang, "lang.pick"), reply_markup=language_kb(lang))
    elif action == "menu.reset":
        await store.reset(user.id)
        await message.answer(t(lang, "reset.done"))
    elif action == "menu.terms":
        from payments import render_terms

        runtime = await load_runtime(store, settings)
        await message.answer(render_terms(settings, runtime))
    elif action == "menu.admin":
        if not has_admin_access(role):
            await message.answer(t(lang, "err.admin_only"))
            return
        from admin import render_main

        text, kb = await render_main(store, settings, role)
        await message.answer(text, reply_markup=kb)
    else:
        await message.answer(
            await help_text(store, settings, lang, user.id),
            reply_markup=main_menu_kb(
                lang,
                staff=has_admin_access(role),
                payments=settings.payments_enabled,
                support=settings.support_ready,
            ),
        )


@router.callback_query(F.data == "menu:home")
async def cb_menu_home(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    lang = await user_lang(store, settings, call.from_user.id)
    role = await resolve_role(call.from_user.id, settings, store)
    if isinstance(call.message, Message):
        try:
            await call.message.answer(
                t(lang, "menu.title"),
                reply_markup=menu_inline(
                    lang,
                    staff=has_admin_access(role),
                    payments=settings.payments_enabled,
                    support=settings.support_ready,
                ),
            )
        except TelegramAPIError:
            pass
    await call.answer()


@router.callback_query(F.data == "menu:donate")
async def cb_menu_donate(
    call: CallbackQuery, store: Store, settings: Settings
) -> None:
    """Кнопка «Поддержать автора» в inline-меню."""
    if call.from_user is None:
        return
    lang = await user_lang(store, settings, call.from_user.id)
    text, kb = donate_view(settings, lang)
    if isinstance(call.message, Message):
        with contextlib.suppress(TelegramAPIError):
            await call.message.answer(
                text, reply_markup=kb, disable_web_page_preview=True
            )
    await call.answer()


@router.callback_query(F.data.startswith("menu:act:"))
async def cb_menu_action(
    call: CallbackQuery,
    store: Store,
    settings: Settings,
    images: ImageClient,
    state: FSMContext,
) -> None:
    """Кнопки inline-меню: те же действия, что и на постоянной клавиатуре."""
    user = call.from_user
    if user is None or call.data is None:
        return
    if not isinstance(call.message, Message):
        await call.answer()
        return
    action = call.data.rsplit(":", 1)[-1]
    lang = await user_lang(store, settings, user.id)
    role = await resolve_role(user.id, settings, store)

    if action == "check":
        await state.set_state(Check.awaiting)
        await call.message.answer(t(lang, "check.hint"))
    elif action == "styles":
        await store.ensure_user(user.id, user.username, user.first_name)
        await send_styles(call.message, store, settings, lang, user.id)
    elif action == "imagine":
        await state.set_state(Imagine.awaiting)
        await call.message.answer(t(lang, "img.ask_prompt"))
    elif action == "tickets":
        from tickets import render_my_tickets, render_ticket_list

        if is_staff(role):
            text, kb = await render_ticket_list(store, 0, admin=has_admin_access(role))
        else:
            text, kb = await render_my_tickets(store, user.id)
        await call.message.answer(text, reply_markup=kb)
    elif action == "files":
        await call.message.answer(
            t(
                lang,
                "file.help",
                mb=settings.file_max_mb,
                pages=settings.file_max_pdf_pages,
            )
        )
    elif action == "promo":
        await store.ensure_user(user.id, user.username, user.first_name)
        await state.set_state(Promo.awaiting)
        await call.message.answer(t(lang, "promo.ask"))
    elif action == "bonus":
        await store.ensure_user(user.id, user.username, user.first_name)
        text, claimed, amount = await bonus_view(store, settings, user.id, lang)
        await call.message.answer(text)
        await call.answer(
            t(lang, "bonus.ok_short", amount=amount)
            if claimed
            else t(lang, "bonus.already_short")
        )
        return
    elif action == "invite":
        await store.ensure_user(user.id, user.username, user.first_name)
        me = await call.bot.me()
        text, keyboard = await invite_view(
            store, settings, user.id, lang, me.username or settings.bot_name
        )
        await call.message.answer(text, reply_markup=keyboard)
    elif action == "help":
        await call.message.answer(
            await help_text(store, settings, lang, user.id),
            reply_markup=main_menu_kb(
                lang,
                staff=has_admin_access(role),
                payments=settings.payments_enabled,
                support=settings.support_ready,
            ),
        )
    elif action == "reset":
        await store.reset(user.id)
        await call.message.answer(t(lang, "reset.done"))
    elif action == "terms":
        from payments import render_terms

        runtime = await load_runtime(store, settings)
        await call.message.answer(render_terms(settings, runtime))
    elif action == "admin":
        if not has_admin_access(role):
            await call.answer(t(lang, "err.admin_only"), show_alert=True)
            return
        from admin import render_main

        text, kb = await render_main(store, settings, role)
        await call.message.answer(text, reply_markup=kb)
    await call.answer()


# --------------------------------------------------------------------------- обычный текст
@router.message(F.text)
async def on_text(
    message: Message,
    bot: Bot,
    store: Store,
    settings: Settings,
    ai: AIClient,
    images: ImageClient,
) -> None:
    if message.text.startswith("/"):
        # Неизвестную команду в личке не оставляем без ответа: иначе человек
        # думает, что бот сломан, а Telegram считает сообщение «без ответа».
        # Скрытые служебные команды (например, /admin) не подсвечиваем.
        command = message.text[1:].split()[0].split("@")[0].lower()
        if message.chat.type == "private" and command not in {"admin"}:
            lang = (
                await user_lang(store, settings, message.from_user.id)
                if message.from_user
                else settings.default_lang
            )
            await message.reply(t(lang, "err.unknown_command"))
        return  # в группах чужие команды молча пропускаем
    text = await addressed_text(message, bot, settings)
    if text is None:
        return

    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang

    replied = message.reply_to_message
    if (
        replied is not None
        and replied.document is not None
        and not files.is_image_document(
            replied.document.file_name, replied.document.mime_type
        )
    ):
        await handle_document(
            message,
            bot=bot,
            store=store,
            settings=settings,
            ai=ai,
            document=replied.document,
            instruction=text,
        )
        return

    # Ответ на фото: «что тут не так?» — картинку тоже передаём модели.
    if replied is not None and (
        replied.photo
        or (
            replied.document is not None
            and files.is_image_document(
                replied.document.file_name, replied.document.mime_type
            )
        )
    ):
        data, mime, _ = await load_image(replied, bot, lang)
        if data:
            await answer_with_ai(
                message,
                bot=bot,
                store=store,
                settings=settings,
                ai=ai,
                question=text or "Разбери это изображение и помоги с заданием.",
                image=data,
                image_mime=mime,
            )
            return

    # Ответ на сообщение бота: «пришли это в PDF» - собираем файл из ответа.
    if (
        replied is not None
        and replied.from_user is not None
        and replied.from_user.id == bot.id
        and replied.text
    ):
        fmt = files.detect_output_format(text) if files.wants_new_file(text) else None
        if fmt:
            plain = unescape(re.sub(r"<[^>]+>", "", replied.text))
            await send_file(
                message,
                plain,
                fmt,
                lang,
                name=files.suggest_filename(text, fmt),
            )
            return

    draw_match = DRAW_RE.match(text)
    if draw_match:
        await send_generated(
            message, images, settings, lang, text[draw_match.end() :].strip(), store=store
        )
        return

    if (
        re.match(r"(?i)^\s*(?:сделай|создай|сгенерируй|нарисуй)\b", text)
        and re.search(
            r"(?i)\b(?:фото|фотографию|фотку|картинк\w*|изображени\w*|рисунок|портрет)\b",
            text,
        )
    ):
        await send_generated(message, images, settings, lang, text, store=store)
        return

    await answer_with_ai(
        message, bot=bot, store=store, settings=settings, ai=ai, question=text
    )


@router.message()
async def on_other(message: Message, bot: Bot, store: Store, settings: Settings) -> None:
    if await addressed_text(message, bot, settings) is None:
        return
    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang
    await message.reply(t(lang, "other.only_text"))