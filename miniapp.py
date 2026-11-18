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

import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import LabeledPrice
from aiogram.utils.web_app import check_webapp_signature
from aiohttp import web

import models as model_catalog
import payments
import reminders
import styles as style_catalog
import toolbox
from config import Settings
from i18n import LANGS, normalize_lang
from roles import is_staff, resolve_role
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
    request: web.Request,
) -> tuple[dict[str, Any] | None, web.Response | None]:
    settings: Settings = request.app["miniapp_settings"]
    body = await _read_body(request)
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
            "unlimited": unlimited,
            "remaining": None if unlimited else int(left),
            "used_today": int(card.get("used_today", 0) or 0),
            "total_requests": int(card.get("total_requests", 0) or 0),
            "bonus_requests": await store.bonus_requests(user_id),
            "bonus_streak": await store.bonus_streak(user_id),
            "bonus_claimed_today": await store.bonus_claimed_today(user_id),
            "bonus_base": settings.bonus_base,
            "bonus_max": settings.bonus_max,
            "invites": await store.referral_count(user_id),
            "invite_reward": settings.invite_reward,
            "invited_reward": settings.invited_reward,
            "invite_link": invite_link,
            "bot_name": settings.bot_name,
            "image_credits": int(card.get("image_credits", 0) or 0),
            "payments_enabled": settings.payments_enabled,
            "langs": list(LANGS),
            "styles": list(STYLES),
            "daily_limit": runtime.daily_limit,
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


# --------------------------------------------------------------------------- подключение
def setup(app: web.Application, settings: Settings, store: Store, bot: Bot) -> None:
    """Вешает маршруты Mini App на уже существующее приложение."""
    app["miniapp_settings"] = settings
    app["miniapp_store"] = store
    app["miniapp_bot"] = bot

    if not app.get("miniapp_no_cache_hook"):
        app["miniapp_no_cache_hook"] = True
        app.on_response_prepare.append(_no_cache)

    app.router.add_get("/app", index)
    app.router.add_get("/app/", index)
    if BASE_DIR.is_dir():
        app.router.add_static("/app/assets/", BASE_DIR, name="miniapp")
    app.router.add_post("/app/api/me", api_me)
    app.router.add_post("/app/api/bonus", api_bonus)
    app.router.add_post("/app/api/settings", api_settings)
    app.router.add_post("/app/api/top", api_top)
    app.router.add_post("/app/api/history", api_history)
    app.router.add_post("/app/api/tools", api_tools)
    app.router.add_post("/app/api/buy", api_buy)
    app.router.add_post("/app/api/invoice", api_invoice)
    app.router.add_post("/app/api/answer", api_answer)
