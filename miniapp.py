"""Telegram Mini App: личный кабинет на том же aiohttp-сервере, что и бот.

Мини-приложение — это обычная веб-страница, которую Telegram открывает внутри
себя. Отдельного хостинга и новых зависимостей не нужно: файлы лежат в папке
`miniapp/`, а данные отдаёт это же приложение по `/app/api/*`.

Авторизация без пароля: клиент присылает `initData`, сервер проверяет подпись
`BOT_TOKEN` через HMAC (`check_webapp_signature`) и так узнаёт `user_id`.
Подделать подпись нельзя, поэтому доверять `initDataUnsafe` не приходится.

Гейт подписки тот же, что и в боте: если настройка канала задана и Telegram
говорит «не подписан» — отдаём 403 с ссылкой на канал. Если проверить не
удалось (UNKNOWN) — пропускаем, как и в остальном боте.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile, LabeledPrice
from aiogram.utils.web_app import check_webapp_signature
from aiohttp import web

import gamification
import models as model_catalog
import payments
import reminders
import share
import styles as style_catalog
import toolbox
from config import Settings
from i18n import LANGS, normalize_lang
from roles import (
    ASSIGNABLE,
    RANKS,
    ROLE_ADMIN,
    ROLE_HEAD_ADMIN,
    ROLE_SUPPORT,
    can_assign,
    can_manage_roles as _can_manage_roles,
    has_admin_access as _has_admin,
    is_staff,
    rank,
    resolve_role,
    role_title as _role_title,
)
from runtime import load_runtime
from store import Store
from subscription import (
    NOT_SUBSCRIBED,
    current_channel,
    membership,
)

log = logging.getLogger("miniapp")

BASE_DIR = Path(__file__).resolve().parent / "miniapp"
STYLES = tuple(style_catalog.STYLE_KEYS)

# initData старше этих секунд считаем просроченным (защита от replay).
AUTH_MAX_AGE = 24 * 3600

# Имя бота для ссылок-приглашений. Проставляется на старте из getMe.
_bot_username: str = ""


def set_bot_username(username: str | None) -> None:
    global _bot_username
    _bot_username = (username or "").strip().lstrip("@")


def webapp_url(settings: Settings) -> str:
    """Публичный адрес Mini App или пустая строка, если webhook выключен."""
    if not settings.use_webhook:
        return ""
    return f"{settings.base_url.rstrip('/')}/app"


# --------------------------------------------------------------------------- авторизация
def parse_init_data(token: str, raw: str) -> dict[str, Any] | None:
    """Проверяет подпись initData и возвращает поля, включая разобранный `user`.

    `WebAppInitData.model_validate` не годится: Telegram шлёт `user`/`chat`/`receiver`
    JSON-строками, а pydantic ждёт словарь. Поэтому разбираем вручную.
    """
    if not raw or not token:
        return None
    try:
        if not check_webapp_signature(token, raw):
            return None
    except Exception:  # noqa: BLE001 — мусор в initData не должен ронять сервер
        return None

    data = dict(parse_qsl(raw, keep_blank_values=True))
    for field in ("user", "chat", "receiver"):
        value = data.get(field)
        if not value:
            continue
        try:
            data[field] = json.loads(value)
        except (TypeError, ValueError):
            data[field] = None

    user = data.get("user")
    if not isinstance(user, dict) or not user.get("id"):
        return None

    try:
        auth_date = int(data.get("auth_date") or 0)
    except (TypeError, ValueError):
        auth_date = 0
    if auth_date and time.time() - auth_date > AUTH_MAX_AGE:
        return None
    return data


async def _read_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — пустое/битое тело равносильно отсутствию подписи
        return {}
    return body if isinstance(body, dict) else {}


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _auth(
    request: web.Request, *, use_body: bool = True
) -> tuple[dict[str, Any] | None, web.Response | None]:
    settings: Settings = request.app["miniapp_settings"]
    body = await _read_body(request) if use_body else {}
    raw = body.get("init_data") or request.headers.get("X-Init-Data") or ""
    data = parse_init_data(settings.bot_token, str(raw))
    if data is None:
        return None, web.json_response({"error": "unauthorized"}, status=401)
    return data, None


async def _gate(request: web.Request, user_id: int) -> web.Response | None:
    """Пускает только подписанных. Не смогли проверить — пропускаем (fail-open)."""
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    bot: Bot = request.app["miniapp_bot"]
    channel, url = await current_channel(store, settings)
    if not channel:
        return None
    state = await membership(bot, channel, user_id)
    if state == NOT_SUBSCRIBED:
        return web.json_response(
            {"error": "subscription", "url": url, "channel": channel.lstrip("@")},
            status=403,
        )
    return None


def _lang_of(value: str | None, settings: Settings) -> str:
    return normalize_lang(value, settings.default_lang)


# --------------------------------------------------------------------------- обработчики
async def _no_cache(request: web.Request, response: web.StreamResponse) -> None:
    """Оболочка Mini App не кешируется.

    Иначе после деплоя браузер продолжает отдавать старый CSS/JS: HTML и ассеты
    живут по одним и тем же путям, а без `Cache-Control` webview применяет
    эвристическое кеширование. `no-cache` не запрещает кеш, а требует
    ревалидацию — при неизменном файле aiohttp ответит 304 и трафик не вырастет.
    """
    path = request.path
    if path in ("/app", "/app/") or path.startswith("/app/assets/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        response.headers["Pragma"] = "no-cache"


async def index(_: web.Request) -> web.FileResponse:
    """Отдаёт страницу Mini App."""
    return web.FileResponse(BASE_DIR / "index.html")


async def api_me(request: web.Request) -> web.Response:
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user = data["user"]
    user_id = int(user["id"])

    gate = await _gate(request, user_id)
    if gate is not None:
        return gate

    await store.ensure_user(user_id, user.get("username"), user.get("first_name"))
    runtime = await load_runtime(store, settings)
    lang = _lang_of(await store.get_lang(user_id), settings)
    style = style_catalog.normalize_style(await store.get_style(user_id))
    model = await store.get_model(user_id) or runtime.model
    # Сотрудники лимитом не ограничены (бот им не отказывает), поэтому в кабинете
    # показываем «∞», хотя расход всё равно считается в статистике.
    role = await resolve_role(user_id, settings, store)
    unlimited = runtime.daily_limit <= 0 or is_staff(role)
    left = await store.remaining(user_id, runtime.daily_limit)
    card = await store.user_card(user_id) or {}
    username = _bot_username
    invite_link = (
        f"https://t.me/{username}?start=ref_{user_id}" if username else ""
    )

    return web.json_response(
        {
            "user": {
                "id": user_id,
                "first_name": user.get("first_name") or "",
                "username": user.get("username") or "",
            },
            "lang": lang,
            "style": style,
            "model": {"id": model, "title": model_catalog.title(model)},
            "models": [
                {"id": item.id, "title": item.title}
                for item in model_catalog.CATALOG
                if not item.stars or await store.has_model_access(user_id, item.id)
            ],
            "unlimited": unlimited,
            "remaining": None if unlimited else int(left),
            "used_today": int(card.get("used_today", 0) or 0),
            "total_requests": int(card.get("total_requests", 0) or 0),
            "bonus_requests": await store.bonus_requests(user_id),
            "bonus_streak": await store.bonus_streak(user_id),
            "bonus_claimed_today": await store.bonus_claimed_today(user_id),
            "gamification": await gamification.profile_payload(store, user_id, lang),
            "bonus_base": settings.bonus_base,
            "bonus_max": settings.bonus_max,
            "invites": await store.referral_count(user_id),
            "invite_reward": settings.invite_reward,
            "invited_reward": settings.invited_reward,
            "invite_link": invite_link,
            "bot_name": settings.bot_name,
            "image_credits": int(card.get("image_credits", 0) or 0),
            "payments_enabled": settings.payments_enabled,
            "support_enabled": settings.support_ready,
            "langs": list(LANGS),
            "styles": list(STYLES),
            "daily_limit": runtime.daily_limit,
            "role": role or "",
            "role_title": _role_title(role),
            "is_staff": is_staff(role),
            "is_admin": _has_admin(role),
            "can_manage_roles": _can_manage_roles(role),
        }
    )


async def api_bonus(request: web.Request) -> web.Response:
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user = data["user"]
    user_id = int(user["id"])

    gate = await _gate(request, user_id)
    if gate is not None:
        return gate

    await store.ensure_user(user_id, user.get("username"), user.get("first_name"))
    result = await store.daily_bonus(user_id, settings.bonus_base, settings.bonus_max)
    runtime = await load_runtime(store, settings)
    unlimited = runtime.daily_limit <= 0
    left = await store.remaining(user_id, runtime.daily_limit)
    return web.json_response(
        {
            "claimed": bool(result["claimed"]),
            "amount": int(result["amount"]),
            "streak": int(result["streak"]),
            "bonus_requests": await store.bonus_requests(user_id),
            "remaining": None if unlimited else int(left),
            "bonus_max": settings.bonus_max,
        }
    )


async def api_promo(request: web.Request) -> web.Response:
    """Активация промокода из Mini App: начисляет запросы и/или генерации."""
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user = data["user"]
    user_id = int(user["id"])
    gate = await _gate(request, user_id)
    if gate is not None:
        return gate
    body = await _read_body(request)
    code = str(body.get("code") or "").strip().upper()
    if not code:
        return web.json_response({"ok": False, "status": "empty"})
    await store.ensure_user(user_id, user.get("username"), user.get("first_name"))
    result = await store.redeem_promo(code, user_id)
    status = str(result.get("status") or "not_found")
    promo = result.get("promo") or {}
    return web.json_response(
        {
            "ok": status == "ok",
            "status": status,
            "requests": int(promo.get("requests") or 0),
            "image_credits": int(promo.get("image_credits") or 0),
            "balance": int(await store.bonus_requests(user_id)),
            "image_balance": int(await store.image_credits(user_id)),
        }
    )


MAX_LEAK_SIZE = 20 * 1024 * 1024


async def api_leaks(request: web.Request) -> web.Response:
    """Список файлов раздела «Сливы»."""
    store: Store = request.app["miniapp_store"]
    bot: Bot = request.app["miniapp_bot"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user_id = int(data["user"]["id"])
    gate = await _gate(request, user_id)
    if gate is not None:
        return gate
    username = await _bot_username(bot)
    return web.json_response(
        {"ok": True, **(await _leaks_payload(store, username=username))}
    )


async def api_leak_file(request: web.Request) -> web.Response:
    """Отдаёт файл из Telegram. Подпись передаётся заголовком X-Init-Data."""
    store: Store = request.app["miniapp_store"]
    bot: Bot = request.app["miniapp_bot"]
    data, error = await _auth(request, use_body=False)
    if error is not None:
        return error
    user_id = int(data["user"]["id"])
    gate = await _gate(request, user_id)
    if gate is not None:
        return gate
    leak_id = _as_int(request.match_info.get("leak_id"))
    row = await store.get_leak(leak_id) if leak_id else None
    if not row:
        return web.json_response({"error": "not_found"}, status=404)
    try:
        buf = await bot.download_file(str(row.get("file_id") or ""))
    except TelegramAPIError as exc:
        return web.json_response(
            {"error": f"Telegram: {getattr(exc, 'message', str(exc))}"}, status=502
        )
    await store.bump_leak_downloads(int(leak_id))
    name = str(row.get("file_name") or f"file-{leak_id}")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120] or "file"
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(name, safe='')}"
    )
    return web.Response(
        body=buf.getvalue(),
        headers={
            "Content-Disposition": disposition,
            "Content-Type": str(row.get("mime") or "application/octet-stream"),
        },
    )


async def api_settings(request: web.Request) -> web.Response:
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user_id = int(data["user"]["id"])
    body = await _read_body(request)
    changed: dict[str, Any] = {}

    lang = body.get("lang")
    if isinstance(lang, str) and lang:
        code = _lang_of(lang, settings)
        await store.set_lang(user_id, code)
        changed["lang"] = code

    style = body.get("style")
    if isinstance(style, str) and style:
        key = style_catalog.normalize_style(style)
        await store.set_style(user_id, key)
        changed["style"] = key

    new_model = body.get("model")
    if isinstance(new_model, str) and new_model:
        info = model_catalog.info(new_model)
        if info is not None and (not info.stars or await store.has_model_access(user_id, new_model)):
            await store.set_model(user_id, new_model)
            changed["model"] = {"id": info.id, "title": info.title}

    return web.json_response({"ok": True, **changed})


async def api_top(request: web.Request) -> web.Response:
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    rows = await store.referral_top(10)
    return web.json_response(
        {
            "top": [
                {
                    "user_id": int(row["user_id"]),
                    "name": str(row.get("name") or ""),
                    "count": int(row.get("count") or 0),
                }
                for row in rows
            ]
        }
    )


async def api_history(request: web.Request) -> web.Response:
    """Последние ответы пользователя: вопрос, ответ, дата."""
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user_id = int(data["user"]["id"])
    gate = await _gate(request, user_id)
    if gate is not None:
        return gate

    rows = await store.recent_exchanges(user_id, 12)
    items: list[dict[str, Any]] = []
    for row in rows:
        created = row.get("created_at")
        if hasattr(created, "isoformat"):
            created = created.isoformat()
        items.append(
            {
                "id": int(row.get("id") or 0),
                "question": str(row.get("question") or "")[:1000],
                "answer": str(row.get("answer") or "")[:6000],
                "kind": str(row.get("kind") or "answer"),
                "created_at": str(created or ""),
            }
        )
    return web.json_response({"items": items})


async def api_answer(request: web.Request) -> web.Response:
    """Один ответ по exchange_id — для просмотра в Mini App."""
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user_id = int(data["user"]["id"])
    body = await _read_body(request)
    exchange_id = _as_int(body.get("id"))
    if exchange_id is None:
        return web.json_response({"error": "missing_id"}, status=400)
    row = await store.get_exchange(exchange_id)
    if not row or int(row.get("user_id") or 0) != user_id:
        return web.json_response({"error": "not_found"}, status=404)
    created = row.get("created_at")
    if hasattr(created, "isoformat"):
        created = created.isoformat()
    return web.json_response(
        {
            "id": int(row.get("id") or 0),
            "question": str(row.get("question") or "")[:2000],
            "answer": str(row.get("answer") or ""),
            "kind": str(row.get("kind") or "answer"),
            "created_at": str(created or ""),
        }
    )


async def _tools_state(store: Store, user_id: int) -> dict[str, Any]:
    todos = await toolbox._todo_load(store, user_id)
    cards = await toolbox._cards_load(store, user_id)
    items = await reminders._load(store, user_id)
    items.sort(key=lambda item: item["due"])
    return {
        "todos": [str(item) for item in todos],
        "cards": [{"q": str(c["q"]), "a": str(c["a"])} for c in cards],
        "reminders": [
            {
                "id": int(item["id"]),
                "text": str(item["text"]),
                "due": str(item["due"]),
                "kind": str(item["kind"]),
            }
            for item in items
        ],
        "limits": {
            "todos": toolbox.TODO_LIMIT,
            "cards": toolbox.CARD_LIMIT,
            "reminders": reminders.MAX_PER_USER,
        },
    }


async def api_tools(request: web.Request) -> web.Response:
    """Дела, карточки и напоминания: чтение и изменения одним эндпоинтом."""
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user_id = int(data["user"]["id"])
    gate = await _gate(request, user_id)
    if gate is not None:
        return gate

    body = await _read_body(request)
    action = str(body.get("action") or "load")
    problem: str | None = None
    index = _as_int(body.get("index"))

    if action == "todo.add":
        text = str(body.get("text") or "").strip()[: toolbox.TODO_ITEM_CHARS]
        items = await toolbox._todo_load(store, user_id)
        if not text:
            problem = "empty"
        elif len(items) >= toolbox.TODO_LIMIT:
            problem = "todo_limit"
        else:
            items.append(text)
            await toolbox._todo_save(store, user_id, items)
    elif action == "todo.del":
        items = await toolbox._todo_load(store, user_id)
        if index is not None and 1 <= index <= len(items):
            items.pop(index - 1)
            await toolbox._todo_save(store, user_id, items)
    elif action == "todo.clear":
        await toolbox._todo_save(store, user_id, [])
    elif action == "card.add":
        question = str(body.get("question") or "").strip()[: toolbox.CARD_ITEM_CHARS]
        answer = str(body.get("answer") or "").strip()[: toolbox.CARD_ITEM_CHARS]
        cards = await toolbox._cards_load(store, user_id)
        if not question or not answer:
            problem = "card_need_both"
        elif len(cards) >= toolbox.CARD_LIMIT:
            problem = "card_limit"
        else:
            cards.append({"q": question, "a": answer})
            await toolbox._cards_save(store, user_id, cards)
    elif action == "card.del":
        cards = await toolbox._cards_load(store, user_id)
        if index is not None and 1 <= index <= len(cards):
            cards.pop(index - 1)
            await toolbox._cards_save(store, user_id, cards)
    elif action == "rem.add":
        text = str(body.get("text") or "").strip()[:500]
        parsed = reminders.parse_duration(str(body.get("duration") or ""))
        if parsed is None:
            problem = "rem_bad_duration"
        else:
            seconds, leftover = parsed
            created = await reminders.add_reminder(
                store,
                settings,
                user_id=user_id,
                chat_id=user_id,
                text=text or leftover or "…",
                seconds=seconds,
            )
            if created is None:
                problem = "rem_limit"
    elif action == "rem.del":
        rid = _as_int(body.get("id"))
        items = await reminders._load(store, user_id)
        keep = [item for item in items if item["id"] != rid]
        if len(keep) != len(items):
            await reminders._save(store, user_id, keep)

    state = await _tools_state(store, user_id)
    state["ok"] = problem is None
    state["error"] = problem
    return web.json_response(state)


async def api_buy(request: web.Request) -> web.Response:
    """Тарифы, курс и доступные к покупке модели."""
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user_id = int(data["user"]["id"])
    gate = await _gate(request, user_id)
    if gate is not None:
        return gate

    runtime = await load_runtime(store, settings)
    owned = set(await store.list_model_access(user_id))
    models = [
        {
            "id": item.id,
            "title": item.title,
            "stars": item.stars,
            "hint": item.hint,
            "owned": item.id in owned,
        }
        for item in model_catalog.CATALOG
        if item.stars > 0
    ]
    support = {
        "enabled": settings.support_ready,
        "wallet": settings.support_wallet,
    }
    return web.json_response(
        {
            "enabled": settings.payments_enabled,
            "rate": runtime.star_rate,
            "min_stars": payments.MIN_STARS,
            "max_stars": payments.MAX_STARS,
            "packages": [
                {"requests": int(requests), "stars": int(stars)}
                for requests, stars in runtime.star_packages
            ],
            "bonus": await store.bonus_requests(user_id),
            "models": models,
            "support": support,
        }
    )


async def api_invoice(request: web.Request) -> web.Response:
    """Создаёт ссылку на счёт Stars для openInvoice в Mini App."""
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    bot: Bot = request.app["miniapp_bot"]
    data, error = await _auth(request)
    if error is not None:
        return error
    user_id = int(data["user"]["id"])
    gate = await _gate(request, user_id)
    if gate is not None:
        return gate
    if not settings.payments_enabled:
        return web.json_response({"error": "payments_disabled"}, status=403)

    body = await _read_body(request)
    runtime = await load_runtime(store, settings)

    model_id = body.get("model")
    try:
        if isinstance(model_id, str) and model_id:
            item = model_catalog.info(model_id)
            if item is None or item.stars <= 0:
                return web.json_response({"error": "bad_offer"}, status=400)
            if await store.has_model_access(user_id, model_id):
                return web.json_response({"error": "owned"}, status=400)
            url = await bot.create_invoice_link(
                title=f"Модель {item.title} в {settings.bot_name}",
                description=(
                    f"Разовое открытие модели {item.title} за {item.stars} ⭐. "
                    "После оплаты она сразу станет активной."
                ),
                payload=f"{payments.MODEL_PREFIX}:{item.id}:{item.stars}",
                currency="XTR",
                prices=[LabeledPrice(label=item.title, amount=item.stars)],
                provider_token="",
            )
            return web.json_response({"url": url})

        requests_count = _as_int(body.get("requests"))
        stars = _as_int(body.get("stars"))
        if (
            requests_count is None
            or stars is None
            or not payments.is_valid_offer(runtime, requests_count, stars)
        ):
            return web.json_response({"error": "bad_offer"}, status=400)
        url = await bot.create_invoice_link(
            title=f"{requests_count} запросов к {settings.bot_name}",
            description=(
                f"{requests_count} дополнительных запросов за {stars} ⭐. "
                "Не сгорают, тратятся после дневного лимита."
            ),
            payload=f"{payments.PAYLOAD_PREFIX}:{requests_count}:{stars}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{requests_count} запросов", amount=stars)],
            provider_token="",
        )
    except TelegramAPIError as exc:
        log.warning("Mini App: не удалось создать счёт для %s: %s", user_id, exc)
        return web.json_response({"error": "invoice_failed"}, status=502)
    return web.json_response({"url": url})


# --------------------------------------------------------------------------- админ-панель
def _iso(value: Any) -> str:
    """Дата/время в JSON: строкой, чтобы браузер сам форматировал."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def _display(row: dict | None) -> str:
    row = row or {}
    username = str(row.get("username") or "").strip()
    if username:
        return "@" + username
    first_name = str(row.get("first_name") or "").strip()
    if first_name:
        return first_name
    return str(row.get("user_id") or "")


async def _bot_username(bot: Bot) -> str:
    """Юзернейм бота для deep-link'ов. aiogram кэширует getMe, так что дёшево."""
    try:
        me = await bot.me()
    except Exception:  # noqa: BLE001 — без ссылки просто не будет кнопки
        return ""
    return str(getattr(me, "username", "") or "")


def _admin_json(payload: dict[str, Any], status: int = 200) -> web.Response:
    return web.json_response(payload, status=status)


def _admin_fail(message: str, *, status: int = 200) -> web.Response:
    return _admin_json({"ok": False, "error": message}, status=status)


async def _admin_ctx(
    request: web.Request, *, min_role: str = ROLE_ADMIN, use_body: bool = True
) -> tuple[dict[str, Any] | None, web.Response | None]:
    """Подпись initData + роль не ниже min_role."""
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    data, error = await _auth(request, use_body=use_body)
    if error is not None:
        return None, error
    user = data["user"]
    user_id = int(user["id"])
    await store.ensure_user(user_id, user.get("username"), user.get("first_name"))
    role = await resolve_role(user_id, settings, store)
    if rank(role) < RANKS[min_role]:
        return None, _admin_fail("forbidden", status=403)
    return {"user_id": user_id, "role": role, "data": data}, None


async def _settings_payload(store: Store, settings: Settings) -> dict[str, Any]:
    rt = await load_runtime(store, settings)
    overrides = await store.all_settings()
    items = [
        {
            "key": "daily_limit",
            "label": "Лимит сообщений в день",
            "hint": "0 — безлимит",
            "value": str(rt.daily_limit),
            "multiline": False,
        },
        {
            "key": "max_context",
            "label": "Глубина контекста",
            "hint": "0 — без памяти",
            "value": str(rt.max_context),
            "multiline": False,
        },
        {
            "key": "image_daily_limit",
            "label": "Бесплатных картинок в день",
            "hint": "0 — без бесплатных",
            "value": str(rt.image_daily_limit),
            "multiline": False,
        },
        {
            "key": "ai_model",
            "label": "Модель ИИ",
            "hint": "например openrouter/free",
            "value": rt.model,
            "multiline": False,
        },
        {
            "key": "ai_vision_model",
            "label": "Модель для фото",
            "hint": "читает изображения",
            "value": rt.vision_model,
            "multiline": False,
        },
        {
            "key": "star_rate",
            "label": "Запросов за 1 звезду",
            "hint": "курс Stars",
            "value": str(rt.star_rate),
            "multiline": False,
        },
        {
            "key": "star_packages",
            "label": "Тарифы Stars",
            "hint": "формат 30:3,60:6,100:10",
            "value": ",".join(f"{n}:{s}" for n, s in rt.star_packages),
            "multiline": False,
        },
        {
            "key": "required_channel",
            "label": "Канал подписки",
            "hint": "@username, ссылка или ID; пусто — выключено",
            "value": rt.required_channel or "",
            "multiline": False,
        },
        {
            "key": "required_channel_url",
            "label": "Ссылка на канал",
            "hint": "кнопка «Подписаться»",
            "value": rt.required_channel_url or "",
            "multiline": False,
        },
        {
            "key": "system_prompt",
            "label": "Системный промпт",
            "hint": "характер и правила ассистента",
            "value": rt.system_prompt,
            "multiline": True,
        },
    ]
    for item in items:
        item["override"] = item["key"] in overrides
    return {
        "items": items,
        "group_gate": bool(rt.group_gate),
        "group_gate_override": "group_gate" in overrides,
        "model": rt.model,
    }


async def _validate_setting(
    key: str, value: str
) -> tuple[str, str]:
    """Проверяет значение настройки так же, как админка в боте."""
    from config import parse_packages
    from runtime import EDITABLE

    if key not in EDITABLE:
        return "", "Неизвестная настройка."
    value = (value or "").strip()

    if key in {"daily_limit", "max_context", "image_daily_limit"}:
        if not value.isdigit():
            return "", "Нужно целое число, например 30. 0 — без ограничений."
        number = int(value)
        if key == "daily_limit" and number > 10000:
            return "", "Слишком много. Поставь до 10000."
        if key == "image_daily_limit" and number > 1000:
            return "", "Слишком много. Поставь до 1000 картинок в день."
        if key == "max_context" and number > 100:
            return "", "Слишком много. Поставь до 100."
        return str(number), ""

    if key in {"ai_model", "ai_vision_model"}:
        if not value or len(value) > 120 or " " in value:
            return "", "Имя модели — одно слово без пробелов, например openrouter/free."
        return value, ""

    if key == "star_rate":
        if not value.isdigit():
            return "", "Нужно целое число, например 2."
        number = int(value)
        if not 1 <= number <= 1000:
            return "", "Поставь от 1 до 1000 запросов за звезду."
        return str(number), ""

    if key == "star_packages":
        try:
            parsed = parse_packages(value, ())
        except ValueError as exc:
            return "", f"Не получилось разобрать тарифы: {exc}. Пример: 30:3,60:6,100:10"
        if not parsed:
            return "", "Нужен хотя бы один тариф."
        return ",".join(f"{requests}:{stars}" for requests, stars in parsed), ""

    if key == "required_channel":
        from subscription import normalize_channel

        normalized = normalize_channel(value)
        if value and value.lower() not in {"0", "-", "off", "no", "none", "нет", "выкл"} and not normalized:
            return "", "Не понял канал. Пришли @username, ссылку https://t.me/... или ID -100..., либо off."
        return normalized, ""

    if key == "required_channel_url":
        from subscription import normalize_channel_url

        if value and " " in value:
            return "", "В ссылке не должно быть пробелов. Пример: https://t.me/gazyavaGPT"
        normalized = normalize_channel_url(value, "")
        if normalized and not normalized.lower().startswith(("http://", "https://")):
            return "", "Нужна ссылка вида https://t.me/..."
        return normalized, ""

    # system_prompt
    if len(value) < 10:
        return "", "Слишком коротко — минимум 10 символов."
    if len(value) > 4000:
        return "", "Слишком длинно — до 4000 символов."
    return value, ""


async def _user_payload(
    store: Store, settings: Settings, actor_role: str | None, user_id: int
) -> dict[str, Any]:
    card = await store.user_card(user_id) or {}
    current = await resolve_role(user_id, settings, store)
    granted = set(await store.list_model_access(user_id))
    chosen = await store.get_model(user_id)
    models = []
    for item in model_catalog.CATALOG:
        owned = item.stars <= 0 or item.id in granted
        models.append(
            {
                "id": item.id,
                "title": item.title,
                "stars": int(item.stars or 0),
                "owned": owned,
                "chosen": item.id == chosen,
                "free": item.stars <= 0,
            }
        )
    options = []
    for role in ASSIGNABLE:
        allowed, reason = can_assign(
            actor_role=actor_role,
            actor_id=0,
            target_id=user_id,
            target_role=current,
            new_role=role,
            settings=settings,
        )
        options.append(
            {
                "role": role,
                "title": _role_title(role),
                "allowed": allowed,
                "reason": reason,
            }
        )
    return {
        "user": {
            "id": user_id,
            "name": _display(card) if card else str(user_id),
            "username": card.get("username") or "",
            "first_name": card.get("first_name") or "",
            "exists": bool(card),
            "banned": bool(card.get("banned")),
            "used_today": int(card.get("used_today") or 0),
            "bonus_requests": int(card.get("bonus_requests") or 0),
            "image_credits": int(card.get("image_credits") or 0),
            "total_requests": int(card.get("total_requests") or 0),
            "history_len": int(card.get("history_len") or 0),
            "subscription_until": _iso(card.get("subscription_until")),
        },
        "role": current or "",
        "role_title": _role_title(current),
        "actor_role": actor_role or "",
        "can_manage_roles": _can_manage_roles(actor_role),
        "models": models,
        "assignable": options,
    }


async def _promos_payload(store: Store) -> dict[str, Any]:
    stats = await store.promo_stats()
    rows = await store.list_promos(30)
    now = datetime.now(UTC)
    items = []
    for row in rows:
        expires = row.get("expires_at")
        items.append(
            {
                "code": row.get("code") or "",
                "requests": int(row.get("requests") or 0),
                "image_credits": int(row.get("image_credits") or 0),
                "max_uses": int(row.get("max_uses") or 0),
                "uses": int(row.get("uses") or 0),
                "active": bool(row.get("active")),
                "expired": bool(expires and expires <= now),
                "expires_at": _iso(expires),
                "created_at": _iso(row.get("created_at")),
            }
        )
    return {"stats": stats, "items": items}


async def _leaks_payload(
    store: Store, *, admin: bool = False, username: str = ""
) -> dict[str, Any]:
    rows = await store.list_leaks(100)
    items = []
    for row in rows:
        leak_id = int(row.get("id") or 0)
        title = str(row.get("title") or row.get("file_name") or "")
        items.append(
            {
                "id": leak_id,
                "title": title,
                "comment": str(row.get("comment") or ""),
                "file_name": str(row.get("file_name") or ""),
                "file_size": int(row.get("file_size") or 0),
                "mime": str(row.get("mime") or ""),
                "downloads": int(row.get("downloads") or 0),
                "created_at": _iso(row.get("created_at")),
                "deep_link": share.deep_link(username, leak_id),
                "share_url": share.share_url(username, leak_id, title),
                **({"created_by": int(row.get("created_by") or 0)} if admin else {}),
            }
        )
    return {"total": await store.count_leaks(), "items": items}


async def _payments_payload(store: Store) -> dict[str, Any]:
    stats = await store.payments_stats()
    rows = await store.recent_payments(30)
    items = []
    for row in rows:
        kind = str(row.get("kind") or "requests")
        items.append(
            {
                "id": int(row.get("id") or 0),
                "user_id": int(row.get("user_id") or 0),
                "name": _display(row) or str(row.get("user_id") or ""),
                "kind": kind,
                "stars": int(row.get("stars") or 0),
                "requests": int(row.get("requests") or 0),
                "model": row.get("model") or "",
                "model_title": model_catalog.title(row.get("model")),
                "created_at": _iso(row.get("created_at")),
                "refunded": bool(row.get("refunded_at")),
            }
        )
    return {"stats": stats, "items": items}


def _ticket_item(row: dict) -> dict[str, Any]:
    from tickets import topic_title

    return {
        "id": int(row.get("id") or 0),
        "user_id": int(row.get("user_id") or 0),
        "name": _display(row),
        "topic": row.get("topic") or "other",
        "topic_title": topic_title(str(row.get("topic") or "other")),
        "status": row.get("status") or "open",
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "closed_at": _iso(row.get("closed_at")),
    }


async def _tickets_payload(
    store: Store, offset: int = 0, limit: int = 20
) -> dict[str, Any]:
    offset = max(0, int(offset))
    rows = await store.open_tickets(limit, offset)
    stats = await store.tickets_stats()
    return {
        "stats": stats,
        "offset": offset,
        "limit": limit,
        "items": [_ticket_item(row) for row in rows],
    }


async def _ticket_payload(store: Store, ticket_id: int) -> dict[str, Any] | None:
    ticket = await store.get_ticket(ticket_id)
    if not ticket:
        return None
    messages = await store.ticket_messages(ticket_id, 50)
    return {
        "ticket": _ticket_item(ticket),
        "messages": [
            {
                "id": int(row.get("id") or 0),
                "author_id": int(row.get("author_id") or 0),
                "from_staff": bool(row.get("from_staff")),
                "text": row.get("text") or "",
                "created_at": _iso(row.get("created_at")),
            }
            for row in messages
        ],
    }


async def _channels_payload(store: Store, bot: Bot) -> dict[str, Any]:
    from admin import (
        CHANNEL_SETTING,
        MAX_CHANNELS,
        REQUIRED_CHANNEL_SETTING,
        _managed_channels,
        _stored_channels,
    )

    channels = await _managed_channels(store)
    required = (await store.get_setting(REQUIRED_CHANNEL_SETTING) or "").strip()
    items = []
    for index, channel in enumerate(channels):
        title = channel
        count = 0
        ok = True
        try:
            chat = await bot.get_chat(channel)
            title = chat.title or channel
            with contextlib.suppress(TelegramAPIError):
                count = int(await bot.get_chat_member_count(chat.id))
        except TelegramAPIError:
            ok = False
        items.append(
            {
                "index": index,
                "channel": channel,
                "title": title,
                "members": count,
                "ok": ok,
                "required": channel == required,
            }
        )
    return {
        "items": items,
        "required": required,
        "max": MAX_CHANNELS,
        "stored": len(_stored_channels(await store.get_setting(CHANNEL_SETTING))),
    }


async def _giveaways_payload(store: Store) -> dict[str, Any]:
    rows = await store.active_giveaways()
    items = []
    for row in rows:
        items.append(
            {
                "id": int(row.get("id") or 0),
                "chat_id": int(row.get("chat_id") or 0),
                "prize": row.get("prize") or "",
                "winners": int(row.get("winners") or 1),
                "entries": int(row.get("entries") or 0),
                "ends_at": _iso(row.get("ends_at")),
                "need_sub": bool(row.get("need_sub")),
            }
        )
    return {"stats": await store.giveaways_stats(), "items": items}


async def _run_admin_broadcast(
    bot: Bot, store: Store, text: str
) -> tuple[int, int]:
    ids = await store.user_ids(only_active=True)
    sent = failed = 0
    for uid in ids:
        try:
            await bot.send_message(uid, text, parse_mode=None)
            sent += 1
        except Exception:  # noqa: BLE001 — один недоставленный не должен ломать рассылку
            failed += 1
        await asyncio.sleep(0.05)
    log.info("Mini App: рассылка завершена — %s/%s", sent, len(ids))
    return sent, failed


async def _do_refund(
    bot: Bot, store: Store, payment_id: int
) -> tuple[bool, str]:
    payment = await store.get_payment(payment_id)
    if not payment:
        return False, "Платёж не найден."
    if payment.get("refunded_at"):
        return False, "Этот платёж уже возвращён."
    try:
        ok = await bot.refund_star_payment(
            user_id=payment["user_id"],
            telegram_payment_charge_id=payment["charge_id"],
        )
    except TelegramAPIError as exc:
        return False, f"Telegram отказал: {getattr(exc, 'message', str(exc))}"
    if not ok:
        return False, "Telegram не подтвердил возврат."
    refunded = await store.mark_payment_refunded(payment_id)
    if not refunded:
        return False, "Платёж уже был возвращён."

    kind = payment.get("kind")
    user_id = int(payment["user_id"])
    with contextlib.suppress(TelegramAPIError):
        if kind == "model":
            model_id = payment.get("model")
            if model_id:
                await store.revoke_model(user_id, model_id)
                if await store.get_model(user_id) == model_id:
                    await store.set_model(user_id, None)
            await bot.send_message(
                user_id,
                "↩️ <b>Возврат выполнен</b>\n\n"
                f"Звёзды за модель {model_catalog.title(payment.get('model'))} "
                f"({payment['stars']} ⭐) возвращены Telegram.\n"
                "Доступ к модели закрыт.",
            )
        elif kind == "sub":
            days = int(payment.get("requests") or 0)
            left = await store.trim_subscription(user_id, days)
            tail = (
                f"Остаток подписки: до <b>{left:%d.%m.%Y}</b>."
                if left
                else "Подписка отменена."
            )
            await bot.send_message(
                user_id,
                "↩️ <b>Возврат выполнен</b>\n\n"
                f"Звёзды за подписку ({payment['stars']} ⭐) возвращены Telegram.\n"
                f"Снято дней: <b>{days}</b>. {tail}",
            )
        else:
            balance = await store.add_bonus(user_id, -int(payment.get("requests") or 0))
            await bot.send_message(
                user_id,
                "↩️ <b>Возврат выполнен</b>\n\n"
                f"Звёзды за покупку ({payment['stars']} ⭐) возвращены Telegram.\n"
                f"Списано запросов: <b>{payment.get('requests') or 0}</b>\n"
                f"Остаток бонусных запросов: <b>{balance}</b>.",
            )
    return True, "Возврат выполнен."


async def api_admin_leak_upload(request: web.Request) -> web.Response:
    """Загрузка файла в «Сливы»: multipart/form-data, подпись — в X-Init-Data."""
    ctx, error = await _admin_ctx(request, use_body=False)
    if error is not None:
        return error
    assert ctx is not None
    store: Store = request.app["miniapp_store"]
    bot: Bot = request.app["miniapp_bot"]
    if not str(request.content_type or "").startswith("multipart/"):
        return _admin_fail("Нужен multipart/form-data.")
    reader = await request.multipart()
    fields: dict[str, str] = {}
    file_bytes = b""
    file_name = ""
    mime = ""
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            file_name = Path(str(part.filename or "file")).name[:120] or "file"
            mime = str(part.headers.get("Content-Type") or "application/octet-stream")
            chunks = bytearray()
            while True:
                chunk = await part.read_chunk(64 * 1024)
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > MAX_LEAK_SIZE:
                    return _admin_fail("Файл больше 20 МБ.")
            file_bytes = bytes(chunks)
        else:
            fields[part.name] = (await part.text()).strip()
    if not file_bytes:
        return _admin_fail("Файл не получен.")
    title = (fields.get("title") or file_name)[:120]
    comment = fields.get("comment") or ""
    if len(comment) > 2000:
        return _admin_fail("Комментарий — до 2000 символов.")
    try:
        message = await bot.send_document(
            chat_id=int(ctx["user_id"]),
            document=BufferedInputFile(file_bytes, filename=file_name),
            caption=("🗂 " + title)[:1024],
        )
    except TelegramAPIError as exc:
        return _admin_fail(
            f"Telegram не принял файл: {getattr(exc, 'message', str(exc))}"
        )
    document = getattr(message, "document", None)
    file_id = str(getattr(document, "file_id", "") or "")
    if not file_id:
        return _admin_fail("Telegram не вернул file_id.")
    await store.add_leak(
        title=title,
        comment=comment,
        file_id=file_id,
        file_name=str(getattr(document, "file_name", "") or file_name),
        file_size=int(getattr(document, "file_size", 0) or len(file_bytes)),
        mime=str(getattr(document, "mime_type", "") or mime),
        created_by=int(ctx["user_id"]),
    )
    return _admin_json(
        {
            "ok": True,
            "notice": "Файл загружен.",
            **(
                await _leaks_payload(
                    store, admin=True, username=await _bot_username(bot)
                )
            ),
        }
    )


async def api_admin(request: web.Request) -> web.Response:
    """Единая точка админ-панели Mini App.

    Один маршрут вместо десятков: клиент присылает `op`, сервер проверяет роль
    и выполняет действие. Так проще держать проверки прав в одном месте.
    """
    settings: Settings = request.app["miniapp_settings"]
    store: Store = request.app["miniapp_store"]
    bot: Bot = request.app["miniapp_bot"]

    body = await _read_body(request)
    op = str(body.get("op") or "dash").strip().lower()
    ticket_ops = {"dash", "tickets", "ticket", "ticket.reply", "ticket.close"}
    ctx, error = await _admin_ctx(
        request, min_role=ROLE_SUPPORT if op in ticket_ops else ROLE_ADMIN
    )
    if error is not None:
        return error
    assert ctx is not None
    user_id = int(ctx["user_id"])
    role = ctx["role"]

    try:
        if op == "dash":
            stats = await store.stats()
            tickets = await store.tickets_stats()
            payments_stats = await store.payments_stats()
            promos = await store.promo_stats()
            rt = await load_runtime(store, settings)
            return _admin_json(
                {
                    "ok": True,
                    "role": role,
                    "role_title": _role_title(role),
                    "is_admin": _has_admin(role),
                    "can_manage_roles": _can_manage_roles(role),
                    "stats": stats,
                    "tickets": tickets,
                    "payments": payments_stats,
                    "promos": promos,
                    "runtime": {
                        "model": rt.model,
                        "daily_limit": rt.daily_limit,
                        "max_context": rt.max_context,
                    },
                }
            )

        if op == "stats":
            stats = await store.stats()
            feedback = await store.feedback_stats()
            tickets = await store.tickets_stats()
            payments_stats = await store.payments_stats()
            top = await store.top_users(10)
            activity = await store.activity_by_day(7)
            rt = await load_runtime(store, settings)
            return _admin_json(
                {
                    "ok": True,
                    "stats": stats,
                    "feedback": feedback,
                    "tickets": tickets,
                    "payments": payments_stats,
                    "top": [
                        {
                            "user_id": int(row["user_id"]),
                            "name": _display(row),
                            "total": int(row.get("total") or 0),
                        }
                        for row in top
                    ],
                    "activity": [
                        {"day": str(row["day"]), "total": int(row.get("total") or 0)}
                        for row in activity
                    ],
                    "runtime": {
                        "model": rt.model,
                        "daily_limit": rt.daily_limit,
                        "max_context": rt.max_context,
                    },
                }
            )

        if op == "users":
            offset = max(0, _as_int(body.get("offset")) or 0)
            page = 20
            total = int((await store.stats()).get("users") or 0)
            offset = max(0, min(offset, max(0, total - page)))
            rows = await store.list_users(offset, page)
            return _admin_json(
                {
                    "ok": True,
                    "offset": offset,
                    "page": page,
                    "total": total,
                    "items": [
                        {
                            "user_id": int(row["user_id"]),
                            "name": _display(row),
                            "username": row.get("username") or "",
                            "first_name": row.get("first_name") or "",
                            "banned": bool(row.get("banned")),
                            "used_today": int(row.get("used_today") or 0),
                        }
                        for row in rows
                    ],
                }
            )

        if op == "user":
            target = _as_int(body.get("id"))
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            return _admin_json(
                {"ok": True, "card": await _user_payload(store, settings, role, target)}
            )

        if op == "user.ban":
            target = _as_int(body.get("id"))
            banned = bool(body.get("banned"))
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            if target == user_id:
                return _admin_fail("Себя забанить нельзя 🙂")
            if settings.owner_id and target == settings.owner_id:
                return _admin_fail("Владельца забанить нельзя 👑")
            target_role = await resolve_role(target, settings, store)
            if rank(target_role) >= rank(role):
                return _admin_fail("Нельзя забанить равного или старшего по роли.")
            if not await store.set_banned(target, banned):
                return _admin_fail("Пользователь не найден в базе.")
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Пользователь забанен." if banned else "Пользователь разбанен.",
                    "card": await _user_payload(store, settings, role, target),
                }
            )

        if op == "user.bonus":
            target = _as_int(body.get("id"))
            count = _as_int(body.get("count")) or 0
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            if not 1 <= count <= 100_000:
                return _admin_fail("Запросов можно выдать от 1 до 100000.")
            if not await store.user_exists(target):
                return _admin_fail("Пользователь не найден в базе.")
            balance = await store.add_bonus(target, count)
            return _admin_json(
                {
                    "ok": True,
                    "notice": f"Выдано {count} запросов. Баланс: {balance}.",
                    "card": await _user_payload(store, settings, role, target),
                }
            )

        if op == "user.images":
            target = _as_int(body.get("id"))
            count = _as_int(body.get("count")) or 0
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            if not 1 <= count <= 10_000:
                return _admin_fail("Генераций можно выдать от 1 до 10000.")
            if not await store.user_exists(target):
                return _admin_fail("Пользователь не найден в базе.")
            balance = await store.add_image_credits(target, count)
            return _admin_json(
                {
                    "ok": True,
                    "notice": f"Выдано {count} генераций. Баланс: {balance}.",
                    "card": await _user_payload(store, settings, role, target),
                }
            )

        if op == "user.reset":
            target = _as_int(body.get("id"))
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            await store.reset(target)
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Контекст диалога сброшен.",
                    "card": await _user_payload(store, settings, role, target),
                }
            )

        if op == "user.role":
            target = _as_int(body.get("id"))
            new_role = str(body.get("role") or "")
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            current = await resolve_role(target, settings, store)
            allowed, reason = can_assign(
                actor_role=role,
                actor_id=user_id,
                target_id=target,
                target_role=current,
                new_role=new_role,
                settings=settings,
            )
            if not allowed:
                return _admin_fail(reason)
            if await store.get_role(target) == new_role:
                return _admin_fail("Уже эта роль.")
            await store.set_role(target, new_role, user_id)
            hint = (
                "Теперь тебе доступны обращения пользователей: /tickets"
                if new_role == ROLE_SUPPORT
                else "Теперь тебе доступна админка: /admin"
            )
            with contextlib.suppress(TelegramAPIError):
                await bot.send_message(
                    target,
                    f"🎖 <b>Тебе выдана роль</b>\n\n{_role_title(new_role)}\n{hint}",
                )
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Роль выдана.",
                    "card": await _user_payload(store, settings, role, target),
                }
            )

        if op == "user.role.clear":
            target = _as_int(body.get("id"))
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            current = await resolve_role(target, settings, store)
            allowed, reason = can_assign(
                actor_role=role,
                actor_id=user_id,
                target_id=target,
                target_role=current,
                new_role=None,
                settings=settings,
            )
            if not allowed:
                return _admin_fail(reason)
            await store.delete_role(target)
            extra = (
                " Доступ из ADMIN_IDS остался — снимите ID в настройках Render."
                if target in settings.admin_ids
                else ""
            )
            with contextlib.suppress(TelegramAPIError):
                await bot.send_message(
                    target,
                    "🎖 <b>Роль снята</b>\n\n"
                    "Если это ошибка — напиши владельцу сообщества." + extra,
                )
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Роль снята." + extra,
                    "card": await _user_payload(store, settings, role, target),
                }
            )

        if op == "user.model":
            target = _as_int(body.get("id"))
            model_id = str(body.get("model") or "")
            grant = bool(body.get("grant"))
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            item = model_catalog.info(model_id)
            if item is None:
                return _admin_fail("Неизвестная модель.")
            if item.stars <= 0:
                return _admin_fail("Эта модель бесплатна для всех.")
            if grant:
                await store.grant_model(target, model_id, user_id)
                notice = f"Модель {item.title} открыта."
            else:
                await store.revoke_model(target, model_id)
                if await store.get_model(target) == model_id:
                    await store.set_model(target, None)
                notice = f"Модель {item.title} закрыта."
            return _admin_json(
                {
                    "ok": True,
                    "notice": notice,
                    "card": await _user_payload(store, settings, role, target),
                }
            )

        if op == "payments":
            return _admin_json({"ok": True, **(await _payments_payload(store))})

        if op == "payment.refund":
            payment_id = _as_int(body.get("id"))
            if payment_id is None:
                return _admin_fail("Некорректный платёж.")
            done, message = await _do_refund(bot, store, payment_id)
            if not done:
                return _admin_fail(message)
            return _admin_json(
                {
                    "ok": True,
                    "notice": message,
                    **(await _payments_payload(store)),
                }
            )

        if op == "promos":
            return _admin_json({"ok": True, **(await _promos_payload(store))})

        if op == "promo.create":
            from store import valid_promo

            code = str(body.get("code") or "").strip().upper()
            if not valid_promo(code):
                return _admin_fail("Код: 3–32 символа, латиница, цифры, _ и -.")
            if await store.get_promo(code):
                return _admin_fail("Такой промокод уже существует.")
            requests = _as_int(body.get("requests")) or 0
            images = _as_int(body.get("images")) or 0
            if requests == 0 and images == 0:
                return _admin_fail("Нужна хотя бы одна награда: запросы или генерации.")
            if requests < 0 or images < 0:
                return _admin_fail("Награда не может быть отрицательной.")
            if requests > 100_000 or images > 10_000:
                return _admin_fail("Слишком много: до 100000 запросов и до 10000 генераций.")
            max_uses = _as_int(body.get("max_uses")) or 0
            if max_uses < 0 or max_uses > 1_000_000:
                return _admin_fail("Лимит активаций — от 0 до 1000000.")
            days = _as_int(body.get("days")) or 0
            if days < 0 or days > 3650:
                return _admin_fail("Срок — от 0 до 3650 дней.")
            expires_at = datetime.now(UTC) + timedelta(days=days) if days else None
            created = await store.create_promo(
                code, requests, images, max_uses, expires_at, user_id
            )
            if not created:
                return _admin_fail("Не удалось создать промокод.")
            return _admin_json(
                {
                    "ok": True,
                    "notice": f"Промокод {code} создан.",
                    **(await _promos_payload(store)),
                }
            )

        if op == "promo.delete":
            code = str(body.get("code") or "").strip()
            if not await store.delete_promo(code):
                return _admin_fail("Промокод не найден.")
            return _admin_json(
                {
                    "ok": True,
                    "notice": f"Промокод {code.upper()} удалён.",
                    **(await _promos_payload(store)),
                }
            )

        if op == "leaks":
            return _admin_json(
                {
                    "ok": True,
                    **(
                        await _leaks_payload(
                            store, admin=True, username=await _bot_username(bot)
                        )
                    ),
                }
            )

        if op == "leak.update":
            leak_id = _as_int(body.get("id"))
            if not leak_id or not await store.get_leak(leak_id):
                return _admin_fail("Файл не найден.")
            title = body.get("title")
            comment = body.get("comment")
            if title is not None and len(str(title)) > 120:
                return _admin_fail("Название — до 120 символов.")
            if comment is not None and len(str(comment)) > 2000:
                return _admin_fail("Комментарий — до 2000 символов.")
            await store.update_leak(
                leak_id,
                title=None if title is None else str(title),
                comment=None if comment is None else str(comment),
            )
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Сохранено.",
                    **(
                        await _leaks_payload(
                            store, admin=True, username=await _bot_username(bot)
                        )
                    ),
                }
            )

        if op == "leak.delete":
            leak_id = _as_int(body.get("id"))
            if not leak_id or not await store.delete_leak(leak_id):
                return _admin_fail("Файл не найден.")
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Файл удалён.",
                    **(
                        await _leaks_payload(
                            store, admin=True, username=await _bot_username(bot)
                        )
                    ),
                }
            )

        if op == "settings":
            return _admin_json(
                {"ok": True, "settings": await _settings_payload(store, settings)}
            )

        if op == "setting.save":
            key = str(body.get("key") or "")
            value, problem = await _validate_setting(key, str(body.get("value") or ""))
            if problem:
                return _admin_fail(problem)
            await store.set_setting(key, value)
            if key in {"required_channel", "required_channel_url"}:
                from subscription import reset_cache

                reset_cache()
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Сохранено.",
                    "settings": await _settings_payload(store, settings),
                }
            )

        if op == "settings.reset":
            from runtime import EDITABLE

            for key in EDITABLE:
                await store.delete_setting(key)
            await store.delete_setting("group_gate")
            for key in (
                "autopost_enabled",
                "autopost_channel",
                "autopost_hour",
                "autopost_kind",
            ):
                await store.delete_setting(key)
            from subscription import reset_cache

            reset_cache()
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Возвращены значения из env.",
                    "settings": await _settings_payload(store, settings),
                }
            )

        if op == "settings.gate":
            rt = await load_runtime(store, settings)
            await store.set_setting("group_gate", "off" if rt.group_gate else "on")
            from subscription import reset_cache

            reset_cache()
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Гейт в чатах выключен."
                    if rt.group_gate
                    else "Гейт в чатах включён.",
                    "settings": await _settings_payload(store, settings),
                }
            )

        if op == "roles":
            rows = await store.list_roles()
            return _admin_json(
                {
                    "ok": True,
                    "can_manage": _can_manage_roles(role),
                    "owner_id": settings.owner_id or 0,
                    "items": [
                        {
                            "user_id": int(row["user_id"]),
                            "name": _display(row),
                            "role": row.get("role") or "",
                            "role_title": _role_title(row.get("role")),
                        }
                        for row in rows
                    ],
                    "env_admins": sorted(
                        set(settings.admin_ids) - {row["user_id"] for row in rows}
                    ),
                    "assignable": [
                        {"role": item, "title": _role_title(item)}
                        for item in ASSIGNABLE
                    ],
                }
            )

        if op == "role.card":
            target = _as_int(body.get("id"))
            if target is None:
                return _admin_fail("Нужен числовой ID пользователя.")
            card = await store.user_card(target)
            current = await resolve_role(target, settings, store)
            options = []
            for item in ASSIGNABLE:
                allowed, reason = can_assign(
                    actor_role=role,
                    actor_id=user_id,
                    target_id=target,
                    target_role=current,
                    new_role=item,
                    settings=settings,
                )
                options.append(
                    {
                        "role": item,
                        "title": _role_title(item),
                        "allowed": allowed,
                        "reason": reason,
                    }
                )
            return _admin_json(
                {
                    "ok": True,
                    "target": {
                        "user_id": target,
                        "name": _display(card) if card else str(target),
                        "exists": bool(card),
                        "role": current or "",
                        "role_title": _role_title(current),
                        "stored": bool(await store.get_role(target)),
                        "from_env": target in settings.admin_ids,
                        "owner": bool(settings.owner_id and target == settings.owner_id),
                    },
                    "assignable": options,
                    "can_manage": _can_manage_roles(role),
                }
            )

        if op == "broadcast.count":
            ids = await store.user_ids(only_active=True)
            return _admin_json({"ok": True, "count": len(ids)})

        if op == "broadcast":
            text = str(body.get("text") or "").strip()
            if len(text) < 2:
                return _admin_fail("Текст рассылки слишком короткий.")
            if len(text) > 4000:
                return _admin_fail("Текст длиннее 4000 символов.")
            ids = await store.user_ids(only_active=True)
            if not ids:
                return _admin_fail("Нет получателей.")
            asyncio.create_task(_run_admin_broadcast(bot, store, text))
            return _admin_json(
                {
                    "ok": True,
                    "notice": f"Рассылка запущена: {len(ids)} получателей.",
                }
            )

        if op == "aitest":
            client = request.app.get("miniapp_ai")
            if client is None:
                return _admin_fail("ИИ-клиент не подключён на сервере.")
            rt = await load_runtime(store, settings)
            loop = asyncio.get_running_loop()
            started = loop.time()
            try:
                answer = await client.reply([], "Ответь одним словом: работает?")
                elapsed = loop.time() - started
                return _admin_json(
                    {
                        "ok": True,
                        "success": True,
                        "model": rt.model,
                        "answer": str(answer)[:500],
                        "elapsed": round(elapsed, 2),
                    }
                )
            except Exception as exc:  # noqa: BLE001 — показываем причину админу
                elapsed = loop.time() - started
                return _admin_json(
                    {
                        "ok": True,
                        "success": False,
                        "model": rt.model,
                        "error": str(exc)[:500],
                        "elapsed": round(elapsed, 2),
                    }
                )

        if op == "tickets":
            return _admin_json(
                {
                    "ok": True,
                    **(await _tickets_payload(
                        store, offset=max(0, _as_int(body.get("offset")) or 0)
                    )),
                }
            )

        if op == "ticket":
            ticket_id = _as_int(body.get("id"))
            if ticket_id is None:
                return _admin_fail("Некорректное обращение.")
            payload = await _ticket_payload(store, ticket_id)
            if payload is None:
                return _admin_fail("Обращение не найдено.")
            return _admin_json({"ok": True, **payload, "can_reply": True})

        if op == "ticket.reply":
            ticket_id = _as_int(body.get("id"))
            text = str(body.get("text") or "").strip()
            if ticket_id is None:
                return _admin_fail("Некорректное обращение.")
            if not text:
                return _admin_fail("Пустой ответ не отправлю.")
            if len(text) > 4000:
                return _admin_fail("Слишком длинно: до 4000 символов.")
            ticket = await store.get_ticket(ticket_id)
            if not ticket:
                return _admin_fail("Обращение не найдено.")
            if ticket.get("status") != "open":
                return _admin_fail("Обращение уже закрыто — ответить нельзя.")
            await store.append_ticket_message(ticket_id, user_id, text, True)
            delivered = True
            with contextlib.suppress(TelegramAPIError):
                await bot.send_message(
                    int(ticket["user_id"]),
                    f"💬 <b>Ответ поддержки</b> · обращение #{ticket_id}\n\n{text}",
                )
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Ответ добавлен."
                    if delivered
                    else "Ответ добавлен, но доставка не удалась.",
                    **(await _ticket_payload(store, ticket_id)),
                }
            )

        if op == "ticket.close":
            ticket_id = _as_int(body.get("id"))
            if ticket_id is None:
                return _admin_fail("Некорректное обращение.")
            ticket = await store.get_ticket(ticket_id)
            if not ticket:
                return _admin_fail("Обращение не найдено.")
            if not await store.close_ticket(ticket_id, user_id):
                return _admin_fail("Обращение уже закрыто.")
            with contextlib.suppress(TelegramAPIError):
                await bot.send_message(
                    int(ticket["user_id"]),
                    f"✅ <b>Обращение #{ticket_id} закрыто</b>\n\n"
                    "Если проблема вернётся — создай новое обращение через /support.",
                )
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Обращение закрыто.",
                    **(await _ticket_payload(store, ticket_id)),
                }
            )

        if op == "channels":
            return _admin_json(
                {"ok": True, **(await _channels_payload(store, bot))}
            )

        if op == "channel.add":
            from admin import (
                CHANNEL_SETTING,
                MAX_CHANNELS,
                _stored_channels,
                _verify_channel,
            )

            raw = str(body.get("channel") or "").strip()
            if not raw:
                return _admin_fail("Укажи канал: @username или ссылку.")
            channel, problem = await _verify_channel(bot, raw)
            if problem:
                return _admin_fail(problem)
            channels = _stored_channels(await store.get_setting(CHANNEL_SETTING))
            if channel and channel not in channels:
                if len(channels) >= MAX_CHANNELS:
                    return _admin_fail("Подключено максимальное число каналов.")
                channels.append(channel)
                await store.set_setting(
                    CHANNEL_SETTING, json.dumps(channels, ensure_ascii=False)
                )
            return _admin_json(
                {
                    "ok": True,
                    "notice": f"Канал {channel} подключён.",
                    **(await _channels_payload(store, bot)),
                }
            )

        if op == "channel.remove":
            from admin import (
                CHANNEL_SETTING,
                REQUIRED_CHANNEL_SETTING,
                _managed_channels,
                _stored_channels,
            )

            index = _as_int(body.get("index")) or 0
            visible = await _managed_channels(store)
            if index < 0 or index >= len(visible):
                return _admin_fail("Канал уже удалён.")
            removed = visible[index]
            required = (await store.get_setting(REQUIRED_CHANNEL_SETTING) or "").strip()
            if removed == required:
                return _admin_fail(
                    "Это канал обязательной подписки. Сначала измени настройку «Канал подписки»."
                )
            channels = [
                channel
                for channel in _stored_channels(await store.get_setting(CHANNEL_SETTING))
                if channel != removed
            ]
            await store.set_setting(
                CHANNEL_SETTING, json.dumps(channels, ensure_ascii=False)
            )
            return _admin_json(
                {
                    "ok": True,
                    "notice": f"Канал {removed} отвязан.",
                    **(await _channels_payload(store, bot)),
                }
            )

        if op == "channel.publish":
            import channelkit
            from admin import _managed_channels

            index = _as_int(body.get("index")) or 0
            text = str(body.get("text") or "").strip()
            if not text:
                return _admin_fail("Текст поста пуст.")
            if len(text) > 4000:
                return _admin_fail("Пост длиннее 4000 символов.")
            channels = await _managed_channels(store)
            if index < 0 or index >= len(channels):
                return _admin_fail("Канал не найден.")
            try:
                sent = await channelkit.publish_to_channel(
                    bot, store, channels[index], {"text": text}
                )
            except TelegramAPIError as exc:
                return _admin_fail(f"Telegram не принял пост: {exc}")
            return _admin_json(
                {
                    "ok": True,
                    "notice": f"Пост опубликован в {channels[index]}.",
                    "message_id": int(sent.message_id),
                    **(await _channels_payload(store, bot)),
                }
            )

        if op == "giveaways":
            return _admin_json({"ok": True, **(await _giveaways_payload(store))})

        if op == "giveaway.cancel":
            giveaway_id = _as_int(body.get("id"))
            if giveaway_id is None:
                return _admin_fail("Некорректный розыгрыш.")
            if not await store.cancel_giveaway(giveaway_id):
                return _admin_fail("Розыгрыш не найден или уже завершён.")
            return _admin_json(
                {
                    "ok": True,
                    "notice": "Розыгрыш отменён.",
                    **(await _giveaways_payload(store)),
                }
            )

        if op == "giftall":
            amount = _as_int(body.get("count")) or 0
            if not 1 <= amount <= 10_000:
                return _admin_fail("Подарить можно от 1 до 10000 запросов.")
            count = await store.add_bonus_all(amount)
            return _admin_json(
                {"ok": True, "notice": f"Подарено {amount} запросов {count} пользователям."}
            )

    except Exception:  # noqa: BLE001 — админка не должна ронять сервер
        log.exception("Mini App admin: ошибка операции %s", op)
        return _admin_fail("Внутренняя ошибка сервера. Попробуй ещё раз.", status=500)

    return _admin_fail("Неизвестная операция.", status=400)


# --------------------------------------------------------------------------- подключение
def setup(
    app: web.Application,
    settings: Settings,
    store: Store,
    bot: Bot,
    ai: Any | None = None,
) -> None:
    """Вешает маршруты Mini App на уже существующее приложение."""
    app["miniapp_settings"] = settings
    app["miniapp_store"] = store
    app["miniapp_bot"] = bot
    if ai is not None:
        app["miniapp_ai"] = ai

    if not app.get("miniapp_no_cache_hook"):
        app["miniapp_no_cache_hook"] = True
        app.on_response_prepare.append(_no_cache)

    app.router.add_get("/app", index)
    app.router.add_get("/app/", index)
    if BASE_DIR.is_dir():
        app.router.add_static("/app/assets/", BASE_DIR, name="miniapp")
    app.router.add_post("/app/api/me", api_me)
    app.router.add_post("/app/api/bonus", api_bonus)
    app.router.add_post("/app/api/promo", api_promo)
    app.router.add_post("/app/api/leaks", api_leaks)
    app.router.add_get("/app/api/leaks/{leak_id}/file", api_leak_file)
    app.router.add_post("/app/api/settings", api_settings)
    app.router.add_post("/app/api/top", api_top)
    app.router.add_post("/app/api/history", api_history)
    app.router.add_post("/app/api/tools", api_tools)
    app.router.add_post("/app/api/buy", api_buy)
    app.router.add_post("/app/api/invoice", api_invoice)
    app.router.add_post("/app/api/admin", api_admin)
    app.router.add_post("/app/api/admin/leak", api_admin_leak_upload)
    app.router.add_post("/app/api/answer", api_answer)
