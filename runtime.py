"""Действующие настройки: значения из .env, перекрытые тем, что сохранено в БД."""

from __future__ import annotations

from dataclasses import dataclass

from config import Settings, parse_packages
from store import Store

EDITABLE = {
    "daily_limit": "Лимит сообщений в день",
    "max_context": "Глубина контекста",
    "ai_model": "Модель ИИ",
    "ai_vision_model": "Модель для изображений",
    "system_prompt": "Системный промпт",
    "star_packages": "Тарифы: запросы за звёзды",
    "star_rate": "Курс: запросов за 1 звезду",
    "image_daily_limit": "Бесплатных картинок в день",
    "required_channel": "Канал обязательной подписки",
    "required_channel_url": "Ссылка на канал подписки",
}


@dataclass(frozen=True)
class Runtime:
    daily_limit: int
    max_context: int
    model: str
    vision_model: str
    system_prompt: str
    star_packages: tuple[tuple[int, int], ...] = ()
    star_rate: int = 10
    image_daily_limit: int = 1
    required_channel: str = ""
    required_channel_url: str = ""


def _safe_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _safe_packages(
    value: str | None, default: tuple[tuple[int, int], ...]
) -> tuple[tuple[int, int], ...]:
    try:
        return parse_packages(value or "", default)
    except ValueError:
        return default


async def load_runtime(store: Store, settings: Settings) -> Runtime:
    overrides = await store.all_settings()
    return Runtime(
        daily_limit=_safe_int(overrides.get("daily_limit"), settings.daily_limit),
        max_context=_safe_int(overrides.get("max_context"), settings.max_context),
        model=(overrides.get("ai_model") or settings.ai_model).strip(),
        vision_model=(overrides.get("ai_vision_model") or settings.ai_vision_model).strip(),
        system_prompt=(overrides.get("system_prompt") or settings.system_prompt).strip(),
        star_packages=_safe_packages(overrides.get("star_packages"), settings.star_packages),
        star_rate=max(1, _safe_int(overrides.get("star_rate"), settings.star_rate)),
        image_daily_limit=max(
            0, _safe_int(overrides.get("image_daily_limit"), settings.image_daily_limit)
        ),
        required_channel=(
            overrides.get("required_channel")
            if "required_channel" in overrides
            else settings.required_channel
        ).strip(),
        required_channel_url=(
            overrides.get("required_channel_url")
            if "required_channel_url" in overrides
            else settings.required_channel_url
        ).strip(),
    )