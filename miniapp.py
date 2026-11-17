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
from aiogram.utils.web_app import check_webapp_signature
from aiohttp import web

import models as model_catalog
import styles as style_catalog
from config import Settings
from i18n import LANGS, normalize_lang
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
    unlimited = runtime.daily_limit <= 0
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


# --------------------------------------------------------------------------- подключение
def setup(app: web.Application, settings: Settings, store: Store, bot: Bot) -> None:
    """Вешает маршруты Mini App на уже существующее приложение."""
    app["miniapp_settings"] = settings
    app["miniapp_store"] = store
    app["miniapp_bot"] = bot

    app.router.add_get("/app", index)
    app.router.add_get("/app/", index)
    if BASE_DIR.is_dir():
        app.router.add_static("/app/assets/", BASE_DIR, name="miniapp")
    app.router.add_post("/app/api/me", api_me)
    app.router.add_post("/app/api/bonus", api_bonus)
    app.router.add_post("/app/api/settings", api_settings)
    app.router.add_post("/app/api/top", api_top)
