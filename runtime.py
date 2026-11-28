"""Действующие настройки: значения из .env, перекрытые тем, что сохранено в БД."""

from __future__ import annotations

from dataclasses import dataclass

from config import (
    DEFAULT_MODELS,
    DEFAULT_VISION_MODELS,
    Settings,
    normalize_providers,
    parse_packages,
)
from store import Store

EDITABLE = {
    "daily_limit": "Лимит сообщений в день",
    "max_context": "Глубина контекста",
    "ai_provider": "Провайдер ИИ",
    "ai_fallback_provider": "Резервные провайдеры",
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
    provider: str = ""
    fallback: str = ""
    star_packages: tuple[tuple[int, int], ...] = ()
    star_rate: int = 10
    image_daily_limit: int = 1
    required_channel: str = ""
    required_channel_url: str = ""
    group_gate: bool = True


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


BOOL_ON = {"1", "true", "yes", "on", "y", "t", "да", "так", "вкл"}
BOOL_OFF = {"0", "false", "no", "off", "n", "f", "нет", "не", "выкл"}


def _safe_bool(value: str | None, default: bool) -> bool:
    """Пусто или мусор — значение из env, иначе явное вкл/выкл."""
    if value is None:
        return default
    raw = value.strip().lower()
    if raw in BOOL_ON:
        return True
    if raw in BOOL_OFF:
        return False
    return default


async def load_runtime(store: Store, settings: Settings) -> Runtime:
    overrides = await store.all_settings()
    # Провайдера можно менять из админки: значение из БД важнее .env.
    provider = (overrides.get("ai_provider") or settings.ai_provider).strip().lower()
    if provider not in DEFAULT_MODELS:
        provider = settings.ai_provider
    fallback = (
        overrides.get("ai_fallback_provider")
        if overrides.get("ai_fallback_provider") is not None
        else settings.ai_fallback_provider
    )
    fallback = ",".join(normalize_providers(fallback or ""))
    # Модель по умолчанию зависит от провайдера: при смене провайдера
    # подставляем его модель, а не чужую из .env.
    default_model = (
        settings.ai_model
        if provider == settings.ai_provider
        else DEFAULT_MODELS[provider]
    )
    default_vision = (
        settings.ai_vision_model
        if provider == settings.ai_provider
        else DEFAULT_VISION_MODELS[provider]
    )
    return Runtime(
        daily_limit=max(0, _safe_int(overrides.get("daily_limit"), settings.daily_limit)),
        max_context=max(0, _safe_int(overrides.get("max_context"), settings.max_context)),
        provider=provider,
        fallback=fallback,
        model=(overrides.get("ai_model") or default_model).strip(),
        vision_model=(overrides.get("ai_vision_model") or default_vision).strip(),
        system_prompt=(overrides.get("system_prompt") or settings.system_prompt).strip(),
        star_packages=_safe_packages(overrides.get("star_packages"), settings.star_packages),
        star_rate=max(1, _safe_int(overrides.get("star_rate"), settings.star_rate)),
        image_daily_limit=max(
            0, _safe_int(overrides.get("image_daily_limit"), settings.image_daily_limit)
        ),
        required_channel=(
            overrides.get("required_channel")
            if overrides.get("required_channel") is not None
            else settings.required_channel
        )
        or "",
        required_channel_url=(
            overrides.get("required_channel_url")
            if overrides.get("required_channel_url") is not None
            else settings.required_channel_url
        )
        or "",
        group_gate=_safe_bool(overrides.get("group_gate"), settings.group_gate_enabled),
    )