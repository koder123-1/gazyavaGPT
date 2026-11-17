"""Быстрые команды-инструменты: считалка, генераторы, мелочи и учебные ИИ-команды.

Здесь собрано то, что не требует ИИ (калькулятор, пароль, UUID, хеш, Base64,
счётчик, кубик) и несколько учебных команд поверх общего ответчика
(`/translate`, `/summary`, `/explain`, `/quiz`). Утилиты не списывают запросы.
"""

from __future__ import annotations

import ast
import base64
import binascii
import contextlib
import hashlib
import json
import math
import operator
import random
import re
import secrets
import string
import time
import uuid
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from ai import AIClient
from config import Settings
from i18n import normalize_lang, t
from store import Store

router = Router(name="toolbox")

# Команды, которые имеют смысл только в личке.
PRIVATE_ONLY = {"todo", "stats", "password"}

TODO_LIMIT = 20
TODO_ITEM_CHARS = 200


# --------------------------------------------------------------------------- helpers
async def _lang(store: Store, settings: Settings, user_id: int) -> str:
    return normalize_lang(await store.get_lang(user_id) or settings.default_lang)


def _arg(message: Message) -> str:
    """Текст после команды."""
    parts = (message.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _reply_text(message: Message) -> str:
    replied = message.reply_to_message
    if replied is None:
        return ""
    return (replied.text or replied.caption or "").strip()


def _payload(message: Message) -> str:
    """Аргумент команды, а если его нет — текст сообщения, на которое ответили."""
    return _arg(message) or _reply_text(message)


async def _private_or_hint(message: Message, lang: str, settings: Settings) -> bool:
    """True, если можно продолжать. В группе подсказывает написать в личку."""
    if message.chat.type == "private":
        return True
    me = await message.bot.me()
    await message.reply(
        t(lang, "tool.private", username=me.username or settings.bot_name)
    )
    return False


async def _need_text(message: Message, lang: str) -> None:
    await message.reply(t(lang, "tool.need_text"))


# --------------------------------------------------------------------------- калькулятор
_ALLOWED_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Call,
    ast.Name,
    ast.Load,
)

_FUNCS = {
    "abs": abs,
    "round": round,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "floor": math.floor,
    "ceil": math.ceil,
    "factorial": math.factorial,
    "gcd": math.gcd,
    "degrees": math.degrees,
    "radians": math.radians,
}

_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


class _CalcError(Exception):
    pass


def _eval_node(node: ast.AST) -> float | int:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _CalcError
        return node.value
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand)
        return -value if isinstance(node.op, ast.USub) else +value
    if isinstance(node, ast.BinOp):
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow):
            # Не даём посчитать 9**9**9 и подвесить бота.
            if abs(right) > 1000 or abs(left) > 1e6:
                raise _CalcError
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise _CalcError
        functions = {
            ast.Add: operator.add,
            ast.Sub: operator.sub,
            ast.Mult: operator.mul,
            ast.Div: operator.truediv,
            ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod,
            ast.Pow: operator.pow,
        }
        return functions[type(node.op)](left, right)
    if isinstance(node, ast.Name):
        if node.id in _CONSTS:
            return _CONSTS[node.id]
        raise _CalcError
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise _CalcError
        if node.keywords:
            raise _CalcError
        args = [_eval_node(arg) for arg in node.args]
        if node.func.id == "factorial" and args and abs(args[0]) > 170:
            raise _CalcError
        return _FUNCS[node.func.id](*args)
    raise _CalcError


def calculate(expression: str) -> str:
    """Безопасно считает арифметику. Бросает _CalcError на мусоре."""
    source = (
        expression.replace("×", "*")
        .replace("÷", "/")
        .replace("−", "-")
        .replace("^", "**")
        .strip()
    )
    # Десятичная запятая (3,5), но не разделитель аргументов в gcd(12, 18).
    source = re.sub(r"(?<=\d),(?=\d)", ".", source)
    if not source or len(source) > 300:
        raise _CalcError
    tree = ast.parse(source, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise _CalcError
    value = _eval_node(tree)
    if isinstance(value, complex):
        raise _CalcError
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise _CalcError
        if value.is_integer() and abs(value) < 1e15:
            value = int(value)
        else:
            text = f"{value:.10g}"
            return text
    if isinstance(value, int) and abs(value) > 10**18:
        raise _CalcError
    return str(value)


@router.message(Command("calc", "math", "кальк", "посчитай"))
async def cmd_calc(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    expression = _payload(message)
    if not expression:
        await message.reply(t(lang, "calc.help"))
        return
    try:
        result = calculate(expression)
    except (SyntaxError, _CalcError, ValueError, OverflowError, TypeError):
        await message.reply(t(lang, "calc.error"))
        return
    await message.reply(
        t(lang, "calc.result", expr=escape(expression[:120]), result=escape(result)),
        parse_mode="HTML",
    )


# --------------------------------------------------------------------------- генераторы
@router.message(Command("random", "рандом", "случайное"))
async def cmd_random(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    raw = _arg(message)
    if "|" in raw:
        choices = [item.strip() for item in raw.split("|") if item.strip()]
        if len(choices) < 2:
            await message.reply(t(lang, "random.help"))
            return
        value = random.choice(choices)
        await message.reply(t(lang, "random.choice", value=escape(value)), parse_mode="HTML")
        return
    numbers = [part for part in raw.replace(",", " ").split() if part]
    try:
        if not numbers:
            low, high = 1, 100
        elif len(numbers) == 1:
            low, high = 1, int(numbers[0])
        else:
            low, high = int(numbers[0]), int(numbers[1])
    except ValueError:
        await message.reply(t(lang, "random.help"))
        return
    if low > high:
        low, high = high, low
    if high - low > 10**9:
        await message.reply(t(lang, "random.help"))
        return
    await message.reply(
        t(lang, "random.number", value=random.randint(low, high), low=low, high=high),
        parse_mode="HTML",
    )


@router.message(Command("coin", "монетка", "орёл"))
async def cmd_coin(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    side = random.choice(("heads", "tails"))
    await message.reply(
        t(lang, "coin.result", value=t(lang, f"coin.{side}")), parse_mode="HTML"
    )


@router.message(Command("dice", "кубик", "кости"))
async def cmd_dice(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    raw = _arg(message)
    try:
        sides = int(raw) if raw else 6
    except ValueError:
        sides = 6
    if not 2 <= sides <= 100:
        sides = 6
    await message.reply(
        t(lang, "dice.result", value=random.randint(1, sides), sides=sides),
        parse_mode="HTML",
    )


# --------------------------------------------------------------------------- кодирование
@router.message(Command("password", "пароль"))
async def cmd_password(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else normalize_lang(settings.default_lang)
    if not await _private_or_hint(message, lang, settings) or user is None:
        return
    raw = _arg(message)
    try:
        length = int(raw) if raw else 16
    except ValueError:
        length = 16
    length = max(8, min(length, 64))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
    while True:
        value = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.islower() for c in value)
            and any(c.isupper() for c in value)
            and any(c.isdigit() for c in value)
            and any(c in "!@#$%^&*()-_=+" for c in value)
        ):
            break
    await message.reply(
        t(lang, "password.result", length=length, value=escape(value)),
        parse_mode="HTML",
    )


@router.message(Command("uuid"))
async def cmd_uuid(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    raw = _arg(message)
    try:
        count = int(raw) if raw else 1
    except ValueError:
        count = 1
    count = max(1, min(count, 10))
    values = [str(uuid.uuid4()) for _ in range(count)]
    await message.reply(
        t(lang, "uuid.result", count=count, value="\n".join(values)),
        parse_mode="HTML",
    )


@router.message(Command("hash", "хеш"))
async def cmd_hash(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    text = _payload(message)
    if not text:
        await _need_text(message, lang)
        return
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    await message.reply(
        t(lang, "hash.result", value=digest), parse_mode="HTML"
    )


@router.message(Command("base64", "б64"))
async def cmd_base64(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    raw = _payload(message)
    if not raw:
        await _need_text(message, lang)
        return
    mode, _, rest = raw.partition(" ")
    if mode.lower() in {"decode", "декод", "расшифруй"} and rest.strip():
        try:
            decoded = base64.b64decode(rest.strip(), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            await message.reply(t(lang, "b64.error"))
            return
        await message.reply(
            t(lang, "b64.decoded", value=escape(decoded[:1500])), parse_mode="HTML"
        )
        return
    if mode.lower() in {"encode", "код", "зашифруй"} and rest.strip():
        raw = rest.strip()
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    await message.reply(
        t(lang, "b64.encoded", value=encoded[:1500]), parse_mode="HTML"
    )


@router.message(Command("count", "счёт", "счет"))
async def cmd_count(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    text = _payload(message)
    if not text:
        await _need_text(message, lang)
        return
    await message.reply(
        t(
            lang,
            "count.result",
            chars=len(text),
            nospace=len("".join(text.split())),
            words=len(text.split()),
            lines=len(text.splitlines()) or 1,
        ),
        parse_mode="HTML",
    )


# --------------------------------------------------------------------------- информация
@router.message(Command("id"))
async def cmd_id(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    reply = ""
    replied = message.reply_to_message
    if replied is not None and replied.from_user is not None:
        target = replied.from_user
        name = target.full_name or str(target.id)
        reply = t(
            lang, "id.reply", name=escape(name), user_id=target.id
        )
    await message.reply(
        t(
            lang,
            "id.result",
            user_id=user.id if user else "—",
            chat_id=message.chat.id,
            reply=reply,
        ),
        parse_mode="HTML",
    )


@router.message(Command("ping", "пинг"))
async def cmd_ping(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    started = time.perf_counter()
    status = await message.reply(t(lang, "ping.checking"))
    elapsed = (time.perf_counter() - started) * 1000
    now = datetime.now(timezone.utc)
    text = t(
        lang,
        "ping.result",
        ms=f"{elapsed:.0f}",
        time=now.strftime("%H:%M:%S UTC"),
    )
    try:
        await status.edit_text(text, parse_mode="HTML")
    except TelegramAPIError:
        # В канале бот может не иметь права редактировать: лучше убрать
        # служебное «Пингую…», чем оставить его висеть.
        with contextlib.suppress(TelegramAPIError):
            await status.delete()


@router.message(Command("time", "время"))
async def cmd_time(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    now = datetime.now(timezone.utc)
    msk = now + timedelta(hours=3)
    await message.reply(
        t(
            lang,
            "time.result",
            utc=now.strftime("%H:%M"),
            msk=msk.strftime("%H:%M"),
            date=msk.strftime("%d.%m.%Y"),
        ),
        parse_mode="HTML",
    )


# --------------------------------------------------------------------------- дела и статистика
async def _todo_load(store: Store, user_id: int) -> list[str]:
    raw = await store.get_setting(f"todo:{user_id}")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item)[:TODO_ITEM_CHARS] for item in data if str(item).strip()][:TODO_LIMIT]


async def _todo_save(store: Store, user_id: int, items: list[str]) -> None:
    await store.set_setting(f"todo:{user_id}", json.dumps(items, ensure_ascii=False))


def _todo_lines(items: list[str]) -> str:
    return "\n".join(f"{index}. {escape(item)}" for index, item in enumerate(items, 1))


@router.message(Command("todo", "дела", "задачи"))
async def cmd_todo(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else normalize_lang(settings.default_lang)
    if not await _private_or_hint(message, lang, settings) or user is None:
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    raw = _arg(message)
    action, _, rest = raw.partition(" ")
    action = action.strip().lower()
    rest = rest.strip()
    items = await _todo_load(store, user.id)

    if not action or action in {"list", "список", "все"}:
        if not items:
            await message.reply(t(lang, "todo.empty"))
        else:
            await message.reply(
                t(lang, "todo.list", count=len(items), items=_todo_lines(items)),
                parse_mode="HTML",
            )
        return

    if action in {"add", "добавь", "добавить", "+"}:
        if not raw.split(maxsplit=1)[1:]:
            await message.reply(t(lang, "todo.help"))
            return
        if len(items) >= TODO_LIMIT:
            await message.reply(t(lang, "todo.full", limit=TODO_LIMIT))
            return
        items.append(rest[:TODO_ITEM_CHARS])
        await _todo_save(store, user.id, items)
        await message.reply(
            t(lang, "todo.added", item=escape(rest[:TODO_ITEM_CHARS])),
            parse_mode="HTML",
        )
        return

    if action in {"done", "del", "delete", "готово", "удали", "удалить", "-"}:
        try:
            index = int(rest)
        except ValueError:
            await message.reply(t(lang, "todo.help"))
            return
        if not 1 <= index <= len(items):
            await message.reply(t(lang, "todo.bad_index"))
            return
        removed = items.pop(index - 1)
        await _todo_save(store, user.id, items)
        await message.reply(
            t(lang, "todo.done", item=escape(removed)), parse_mode="HTML"
        )
        return

    if action in {"clear", "очисти", "сброс"}:
        await _todo_save(store, user.id, [])
        await message.reply(t(lang, "todo.cleared"))
        return

    # Всё остальное считаем новым делом: /todo купить хлеб.
    if len(items) >= TODO_LIMIT:
        await message.reply(t(lang, "todo.full", limit=TODO_LIMIT))
        return
    items.append(raw[:TODO_ITEM_CHARS])
    await _todo_save(store, user.id, items)
    await message.reply(
        t(lang, "todo.added", item=escape(raw[:TODO_ITEM_CHARS])), parse_mode="HTML"
    )


@router.message(Command("stats", "стата", "статистика"))
async def cmd_stats(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else normalize_lang(settings.default_lang)
    if not await _private_or_hint(message, lang, settings) or user is None:
        return
    await store.ensure_user(user.id, user.username, user.first_name)
    from runtime import load_runtime

    runtime = await load_runtime(store, settings)
    card = await store.user_card(user.id) or {}
    bonus = await store.bonus_requests(user.id)
    streak = await store.bonus_streak(user.id)
    invites = await store.referral_count(user.id)
    if runtime.daily_limit <= 0:
        left_text = "∞"
    else:
        left_text = str(await store.remaining(user.id, runtime.daily_limit))
    await message.reply(
        t(
            lang,
            "stats.body",
            used=card.get("used_today", 0),
            total=card.get("total_requests", 0),
            left=left_text,
            bonus=bonus,
            streak=streak,
            invites=invites,
            images=card.get("image_credits", 0),
        ),
        parse_mode="HTML",
    )


# --------------------------------------------------------------------------- учебные ИИ-команды
_TRANSLATE_TARGETS = {
    "ru": "ru",
    "рус": "ru",
    "русский": "ru",
    "uk": "uk",
    "укр": "uk",
    "украинский": "uk",
    "be": "be",
    "бел": "be",
    "en": "en",
    "англ": "en",
    "английский": "en",
    "de": "de",
    "нем": "de",
    "немецкий": "de",
    "fr": "fr",
    "франц": "fr",
    "es": "es",
    "исп": "es",
    "it": "it",
    "итал": "it",
    "pl": "pl",
    "польск": "pl",
    "tr": "tr",
    "турец": "tr",
    "zh": "zh",
    "кит": "zh",
    "ja": "ja",
    "яп": "ja",
    "ko": "ko",
    "кор": "ko",
    "ar": "ar",
    "араб": "ar",
}

_LANG_FULL = {
    "ru": "русский",
    "uk": "украинский",
    "be": "белорусский",
    "en": "английский",
    "de": "немецкий",
    "fr": "французский",
    "es": "испанский",
    "it": "итальянский",
    "pl": "польский",
    "tr": "турецкий",
    "zh": "китайский",
    "ja": "японский",
    "ko": "корейский",
    "ar": "арабский",
}


@router.message(Command("translate", "перевод", "переведи"))
async def cmd_translate(
    message: Message, bot: Bot, store: Store, settings: Settings, ai: AIClient
) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await _lang(store, settings, user.id)
    raw = _payload(message)
    if not raw:
        await _need_text(message, lang)
        return
    target = lang
    first, _, tail = raw.partition(" ")
    if first.lower() in _TRANSLATE_TARGETS and tail.strip():
        target = _TRANSLATE_TARGETS[first.lower()]
        raw = tail.strip()
    instruction = (
        f"Переведи текст на {_LANG_FULL.get(target, target)} язык. "
        "Верни только перевод: без пояснений, заголовков, кавычек и списка "
        "языков. Сохрани абзацы, списки и форматирование оригинала."
    )
    from handlers import answer_with_ai

    await answer_with_ai(
        message,
        bot=bot,
        store=store,
        settings=settings,
        ai=ai,
        question=raw,
        instruction=instruction,
        use_history=False,
    )


@router.message(Command("summary", "кратко", "пересказ"))
async def cmd_summary(
    message: Message, bot: Bot, store: Store, settings: Settings, ai: AIClient
) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await _lang(store, settings, user.id)
    raw = _payload(message)
    if not raw:
        await _need_text(message, lang)
        return
    instruction = (
        "Сделай краткий пересказ текста: 3–5 коротких пунктов с главным и один "
        "вывод в конце. Пиши на языке текста. Не выдумывай факты, которых нет "
        "в тексте."
    )
    from handlers import answer_with_ai

    await answer_with_ai(
        message,
        bot=bot,
        store=store,
        settings=settings,
        ai=ai,
        question=raw,
        instruction=instruction,
        use_history=False,
    )


@router.message(Command("explain", "объясни"))
async def cmd_explain(
    message: Message, bot: Bot, store: Store, settings: Settings, ai: AIClient
) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await _lang(store, settings, user.id)
    raw = _payload(message)
    if not raw:
        await _need_text(message, lang)
        return
    instruction = (
        "Объясни это простыми словами, как для школьника: по шагам, с одним "
        "бытовым примером и коротким итогом. Пиши на языке текста. Без воды и "
        "без повторения условия."
    )
    from handlers import answer_with_ai

    await answer_with_ai(
        message,
        bot=bot,
        store=store,
        settings=settings,
        ai=ai,
        question=raw,
        instruction=instruction,
        use_history=False,
    )


@router.message(Command("quiz", "квиз", "вопросы"))
async def cmd_quiz(
    message: Message, bot: Bot, store: Store, settings: Settings, ai: AIClient
) -> None:
    user = message.from_user
    if user is None:
        return
    lang = await _lang(store, settings, user.id)
    topic = _payload(message)
    if not topic:
        await message.reply(t(lang, "quiz.help"))
        return
    instruction = (
        "Составь тренировочный тест по теме: 5 вопросов, у каждого 4 варианта "
        "ответа (A–D). В конце отдельным блоком дай ключ: номер — правильная "
        "буква и одно короткое пояснение. Пиши на языке темы."
    )
    from handlers import answer_with_ai

    await answer_with_ai(
        message,
        bot=bot,
        store=store,
        settings=settings,
        ai=ai,
        question=topic,
        instruction=instruction,
        use_history=False,
    )


# --------------------------------------------------------------------------- опросы
@router.message(Command("poll", "опрос"))
async def cmd_poll(message: Message, store: Store, settings: Settings) -> None:
    """`/poll Вопрос | вариант | вариант` и `/poll -m ...` для нескольких ответов."""
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else normalize_lang(settings.default_lang)
    raw = _arg(message)
    multiple = False
    lowered = raw.lower()
    if lowered.startswith("-m ") or lowered.startswith("--multi "):
        multiple = True
        raw = raw.split(maxsplit=1)[1] if " " in raw else ""
    if not raw:
        await message.reply(t(lang, "poll.help"), parse_mode="HTML")
        return
    chunks = [part.strip() for part in raw.split("|")]
    question = chunks[0][:300]
    options = [part[:100] for part in chunks[1:] if part][:10]
    if len(options) < 2 or not question:
        await message.reply(t(lang, "poll.error"), parse_mode="HTML")
        return
    try:
        await message.bot.send_poll(
            chat_id=message.chat.id,
            question=question,
            options=options,
            is_anonymous=True,
            allows_multiple_answers=multiple,
        )
    except TelegramAPIError:
        await message.reply(t(lang, "poll.error"), parse_mode="HTML")


# --------------------------------------------------------------------------- карточки
CARD_LIMIT = 100
CARD_ITEM_CHARS = 400


async def _card_owner(message: Message) -> int:
    """В канале автора нет: карточки канала живут под его chat_id."""
    return message.from_user.id if message.from_user else message.chat.id


async def _cards_load(store: Store, owner: int) -> list[dict]:
    raw = await store.get_setting(f"card:{owner}")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    cards: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        question = str(row.get("q") or "").strip()
        answer = str(row.get("a") or "").strip()
        if question and answer:
            cards.append({"q": question[:CARD_ITEM_CHARS], "a": answer[:CARD_ITEM_CHARS]})
    return cards[:CARD_LIMIT]


async def _cards_save(store: Store, owner: int, cards: list[dict]) -> None:
    key = f"card:{owner}"
    if not cards:
        await store.delete_setting(key)
        return
    await store.set_setting(key, json.dumps(cards, ensure_ascii=False))


def _card_keyboard(lang: str, owner: int, index: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👀 " + t(lang, "card.show_button"),
                    callback_data=f"card:a:{owner}:{index}",
                )
            ]
        ]
    )


async def _send_random_card(
    message: Message, store: Store, settings: Settings, lang: str, owner: int
) -> None:
    cards = await _cards_load(store, owner)
    if not cards:
        await message.reply(t(lang, "card.empty"), parse_mode="HTML")
        return
    index = random.randrange(len(cards))
    card = cards[index]
    await message.reply(
        t(lang, "card.show", id=index + 1, question=escape(card["q"])),
        parse_mode="HTML",
        reply_markup=_card_keyboard(lang, owner, index),
    )


@router.message(Command("cards", "карточки"))
async def cmd_cards(message: Message, store: Store, settings: Settings) -> None:
    owner = await _card_owner(message)
    lang = await _lang(store, settings, owner)
    cards = await _cards_load(store, owner)
    if not cards:
        await message.reply(t(lang, "card.empty"), parse_mode="HTML")
        return
    items = "\n".join(
        t(lang, "card.item", id=index, question=escape(card["q"]))
        for index, card in enumerate(cards, 1)
    )
    await message.reply(
        t(lang, "card.list", count=len(cards), items=items), parse_mode="HTML"
    )


@router.message(Command("card", "карточка"))
async def cmd_card(message: Message, store: Store, settings: Settings) -> None:
    owner = await _card_owner(message)
    lang = await _lang(store, settings, owner)
    raw = _arg(message)
    if not raw:
        await _send_random_card(message, store, settings, lang, owner)
        return
    action, _, rest = raw.partition(" ")
    action = action.strip().lower()
    rest = rest.strip()
    cards = await _cards_load(store, owner)

    if action in {"add", "добавь", "добавить", "+"}:
        if "|" not in rest:
            await message.reply(t(lang, "card.need_both"), parse_mode="HTML")
            return
        question, _, answer = rest.partition("|")
        question, answer = question.strip(), answer.strip()
        if not question or not answer:
            await message.reply(t(lang, "card.need_both"), parse_mode="HTML")
            return
        if len(cards) >= CARD_LIMIT:
            await message.reply(t(lang, "card.full", limit=CARD_LIMIT), parse_mode="HTML")
            return
        cards.append(
            {"q": question[:CARD_ITEM_CHARS], "a": answer[:CARD_ITEM_CHARS]}
        )
        await _cards_save(store, owner, cards)
        await message.reply(
            t(lang, "card.added", id=len(cards), question=escape(question[:CARD_ITEM_CHARS])),
            parse_mode="HTML",
        )
        return

    if action in {"del", "delete", "удали", "удалить", "-"}:
        try:
            index = int(rest)
        except ValueError:
            await message.reply(t(lang, "card.del_help"), parse_mode="HTML")
            return
        if not 1 <= index <= len(cards):
            await message.reply(t(lang, "card.not_found", id=index), parse_mode="HTML")
            return
        cards.pop(index - 1)
        await _cards_save(store, owner, cards)
        await message.reply(t(lang, "card.deleted", id=index), parse_mode="HTML")
        return

    if action in {"clear", "очисти", "сброс"}:
        await _cards_save(store, owner, [])
        await message.reply(t(lang, "card.cleared"), parse_mode="HTML")
        return

    # `/card Вопрос | Ответ` — короткий путь вместо `add`.
    if "|" in raw:
        question, _, answer = raw.partition("|")
        question, answer = question.strip(), answer.strip()
        if not question or not answer:
            await message.reply(t(lang, "card.need_both"), parse_mode="HTML")
            return
        if len(cards) >= CARD_LIMIT:
            await message.reply(t(lang, "card.full", limit=CARD_LIMIT), parse_mode="HTML")
            return
        cards.append(
            {"q": question[:CARD_ITEM_CHARS], "a": answer[:CARD_ITEM_CHARS]}
        )
        await _cards_save(store, owner, cards)
        await message.reply(
            t(lang, "card.added", id=len(cards), question=escape(question[:CARD_ITEM_CHARS])),
            parse_mode="HTML",
        )
        return

    await message.reply(t(lang, "card.help"), parse_mode="HTML")


@router.callback_query(F.data.startswith("card:a:"))
async def cb_card_answer(
    callback: CallbackQuery, store: Store, settings: Settings
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4 or not parts[2].lstrip("-").isdigit() or not parts[3].isdigit():
        await callback.answer()
        return
    owner, index = int(parts[2]), int(parts[3])
    lang = await _lang(store, settings, owner)
    cards = await _cards_load(store, owner)
    if not 0 <= index < len(cards):
        await callback.answer(t(lang, "card.not_found", id=index + 1), show_alert=True)
        return
    card = cards[index]
    text = (
        t(lang, "card.show", id=index + 1, question=escape(card["q"]))
        + "\n\n"
        + t(lang, "card.answer", answer=escape(card["a"]))
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 " + t(lang, "card.next_button"),
                    callback_data=f"card:r:{owner}",
                )
            ]
        ]
    )
    with contextlib.suppress(TelegramAPIError):
        await callback.message.edit_text(
            text, parse_mode="HTML", reply_markup=keyboard
        )
    await callback.answer()


@router.callback_query(F.data.startswith("card:r:"))
async def cb_card_next(
    callback: CallbackQuery, store: Store, settings: Settings
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 3 or not parts[2].lstrip("-").isdigit():
        await callback.answer()
        return
    owner = int(parts[2])
    lang = await _lang(store, settings, owner)
    cards = await _cards_load(store, owner)
    if not cards:
        await callback.answer(t(lang, "card.empty"), show_alert=True)
        return
    index = random.randrange(len(cards))
    card = cards[index]
    with contextlib.suppress(TelegramAPIError):
        await callback.message.edit_text(
            t(lang, "card.show", id=index + 1, question=escape(card["q"])),
            parse_mode="HTML",
            reply_markup=_card_keyboard(lang, owner, index),
        )
    await callback.answer()


# --------------------------------------------------------------------------- справка
@router.message(Command("tools", "инструменты"))
async def cmd_tools(message: Message, store: Store, settings: Settings) -> None:
    user = message.from_user
    lang = await _lang(store, settings, user.id) if user else settings.default_lang
    await message.reply(t(lang, "tools.help"), parse_mode="HTML")


# --------------------------------------------------------------------------- каналы
# В канал пишут только администраторы, поэтому утилиты безопасны и там:
# считалка, генераторы, ID канала, пинг. Личные команды (todo/stats/password)
# в канал не регистрируем — они подскажут написать в личку.
_CHANNEL_COMMANDS: tuple[tuple[object, tuple[str, ...]], ...] = (
    (cmd_calc, ("calc", "math", "кальк", "посчитай")),
    (cmd_random, ("random", "рандом", "случайное")),
    (cmd_coin, ("coin", "монетка", "орёл")),
    (cmd_dice, ("dice", "кубик", "кости")),
    (cmd_uuid, ("uuid",)),
    (cmd_hash, ("hash", "хеш")),
    (cmd_base64, ("base64", "б64")),
    (cmd_count, ("count", "счёт", "счет")),
    (cmd_id, ("id",)),
    (cmd_ping, ("ping", "пинг")),
    (cmd_time, ("time", "время")),
    (cmd_poll, ("poll", "опрос")),
    (cmd_card, ("card", "карточка")),
    (cmd_cards, ("cards", "карточки")),
    (cmd_tools, ("tools", "инструменты", "help", "помощь")),
    # Личные команды в канале не выполняются, но вежливо зовут в личку.
    (cmd_password, ("password", "пароль")),
    (cmd_todo, ("todo", "дела", "задачи")),
    (cmd_stats, ("stats", "стата", "статистика")),
)

for _handler, _commands in _CHANNEL_COMMANDS:
    router.channel_post(Command(*_commands))(_handler)