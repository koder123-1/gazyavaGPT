"""Каталог моделей для выбора пользователем: название и цена в звёздах.

Цена — разовое открытие модели для пользователя. Бесплатная модель (DeepSeek)
доступна всем и отвечает по умолчанию. Админ может выдать любую модель без оплаты.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelInfo:
    id: str
    title: str
    stars: int = 0
    hint: str = ""


CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo("deepseek-v4.1-flash-1017", "DeepSeek V4.1 Flash", 0, "бесплатно"),
    ModelInfo("gpt-6-luna", "GPT-6 Luna", 5, "самая сильная"),
    ModelInfo("claude-sonnet-5-5", "Claude Sonnet 5.5", 4, "сильная"),
    ModelInfo("gemini-4-argon", "Gemini 4 Argon", 3, "универсальная"),
    ModelInfo("glm-5.3", "GLM-5.3", 3, "универсальная"),
    ModelInfo("grok-4.7", "Grok 4.7", 2, "быстрая"),
    ModelInfo("glm-5.3-flash", "GLM-5.3 Flash", 1, "самая быстрая"),
)

BY_ID: dict[str, ModelInfo] = {item.id: item for item in CATALOG}
DEFAULT_MODEL = CATALOG[0].id


def info(model_id: str | None) -> ModelInfo | None:
    return BY_ID.get(model_id or "")


def title(model_id: str | None) -> str:
    item = info(model_id)
    return item.title if item else (model_id or "—")


def stars(model_id: str | None) -> int:
    item = info(model_id)
    return item.stars if item else 0


def is_free(model_id: str | None) -> bool:
    return stars(model_id) <= 0


def ids() -> list[str]:
    return [item.id for item in CATALOG]


def index_of(model_id: str | None) -> int | None:
    for index, item in enumerate(CATALOG):
        if item.id == model_id:
            return index
    return None


def by_index(index: int) -> ModelInfo | None:
    if 0 <= index < len(CATALOG):
        return CATALOG[index]
    return None