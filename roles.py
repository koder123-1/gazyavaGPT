"""Роли и права: владелец, гл. админ, админ, саппорт.

Владелец задаётся `OWNER_ID` и не меняется из бота. Остальные роли хранятся в БД
и перекрывают `ADMIN_IDS` из окружения. Гл. админ может почти всё, что владелец,
кроме управления владельцем и другими гл. админами.
"""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from config import Settings
from store import Store

ROLE_OWNER = "owner"
ROLE_HEAD_ADMIN = "head_admin"
ROLE_ADMIN = "admin"
ROLE_SUPPORT = "support"

RANKS = {
    ROLE_SUPPORT: 10,
    ROLE_ADMIN: 50,
    ROLE_HEAD_ADMIN: 80,
    ROLE_OWNER: 100,
}

TITLES = {
    ROLE_OWNER: "👑 Владелец",
    ROLE_HEAD_ADMIN: "👑 Гл. админ",
    ROLE_ADMIN: "🛡 Админ",
    ROLE_SUPPORT: "🎫 Саппорт",
}

HINTS = {
    ROLE_OWNER: "полный доступ, назначается только через OWNER_ID",
    ROLE_HEAD_ADMIN: "почти все права владельца: админка, роли, платежи, тикеты",
    ROLE_ADMIN: "админка, пользователи, рассылка, настройки, платежи",
    ROLE_SUPPORT: "тикеты поддержки: читает и отвечает, закрывает обращения",
}

# Роли, которые можно выдать из бота. Владелец — только через OWNER_ID.
ASSIGNABLE = (ROLE_HEAD_ADMIN, ROLE_ADMIN, ROLE_SUPPORT)


def rank(role: str | None) -> int:
    return RANKS.get(role or "", 0)


def role_title(role: str | None) -> str:
    return TITLES.get(role or "", "—")


def is_staff(role: str | None) -> bool:
    return rank(role) >= RANKS[ROLE_SUPPORT]


def has_admin_access(role: str | None) -> bool:
    return rank(role) >= RANKS[ROLE_ADMIN]


def can_manage_roles(role: str | None) -> bool:
    return rank(role) >= RANKS[ROLE_HEAD_ADMIN]


async def resolve_role(user_id: int, settings: Settings, store: Store) -> str | None:
    """Владелец из env > роль из БД > ADMIN_IDS из env > None."""
    if settings.owner_id and user_id == settings.owner_id:
        return ROLE_OWNER
    stored = await store.get_role(user_id)
    if stored in RANKS and stored != ROLE_OWNER:
        return stored
    if user_id in settings.admin_ids:
        return ROLE_ADMIN
    return None


async def staff_ids(
    store: Store, settings: Settings, min_role: str = ROLE_SUPPORT
) -> list[int]:
    """Кому присылать уведомления: владелец, роли из БД и ADMIN_IDS."""
    needed = RANKS[min_role]
    ids = {row["user_id"] for row in await store.list_roles() if rank(row["role"]) >= needed}
    if needed <= RANKS[ROLE_ADMIN]:
        ids |= set(settings.admin_ids)
    if settings.owner_id:
        ids.add(settings.owner_id)
    return sorted(ids)


def can_assign(
    *,
    actor_role: str | None,
    actor_id: int,
    target_id: int,
    target_role: str | None,
    new_role: str | None,
    settings: Settings,
) -> tuple[bool, str]:
    """Проверяет, может ли actor выдать/снять роль target. Возвращает (можно, причина)."""
    if not can_manage_roles(actor_role):
        return False, "Управлять ролями могут только владелец и гл. админ."
    if settings.owner_id and target_id == settings.owner_id:
        return False, "Роль владельца менять нельзя — она задаётся через OWNER_ID."
    if target_id == actor_id:
        return False, "Свою роль менять нельзя — попроси другого администратора."
    if new_role is not None and new_role not in ASSIGNABLE:
        return False, "Такой роли нет."
    if rank(actor_role) == RANKS[ROLE_HEAD_ADMIN]:
        if target_role in {ROLE_OWNER, ROLE_HEAD_ADMIN}:
            return False, "Гл. админ не может менять владельца или другого гл. админа."
        if new_role in {ROLE_OWNER, ROLE_HEAD_ADMIN}:
            return False, "Назначать гл. админа может только владелец."
    return True, ""


class RoleFilter(BaseFilter):
    """Пускает только пользователей с ролью не ниже указанной."""

    def __init__(self, min_role: str = ROLE_ADMIN) -> None:
        self.min_role = min_role

    async def __call__(
        self, event: Message | CallbackQuery, settings: Settings, store: Store
    ) -> bool:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        role = await resolve_role(user.id, settings, store)
        return rank(role) >= RANKS[self.min_role]


class StaffFilter(BaseFilter):
    """Пускает владельца, админов и саппорт."""

    async def __call__(
        self, event: Message | CallbackQuery, settings: Settings, store: Store
    ) -> bool:
        user = getattr(event, "from_user", None)
        if user is None:
            return False
        return is_staff(await resolve_role(user.id, settings, store))