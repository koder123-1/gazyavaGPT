"""«Режим отладки» — заскриптованный спектакль с «внутренними мыслями» бота.

Это НЕ настоящие рассуждения модели: бот не показывает системный промпт,
не обходит фильтры и ничего не взламывает. Включённый режим просто меняет
текст одного сообщения по шагам — «инициализация», «системный промпт»,
«роутер предметов», «генерация», «проверка на цензуру» — и заканчивает
«успехом». Нужен ради вау-эффекта, поэтому включается секретной командой
и хранится персонально для каждого пользователя.

Секрет задаётся через `DEBUG_COMMAND_SECRET` (по умолчанию `gazyava-debug`).
Задержку шагов можно ускорить через `DEBUG_DELAY` (секунды, по умолчанию 0.9).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
from dataclasses import dataclass, field
from html import escape

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from i18n import t

log = logging.getLogger("debugmode")

DEFAULT_SECRET = "gazyava-debug"
KEY = "debug_mode:{user_id}"


def _delay() -> float:
    raw = os.getenv("DEBUG_DELAY", "").strip()
    try:
        value = float(raw) if raw else 0.9
    except ValueError:
        value = 0.9
    # Ноль превратился бы в бесконечный цикл правок — держим нижнюю границу.
    return max(0.05, value)


def _key(user_id: int) -> str:
    return KEY.format(user_id=user_id)


async def enabled(store, user_id: int) -> bool:
    return (await store.get_setting(_key(user_id))) == "1"


async def set_enabled(store, user_id: int, value: bool) -> bool:
    if value:
        await store.set_setting(_key(user_id), "1")
    else:
        await store.delete_setting(_key(user_id))
    return value


def secret(configured: str) -> str:
    return (configured or DEFAULT_SECRET).strip()


def _short(text: str, limit: int = 110) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return escape(text)
    return escape(text[: limit - 1].rstrip()) + "…"


@dataclass
class DebugShow:
    """Одно сообщение, которое по шагам «думает» вслух."""

    message: Message
    lang: str
    system_prompt: str = ""
    subject: str = ""
    photo: bool = False

    done: list[str] = field(default_factory=list)
    queue: list[str] = field(default_factory=list)
    percent: int = 3
    finished: bool = False
    ok: bool = True

    _msg: Message | None = None
    _task: asyncio.Task | None = None
    _stopped: bool = False

    # ------------------------------------------------------------------ шаги
    def _steps(self) -> list[str]:
        lang = self.lang
        steps: list[str] = []
        if self.photo:
            steps += [
                t(lang, "dbg.step.decode"),
                t(lang, "dbg.step.ocr"),
                t(lang, "dbg.step.formulas"),
                t(lang, "dbg.step.condition"),
            ]
        else:
            steps += [
                t(lang, "dbg.step.init"),
                t(lang, "dbg.step.prompt", prompt=_short(self.system_prompt)),
                t(lang, "dbg.step.router", subject=_short(self.subject, 40)),
            ]
        return steps

    def _render(self) -> str:
        lines = [f"▸ {line}" for line in self.done]
        if self.finished:
            lines.append(f"▸ {t(self.lang, 'dbg.step.censor')}")
            lines.append(f"▸ {t(self.lang, 'dbg.step.filters')}")
            lines.append(
                t(self.lang, "dbg.step.success" if self.ok else "dbg.step.fail")
            )
        elif self.queue:
            lines.append(f"▸ {self.queue[0]}…")
        else:
            lines.append(t(self.lang, "dbg.step.gen", percent=self.percent))
        body = "\n".join(lines)
        return f"{t(self.lang, 'dbg.header')}\n<blockquote>{body}</blockquote>"

    # ------------------------------------------------------------------ жизнь
    async def start(self) -> None:
        self.queue = self._steps()
        try:
            self._msg = await self.message.answer(self._render(), parse_mode="HTML")
        except TelegramAPIError:
            log.warning("Не удалось показать режим отладки", exc_info=True)
            self._msg = None
            return
        self._task = asyncio.create_task(self._animate())

    def _advance(self) -> None:
        if self.queue:
            self.done.append(self.queue.pop(0))
        elif self.percent < 95:
            self.percent = min(95, self.percent + random.randint(4, 12))

    async def _refresh(self, text: str | None = None) -> None:
        if self._msg is None or self.finished:
            return
        with contextlib.suppress(TelegramAPIError):
            await self._msg.edit_text(text or self._render(), parse_mode="HTML")

    async def _animate(self) -> None:
        delay = _delay()
        last: str | None = None
        loop = asyncio.get_running_loop()
        # Страховка: даже если ответ завис, цикл не живёт дольше 10 минут.
        deadline = loop.time() + 600
        try:
            while not self._stopped:
                if loop.time() > deadline:
                    return
                await asyncio.sleep(delay)
                if self._stopped:
                    return
                if not self.queue and self.percent >= 95:
                    # Текст больше не меняется: ждём finish() молча.
                    return
                self._advance()
                text = self._render()
                if text == last:
                    # Повторная правка тем же текстом = «message is not modified».
                    continue
                last = text
                await self._refresh(text)
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            log.debug("Анимация режима отладки остановлена", exc_info=True)

    async def finish(self, ok: bool = True) -> None:
        """Останавливает анимацию и оставляет полный «лог» с успехом."""
        self._stopped = True
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        while self.queue:
            self.done.append(self.queue.pop(0))
        self.percent = 100
        self.ok = ok
        self.finished = True
        if self._msg is None:
            return
        with contextlib.suppress(TelegramAPIError):
            await self._msg.edit_text(self._render(), parse_mode="HTML")


async def begin(
    message: Message,
    *,
    store,
    user_id: int,
    lang: str,
    system_prompt: str = "",
    subject: str = "",
    photo: bool = False,
) -> DebugShow | None:
    """Включает спектакль, если пользователь его активировал."""
    if message.chat.type != "private":
        return None
    if store is None or not await enabled(store, user_id):
        return None
    show = DebugShow(
        message=message,
        lang=lang,
        system_prompt=system_prompt,
        subject=subject,
        photo=photo,
    )
    await show.start()
    return show
