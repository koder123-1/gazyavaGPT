"""Клиент ИИ: OpenRouter / Gemini / OpenAI-совместимые API, включая картинки."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import replace
from typing import Any

import aiohttp

from aipool import ModelPool
from config import (
    COARENA_MODELS,
    DEFAULT_BASE_URLS,
    DEFAULT_MODELS,
    DEFAULT_VISION_MODELS,
    Settings,
    _provider_key,
)
from guards import build_system_prompt, sanitize_answer

log = logging.getLogger("ai")

# Если выбранная vision-модель недоступна (429/403/5xx), пробуем следующую.
# Список проверен вручную: все модели читают картинку и решают пример с фото.
# Это резерв именно для OpenRouter; у Coarena свои модели из /v1/models.
VISION_FALLBACKS = [
    "openrouter/free",
    "inclusionai/ling-3.2-flash:free",
    "particle-ai/particle-1:free",
    "dots-studio/dots-3-note-preview:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]


class AIError(Exception):
    """Ошибка с текстом, который можно показать пользователю."""

    def __init__(self, message: str, *, retryable: bool = False, fatal: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.fatal = fatal


class AIClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session: aiohttp.ClientSession | None = None
        # Ограничиваем параллельные запросы: free-тарифы ИИ не любят шквал запросов.
        self._semaphore = asyncio.Semaphore(4)

        models = list(settings.ai_models)
        # Шлюзы вроде Coarena и ReformBoss сами отдают список моделей:
        # AI_MODELS=auto подставляется по умолчанию.
        if settings.ai_provider in {"coarena", "reformboss"} and not models:
            models = ["auto"]
        self._auto = any(m.lower() == "auto" for m in models)
        seed = (
            [m.strip() for m in COARENA_MODELS.split(",") if m.strip()]
            if settings.ai_provider == "coarena"
            else []
        )
        base = settings.ai_base_url.rstrip("/")
        self._pool = ModelPool(
            seed + [m for m in models if m.lower() != "auto"],
            discover_url=base + "/models" if self._auto else "",
            api_key=settings.ai_api_key,
            rotate=settings.ai_model_rotate,
        )
        # Для фото можно задать отдельный список (AI_VISION_MODELS): у некоторых
        # шлюзов в каталоге нет пометки vision, и общий пул туда не годится.
        vision_models = [m for m in settings.ai_vision_models if m]
        self._vision_pool = (
            ModelPool(vision_models, rotate=settings.ai_model_rotate)
            if vision_models
            else self._pool
        )

        # Резервный провайдер: если основной исчерпал дневной лимит или лёг,
        # отвечаем через него. Настраивается одной строкой AI_FALLBACK_PROVIDER.
        self._fallback: AIClient | None = None
        fallback = (settings.ai_fallback_provider or "").strip().lower()
        if fallback and fallback != settings.ai_provider and fallback in DEFAULT_MODELS:
            self._fallback = AIClient(
                replace(
                    settings,
                    ai_provider=fallback,
                    ai_api_key=_provider_key(fallback),
                    ai_base_url=DEFAULT_BASE_URLS[fallback],
                    ai_model=DEFAULT_MODELS[fallback],
                    ai_vision_model=DEFAULT_VISION_MODELS[fallback],
                    ai_models=(),
                    ai_fallback_provider="",
                )
            )

    @property
    def configured(self) -> bool:
        return bool(self._settings.ai_api_key)

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=65, connect=15)
            )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None
        if self._fallback is not None:
            await self._fallback.close()

    async def reply(
        self,
        history: list[dict[str, str]],
        text: str,
        *,
        model: str | None = None,
        system_prompt: str | None = None,
        image: bytes | None = None,
        image_mime: str = "image/jpeg",
        vision_model: str | None = None,
        subject_note: str | None = None,
        style_note: str | None = None,
        lang: str = "ru",
        task_lang: str | None = None,
    ) -> str:
        """history: [{"role": "user"|"assistant", "content": "..."}], text — новый вопрос.

        Если передан image, запрос уходит в vision-модель (с запасными вариантами).
        """
        if not self.configured:
            raise AIError("ИИ не настроен: администратору нужно добавить переменную AI_API_KEY.")

        settings = self._settings
        # Coarena/OpenAI-совместимые провайдеры используют общий список моделей.
        if self._pool.needs_discovery:
            await self.start()
            assert self._session is not None
            await self._pool.discover(self._session)

        pool = self._vision_pool if image is not None else self._pool
        if settings.ai_provider in {"coarena", "reformboss"}:
            primary = (
                (vision_model or settings.ai_vision_model)
                if image is not None
                else (model or settings.ai_model)
            )
            ordered = pool.order(vision=image is not None)
            # Выбранная пользователем модель идёт первой, даже если её нет в пуле.
            if model and image is None and primary:
                candidates = [primary] + [m for m in ordered if m != primary]
            else:
                candidates = ordered or ([primary] if primary else [])
        elif image is not None:
            candidates = [vision_model or settings.ai_vision_model]
            candidates += [m for m in VISION_FALLBACKS if m not in candidates]
        else:
            candidates = [model or settings.ai_model]

        # Защитные правила идут всегда, поверх того, что задал админ.
        prompt = build_system_prompt(
            settings.bot_name,
            system_prompt or settings.system_prompt,
            has_image=image is not None,
            subject_note=subject_note,
            style_note=style_note,
            lang=lang,
            task_lang=task_lang,
        )

        errors: list[AIError] = []
        # Повтор одиночной модели нужен, если она вернула только reasoning.
        rounds = 2 if len(candidates) == 1 else 1
        for round_no in range(rounds):
            for candidate in candidates:
                try:
                    answer = await self._call(
                        model=candidate,
                        history=history,
                        text=text,
                        prompt=prompt,
                        image=image,
                        image_mime=image_mime,
                    )
                    pool.mark_ok(candidate)
                    return sanitize_answer(answer)
                except AIError as exc:
                    errors.append(exc)
                    # Ключ/скоуп или единственная модель: сразу пробуем резерв.
                    if exc.fatal or (not exc.retryable and len(candidates) == 1):
                        return await self._fallback_reply(
                            exc,
                            history,
                            text,
                            model=model,
                            system_prompt=system_prompt,
                            image=image,
                            image_mime=image_mime,
                            vision_model=vision_model,
                            subject_note=subject_note,
                            style_note=style_note,
                            lang=lang,
                            task_lang=task_lang,
                        )
                    pool.mark_failed(candidate)
                    log.warning("Модель %s не ответила: %s -> пробуем ещё", candidate, exc)
            if round_no + 1 < rounds:
                log.info("Повторный запрос к ИИ после пустого ответа")

        last = errors[-1] if errors else AIError("Сервис ИИ недоступен. Попробуй позже.")
        if len(candidates) > 1:
            last = AIError(
                "Все модели сейчас заняты или временно недоступны. Попробуй через минуту.",
                retryable=True,
            )
        return await self._fallback_reply(
            last,
            history,
            text,
            model=model,
            system_prompt=system_prompt,
            image=image,
            image_mime=image_mime,
            vision_model=vision_model,
            subject_note=subject_note,
            style_note=style_note,
            lang=lang,
            task_lang=task_lang,
        )

    async def _fallback_reply(
        self,
        exc: AIError,
        history: list[dict[str, str]],
        text: str,
        **kwargs: Any,
    ) -> str:
        """Отвечает через резервного провайдера или поднимает исходную ошибку."""
        if self._fallback is None:
            raise exc
        log.warning("Основной провайдер не ответил (%s) -> резервный", exc)
        return await self._fallback.reply(history, text, **kwargs)

    # ------------------------------------------------------------------ один запрос
    async def _call(
        self,
        *,
        model: str,
        history: list[dict[str, str]],
        text: str,
        prompt: str,
        image: bytes | None,
        image_mime: str,
    ) -> str:
        settings = self._settings
        if settings.ai_provider == "gemini":
            url, headers, payload = self._gemini_request(
                history, text, model, prompt, image, image_mime
            )
        else:
            url, headers, payload = self._openai_request(
                history, text, model, prompt, image, image_mime
            )

        await self.start()
        assert self._session is not None

        async with self._semaphore:
            try:
                async with self._session.post(url, json=payload, headers=headers) as resp:
                    raw = await resp.text()
                    if resp.status != 200:
                        log.warning("AI HTTP %s (%s): %s", resp.status, model, raw[:400])
                        message, retryable = self._explain_status(
                            resp.status, raw, settings.ai_provider
                        )
                        # Неверный ключ/скоуп одинаков для всех моделей: перебор
                        # остальных ничего не даст, только сожжёт время.
                        fatal = resp.status in {401, 403}
                        raise AIError(message, retryable=retryable, fatal=fatal)
                    data = json.loads(raw)
            except TimeoutError as exc:
                log.warning("AI timeout (%s) — переключаюсь на другую модель", model)
                raise AIError(
                    "Модель думает слишком долго. Пробую другую.", retryable=True
                ) from exc
            except aiohttp.ClientError as exc:
                log.warning("AI network error: %r", exc)
                raise AIError("Сервис ИИ сейчас недоступен. Попробуй через минуту.", retryable=True) from exc
            except json.JSONDecodeError as exc:
                log.warning("AI вернул не JSON: %s", raw[:300])
                raise AIError("Сервис ИИ ответил невнятно. Попробуй ещё раз.", retryable=True) from exc

        return self._extract_text(data)

    # ------------------------------------------------------------------ запросы
    def _gemini_request(
        self,
        history: list[dict[str, str]],
        text: str,
        model: str,
        prompt: str,
        image: bytes | None,
        image_mime: str,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        s = self._settings
        base = s.ai_base_url or "https://generativelanguage.googleapis.com"
        url = f"{base}/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": s.ai_api_key, "Content-Type": "application/json"}

        contents: list[dict[str, Any]] = [
            {
                "role": "user" if m["role"] == "user" else "model",
                "parts": [{"text": m["content"]}],
            }
            for m in history
        ]

        parts: list[dict[str, Any]] = [{"text": text}]
        if image is not None:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": image_mime,
                        "data": base64.b64encode(image).decode("ascii"),
                    }
                }
            )
        contents.append({"role": "user", "parts": parts})

        payload = {
            "system_instruction": {"parts": [{"text": prompt}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4000},
        }
        return url, headers, payload

    def _openai_request(
        self,
        history: list[dict[str, str]],
        text: str,
        model: str,
        prompt: str,
        image: bytes | None,
        image_mime: str,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        s = self._settings
        if not model:
            raise AIError("Не задан AI_MODEL — укажите модель в /admin → Настройки.")

        base = s.ai_base_url or "https://api.openai.com/v1"
        url = f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {s.ai_api_key}", "Content-Type": "application/json"}

        messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}]
        messages += [
            {"role": "assistant" if m["role"] == "assistant" else "user", "content": m["content"]}
            for m in history
        ]

        if image is not None:
            data_url = f"data:{image_mime};base64,{base64.b64encode(image).decode('ascii')}"
            content: Any = [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]
        else:
            content = text
        messages.append({"role": "user", "content": content})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.6 if image is not None else 0.7,
            "max_tokens": 4000,
        }
        if s.ai_provider == "openrouter":
            # Не просим и не показываем reasoning: ответ должен быть готовым текстом.
            payload["reasoning"] = {"exclude": True}
        return url, headers, payload

    # ------------------------------------------------------------------ разбор
    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        if "candidates" in data:  # Gemini
            candidates = data.get("candidates") or []
            if not candidates:
                blocked = (data.get("promptFeedback") or {}).get("blockReason")
                hint = f" (причина: {blocked})" if blocked else ""
                raise AIError(f"Модель отказалась отвечать{hint}. Попробуй переформулировать.")
            parts = (candidates[0].get("content") or {}).get("parts") or []
            answer = "".join(p.get("text", "") for p in parts).strip()
        else:  # OpenAI-совместимые
            choices = data.get("choices") or []
            if not choices:
                raise AIError("Модель вернула пустой ответ. Попробуй ещё раз.", retryable=True)
            message = choices[0].get("message") or {}
            answer = (message.get("content") or "").strip()
            if not answer:
                # Ход рассуждений показывать нельзя вообще: это не ответ.
                # Если модель вернула только reasoning — пробуем ещё раз.
                raise AIError(
                    "Модель не дала готовый ответ. Попробуй ещё раз через минуту.",
                    retryable=True,
                )

        if not answer:
            raise AIError("Модель вернула пустой ответ. Попробуй переформулировать.", retryable=True)
        return answer

    @staticmethod
    def _explain_status(
        status: int, raw: str = "", provider: str = ""
    ) -> tuple[str, bool]:
        """Возвращает (текст для пользователя, стоит ли пробовать другую модель)."""
        message = ""
        try:
            error = json.loads(raw).get("error")
            if isinstance(error, dict):
                message = str(error.get("message") or "")
            elif isinstance(error, str):
                message = error
        except (json.JSONDecodeError, AttributeError):
            message = raw
        lowered = message.lower()
        code = ""
        try:
            error = json.loads(raw).get("error")
            if isinstance(error, dict):
                code = str(error.get("code") or "").lower()
        except (json.JSONDecodeError, AttributeError):
            pass
        haystack = f"{lowered} {code}"

        if "location is not supported" in lowered:
            return (
                "Провайдер ИИ блокирует запросы из этой страны. "
                "Смените провайдера (AI_PROVIDER=openrouter) или запустите бота "
                "на сервере в другой стране — например, на Render.",
                False,
            )
        if "model_api_terms_required" in haystack:
            return (
                "Ключ Coarena без доступа к Model API: при создании ключа нужно "
                "принять условия Model API. Создайте ключ заново на "
                "https://coarena.ai/account/api",
                False,
            )
        if "insufficient_scope" in haystack:
            return (
                "У ключа нет права inference:write (запросы к моделям). "
                "Создайте ключ с этим правом.",
                False,
            )
        if "model_not_found" in haystack:
            # У пула моделей это повод взять другую модель.
            return "Эта модель недоступна: пробую другую.", bool(provider)
        if "no longer available" in lowered or "not found for api version" in lowered:
            return "Эта модель недоступна: обновите AI_MODEL или AI_PROVIDER.", False
        if "rate-limited upstream" in lowered or "rate limited" in lowered:
            return "Модель перегружена (бесплатный тариф). Пробую другую.", True
        if "insufficient_quota" in haystack or "limit_increase" in haystack:
            return (
                "Дневной бесплатный лимит провайдера закончился. "
                "Он обновится в полночь по UTC.",
                False,
            )
        if status == 429:
            return "Лимит ИИ исчерпан (слишком много запросов). Попробуй позже.", True
        if status in (401, 403):
            return "ИИ отклонил ключ: проверьте AI_API_KEY и AI_PROVIDER.", False
        if status == 404:
            return "Модель не найдена: проверьте AI_MODEL.", False
        if status == 413:
            return "Изображение слишком большое для модели. Пришли фото поменьше.", False
        if status >= 500:
            return "Сервис ИИ перегружен. Попробуй позже.", True
        return f"Сервис ИИ вернул ошибку ({status}). Попробуй позже.", False