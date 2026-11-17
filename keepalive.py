"""Самопинг /health, чтобы бесплатный инстанс Render не засыпал.

Render free останавливает сервис после 15 минут без входящего HTTP-трафика,
а следующий запрос пользователя получает 502 и ждёт холодного старта. Раз в
`KEEPALIVE_SECONDS` (по умолчанию 10 минут) бот сам запрашивает свой публичный
`/health`: запрос проходит через прокси Render и считается входящим, поэтому
инстанс остаётся живым и отвечает сразу.

Выключить можно переменной `KEEPALIVE=off` (или `KEEPALIVE_SECONDS=0`).
Локально без `RENDER_EXTERNAL_URL` цикл не запускается.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os

import aiohttp

from config import Settings

log = logging.getLogger("keepalive")

DEFAULT_SECONDS = 600
MIN_SECONDS = 60
MAX_SECONDS = 3600
_task: asyncio.Task | None = None
DISABLED_VALUES = {"", "0", "off", "no", "false", "нет", "выкл"}


def health_url(settings: Settings) -> str:
    """Публичный адрес /health или пустая строка, если webhook не используется."""
    if not settings.use_webhook:
        return ""
    return f"{settings.base_url.rstrip('/')}/health"


def interval_seconds() -> int:
    """Период пинга с защитой от опечаток в переменной окружения."""
    if os.getenv("KEEPALIVE", "").strip().lower() in DISABLED_VALUES - {""}:
        return 0
    raw = os.getenv("KEEPALIVE_SECONDS", str(DEFAULT_SECONDS)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_SECONDS
    if value <= 0:
        return 0
    return max(MIN_SECONDS, min(value, MAX_SECONDS))


async def ping_once(url: str, timeout: float = 60.0) -> bool:
    """Один запрос к /health. Ошибки сети не считаем фатальными."""
    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            async with session.get(url) as response:
                if 200 <= response.status < 300:
                    return True
                log.warning("keep-alive: /health вернул HTTP %s", response.status)
                return False
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — пинг не должен ронять бота
        log.warning("keep-alive: пинг не удался: %s", exc)
        return False


async def _loop(url: str, seconds: int) -> None:
    # Первый пинг пораньше: подтверждаем, что сервис жив, и не подходим
    # к 15-минутному порогу засыпания впритык.
    await asyncio.sleep(min(seconds, 120))
    while True:
        await ping_once(url)
        await asyncio.sleep(seconds)


def start_loop(settings: Settings) -> None:
    """Запускает фоновый пинг, если есть публичный адрес и он не выключен."""
    global _task
    url = health_url(settings)
    seconds = interval_seconds()
    if not url or seconds <= 0:
        return
    if _task is None or _task.done():
        log.info("keep-alive: пинг %s каждые %s с", url, seconds)
        _task = asyncio.create_task(_loop(url, seconds))


async def stop_loop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None