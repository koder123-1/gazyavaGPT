"""Хранилище: Postgres (Neon/Render/Supabase) или память — для локальной отладки."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from config import Settings

log = logging.getLogger("store")


class Store(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def ping(self) -> bool: ...

    async def ensure_user(self, user_id: int, username: str | None, first_name: str | None) -> None: ...
    async def get_lang(self, user_id: int) -> str | None: ...
    async def set_lang(self, user_id: int, lang: str) -> None: ...
    async def get_model(self, user_id: int) -> str | None: ...
    async def set_model(self, user_id: int, model: str | None) -> None: ...
    async def grant_model(self, user_id: int, model: str, granted_by: int = 0) -> None: ...
    async def revoke_model(self, user_id: int, model: str) -> None: ...
    async def list_model_access(self, user_id: int) -> list[str]: ...
    async def has_model_access(self, user_id: int, model: str) -> bool: ...
    async def is_banned(self, user_id: int) -> bool: ...
    async def set_banned(self, user_id: int, banned: bool) -> bool: ...

    async def remaining(self, user_id: int, daily_limit: int) -> int: ...
    async def consume(self, user_id: int, daily_limit: int = 0) -> int: ...
    async def bonus_requests(self, user_id: int) -> int: ...
    async def add_bonus(self, user_id: int, count: int) -> int: ...
    async def record_payment(
        self, user_id: int, requests: int, stars: int, charge_id: str, kind: str = "requests"
    ) -> bool: ...
    async def get_payment(self, payment_id: int) -> dict | None: ...
    async def mark_payment_refunded(self, payment_id: int) -> dict | None: ...
    async def get_subscription(self, user_id: int) -> datetime | None: ...
    async def activate_subscription(self, user_id: int, days: int) -> datetime: ...
    async def cancel_subscription(self, user_id: int) -> None: ...
    async def trim_subscription(self, user_id: int, days: int) -> datetime | None: ...
    async def payments_stats(self) -> dict[str, int]: ...
    async def recent_payments(self, limit: int) -> list[dict]: ...
    async def history(self, user_id: int, limit: int) -> list[dict[str, str]]: ...
    async def add_exchange(self, user_id: int, question: str, answer: str, keep: int) -> None: ...
    async def reset(self, user_id: int) -> None: ...

    async def stats(self) -> dict[str, int]: ...
    async def list_users(self, offset: int, limit: int) -> list[dict]: ...
    async def user_card(self, user_id: int) -> dict | None: ...
    async def top_users(self, limit: int) -> list[dict]: ...
    async def user_ids(self, only_active: bool = False) -> list[int]: ...

    async def get_setting(self, key: str) -> str | None: ...
    async def set_setting(self, key: str, value: str) -> None: ...
    async def delete_setting(self, key: str) -> None: ...
    async def all_settings(self) -> dict[str, str]: ...

    async def add_exchange_record(
        self, user_id: int, question: str, answer: str, kind: str
    ) -> int: ...
    async def get_exchange(self, exchange_id: int) -> dict | None: ...
    async def set_vote(self, exchange_id: int, vote: str) -> None: ...
    async def feedback_stats(self) -> dict[str, int]: ...

    async def get_profile(self, user_id: int) -> dict | None: ...
    async def set_profile(
        self, user_id: int, grade: str | None, subject: str | None, style: str | None
    ) -> None: ...
    async def delete_profile(self, user_id: int) -> None: ...

    async def get_role(self, user_id: int) -> str | None: ...
    async def set_role(self, user_id: int, role: str, granted_by: int = 0) -> None: ...
    async def delete_role(self, user_id: int) -> None: ...
    async def list_roles(self) -> list[dict]: ...
    async def role_ids(self) -> list[int]: ...

    async def create_ticket(self, user_id: int, topic: str, text: str) -> int: ...
    async def append_ticket_message(
        self, ticket_id: int, author_id: int, text: str, from_staff: bool
    ) -> int: ...
    async def get_ticket(self, ticket_id: int) -> dict | None: ...
    async def ticket_messages(self, ticket_id: int, limit: int = 30) -> list[dict]: ...
    async def open_tickets(self, limit: int, offset: int = 0) -> list[dict]: ...
    async def user_open_ticket(self, user_id: int) -> dict | None: ...
    async def user_tickets(self, user_id: int, limit: int = 10) -> list[dict]: ...
    async def close_ticket(self, ticket_id: int, closed_by: int) -> bool: ...
    async def tickets_stats(self) -> dict[str, int]: ...


# --------------------------------------------------------------------------- память
class MemoryStore:
    """Данные живут в процессе. После рестарта всё пропадает — только для разработки."""

    def __init__(self) -> None:
        self._users: dict[int, dict] = {}
        self._usage: dict[int, tuple[date, int]] = {}
        self._history: dict[int, deque[dict[str, str]]] = defaultdict(lambda: deque(maxlen=64))
        self._total_requests: dict[int, int] = defaultdict(int)
        self._settings: dict[str, str] = {}
        self._exchanges: dict[int, dict] = {}
        self._profiles: dict[int, dict] = {}
        self._payments: dict[str, dict] = {}
        self._model_access: dict[int, set[str]] = {}
        self._roles: dict[int, str] = {}
        self._tickets: dict[int, dict] = {}
        self._ticket_msgs: dict[int, list[dict]] = {}
        self._seq = 0
        self._exchange_seq = 0
        self._payment_seq = 0
        self._ticket_seq = 0

    async def start(self) -> None:
        log.warning("DATABASE_URL не задан -> данные хранятся в памяти (пропадут при рестарте)")

    async def close(self) -> None:
        pass

    async def ping(self) -> bool:
        return True

    async def ensure_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        user = self._users.setdefault(
            user_id,
            {"username": None, "first_name": None, "banned": False, "seen": 0, "bonus_requests": 0},
        )
        user.setdefault("bonus_requests", 0)
        user.setdefault("lang", None)
        self._seq += 1
        user.update({"username": username, "first_name": first_name, "seen": self._seq})

    async def get_lang(self, user_id: int) -> str | None:
        return self._users.get(user_id, {}).get("lang")

    async def set_lang(self, user_id: int, lang: str) -> None:
        user = self._users.setdefault(
            user_id,
            {"username": None, "first_name": None, "banned": False, "seen": 0, "bonus_requests": 0},
        )
        user["lang"] = lang

    async def get_model(self, user_id: int) -> str | None:
        return self._users.get(user_id, {}).get("model")

    async def set_model(self, user_id: int, model: str | None) -> None:
        user = self._users.setdefault(
            user_id,
            {"username": None, "first_name": None, "banned": False, "seen": 0, "bonus_requests": 0},
        )
        user["model"] = model or None

    async def grant_model(self, user_id: int, model: str, granted_by: int = 0) -> None:
        if model:
            self._model_access.setdefault(user_id, set()).add(model)

    async def revoke_model(self, user_id: int, model: str) -> None:
        self._model_access.get(user_id, set()).discard(model)

    async def list_model_access(self, user_id: int) -> list[str]:
        return sorted(self._model_access.get(user_id, set()))

    async def has_model_access(self, user_id: int, model: str) -> bool:
        return model in self._model_access.get(user_id, set())

    async def is_banned(self, user_id: int) -> bool:
        return bool(self._users.get(user_id, {}).get("banned"))

    async def set_banned(self, user_id: int, banned: bool) -> bool:
        # Бан из группы может прийти раньше, чем человек писал боту:
        # создаём запись, иначе запрет потеряется.
        user = self._users.setdefault(
            user_id,
            {
                "username": None,
                "first_name": None,
                "banned": False,
                "seen": 0,
                "bonus_requests": 0,
                "lang": None,
            },
        )
        user.setdefault("lang", None)
        user["banned"] = banned
        return True

    def _used_today(self, user_id: int) -> int:
        day, count = self._usage.get(user_id, (date.today(), 0))
        return count if day == date.today() else 0

    async def remaining(self, user_id: int, daily_limit: int) -> int:
        if daily_limit <= 0:
            return 10**9
        return max(0, daily_limit - self._used_today(user_id)) + await self.bonus_requests(user_id)

    async def consume(self, user_id: int, daily_limit: int = 0) -> int:
        count = self._used_today(user_id) + 1
        self._usage[user_id] = (date.today(), count)
        self._total_requests[user_id] += 1
        # Дневной лимит израсходован — списываем купленный/выданный бонус.
        if daily_limit > 0 and count > daily_limit:
            user = self._users.get(user_id)
            if user is not None:
                user["bonus_requests"] = max(0, user.get("bonus_requests", 0) - 1)
        return count

    async def bonus_requests(self, user_id: int) -> int:
        return int(self._users.get(user_id, {}).get("bonus_requests", 0))

    async def add_bonus(self, user_id: int, count: int) -> int:
        user = self._users.setdefault(
            user_id,
            {"username": None, "first_name": None, "banned": False, "seen": 0, "bonus_requests": 0},
        )
        user["bonus_requests"] = max(0, int(user.get("bonus_requests", 0)) + count)
        return int(user["bonus_requests"])

    async def record_payment(
        self,
        user_id: int,
        requests: int,
        stars: int,
        charge_id: str,
        kind: str = "requests",
        model: str | None = None,
    ) -> bool:
        if charge_id in self._payments:
            return False
        self._payment_seq += 1
        self._payments[charge_id] = {
            "id": self._payment_seq,
            "user_id": user_id,
            "requests": requests,
            "stars": stars,
            "charge_id": charge_id,
            "kind": kind,
            "model": model,
            "created_at": datetime.now(UTC),
            "refunded_at": None,
        }
        if kind == "requests":
            await self.add_bonus(user_id, requests)
        return True

    async def get_payment(self, payment_id: int) -> dict | None:
        for payment in self._payments.values():
            if payment["id"] == payment_id:
                return dict(payment)
        return None

    async def mark_payment_refunded(self, payment_id: int) -> dict | None:
        for payment in self._payments.values():
            if payment["id"] == payment_id:
                if payment.get("refunded_at") is not None:
                    return None
                payment["refunded_at"] = datetime.now(UTC)
                return dict(payment)
        return None

    # ------------------------------------------------------------------ подписка
    async def get_subscription(self, user_id: int) -> datetime | None:
        value = self._users.get(user_id, {}).get("subscription_until")
        if isinstance(value, datetime) and value > datetime.now(UTC):
            return value
        return None

    async def activate_subscription(self, user_id: int, days: int) -> datetime:
        user = self._users.setdefault(
            user_id,
            {"username": None, "first_name": None, "banned": False, "seen": 0, "bonus_requests": 0},
        )
        now = datetime.now(UTC)
        current = user.get("subscription_until")
        base = current if isinstance(current, datetime) and current > now else now
        until = base + timedelta(days=max(1, int(days)))
        user["subscription_until"] = until
        return until

    async def cancel_subscription(self, user_id: int) -> None:
        user = self._users.get(user_id)
        if user is not None:
            user["subscription_until"] = None

    async def trim_subscription(self, user_id: int, days: int) -> datetime | None:
        """Возврат подписки: убирает купленные дни, не трогая остальные."""
        user = self._users.get(user_id)
        if user is None:
            return None
        current = user.get("subscription_until")
        if not isinstance(current, datetime):
            return None
        until = current - timedelta(days=max(0, int(days)))
        if until <= datetime.now(UTC):
            user["subscription_until"] = None
            return None
        user["subscription_until"] = until
        return until

    async def payments_stats(self) -> dict[str, int]:
        rows = list(self._payments.values())
        paid = [r for r in rows if r.get("refunded_at") is None]
        bought = [r for r in paid if r.get("kind", "requests") == "requests"]
        return {
            "count": len(rows),
            "stars": sum(int(r["stars"]) for r in paid),
            "requests": sum(int(r["requests"]) for r in bought),
            "refunded": len(rows) - len(paid),
            "subs": sum(1 for r in paid if r.get("kind") == "sub"),
            "models": sum(1 for r in paid if r.get("kind") == "model"),
        }

    async def recent_payments(self, limit: int) -> list[dict]:
        rows = sorted(self._payments.values(), key=lambda r: r["id"], reverse=True)
        return [
            {
                **row,
                "username": self._users.get(row["user_id"], {}).get("username"),
            }
            for row in rows[:limit]
        ]

    async def history(self, user_id: int, limit: int) -> list[dict[str, str]]:
        return list(self._history[user_id])[-limit:]

    async def add_exchange(self, user_id: int, question: str, answer: str, keep: int) -> None:
        box = self._history[user_id]
        box.append({"role": "user", "content": question})
        box.append({"role": "assistant", "content": answer})
        while len(box) > keep:
            box.popleft()

    async def reset(self, user_id: int) -> None:
        self._history.pop(user_id, None)

    async def stats(self) -> dict[str, int]:
        today = date.today()
        requests_today = sum(n for d, n in self._usage.values() if d == today)
        return {
            "users": len(self._users),
            "banned": sum(1 for u in self._users.values() if u.get("banned")),
            "active_today": sum(1 for d, _ in self._usage.values() if d == today),
            "requests_today": requests_today,
            "messages_total": sum(self._total_requests.values()) * 2,
        }

    async def list_users(self, offset: int, limit: int) -> list[dict]:
        users = sorted(self._users.items(), key=lambda kv: kv[1].get("seen", 0), reverse=True)
        return [
            {
                "user_id": uid,
                "username": info.get("username"),
                "first_name": info.get("first_name"),
                "banned": bool(info.get("banned")),
                "used_today": self._used_today(uid),
            }
            for uid, info in users[offset : offset + limit]
        ]

    async def user_card(self, user_id: int) -> dict | None:
        info = self._users.get(user_id)
        if not info:
            return None
        return {
            "user_id": user_id,
            "username": info.get("username"),
            "first_name": info.get("first_name"),
            "banned": bool(info.get("banned")),
            "used_today": self._used_today(user_id),
            "bonus_requests": self._users.get(user_id, {}).get("bonus_requests", 0),
            "subscription_until": self._users.get(user_id, {}).get("subscription_until"),
            "total_requests": self._total_requests.get(user_id, 0),
            "history_len": len(self._history.get(user_id, [])),
        }

    async def top_users(self, limit: int) -> list[dict]:
        rows = sorted(self._total_requests.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [
            {
                "user_id": uid,
                "username": self._users.get(uid, {}).get("username"),
                "total": total,
            }
            for uid, total in rows
        ]

    async def user_ids(self, only_active: bool = False) -> list[int]:
        if only_active:
            return [uid for uid, info in self._users.items() if not info.get("banned")]
        return list(self._users)

    async def get_setting(self, key: str) -> str | None:
        return self._settings.get(key)

    async def set_setting(self, key: str, value: str) -> None:
        self._settings[key] = value

    async def delete_setting(self, key: str) -> None:
        self._settings.pop(key, None)

    async def all_settings(self) -> dict[str, str]:
        return dict(self._settings)

    async def add_exchange_record(
        self, user_id: int, question: str, answer: str, kind: str
    ) -> int:
        self._exchange_seq += 1
        self._exchanges[self._exchange_seq] = {
            "id": self._exchange_seq,
            "user_id": user_id,
            "question": question,
            "answer": answer,
            "kind": kind,
            "vote": None,
        }
        return self._exchange_seq

    async def get_exchange(self, exchange_id: int) -> dict | None:
        return self._exchanges.get(exchange_id)

    async def set_vote(self, exchange_id: int, vote: str) -> None:
        if exchange_id in self._exchanges:
            self._exchanges[exchange_id]["vote"] = vote

    async def feedback_stats(self) -> dict[str, int]:
        votes = [e["vote"] for e in self._exchanges.values()]
        up = sum(1 for v in votes if v == "up")
        down = sum(1 for v in votes if v == "down")
        return {"up": up, "down": down, "total": up + down}

    async def get_profile(self, user_id: int) -> dict | None:
        return self._profiles.get(user_id)

    async def set_profile(
        self, user_id: int, grade: str | None, subject: str | None, style: str | None
    ) -> None:
        self._profiles[user_id] = {
            "user_id": user_id,
            "grade": grade,
            "subject": subject,
            "style": style,
        }

    async def delete_profile(self, user_id: int) -> None:
        self._profiles.pop(user_id, None)

    # ------------------------------------------------------------------ роли
    async def get_role(self, user_id: int) -> str | None:
        return self._roles.get(user_id)

    async def set_role(self, user_id: int, role: str, granted_by: int = 0) -> None:
        self._roles[user_id] = role

    async def delete_role(self, user_id: int) -> None:
        self._roles.pop(user_id, None)

    async def list_roles(self) -> list[dict]:
        rows = [
            {
                "user_id": user_id,
                "role": role,
                "username": self._users.get(user_id, {}).get("username"),
                "first_name": self._users.get(user_id, {}).get("first_name"),
            }
            for user_id, role in self._roles.items()
        ]
        return sorted(rows, key=lambda r: (r["role"], r["user_id"]))

    async def role_ids(self) -> list[int]:
        return list(self._roles)

    # ------------------------------------------------------------------ тикеты
    async def create_ticket(self, user_id: int, topic: str, text: str) -> int:
        self._ticket_seq += 1
        now = datetime.now(UTC)
        self._tickets[self._ticket_seq] = {
            "id": self._ticket_seq,
            "user_id": user_id,
            "topic": topic,
            "status": "open",
            "created_at": now,
            "updated_at": now,
            "closed_at": None,
            "closed_by": None,
        }
        self._ticket_msgs[self._ticket_seq] = [
            {
                "id": 1,
                "ticket_id": self._ticket_seq,
                "author_id": user_id,
                "from_staff": False,
                "text": text,
                "created_at": now,
            }
        ]
        return self._ticket_seq

    async def append_ticket_message(
        self, ticket_id: int, author_id: int, text: str, from_staff: bool
    ) -> int:
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            return 0
        box = self._ticket_msgs.setdefault(ticket_id, [])
        message_id = (box[-1]["id"] if box else 0) + 1
        now = datetime.now(UTC)
        box.append(
            {
                "id": message_id,
                "ticket_id": ticket_id,
                "author_id": author_id,
                "from_staff": from_staff,
                "text": text,
                "created_at": now,
            }
        )
        ticket["updated_at"] = now
        return message_id

    async def get_ticket(self, ticket_id: int) -> dict | None:
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            return None
        info = self._users.get(ticket["user_id"], {})
        return {
            **ticket,
            "username": info.get("username"),
            "first_name": info.get("first_name"),
        }

    async def ticket_messages(self, ticket_id: int, limit: int = 30) -> list[dict]:
        return [dict(m) for m in self._ticket_msgs.get(ticket_id, [])[-limit:]]

    async def open_tickets(self, limit: int, offset: int = 0) -> list[dict]:
        rows = [t for t in self._tickets.values() if t["status"] == "open"]
        rows.sort(key=lambda t: t["updated_at"])
        return [
            {
                **t,
                "username": self._users.get(t["user_id"], {}).get("username"),
                "first_name": self._users.get(t["user_id"], {}).get("first_name"),
            }
            for t in rows[offset : offset + limit]
        ]

    async def user_open_ticket(self, user_id: int) -> dict | None:
        for ticket in self._tickets.values():
            if ticket["user_id"] == user_id and ticket["status"] == "open":
                return dict(ticket)
        return None

    async def user_tickets(self, user_id: int, limit: int = 10) -> list[dict]:
        rows = [t for t in self._tickets.values() if t["user_id"] == user_id]
        rows.sort(key=lambda t: t["id"], reverse=True)
        return [dict(t) for t in rows[:limit]]

    async def close_ticket(self, ticket_id: int, closed_by: int) -> bool:
        ticket = self._tickets.get(ticket_id)
        if ticket is None or ticket["status"] != "open":
            return False
        ticket["status"] = "closed"
        ticket["closed_at"] = datetime.now(UTC)
        ticket["closed_by"] = closed_by
        return True

    async def tickets_stats(self) -> dict[str, int]:
        rows = list(self._tickets.values())
        opened = sum(1 for t in rows if t["status"] == "open")
        return {"open": opened, "closed": len(rows) - opened, "total": len(rows)}


# --------------------------------------------------------------------------- postgres
def normalize_db_url(url: str) -> tuple[str, bool]:
    """asyncpg не понимает ?sslmode=..., поэтому вытаскиваем SSL в отдельный флаг."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]

    parts = urlsplit(url)
    params = dict(parse_qsl(parts.query))
    sslmode = params.pop("sslmode", "").lower()
    for noisy in ("channel_binding", "application_name", "options"):
        params.pop(noisy, None)

    dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))
    use_ssl = sslmode in {"require", "prefer", "verify-ca", "verify-full", "true", "1"}
    if not sslmode and "neon.tech" in parts.netloc:
        use_ssl = True
    return dsn, use_ssl


class PostgresStore:
    def __init__(self, database_url: str) -> None:
        self._dsn, self._ssl = normalize_db_url(database_url)
        self._pool = None

    async def start(self) -> None:
        import asyncpg

        kwargs: dict = {
            "min_size": 1,
            "max_size": 5,
            "command_timeout": 30,
            "max_inactive_connection_lifetime": 60,
        }
        if self._ssl:
            kwargs["ssl"] = True
        # Пулер Neon/PgBouncer не умеет prepared statements.
        if "pooler" in self._dsn:
            kwargs["statement_cache_size"] = 0

        self._pool = await asyncpg.create_pool(self._dsn, **kwargs)
        async with self._pool.acquire() as conn:
            await conn.execute(SCHEMA)
        log.info("Postgres подключён, схема проверена")

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def ping(self) -> bool:
        if self._pool is None:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception:  # noqa: BLE001 - health-check не должен падать
            log.exception("Postgres ping failed")
            return False

    async def ensure_user(self, user_id: int, username: str | None, first_name: str | None) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO users (user_id, username, first_name)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
               SET username = EXCLUDED.username,
                   first_name = EXCLUDED.first_name,
                   last_seen = now()
            """,
            user_id,
            username,
            first_name,
        )

    async def get_lang(self, user_id: int) -> str | None:
        assert self._pool is not None
        value = await self._pool.fetchval("SELECT lang FROM users WHERE user_id = $1", user_id)
        return str(value) if value else None

    async def set_lang(self, user_id: int, lang: str) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO users (user_id, lang) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET lang = EXCLUDED.lang
            """,
            user_id,
            lang,
        )

    async def is_banned(self, user_id: int) -> bool:
        assert self._pool is not None
        return bool(
            await self._pool.fetchval("SELECT banned FROM users WHERE user_id = $1", user_id)
        )

    async def get_model(self, user_id: int) -> str | None:
        assert self._pool is not None
        value = await self._pool.fetchval(
            "SELECT model FROM users WHERE user_id = $1", user_id
        )
        return str(value) if value else None

    async def set_model(self, user_id: int, model: str | None) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO users (user_id, model) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET model = EXCLUDED.model
            """,
            user_id,
            model or None,
        )

    async def grant_model(self, user_id: int, model: str, granted_by: int = 0) -> None:
        assert self._pool is not None
        if not model:
            return
        await self._pool.execute(
            """
            INSERT INTO model_access (user_id, model, granted_by) VALUES ($1, $2, $3)
            ON CONFLICT (user_id, model) DO UPDATE SET granted_by = EXCLUDED.granted_by
            """,
            user_id,
            model,
            granted_by or None,
        )

    async def revoke_model(self, user_id: int, model: str) -> None:
        assert self._pool is not None
        await self._pool.execute(
            "DELETE FROM model_access WHERE user_id = $1 AND model = $2", user_id, model
        )

    async def list_model_access(self, user_id: int) -> list[str]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            "SELECT model FROM model_access WHERE user_id = $1 ORDER BY model", user_id
        )
        return [str(row["model"]) for row in rows]

    async def has_model_access(self, user_id: int, model: str) -> bool:
        assert self._pool is not None
        return bool(
            await self._pool.fetchval(
                "SELECT 1 FROM model_access WHERE user_id = $1 AND model = $2",
                user_id,
                model,
            )
        )

    async def set_banned(self, user_id: int, banned: bool) -> bool:
        assert self._pool is not None
        row = await self._pool.fetchval(
            """
            INSERT INTO users (user_id, banned) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET banned = EXCLUDED.banned
            RETURNING user_id
            """,
            user_id,
            banned,
        )
        return row is not None

    async def remaining(self, user_id: int, daily_limit: int) -> int:
        assert self._pool is not None
        if daily_limit <= 0:
            return 10**9
        row = await self._pool.fetchrow(
            """
            SELECT coalesce((SELECT count FROM usage WHERE user_id = $1 AND day = CURRENT_DATE), 0) AS used,
                   coalesce((SELECT bonus_requests FROM users WHERE user_id = $1), 0) AS bonus
            """,
            user_id,
        )
        used = int(row["used"] or 0)
        bonus = int(row["bonus"] or 0)
        return max(0, daily_limit - used) + bonus

    async def consume(self, user_id: int, daily_limit: int = 0) -> int:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                count = int(
                    await conn.fetchval(
                        """
                        INSERT INTO usage (user_id, day, count) VALUES ($1, CURRENT_DATE, 1)
                        ON CONFLICT (user_id, day) DO UPDATE SET count = usage.count + 1
                        RETURNING count
                        """,
                        user_id,
                    )
                )
                # Дневной лимит израсходован — списываем купленный/выданный бонус.
                if daily_limit > 0 and count > daily_limit:
                    await conn.execute(
                        "UPDATE users SET bonus_requests = GREATEST(0, bonus_requests - 1) WHERE user_id = $1",
                        user_id,
                    )
                return count

    async def bonus_requests(self, user_id: int) -> int:
        assert self._pool is not None
        value = await self._pool.fetchval(
            "SELECT bonus_requests FROM users WHERE user_id = $1", user_id
        )
        return int(value or 0)

    async def add_bonus(self, user_id: int, count: int) -> int:
        assert self._pool is not None
        value = await self._pool.fetchval(
            """
            UPDATE users SET bonus_requests = GREATEST(0, bonus_requests + $2)
            WHERE user_id = $1
            RETURNING bonus_requests
            """,
            user_id,
            count,
        )
        return int(value or 0)

    async def record_payment(
        self,
        user_id: int,
        requests: int,
        stars: int,
        charge_id: str,
        kind: str = "requests",
        model: str | None = None,
    ) -> bool:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                payment_id = await conn.fetchval(
                    """
                    INSERT INTO payments (user_id, requests, stars, charge_id, kind, model)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    ON CONFLICT (charge_id) DO NOTHING
                    RETURNING id
                    """,
                    user_id,
                    requests,
                    stars,
                    charge_id,
                    kind,
                    model,
                )
                if payment_id is None:
                    # Telegram может повторить апдейт — второй раз не начисляем.
                    return False
                if kind == "requests" and requests:
                    await conn.execute(
                        "UPDATE users SET bonus_requests = bonus_requests + $2 WHERE user_id = $1",
                        user_id,
                        requests,
                    )
                return True

    # ------------------------------------------------------------------ подписка
    async def get_subscription(self, user_id: int) -> datetime | None:
        assert self._pool is not None
        return await self._pool.fetchval(
            "SELECT subscription_until FROM users WHERE user_id = $1 AND subscription_until > now()",
            user_id,
        )

    async def activate_subscription(self, user_id: int, days: int) -> datetime:
        assert self._pool is not None
        value = await self._pool.fetchval(
            """
            INSERT INTO users (user_id, subscription_until)
            VALUES ($1, now() + make_interval(days => $2))
            ON CONFLICT (user_id) DO UPDATE SET subscription_until =
                GREATEST(coalesce(users.subscription_until, now()), now())
                + make_interval(days => $2)
            RETURNING subscription_until
            """,
            user_id,
            max(1, int(days)),
        )
        return value

    async def cancel_subscription(self, user_id: int) -> None:
        assert self._pool is not None
        await self._pool.execute(
            "UPDATE users SET subscription_until = NULL WHERE user_id = $1", user_id
        )

    async def trim_subscription(self, user_id: int, days: int) -> datetime | None:
        assert self._pool is not None
        return await self._pool.fetchval(
            """
            UPDATE users SET subscription_until =
                CASE
                    WHEN subscription_until - make_interval(days => $2) > now()
                    THEN subscription_until - make_interval(days => $2)
                    ELSE NULL
                END
            WHERE user_id = $1
            RETURNING subscription_until
            """,
            user_id,
            max(0, int(days)),
        )

    async def payments_stats(self) -> dict[str, int]:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            SELECT count(*) AS count,
                   coalesce(sum(stars) FILTER (WHERE refunded_at IS NULL), 0) AS stars,
                   coalesce(sum(requests) FILTER (WHERE refunded_at IS NULL AND kind = 'requests'), 0) AS requests,
                   count(*) FILTER (WHERE refunded_at IS NOT NULL) AS refunded,
                   count(*) FILTER (WHERE refunded_at IS NULL AND kind = 'sub') AS subs,
                   count(*) FILTER (WHERE refunded_at IS NULL AND kind = 'model') AS models
            FROM payments
            """
        )
        return {
            key: int(row[key] or 0)
            for key in ("count", "stars", "requests", "refunded", "subs", "models")
        }

    async def get_payment(self, payment_id: int) -> dict | None:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            SELECT id, user_id, requests, stars, charge_id, kind, model, created_at, refunded_at
            FROM payments WHERE id = $1
            """,
            payment_id,
        )
        return dict(row) if row else None

    async def mark_payment_refunded(self, payment_id: int) -> dict | None:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            UPDATE payments SET refunded_at = now()
            WHERE id = $1 AND refunded_at IS NULL
            RETURNING id, user_id, requests, stars, charge_id, kind, model, created_at, refunded_at
            """,
            payment_id,
        )
        return dict(row) if row else None

    async def recent_payments(self, limit: int) -> list[dict]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT p.id, p.user_id, p.requests, p.stars, p.charge_id, p.kind, p.model, p.created_at,
                   p.refunded_at, u.username
            FROM payments p
            LEFT JOIN users u ON u.user_id = p.user_id
            ORDER BY p.id DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(row) for row in rows]

    async def history(self, user_id: int, limit: int) -> list[dict[str, str]]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            "SELECT role, content FROM messages WHERE user_id = $1 ORDER BY id DESC LIMIT $2",
            user_id,
            limit,
        )
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def add_exchange(self, user_id: int, question: str, answer: str, keep: int) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    "INSERT INTO messages (user_id, role, content) VALUES ($1, $2, $3)",
                    [(user_id, "user", question), (user_id, "assistant", answer)],
                )
                await conn.execute(
                    """
                    DELETE FROM messages
                    WHERE user_id = $1
                      AND id NOT IN (
                          SELECT id FROM messages WHERE user_id = $1 ORDER BY id DESC LIMIT $2
                      )
                    """,
                    user_id,
                    keep,
                )

    async def reset(self, user_id: int) -> None:
        assert self._pool is not None
        await self._pool.execute("DELETE FROM messages WHERE user_id = $1", user_id)

    async def stats(self) -> dict[str, int]:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            SELECT (SELECT count(*) FROM users) AS users,
                   (SELECT count(*) FROM users WHERE banned) AS banned,
                   (SELECT count(*) FROM usage WHERE day = CURRENT_DATE) AS active_today,
                   (SELECT coalesce(sum(count), 0) FROM usage WHERE day = CURRENT_DATE) AS requests_today,
                   (SELECT count(*) FROM messages) AS messages_total
            """
        )
        return {k: int(row[k] or 0) for k in row.keys()}

    async def list_users(self, offset: int, limit: int) -> list[dict]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT u.user_id, u.username, u.first_name, u.banned,
                   coalesce(x.count, 0) AS used_today
            FROM users u
            LEFT JOIN usage x ON x.user_id = u.user_id AND x.day = CURRENT_DATE
            ORDER BY u.last_seen DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        return [dict(r) for r in rows]

    async def user_card(self, user_id: int) -> dict | None:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            SELECT u.user_id, u.username, u.first_name, u.banned, u.bonus_requests,
                   u.subscription_until, u.model,
                   coalesce(x.count, 0) AS used_today,
                   (SELECT coalesce(sum(count), 0) FROM usage WHERE user_id = u.user_id) AS total_requests,
                   (SELECT count(*) FROM messages WHERE user_id = u.user_id) AS history_len
            FROM users u
            LEFT JOIN usage x ON x.user_id = u.user_id AND x.day = CURRENT_DATE
            WHERE u.user_id = $1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def top_users(self, limit: int) -> list[dict]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT u.user_id, u.username,
                   coalesce(sum(x.count), 0) AS total
            FROM users u
            LEFT JOIN usage x ON x.user_id = u.user_id
            GROUP BY u.user_id, u.username
            ORDER BY total DESC
            LIMIT $1
            """,
            limit,
        )
        return [dict(r) for r in rows]

    async def user_ids(self, only_active: bool = False) -> list[int]:
        assert self._pool is not None
        query = "SELECT user_id FROM users"
        if only_active:
            query += " WHERE NOT banned"
        return [r["user_id"] for r in await self._pool.fetch(query)]

    async def get_setting(self, key: str) -> str | None:
        assert self._pool is not None
        return await self._pool.fetchval("SELECT value FROM settings WHERE key = $1", key)

    async def set_setting(self, key: str, value: str) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO settings (key, value) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            """,
            key,
            value,
        )

    async def delete_setting(self, key: str) -> None:
        assert self._pool is not None
        await self._pool.execute("DELETE FROM settings WHERE key = $1", key)

    async def all_settings(self) -> dict[str, str]:
        assert self._pool is not None
        rows = await self._pool.fetch("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in rows}

    async def add_exchange_record(
        self, user_id: int, question: str, answer: str, kind: str
    ) -> int:
        assert self._pool is not None
        return int(
            await self._pool.fetchval(
                """
                INSERT INTO exchanges (user_id, question, answer, kind)
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                user_id,
                question,
                answer,
                kind,
            )
        )

    async def get_exchange(self, exchange_id: int) -> dict | None:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            "SELECT id, user_id, question, answer, kind, vote FROM exchanges WHERE id = $1",
            exchange_id,
        )
        return dict(row) if row else None

    async def set_vote(self, exchange_id: int, vote: str) -> None:
        assert self._pool is not None
        await self._pool.execute(
            "UPDATE exchanges SET vote = $2 WHERE id = $1", exchange_id, vote
        )

    async def feedback_stats(self) -> dict[str, int]:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            SELECT count(*) FILTER (WHERE vote = 'up')   AS up,
                   count(*) FILTER (WHERE vote = 'down') AS down,
                   count(*) FILTER (WHERE vote IS NOT NULL) AS total
            FROM exchanges
            """
        )
        return {k: int(row[k] or 0) for k in ("up", "down", "total")}

    async def get_profile(self, user_id: int) -> dict | None:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            "SELECT user_id, grade, subject, style FROM profiles WHERE user_id = $1", user_id
        )
        return dict(row) if row else None

    async def set_profile(
        self, user_id: int, grade: str | None, subject: str | None, style: str | None
    ) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO profiles (user_id, grade, subject, style)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) DO UPDATE
               SET grade = EXCLUDED.grade,
                   subject = EXCLUDED.subject,
                   style = EXCLUDED.style,
                   updated_at = now()
            """,
            user_id,
            grade,
            subject,
            style,
        )

    async def delete_profile(self, user_id: int) -> None:
        assert self._pool is not None
        await self._pool.execute("DELETE FROM profiles WHERE user_id = $1", user_id)

    # ------------------------------------------------------------------ роли
    async def get_role(self, user_id: int) -> str | None:
        assert self._pool is not None
        value = await self._pool.fetchval("SELECT role FROM roles WHERE user_id = $1", user_id)
        return str(value) if value else None

    async def set_role(self, user_id: int, role: str, granted_by: int = 0) -> None:
        assert self._pool is not None
        await self._pool.execute(
            """
            INSERT INTO roles (user_id, role, granted_by) VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO UPDATE
               SET role = EXCLUDED.role,
                   granted_by = EXCLUDED.granted_by,
                   updated_at = now()
            """,
            user_id,
            role,
            granted_by or None,
        )

    async def delete_role(self, user_id: int) -> None:
        assert self._pool is not None
        await self._pool.execute("DELETE FROM roles WHERE user_id = $1", user_id)

    async def list_roles(self) -> list[dict]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT r.user_id, r.role, u.username, u.first_name
            FROM roles r
            LEFT JOIN users u ON u.user_id = r.user_id
            ORDER BY CASE r.role
                         WHEN 'head_admin' THEN 0
                         WHEN 'admin' THEN 1
                         WHEN 'support' THEN 2
                         ELSE 3
                     END,
                     r.updated_at
            """
        )
        return [dict(r) for r in rows]

    async def role_ids(self) -> list[int]:
        assert self._pool is not None
        return [r["user_id"] for r in await self._pool.fetch("SELECT user_id FROM roles")]

    # ------------------------------------------------------------------ тикеты
    async def create_ticket(self, user_id: int, topic: str, text: str) -> int:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                ticket_id = int(
                    await conn.fetchval(
                        "INSERT INTO tickets (user_id, topic) VALUES ($1, $2) RETURNING id",
                        user_id,
                        topic,
                    )
                )
                await conn.execute(
                    """
                    INSERT INTO ticket_messages (ticket_id, author_id, from_staff, text)
                    VALUES ($1, $2, FALSE, $3)
                    """,
                    ticket_id,
                    user_id,
                    text,
                )
                return ticket_id

    async def append_ticket_message(
        self, ticket_id: int, author_id: int, text: str, from_staff: bool
    ) -> int:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                message_id = int(
                    await conn.fetchval(
                        """
                        INSERT INTO ticket_messages (ticket_id, author_id, from_staff, text)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id
                        """,
                        ticket_id,
                        author_id,
                        from_staff,
                        text,
                    )
                )
                await conn.execute(
                    "UPDATE tickets SET updated_at = now() WHERE id = $1", ticket_id
                )
                return message_id

    async def get_ticket(self, ticket_id: int) -> dict | None:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            SELECT t.id, t.user_id, t.topic, t.status, t.created_at, t.updated_at,
                   t.closed_at, t.closed_by, u.username, u.first_name
            FROM tickets t
            LEFT JOIN users u ON u.user_id = t.user_id
            WHERE t.id = $1
            """,
            ticket_id,
        )
        return dict(row) if row else None

    async def ticket_messages(self, ticket_id: int, limit: int = 30) -> list[dict]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT id, ticket_id, author_id, from_staff, text, created_at
            FROM ticket_messages
            WHERE ticket_id = $1
            ORDER BY id DESC
            LIMIT $2
            """,
            ticket_id,
            limit,
        )
        return [dict(r) for r in reversed(rows)]

    async def open_tickets(self, limit: int, offset: int = 0) -> list[dict]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT t.id, t.user_id, t.topic, t.status, t.created_at, t.updated_at,
                   t.closed_at, t.closed_by, u.username, u.first_name
            FROM tickets t
            LEFT JOIN users u ON u.user_id = t.user_id
            WHERE t.status = 'open'
            ORDER BY t.updated_at
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
        return [dict(r) for r in rows]

    async def user_open_ticket(self, user_id: int) -> dict | None:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            SELECT id, user_id, topic, status, created_at, updated_at, closed_at, closed_by
            FROM tickets
            WHERE user_id = $1 AND status = 'open'
            ORDER BY id DESC
            LIMIT 1
            """,
            user_id,
        )
        return dict(row) if row else None

    async def user_tickets(self, user_id: int, limit: int = 10) -> list[dict]:
        assert self._pool is not None
        rows = await self._pool.fetch(
            """
            SELECT id, user_id, topic, status, created_at, updated_at, closed_at, closed_by
            FROM tickets
            WHERE user_id = $1
            ORDER BY id DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
        return [dict(r) for r in rows]

    async def close_ticket(self, ticket_id: int, closed_by: int) -> bool:
        assert self._pool is not None
        row = await self._pool.fetchval(
            """
            UPDATE tickets
            SET status = 'closed', closed_at = now(), closed_by = $2, updated_at = now()
            WHERE id = $1 AND status = 'open'
            RETURNING id
            """,
            ticket_id,
            closed_by,
        )
        return row is not None

    async def tickets_stats(self) -> dict[str, int]:
        assert self._pool is not None
        row = await self._pool.fetchrow(
            """
            SELECT count(*) FILTER (WHERE status = 'open')   AS open,
                   count(*) FILTER (WHERE status = 'closed') AS closed,
                   count(*)                                 AS total
            FROM tickets
            """
        )
        return {k: int(row[k] or 0) for k in ("open", "closed", "total")}


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id    BIGINT PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    banned     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS banned BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS bonus_requests INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS lang TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_until TIMESTAMPTZ;
ALTER TABLE users ADD COLUMN IF NOT EXISTS model TEXT;

CREATE TABLE IF NOT EXISTS usage (
    user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    day     DATE NOT NULL DEFAULT CURRENT_DATE,
    count   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

CREATE TABLE IF NOT EXISTS messages (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    role       TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS messages_user_id_id_idx ON messages (user_id, id DESC);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exchanges (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    question   TEXT NOT NULL,
    answer     TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'answer',
    vote       TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS exchanges_vote_idx ON exchanges (vote) WHERE vote IS NOT NULL;

CREATE TABLE IF NOT EXISTS profiles (
    user_id    BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
    grade      TEXT,
    subject    TEXT,
    style      TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS payments (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    requests   INTEGER NOT NULL,
    stars      INTEGER NOT NULL,
    charge_id  TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS payments_user_id_id_idx ON payments (user_id, id DESC);
ALTER TABLE payments ADD COLUMN IF NOT EXISTS refunded_at TIMESTAMPTZ;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'requests';
ALTER TABLE payments ADD COLUMN IF NOT EXISTS model TEXT;

CREATE TABLE IF NOT EXISTS model_access (
    user_id    BIGINT NOT NULL,
    model      TEXT NOT NULL,
    granted_by BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, model)
);

CREATE TABLE IF NOT EXISTS roles (
    user_id    BIGINT PRIMARY KEY,
    role       TEXT NOT NULL,
    granted_by BIGINT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tickets (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL,
    topic      TEXT NOT NULL DEFAULT 'other',
    status     TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at  TIMESTAMPTZ,
    closed_by  BIGINT
);

CREATE INDEX IF NOT EXISTS tickets_user_status_idx ON tickets (user_id, status);
CREATE INDEX IF NOT EXISTS tickets_status_updated_idx ON tickets (status, updated_at);

CREATE TABLE IF NOT EXISTS ticket_messages (
    id         BIGSERIAL PRIMARY KEY,
    ticket_id  BIGINT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author_id  BIGINT NOT NULL,
    from_staff BOOLEAN NOT NULL DEFAULT FALSE,
    text       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ticket_messages_ticket_idx ON ticket_messages (ticket_id, id);
"""


def create_store(settings: Settings) -> Store:
    if settings.database_url:
        return PostgresStore(settings.database_url)
    return MemoryStore()