"""Inline-режим: `@bot вопрос` — ответ прямо в любом чате.

У Telegram жёсткий дедлайн на ответ (10 секунд), а ИИ иногда думает дольше.
Поэтому: короткий таймаут, мгновенный кэш на повторные запросы и аккуратная
подсказка «открой в боте», если модель не успела.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import OrderedDict
from html import escape

from aiogram import F, Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultsButton,
    InputTextMessageContent,
)

from ai import AIClient
from config import Settings
from formatting import to_telegram_html
from i18n import normalize_lang, t
from roles import has_admin_access, resolve_role
from runtime import load_runtime
from store import Store

router = Router(name="inline")

# Сколько ждём модель: остальное время нужно на сеть и отправку ответа.
AI_TIMEOUT = 7.5
CACHE_TTL = 15 * 60
CACHE_SIZE = 200
MAX_QUERY = 900

_cache: OrderedDict[str, tuple[float, str]] = OrderedDict()


def _cache_get(key: str) -> str | None:
    item = _cache.get(key)
    if item is None:
        return None
    stamp, value = item
    if time.monotonic() - stamp > CACHE_TTL:
        _cache.pop(key, None)
        return None
    _cache.move_to_end(key)
    return value


def _cache_put(key: str, value: str) -> None:
    _cache[key] = (time.monotonic(), value)
    _cache.move_to_end(key)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)


def _article(
    result_id: str,
    title: str,
    text: str,
    description: str = "",
    *,
    markup=None,
) -> InlineQueryResultArticle:
    return InlineQueryResultArticle(
        id=result_id[:64],
        title=title[:120],
        description=description[:120] or None,
        input_message_content=InputTextMessageContent(
            message_text=text[:4096],
            parse_mode="HTML",
            disable_web_page_preview=True,
        ),
        reply_markup=markup,
    )


@router.inline_query()
async def on_inline(
    query: InlineQuery,
    ai: AIClient,
    store: Store,
    settings: Settings,
) -> None:
    user = query.from_user
    lang = await _lang(store, settings, user.id) if user else normalize_lang(
        settings.default_lang
    )
    prompt = " ".join((query.query or "").split())[:MAX_QUERY]

    # Пустой запрос: рассказываем, как пользоваться.
    if not prompt:
        await query.answer(
            [],
            cache_time=0,
            is_personal=True,
            button=InlineQueryResultsButton(
                text=t(lang, "inline.open"),
                start_parameter="inline",
            ),
        )
        return

    cached = _cache_get(prompt)
    if cached:
        await query.answer(
            [
                _article(
                    "ai-cache",
                    t(lang, "inline.answer_title", prompt=prompt[:60]),
                    cached,
                    t(lang, "inline.answer_desc"),
                )
            ],
            cache_time=0,
            is_personal=True,
        )
        return

    if user is not None:
        await store.ensure_user(user.id, user.username, user.first_name)

    runtime = await load_runtime(store, settings)
    role = await resolve_role(user.id, settings, store) if user else None
    limit = 0 if has_admin_access(role) else runtime.daily_limit
    reserved = await store.try_consume(user.id, limit) if user else None
    if reserved is None:
        await query.answer(
            [
                _article(
                    "ai-limit",
                    t(lang, "inline.limit_title"),
                    t(lang, "inline.limit_text"),
                    t(lang, "inline.limit_desc"),
                )
            ],
            cache_time=0,
            is_personal=True,
            button=InlineQueryResultsButton(
                text=t(lang, "inline.open"),
                start_parameter="inline",
            ),
        )
        return

    model = runtime.model or None
    try:
        answer = await asyncio.wait_for(
            ai.reply(
                [],
                prompt,
                model=model,
                system_prompt=runtime.system_prompt,
                lang=lang,
            ),
            timeout=AI_TIMEOUT,
        )
    except asyncio.TimeoutError:
        if user is not None and reserved:
            await store.refund_consume(user.id, reserved)
        await query.answer(
            [
                _article(
                    "ai-slow",
                    t(lang, "inline.slow_title"),
                    t(lang, "inline.slow_text"),
                    t(lang, "inline.slow_desc"),
                )
            ],
            cache_time=0,
            is_personal=True,
            button=InlineQueryResultsButton(
                text=t(lang, "inline.open"),
                start_parameter="inline",
            ),
        )
        return
    except Exception:  # noqa: BLE001 — inline не должен падать молча
        if user is not None and reserved:
            await store.refund_consume(user.id, reserved)
        await query.answer(
            [
                _article(
                    "ai-error",
                    t(lang, "inline.error_title"),
                    t(lang, "inline.error_text"),
                    t(lang, "inline.error_desc"),
                )
            ],
            cache_time=0,
            is_personal=True,
            button=InlineQueryResultsButton(
                text=t(lang, "inline.open"),
                start_parameter="inline",
            ),
        )
        return

    text = (answer or "").strip()
    if not text:
        if user is not None and reserved:
            await store.refund_consume(user.id, reserved)
        await query.answer([], cache_time=0, is_personal=True)
        return

    html = to_telegram_html(text)
    _cache_put(prompt, html)
    if user is not None:
        with contextlib.suppress(Exception):
            await store.add_exchange(user.id, prompt, text, 2)

    results = [
        _article(
            "ai-answer",
            t(lang, "inline.answer_title", prompt=prompt[:60]),
            html,
            t(lang, "inline.answer_desc"),
        )
    ]
    short = html if len(html) <= 900 else html[:900].rsplit(" ", 1)[0] + "…"
    results.append(
        _article(
            "ai-share",
            t(lang, "inline.share_title"),
            short,
            t(lang, "inline.share_desc"),
        )
    )
    await query.answer(results, cache_time=0, is_personal=True)


async def _lang(store: Store, settings: Settings, user_id: int) -> str:
    stored = await store.get_lang(user_id)
    return normalize_lang(stored or settings.default_lang)