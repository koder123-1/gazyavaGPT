"""Здоровье провайдеров ИИ: незаметное переключение на живой резерв.

Пользователь не должен ждать мёртвый API. Если провайдер упал, упёрся в лимит
или заблокирован по региону, бот сразу отвечает через следующий из
`AI_FALLBACK_PROVIDER`, а сам провайдер остывает на время. Через cooldown бот
снова пробует его первым — вручную ничего переключать не нужно.

Фоновый пробник раз в `AI_HEALTH_SECONDS` проверяет `/models` каждого
провайдера, поэтому к моменту вопроса статус уже известен и переключение
занимает миллисекунды, а не таймаут запроса.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass, field

import aiohttp

from config import (
    DEFAULT_BASE_URLS,
    DEFAULT_MODELS,
    HTTP_USER_AGENT,
    Settings,
    _provider_key,
    _specific_provider_key,
)

log = logging.getLogger("providerhealth")

# Сколько секунд не зовём провайдера после ошибки.
FAIL_COOLDOWN = 90.0
LIMIT_COOLDOWN = 300.0
AUTH_COOLDOWN = 1800.0
GEO_COOLDOWN = 6 * 3600.0
UNKNOWN_COOLDOWN = 120.0

DEFAULT_PROBE_SECONDS = 300
MIN_PROBE = 60
MAX_PROBE = 3600

DISABLED_VALUES = {"", "0", "off", "no", "false", "нет", "выкл"}


@dataclass
class _State:
    until: float = 0.0
    reason: str = ""
    kind: str = ""
    failures: int = 0
    ok_at: float = 0.0
    # Медиана последних замеров: один медленный ответ не должен навсегда
    # отодвигать быстрого провайдера в конец очереди.
    latency: float = 0.0
    samples: int = 0
    recent: list[float] = field(default_factory=list)


_states: dict[str, _State] = {}
# Отдельно по моделям: Coarena блокирует регион для одной модели, но
# остальные её модели работают. Ключ — "провайдер/модель".
_model_states: dict[str, _State] = {}
_task: asyncio.Task | None = None


def _model_key(provider: str, model: str) -> str:
    return f"{provider}/{model}"


def _classify(status: int, reason: str) -> tuple[str, float]:
    """(вид сбоя, сколько секунд остывать) по ответу провайдера."""
    low = (reason or "").lower()
    if any(
        marker in low
        for marker in (
            "country or region",
            "not available in your",
            "location is not supported",
            "unsupported_country",
            "model_region_restricted",
        )
    ):
        return "geo", GEO_COOLDOWN
    # Ключ без права inference — проблема всего провайдера, а не модели.
    if any(
        marker in low
        for marker in (
            "insufficient_scope",
            "invalid_api_key",
            "invalid api key",
            "incorrect api key",
            "model_api_terms_required",
        )
    ):
        return "auth", AUTH_COOLDOWN
    if status in (401, 403):
        # 403 часто про конкретную модель (скоуп/тариф): остужаем ненадолго,
        # чтобы живые модели того же провайдера не простаивали.
        return "auth", UNKNOWN_COOLDOWN
    if status in (402, 429) or any(
        marker in low
        for marker in (
            "insufficient_quota",
            "rate limit",
            "rate-limited",
            "too many requests",
            "quota",
        )
    ):
        return "limit", LIMIT_COOLDOWN
    if status >= 500 or status == 0:
        return "down", FAIL_COOLDOWN
    return "error", UNKNOWN_COOLDOWN


def is_provider_level(status: int, reason: str) -> bool:
    """Стоит ли остужать всего провайдера, а не только одну модель.

    404/400 про модель — это «нет такой модели», другие модели работать будут.
    403 без явных маркеров ключа — почти всегда про одну модель (скоуп/тариф).
    """
    if status in (404, 413, 422):
        return False
    low = (reason or "").lower()
    auth_markers = (
        "insufficient_scope",
        "invalid_api_key",
        "invalid api key",
        "incorrect api key",
        "model_api_terms_required",
    )
    if status == 403:
        return any(marker in low for marker in auth_markers)
    if status == 400:
        kind, _ = _classify(status, reason)
        if kind == "geo":
            # «not available in your country (BY) ... Pick another model» —
            # это про конкретную модель, остальные у провайдера работают.
            if "pick another model" in low or "model_region_restricted" in low:
                return False
            return True
        return kind == "auth"
    if status == 401:
        return True
    kind, _ = _classify(status, reason)
    return kind != "error" or status >= 500


def available(provider: str) -> bool:
    """Можно ли сейчас звать провайдера (не остывает ли он)."""
    state = _states.get(provider)
    return state is None or state.until <= time.monotonic()


def model_available(provider: str, model: str) -> bool:
    """Не остывает ли конкретная модель провайдера."""
    state = _model_states.get(_model_key(provider, model))
    return state is None or state.until <= time.monotonic()


def mark_model_failed(provider: str, model: str, *, status: int = 0, reason: str = "") -> None:
    """Модель не подошла (регион, тариф, нет в каталоге): не зовём её снова
    какое-то время, но провайдер в целом остаётся живым."""
    if not provider or not model:
        return
    kind, cooldown = _classify(status, reason)
    if kind == "error":
        cooldown = UNKNOWN_COOLDOWN
    key = _model_key(provider, model)
    state = _model_states.setdefault(key, _State())
    state.failures += 1
    state.until = time.monotonic() + cooldown
    state.reason = (reason or kind)[:200]
    state.kind = kind
    log.info(
        "Модель %s у %s остывает %.0f с (%s)", model, provider, cooldown, kind
    )


def mark_model_ok(provider: str, model: str) -> None:
    if not provider or not model:
        return
    _model_states.pop(_model_key(provider, model), None)


def filter_models(provider: str, models: list[str]) -> list[str]:
    """Убирает остывшие модели, но никогда не возвращает пустой список."""
    fresh = [m for m in models if model_available(provider, m)]
    return fresh or list(models)


def cooldown_left(provider: str) -> float:
    state = _states.get(provider)
    if state is None:
        return 0.0
    return max(0.0, state.until - time.monotonic())


def order(providers: list[str] | tuple[str, ...]) -> list[str]:
    """Живые в исходном порядке, остывшие — в конце (по времени возврата).

    Остывших не выбрасываем совсем: если все провайдеры прилегли, лучше
    попробовать хоть кого-то, чем сразу сказать пользователю «недоступно».
    """
    now = time.monotonic()
    ready = [name for name in providers if available(name)]
    cooling = [name for name in providers if not available(name)]
    cooling.sort(key=lambda name: _states.get(name, _State()).until)
    return ready + cooling


UNKNOWN_LATENCY = 4.0
# Сколько последних замеров учитываем в медиане.
LATENCY_WINDOW = 5


def fastest(providers: list[str] | tuple[str, ...]) -> list[str]:
    """Резервы по скорости: быстрые первыми, медленные — в конце.

    Резервы различаются в разы (0.5 с против 18 с), а пользователь ждёт
    каждый. Неизмеренный провайдер получает среднее значение: он не должен
    ни обгонять проверенно быстрых, ни простаивать за проверенно медленными.
    """
    def key(name: str) -> float:
        state = _states.get(name)
        if state is None or state.samples <= 0:
            return UNKNOWN_LATENCY
        return state.latency

    return sorted(providers, key=key)


def mark_latency(provider: str, seconds: float) -> None:
    """Запоминает время ответа: медиана последних замеров.

    Среднее ломается от одного зависшего ответа (18 с, 18 с, 0.5 с — среднее
    хуже, чем есть на самом деле). Медиана устойчива к таким выбросам.
    """
    if not provider or seconds <= 0:
        return
    state = _states.setdefault(provider, _State())
    state.recent.append(float(seconds))
    del state.recent[:-LATENCY_WINDOW]
    ordered = sorted(state.recent)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        state.latency = ordered[middle]
    else:
        state.latency = (ordered[middle - 1] + ordered[middle]) / 2
    state.samples += 1


def mark_ok(provider: str) -> None:
    if not provider:
        return
    state = _states.setdefault(provider, _State())
    state.until = 0.0
    state.reason = ""
    state.kind = ""
    state.failures = 0
    state.ok_at = time.monotonic()


def mark_probe_ok(provider: str) -> None:
    """Пробник увидел 200 на /models.

    Каталог отдаётся и при исчерпанной квоте, поэтому лимит и гео-блокировку
    пробник не снимает: только простой и отклонённый ключ (200 значит, что
    ключ принят).
    """
    if not provider:
        return
    state = _states.setdefault(provider, _State())
    state.ok_at = time.monotonic()
    if state.kind not in ("limit", "geo"):
        state.until = 0.0
        state.reason = ""
        state.kind = ""
        state.failures = 0


def suspect(provider: str) -> bool:
    """Провайдер уже сбоил и с тех пор не отвечал — ждём его недолго.

    Здоровому провайдеру даём полный таймаут: длинный ответ может писаться
    и минуту. А после сбоя держать пользователя 65 секунд нельзя — лучше
    быстро уйти на резерв.
    """
    state = _states.get(provider)
    return state is not None and state.failures > 0


def call_timeout(provider: str) -> float | None:
    """Таймаут запроса к модели: короткий для подозрительного провайдера.

    None — оставить общий таймаут сессии, чтобы не обрезать долгий ответ
    у здорового провайдера.
    """
    return 20.0 if suspect(provider) else None


def mark_failed(provider: str, *, status: int = 0, reason: str = "") -> None:
    """Провайдер не ответил: остывает, чтобы не тормозить следующий запрос."""
    if not provider:
        return
    kind, cooldown = _classify(status, reason)
    state = _states.setdefault(provider, _State())
    state.failures += 1
    state.until = time.monotonic() + cooldown
    state.reason = (reason or kind)[:200]
    state.kind = kind
    log.warning(
        "Провайдер %s остывает %.0f с (%s): %s",
        provider,
        cooldown,
        kind,
        state.reason[:120],
    )


def snapshot() -> dict[str, dict]:
    """Статус для админки: сколько ещё остывать и почему."""
    now = time.monotonic()
    result: dict[str, dict] = {}
    for name, state in _states.items():
        result[name] = {
            "left": max(0.0, state.until - now),
            "reason": state.reason,
            "kind": state.kind,
            "failures": state.failures,
            "ok_at": state.ok_at,
            "latency": round(state.latency, 2),
            "samples": state.samples,
        }
    return result


def model_snapshot() -> dict[str, dict]:
    """Остывшие модели: ключ "провайдер/модель" -> статус."""
    now = time.monotonic()
    result: dict[str, dict] = {}
    for key, state in _model_states.items():
        left = max(0.0, state.until - now)
        if left <= 0:
            continue
        provider, _, model = key.partition("/")
        result[key] = {
            "provider": provider,
            "model": model,
            "left": left,
            "kind": state.kind,
            "reason": state.reason,
        }
    return result


def reset() -> None:
    """Для тестов: забыть историю."""
    _states.clear()
    _model_states.clear()


def interval_seconds() -> int:
    raw = os.getenv("AI_HEALTH_SECONDS", str(DEFAULT_PROBE_SECONDS)).strip()
    if raw.lower() in DISABLED_VALUES:
        return 0
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_PROBE_SECONDS
    if value <= 0:
        return 0
    return max(MIN_PROBE, min(value, MAX_PROBE))


def probe_targets(settings: Settings) -> list[str]:
    """Провайдеры, которых есть чем проверить: свой ключ и известный адрес."""
    names: list[str] = []
    for name in DEFAULT_MODELS:
        if name == "gemini":
            # У Gemini каталог другого формата (/v1beta/models?key=).
            continue
        if not _probe_base(name):
            continue
        key = _specific_provider_key(name)
        if not key and name == settings.ai_provider:
            key = _provider_key(name)
        if key:
            names.append(name)
    return names


def _probe_base(name: str) -> str:
    """Адрес для пробника: <PROVIDER>_BASE_URL важнее стандартного."""
    return (
        os.getenv(f"{name.upper()}_BASE_URL", "").strip().rstrip("/")
        or DEFAULT_BASE_URLS.get(name, "")
    )


async def _probe_one(
    session: aiohttp.ClientSession, name: str, settings: Settings
) -> bool:
    base = _probe_base(name)
    key = _specific_provider_key(name)
    if not key and name == settings.ai_provider:
        key = _provider_key(name)
    if not base or not key:
        return False

    headers = {"Accept": "application/json", "User-Agent": HTTP_USER_AGENT}
    headers["Authorization"] = f"Bearer {key}"
    try:
        async with session.get(base.rstrip("/") + "/models", headers=headers) as resp:
            if resp.status == 200:
                mark_probe_ok(name)
                return True
            if resp.status == 404:
                # Каталога может не быть — это не значит, что провайдер мёртв.
                mark_probe_ok(name)
                return True
            body = await resp.text()
            mark_failed(name, status=resp.status, reason=body[:200])
            return False
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — пробник не должен ронять бота
        mark_failed(name, reason=str(exc))
        return False


async def probe(name: str, settings: Settings, *, timeout: float = 12.0) -> bool:
    """Один запрос к /models. True — провайдер жив."""
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with aiohttp.ClientSession(timeout=client_timeout) as session:
        return await _probe_one(session, name, settings)


async def _loop(names: list[str], settings: Settings, seconds: int) -> None:
    # Первый проход почти сразу: к первому вопросу статус уже известен.
    await asyncio.sleep(3)
    client_timeout = aiohttp.ClientTimeout(total=20)
    while True:
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            await asyncio.gather(
                *(_probe_one(session, name, settings) for name in names),
                return_exceptions=True,
            )
        await asyncio.sleep(seconds)


def start_loop(settings: Settings) -> None:
    global _task
    seconds = interval_seconds()
    names = probe_targets(settings)
    if seconds <= 0 or not names:
        return
    if _task is None or _task.done():
        log.info(
            "Проверка провайдеров ИИ каждые %s с: %s", seconds, ", ".join(names)
        )
        _task = asyncio.create_task(_loop(names, settings, seconds))


async def stop_loop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
