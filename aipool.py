"""Пул моделей: ротация, остывание после ошибок и автоподбор списка у провайдера.

Провайдеры вроде Coarena дают десяток моделей по одному ключу. Бот берёт
следующую модель на каждый запрос (ротация), а модель, которая ответила
ошибкой 429/5xx, на время выпадает из начала очереди. Так бесплатный дневной
лимит расходуется ровнее, и один занятый провайдер не ломает ответ.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

log = logging.getLogger("aipool")

# Сколько секунд не трогаем модель после 429/5xx/таймаута.
COOLDOWN_SECONDS = 90.0
# Как часто перечитывать список моделей у провайдера.
DISCOVERY_TTL = 6 * 3600


def parse_model_list(payload: Any) -> tuple[list[str], set[str]]:
    """Разбирает ответ GET /models: (все id, id с поддержкой изображений)."""
    if not isinstance(payload, dict):
        return [], set()
    items = payload.get("data")
    if not isinstance(items, list):
        return [], set()

    models: list[str] = []
    vision: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("id") or "").strip()
        if not name:
            continue
        # Выведенные из эксплуатации модели не предлагаем.
        lifecycle = item.get("lifecycle")
        if lifecycle not in (None, "active"):
            continue
        models.append(name)
        capabilities = item.get("capabilities") or {}
        if capabilities.get("vision"):
            vision.add(name)
    return models, vision


class ModelPool:
    def __init__(
        self,
        models: list[str] | tuple[str, ...] = (),
        *,
        discover_url: str = "",
        api_key: str = "",
        rotate: bool = True,
        cooldown: float = COOLDOWN_SECONDS,
        ttl: float = DISCOVERY_TTL,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fixed = [m for m in dict.fromkeys(models) if m]
        self._discover_url = discover_url
        self._api_key = api_key
        self._rotate = rotate
        self._cooldown = cooldown
        self._ttl = ttl
        self._clock = clock
        self._models: list[str] = list(self._fixed)
        self._vision: set[str] = set()
        self._failed: dict[str, float] = {}
        self._cursor = 0
        self._discovered_at = 0.0
        self._lock = asyncio.Lock()

    @property
    def needs_discovery(self) -> bool:
        return bool(self._discover_url)

    @property
    def models(self) -> list[str]:
        return list(self._models)

    def order(self, *, vision: bool = False) -> list[str]:
        """Модели в порядке попыток: живые первыми, остывшие — в конце."""
        names = self._models
        if vision and self._vision:
            names = [m for m in names if m in self._vision]
        if not names:
            # Провайдер не сообщил о поддержке фото — не отсекаем всё подряд.
            names = self._models
        if not names:
            return []

        now = self._clock()
        ready = [m for m in names if self._failed.get(m, 0.0) <= now]
        cooling = [m for m in names if self._failed.get(m, 0.0) > now]
        cooling.sort(key=lambda m: self._failed.get(m, 0.0))

        # Ротация — только среди живых: остывшая модель не должна всплывать
        # в начало очереди на следующем запросе.
        if self._rotate and len(ready) > 1:
            self._cursor %= len(ready)
            ready = ready[self._cursor :] + ready[: self._cursor]
            self._cursor = (self._cursor + 1) % len(ready)
        return ready + cooling

    def mark_failed(self, model: str) -> None:
        if model:
            self._failed[model] = self._clock() + self._cooldown

    def mark_ok(self, model: str) -> None:
        self._failed.pop(model, None)

    def cooldown_left(self, model: str) -> float:
        return max(0.0, self._failed.get(model, 0.0) - self._clock())

    async def discover(self, session: Any) -> None:
        """Перечитывает список моделей, если он устарел."""
        if not self._discover_url:
            return
        async with self._lock:
            now = self._clock()
            if self._models and now - self._discovered_at < self._ttl:
                return
            headers = {"Accept": "application/json"}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            try:
                async with session.get(self._discover_url, headers=headers) as resp:
                    if resp.status != 200:
                        log.warning(
                            "Список моделей недоступен: HTTP %s", resp.status
                        )
                        return
                    data = await resp.json()
            except Exception as exc:  # noqa: BLE001 — список моделей не критичен
                log.warning("Не удалось получить список моделей: %r", exc)
                return

            models, vision = parse_model_list(data)
            if not models:
                return
            preferred = [m for m in self._fixed if m in models]
            self._models = preferred + [m for m in models if m not in preferred]
            self._vision = vision & set(models)
            self._discovered_at = now
            log.info(
                "Моделей у провайдера: %d, из них читают фото: %d",
                len(self._models),
                len(self._vision),
            )