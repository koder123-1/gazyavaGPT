"""Хендлеры: диалог с ИИ, квоты, кнопки под ответом, меню, режим проверки."""

from __future__ import annotations

import asyncio
import contextlib
import io
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from html import escape, unescape

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
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
)

import files
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
    "menu.support",
    "menu.tickets",
    "menu.files",
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
    lang: str, *, staff: bool = False, payments: bool = True
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
    rows.append(_button_row(lang, "menu.tickets", "menu.files"))
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
    lang: str, *, staff: bool = False, payments: bool = True
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


def html_parts(
    chunk: str, limit: int = HTML_LIMIT, *, code: bool = False
) -> list[tuple[str, str]]:
    """(html, plain) куски: HTML не должен вылезти за лимит Telegram.

    Экранирование (< -> &lt;) и теги удлиняют текст, поэтому кусок, который
    в plain-виде влезал, в HTML может не влезть. Тогда дробим ещё мельче.
    """
    html = to_telegram_html(chunk, code=code)
    if len(html) <= limit:
        return [(html, chunk)]
    # Пропорционально ужимаем plain-кусок под HTML-лимит.
    smaller = max(100, len(chunk) * limit // max(1, len(html)) - 1)
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
            await message.reply(plain, parse_mode=None, reply_markup=markup)


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
        if not mime.startswith("image/"):
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
    r"(?i)^\s*(?:нарисуй(?: мне)?|нарисуйте|сгенерируй(?: картинку| изображение| фото)?|"
    r"draw|generate(?: an? image)?|imagine|paint)\b[:,]?\s*"
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
    free_left = 0
    credits = 0
    charge = False
    if store is not None and user is not None:
        await store.ensure_user(user.id, user.username, user.first_name)
        admin = await is_admin(user.id, settings, store)
        limit = runtime.image_daily_limit if runtime else 0
        used = await store.image_used_today(user.id)
        credits = await store.image_credits(user.id)
        free_left = max(0, limit - used)
        if not admin and free_left <= 0 and credits <= 0:
            await message.reply(
                t(lang, "img.quota_exhausted", limit=limit),
                reply_markup=image_more_kb(prompt, lang),
            )
            return
        charge = not admin

    status = await message.reply(t(lang, "img.generating"))
    markup = image_more_kb(prompt, lang) if source is None else None
    try:
        if source is not None:
            data = await images.edit(source, mime, prompt)
        else:
            data = await images.generate(prompt)
        if not data:
            raise ImageError("empty")
        if charge and user is not None and store is not None:
            if free_left > 0:
                await store.consume_image(user.id)
            else:
                await store.add_image_credits(user.id, -1)
        await message.reply_photo(
            photo=BufferedInputFile(data, filename=image_filename(data)),
            caption=t(lang, "img.done", prompt=escape(prompt[:500])),
            parse_mode="HTML",
            reply_markup=markup,
        )
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
    if not prompt:
        await call.answer("Запрос устарел — напиши /imagine заново.", show_alert=True)
        return
    await call.answer("Рисую ещё вариант…")
    if call.message is None:
        return
    lang = await user_lang(store, settings, call.from_user.id)
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
            await message.reply(f"Вопрос обрезан до {MAX_INPUT_CHARS} символов.")

    payload_text = f"{instruction}\n\n---\n{question}" if instruction else question

    # «Сделай PDF с планом», «создай .py файл» — просим ИИ контент и отдаём файлом.
    out_fmt = (
        files.detect_output_format(question)
        if deliver and files.wants_new_file(question)
        else None
    )

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
            await send_file(message, last["content"], out_fmt, lang)
            return last["content"]

    chosen_model = await user_model(store, settings, runtime, user.id)

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
        await message.reply(t(lang, "err.ai", message=escape(str(exc))))
        return
    except Exception:  # noqa: BLE001
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
        log.warning("Модель вернула только рассуждения, ответ не отправлен")
        await message.reply(t(lang, "err.retry"))
        return

    if not admin:
        await store.consume(user.id, runtime.daily_limit)
    label = store_question or question
    await store.add_exchange(
        user.id,
        label,
        answer,
        keep=max(2, runtime.max_context * 2) if runtime.max_context else 2,
    )
    await store.add_exchange_record(user.id, label, answer, kind)
    if out_fmt:
        await send_file(message, answer, out_fmt, lang)
    elif deliver:
        await deliver_answer(message, answer, code=code_view, lang=lang)
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
    # Меню показываем сразу, даже если язык ещё не выбран: иначе новый
    # пользователь видит только выбор языка и не находит кнопки.
    await send_welcome(message, store, settings, lang)
    if not stored:
        await message.answer(t(lang, "lang.pick"), reply_markup=language_kb(lang))


@router.callback_query(F.data.startswith("lg:"))
async def cb_lang(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None or call.data is None:
        return
    code = normalize_lang(call.data.split(":", 1)[1], settings.default_lang)
    await store.set_lang(call.from_user.id, code)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(t(code, "lang.saved", name=LANG_NAMES[code]))
    await call.answer()
    if call.message:
        await send_welcome(call.message, store, settings, code, user=call.from_user)


@router.callback_query(F.data == "lang:menu")
async def cb_lang_menu(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    lang = await user_lang(store, settings, call.from_user.id)
    with contextlib.suppress(TelegramAPIError):
        await call.message.edit_text(t(lang, "lang.pick"), reply_markup=language_kb(lang))
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
        await call.answer()
        try:
            await send_model_invoice(bot, call.from_user.id, item, settings)
        except TelegramAPIError as exc:
            log.warning("Не удалось выставить счёт на модель %s: %s", value, exc)
            await call.answer(t(lang, "model.invoice"), show_alert=True)
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
        + t(lang, "help.support")
        + t(lang, "help.tail", model=escape(model_title(current_model)), lang=LANG_NAMES[lang])
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
            )
            if message.chat.type == "private"
            else None
        ),
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
    await message.answer(
        t(
            lang,
            "me.body",
            user_id=user.id,
            role_line=role_line,
            sub_line="",
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


async def send_file(message: Message, text: str, fmt: str, lang: str) -> None:
    """Собирает файл с ответом и отправляет его в чат."""
    fmt = fmt.lower()
    try:
        data, filename = await asyncio.to_thread(files.build_output, text, fmt)
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

    if len(data) > SEND_LIMIT_BYTES:
        await message.reply(t(lang, "file.build_failed", fmt=fmt.upper()))
        await send_answer(message, text)
        return

    try:
        await message.answer_document(
            BufferedInputFile(data, filename=filename),
            caption=t(lang, "file.caption", name=filename),
        )
    except TelegramAPIError:
        log.exception("Не удалось отправить файл %s — отдаю текстом", filename)
        await send_answer(message, text)


async def send_code_file(
    message: Message, code: str, language: str, index: int, lang: str
) -> bool:
    """Отправляет большой блок кода отдельным файлом. True, если получилось."""
    ext = CODE_EXT.get((language or "").strip().lower(), "txt")
    name = f"gazyavaGPT-{index}.{ext}"
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


async def deliver_answer(
    message: Message, text: str, *, code: bool, lang: str
) -> None:
    """Отправляет ответ: большой код — файлами, остальное — текстом."""
    rest, blocks = split_big_code(text)
    sent_blocks = 0
    for index, (language, source) in enumerate(blocks, 1):
        if await send_code_file(message, source, language, index, lang):
            sent_blocks += 1
    if rest.strip():
        await send_answer(message, rest, code=code)
    elif blocks and not sent_blocks:
        # Ни файл, ни текст не ушли — лучше показать код сообщением, чем молчать.
        await send_answer(message, text, code=code)


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

    name = doc.file_name or "file"
    ext = files.extension(name, doc.mime_type)
    if not files.is_supported(name, doc.mime_type):
        await message.reply(t(lang, "file.unsupported", ext=ext or "?"))
        return

    limit = settings.file_max_mb * 1024 * 1024
    if (doc.file_size or 0) > limit:
        await message.reply(t(lang, "file.too_big", mb=settings.file_max_mb))
        return

    status = await message.reply(t(lang, "file.reading"))
    try:
        buffer = io.BytesIO()
        await bot.download(doc, destination=buffer)
        data = buffer.getvalue()
        text = await asyncio.to_thread(
            files.extract_text,
            data,
            name,
            doc.mime_type,
            settings.file_max_pdf_pages,
        )
    except TelegramAPIError:
        await message.reply(t(lang, "file.download_failed"))
        return
    except files.FileError as exc:
        await message.reply(t(lang, exc.key, **exc.kwargs))
        return
    finally:
        with contextlib.suppress(Exception):
            await status.delete()

    text = files.clip_text(text, settings.file_max_chars)
    if not text.strip():
        await message.reply(t(lang, "file.empty"))
        return

    task = (instruction or "").strip()
    fmt = (
        files.detect_output_format(task)
        if files.wants_document_output(task)
        else None
    )
    if not task:
        task = t(lang, "file.default_task")
    elif fmt and files.is_pure_file_request(task):
        # «PDF», «пришли в DOCX» — просят переоформить, а не пересказать.
        task = t(lang, "file.convert_task")

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
        await send_file(message, answer, fmt, lang)


# --------------------------------------------------------------------------- картинки (фото)
@router.message(F.photo | F.document)
async def on_image(
    message: Message,
    bot: Bot,
    store: Store,
    settings: Settings,
    ai: AIClient,
    images: ImageClient,
) -> None:
    caption = await addressed_text(message, bot, settings)
    if caption is None:
        return

    user = message.from_user
    lang = await user_lang(store, settings, user.id) if user else settings.default_lang

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

    draw_match = DRAW_RE.match(caption or "")
    if draw_match:
        await send_generated(
            message,
            images,
            settings,
            lang,
            (caption or "")[draw_match.end() :].strip(),
            store=store,
        )
        return

    if caption and EDIT_RE.search(caption):
        await send_generated(
            message, images, settings, lang, caption, source=data, mime=mime, store=store
        )
        return

    check_mode = bool(
        re.search(r"провер|правильн|найди ошибк|\bcheck\b", caption or "", re.IGNORECASE)
    )
    question = caption or IMAGE_PROMPT

    status = await message.reply(t(lang, "image.checking"))
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
    "Пользователь прислал стикер. Опиши, что на нём изображено, и объясни смысл или настроение."
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
) -> None:
    text = await addressed_text(message, bot, settings)
    if text is None:
        return
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)

    video = message.video or message.animation or message.video_note
    limit = media.VIDEO_MAX_BYTES
    status = await message.reply(t(lang, "media.video_reading"))

    try:
        data, error = await _download_bytes(bot, video, limit)
        if error == "too_big":
            await status.delete()
            await message.reply(t(lang, "media.too_big", mb=limit // (1024 * 1024)))
            return
        if error or not data:
            await status.delete()
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
            await status.delete()
            await message.reply(t(lang, "media.video_failed"))
            return

        duration = int(getattr(video, "duration", 0) or 0)
        hint = f" Длительность: {duration} с." if duration else ""
        question = text.strip() or VIDEO_PROMPT
        with contextlib.suppress(Exception):
            await status.delete()
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
        with contextlib.suppress(Exception):
            await status.delete()


@router.message(F.sticker)
async def on_sticker(
    message: Message,
    bot: Bot,
    store: Store,
    settings: Settings,
    ai: AIClient,
) -> None:
    text = await addressed_text(message, bot, settings)
    if text is None:
        return
    user = message.from_user
    if user is None:
        return
    lang = await user_lang(store, settings, user.id)
    sticker = message.sticker

    # Анимированный .tgs — это gzip с векторами, его нельзя отдать vision-модели.
    if getattr(sticker, "is_animated", False):
        await message.reply(t(lang, "media.sticker_animated"))
        return

    data: bytes | None = None
    if getattr(sticker, "is_video", False):
        thumb_data, _ = await _download_bytes(
            bot, getattr(sticker, "thumbnail", None), 5 * 1024 * 1024
        )
        data = thumb_data
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
    new_id = await store.add_exchange_record(owner, exchange["question"], answer, action)
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
            ),
        )


@router.callback_query(F.data == "menu:home")
async def cb_menu_home(call: CallbackQuery, store: Store, settings: Settings) -> None:
    if call.from_user is None:
        return
    lang = await user_lang(store, settings, call.from_user.id)
    role = await resolve_role(call.from_user.id, settings, store)
    if call.message is not None:
        try:
            await call.message.answer(
                t(lang, "menu.title"),
                reply_markup=menu_inline(
                    lang,
                    staff=has_admin_access(role),
                    payments=settings.payments_enabled,
                ),
            )
        except TelegramAPIError:
            pass
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
    if user is None or call.data is None or call.message is None:
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
    elif action == "help":
        await call.message.answer(
            await help_text(store, settings, lang, user.id),
            reply_markup=main_menu_kb(
                lang,
                staff=has_admin_access(role),
                payments=settings.payments_enabled,
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
        return  # неизвестная команда — молча игнорируем
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

    # Ответ на сообщение бота: «пришли это в PDF» — собираем файл из ответа.
    if (
        replied is not None
        and replied.from_user is not None
        and replied.from_user.id == bot.id
        and replied.text
    ):
        fmt = files.detect_output_format(text) if files.wants_new_file(text) else None
        if fmt:
            plain = unescape(re.sub(r"<[^>]+>", "", replied.text))
            await send_file(message, plain, fmt, lang)
            return

    draw_match = DRAW_RE.match(text)
    if draw_match:
        await send_generated(
            message, images, settings, lang, text[draw_match.end() :].strip(), store=store
        )
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