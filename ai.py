"""Клиент ИИ: OpenRouter / Gemini / OpenAI-совместимые API, включая картинки."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import replace
from typing import Any

import aiohttp

import alerts
import providerhealth
from aipool import ModelPool
from config import (
    COARENA_MODELS,
    DEFAULT_BASE_URLS,
    DEFAULT_MODELS,
    DEFAULT_VISION_MODELS,
    GATEWAY_PROVIDERS,
    HTTP_USER_AGENT,
    Settings,
    _provider_base,
    _provider_key,
    _specific_provider_key,
    normalize_providers,
)
from guards import build_system_prompt, sanitize_answer, strip_meta_preamble

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

# Модель упёрлась в лимит токенов: просим продолжить ровно с обрыва, чтобы
# большие листинги кода не приходили половинчатыми.
CONTINUE_PROMPT = (
    "Продолжи предыдущий ответ ровно с того места, где он оборвался. "
    "Не повторяй уже написанное, не начинай заново, не пиши вступление и не "
    "извиняйся. Никаких служебных фраз вида «Continuing from the previous "
    "discussion» или «Продолжаю с того места» — сразу продолжай текст. "
    "Если оборвался блок кода — продолжай с той же строки и внутри "
    "того же блока ```…```. Если оборвался текст — продолжай с того же слова."
)


def _fallback_key(name: str, settings: Settings) -> str:
    """Ключ провайдера: свой, а общий AI_API_KEY — только когда он точно его.

    У каждого шлюза свой адрес, и ключ ReformBoss на api.crowllm.com — это
    гарантированный 401. Поэтому общий ключ берём лишь для провайдера из
    AI_PROVIDER (там он и задан) или если адреса совпадают.
    """
    specific = _specific_provider_key(name)
    if specific:
        return specific
    if name == settings.ai_provider:
        return _provider_key(name)
    common = (settings.ai_api_key or "").strip()
    if not common:
        return ""
    own_base = DEFAULT_BASE_URLS.get(name, "").rstrip("/")
    main_base = (settings.ai_base_url or "").rstrip("/")
    return common if own_base and own_base == main_base else ""


def _merge_continuation(base: str, part: str) -> str:
    """Склеивает продолжение с ответом, убирая повтор уже написанного хвоста."""
    if not base:
        return strip_meta_preamble(part)
    part = (part or "").strip("\n")
    if not part:
        return base
    # Модель часто начинает продолжение со служебной фразы «Continuing from
    # the previous discussion …» — это не текст ответа, а остаток контекста.
    part = strip_meta_preamble(part)
    if not part:
        return base
    for marker in ("Продолжение:", "Продолжение ответа:", "Continuation:"):
        if part.lower().startswith(marker.lower()):
            part = part[len(marker) :]
            break
    tail = base.rstrip()
    # Модель иногда начинает ответ заново вместо продолжения: тогда оставляем
    # более длинный вариант, а не дублируем текст.
    head = base.lstrip()[:200]
    if len(head) > 40 and part.lstrip().startswith(head):
        return part if len(part) > len(base) else base
    limit = min(600, len(tail), len(part))
    for size in range(limit, 2, -1):
        if tail.endswith(part[:size]):
            part = part[size:]
            break
    if not part:
        return base
    # Модель часто продолжает с середины слова или строки: не вставляем
    # лишний перевод строки, только пробел между словами.
    if tail and part[0].isalnum() and tail[-1].isalnum() and not base[-1].isspace():
        return base + " " + part
    if base[-1].isspace() or part[0] in "\n\t ":
        return base + part
    return base + part


class AIError(Exception):
    """Ошибка с текстом, который можно показать пользователю."""

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        fatal: bool = False,
        status: int = 0,
        raw: str = "",
        model_level: bool = False,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.fatal = fatal
        self.status = status
        # Сырой ответ провайдера: по нему видно «регион заблокирован» или
        # «ключ без скоупа», даже если пользователю показываем другой текст.
        self.raw = raw
        # Сбой относится к одной модели (пустой ответ, странный формат),
        # а не ко всему провайдеру: остальные модели пробуем дальше.
        self.model_level = model_level


class AIClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings
        self._session: aiohttp.ClientSession | None = None
        # Ограничиваем параллельные запросы: free-тарифы ИИ не любят шквал запросов.
        self._semaphore = asyncio.Semaphore(4)
        self._settings = settings
        self._pool: ModelPool
        self._vision_pool: ModelPool
        self._auto = False
        self._fallbacks: list[AIClient] = []
        self._build(settings)
        self._build_fallbacks(settings)

    # ------------------------------------------------------------- настройка
    def _build(self, settings: Settings) -> None:
        """Готовит пул моделей под выбранного провайдера."""
        self._settings = settings
        models = list(settings.ai_models)
        # Шлюзы сами отдают список моделей: «auto» подставляется по умолчанию.
        if not models and (
            settings.ai_provider in GATEWAY_PROVIDERS
            or (settings.ai_model or "").strip().lower() == "auto"
        ):
            models = ["auto"]
        self._auto = any(m.lower() == "auto" for m in models) or (
            settings.ai_model or ""
        ).strip().lower() == "auto"
        seed = (
            [m.strip() for m in COARENA_MODELS.split(",") if m.strip()]
            if settings.ai_provider == "coarena"
            else []
        )
        base = (settings.ai_base_url or "").rstrip("/")
        self._pool = ModelPool(
            seed + [m for m in models if m.lower() != "auto"],
            discover_url=base + "/models" if self._auto and base else "",
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

    def _build_fallbacks(self, settings: Settings) -> None:
        """Собирает цепочку резервных провайдеров из AI_FALLBACK_PROVIDER.

        Если включён AI_AUTO_FALLBACK (по умолчанию), в конец цепочки молча
        добавляются все остальные провайдеры, у которых есть свой ключ. Так
        новый ключ в переменных окружения начинает работать сам, без правки
        AI_FALLBACK_PROVIDER, а порядок из настройки остаётся приоритетным.
        """
        names = list(normalize_providers(settings.ai_fallback_provider))
        if settings.ai_auto_fallback:
            for name in DEFAULT_MODELS:
                if name not in names and _fallback_key(name, settings):
                    names.append(name)
        chain: list[AIClient] = []
        seen = {settings.ai_provider}
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            key = _fallback_key(name, settings)
            if not key:
                # Без ключа провайдер всё равно ответит 401 — не тратим запрос.
                log.info("Резервный провайдер %s пропущен: нет ключа", name)
                continue
            chain.append(
                AIClient(
                    replace(
                        settings,
                        ai_provider=name,
                        ai_api_key=key,
                        ai_base_url=(
                            _provider_base(name) or DEFAULT_BASE_URLS.get(name, "")
                        ),
                        ai_model=DEFAULT_MODELS[name],
                        ai_vision_model=DEFAULT_VISION_MODELS[name],
                        ai_models=(
                            self._base.ai_models
                            if name == self._base.ai_provider
                            else ()
                        ),
                        ai_vision_models=(
                            self._base.ai_vision_models
                            if name == self._base.ai_provider
                            else ()
                        ),
                        ai_fallback_provider="",
                        ai_auto_fallback=False,
                    )
                )
            )
        self._fallbacks = chain

    async def use_provider(self, provider: str, fallback: str = "") -> None:
        """Переключает провайдера на лету — из админки, без рестарта.

        Модели и ключ берутся для нового провайдера, старые резервные клиенты
        закрываются, чтобы не держать лишние соединения.
        """
        provider = (provider or "").strip().lower()
        if provider not in DEFAULT_MODELS:
            return
        fallback = ",".join(normalize_providers(fallback or ""))
        if (
            provider == self._settings.ai_provider
            and fallback == self._settings.ai_fallback_provider
        ):
            return
        old_fallbacks = self._fallbacks
        self._build(
            replace(
                self._base,
                ai_provider=provider,
                ai_api_key=_fallback_key(provider, self._base),
                ai_base_url=(
                    _provider_base(provider) or DEFAULT_BASE_URLS.get(provider, "")
                ),
                ai_model=DEFAULT_MODELS[provider],
                ai_vision_model=DEFAULT_VISION_MODELS[provider],
                ai_models=(
                    self._base.ai_models if provider == self._base.ai_provider else ()
                ),
                ai_vision_models=(
                    self._base.ai_vision_models
                    if provider == self._base.ai_provider
                    else ()
                ),
                ai_fallback_provider=fallback,
            )
        )
        self._build_fallbacks(self._settings)
        for client in old_fallbacks:
            await client.close()
        # Админ выбрал провайдера руками — пробуем его сразу, даже если он
        # остывал после сбоя: возможно, ключ уже починили.
        providerhealth.mark_ok(provider)
        for client in self._fallbacks:
            providerhealth.mark_ok(client._settings.ai_provider)
        log.info(
            "Провайдер ИИ переключён: %s (резерв: %s)",
            provider,
            fallback or "нет",
        )

    @property
    def configured(self) -> bool:
        return bool(self._settings.ai_api_key)

    @property
    def _gateway(self) -> bool:
        """Шлюз сам выдаёт каталог моделей — значит, можно ротировать их."""
        return self._settings.ai_provider in GATEWAY_PROVIDERS

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=65, connect=15),
                # Cloudflare у части шлюзов пропускает только браузерный UA.
                headers={"User-Agent": HTTP_USER_AGENT},
            )

    async def close(self) -> None:
        session = self._session
        self._session = None
        if session is not None and not getattr(session, "closed", False):
            closer = getattr(session, "close", None)
            if closer is not None:
                await closer()
        if self._fallbacks:
            for client in self._fallbacks:
                await client.close()

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
            exc = AIError(
                "ИИ не настроен: администратору нужно добавить ключ выбранного провайдера."
            )
            if self._fallbacks:
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
            await self._alert_down(exc)
            raise exc

        settings = self._settings
        # Провайдер остывает после сбоя, а живой резерв есть — не ждём таймаут,
        # сразу отвечаем через резерв. Пользователь разницы не заметит.
        if (
            self._fallbacks
            and not providerhealth.available(settings.ai_provider)
            and any(
                providerhealth.available(client._settings.ai_provider)
                for client in self._fallbacks
            )
        ):
            log.info(
                "Провайдер %s остывает (%.0f с) -> сразу резерв",
                settings.ai_provider,
                providerhealth.cooldown_left(settings.ai_provider),
            )
            return await self._fallback_reply(
                AIError(
                    f"Провайдер {settings.ai_provider} временно недоступен.",
                    retryable=True,
                ),
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
        # Шлюзы отдают список моделей через /models — подтягиваем его.
        if self._pool.needs_discovery:
            await self.start()
            assert self._session is not None
            await self._pool.discover(self._session)

        pool = self._vision_pool if image is not None else self._pool
        if self._gateway:
            wanted = (
                (vision_model or settings.ai_vision_model)
                if image is not None
                else (model or settings.ai_model)
            )
            primary = "" if (wanted or "").strip().lower() == "auto" else (wanted or "")
            ordered = pool.order(vision=image is not None)
            # Выбранная пользователем модель идёт первой, даже если её нет в пуле.
            if primary:
                candidates = [primary] + [m for m in ordered if m != primary]
            else:
                candidates = ordered
            if not candidates and primary:
                candidates = [primary]
            # Модели, упёршиеся в регион/тариф, не зовём снова — но если
            # все остыли, всё равно пробуем: пустой ответ хуже.
            candidates = providerhealth.filter_models(settings.ai_provider, candidates)
        elif image is not None:
            candidates = [vision_model or settings.ai_vision_model]
            # VISION_FALLBACKS — id моделей OpenRouter; другим провайдерам они
            # дают только 404 и лишние запросы.
            if settings.ai_provider == "openrouter":
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
                    started = time.monotonic()
                    answer, truncated = await self._call(
                        model=candidate,
                        history=history,
                        text=text,
                        prompt=prompt,
                        image=image,
                        image_mime=image_mime,
                        timeout=providerhealth.call_timeout(settings.ai_provider),
                    )
                    if truncated and image is None:
                        answer = await self._extend(
                            model=candidate,
                            history=history,
                            text=text,
                            prompt=prompt,
                            answer=answer,
                        )
                    # Модель могла выдать только служебный мусор («Continuing
                    # from the previous discussion …») — это не ответ. Тогда
                    # пробуем следующую модель, а не отправляем пустоту.
                    cleaned = sanitize_answer(answer)
                    if not cleaned.strip():
                        raise AIError(
                            "Модель вернула пустой ответ. Попробуй ещё раз.",
                            retryable=True,
                            model_level=True,
                        )
                    pool.mark_ok(candidate)
                    providerhealth.mark_ok(settings.ai_provider)
                    providerhealth.mark_model_ok(settings.ai_provider, candidate)
                    providerhealth.mark_latency(
                        settings.ai_provider, time.monotonic() - started
                    )
                    return cleaned
                except AIError as exc:
                    errors.append(exc)
                    # Классифицируем по сырому ответу: в тексте для пользователя
                    # нет слов «country or region» и «insufficient_scope».
                    raw_reason = exc.raw or str(exc)
                    # Пустой ответ — вина одной модели, а не провайдера.
                    provider_level = (
                        False
                        if exc.model_level
                        else providerhealth.is_provider_level(exc.status, raw_reason)
                    )
                    # Сбой провайдера целиком (ключ, регион, лимит, 5xx) — остужаем
                    # его, чтобы следующий вопрос не ждал тот же таймаут.
                    if provider_level:
                        providerhealth.mark_failed(
                            settings.ai_provider,
                            status=exc.status,
                            reason=raw_reason,
                        )
                    else:
                        # Проблема одной модели: остальные модели провайдера живы.
                        providerhealth.mark_model_failed(
                            settings.ai_provider,
                            candidate,
                            status=exc.status,
                            reason=raw_reason,
                        )
                    # Ключ/скоуп, сбой всего провайдера или единственная модель:
                    # сразу пробуем резерв, не тратя время на другие модели.
                    if (
                        exc.fatal
                        or provider_level
                        or (not exc.retryable and len(candidates) == 1)
                    ):
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
                # Не бомбим провайдера повтором сразу: у 429 просили подождать.
                await asyncio.sleep(1.5)
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

    async def _extend(
        self,
        *,
        model: str,
        history: list[dict[str, str]],
        text: str,
        prompt: str,
        answer: str,
    ) -> str:
        """Дописывает ответ, если модель оборвалась на лимите токенов.

        Так большие листинги кода собираются из нескольких кусков, а не
        приходят половиной файла.
        """
        rounds = max(0, int(self._settings.ai_continue_rounds))
        current = answer
        for _ in range(rounds):
            try:
                part, truncated = await self._call(
                    model=model,
                    history=history,
                    text=CONTINUE_PROMPT,
                    prompt=prompt,
                    image=None,
                    image_mime="image/jpeg",
                    assistant_prefix=current[-4000:],
                )
            except AIError as exc:
                # Уже есть нормальный ответ — не теряем его из-за продолжения.
                log.info("Продолжение не удалось (%s) — оставляю как есть", exc)
                break
            if not part.strip():
                break
            current = _merge_continuation(current, part)
            if not truncated:
                break
        return current

    async def _alert_down(self, detail: object) -> None:
        """Один алерт на падение провайдера: без текста вопроса и личных данных."""
        await alerts.ai_failed(
            f"Провайдер: {self._settings.ai_provider}\n"
            f"Модель: {self._settings.ai_model}\n"
            f"{type(detail).__name__}: {detail}"
        )

    async def _fallback_reply(
        self,
        exc: AIError,
        history: list[dict[str, str]],
        text: str,
        **kwargs: Any,
    ) -> str:
        """Отвечает через цепочку резервных провайдеров или поднимает ошибку."""
        if not self._fallbacks:
            await self._alert_down(exc)
            raise exc
        # Имена моделей у провайдеров разные: нельзя передавать резерву чужой
        # AI_MODEL/AI_VISION_MODEL, иначе гарантированный 404.
        kwargs.pop("model", None)
        kwargs.pop("vision_model", None)
        last: AIError = exc
        # Живые резервы первыми, быстрые — впереди медленных: пользователь
        # ждёт ответ, а не порядок из настройки.
        names = [client._settings.ai_provider for client in self._fallbacks]
        ordered = providerhealth.fastest(providerhealth.order(names))
        by_name = {client._settings.ai_provider: client for client in self._fallbacks}
        for name in ordered:
            client = by_name.get(name)
            if client is None or not client.configured:
                continue
            log.warning(
                "Провайдер %s не ответил (%s) -> резерв %s",
                self._settings.ai_provider,
                exc,
                name,
            )
            try:
                return await client.reply(history, text, **kwargs)
            except AIError as fallback_exc:
                last = fallback_exc
                continue
            except Exception as fallback_exc:  # noqa: BLE001
                log.warning("Резервный провайдер упал: %r", fallback_exc)
                last = AIError("Сервис ИИ сейчас недоступен. Попробуй через минуту.")
                continue
        await self._alert_down(exc)
        raise last

    # ------------------------------------------------------------------ один запрос
    @staticmethod
    def _token_limit_error(raw: str) -> bool:
        low = (raw or "").lower()
        return any(
            marker in low
            for marker in (
                "max_tokens",
                "max_output_tokens",
                "maxoutputtokens",
                "max token",
                "token limit",
                "too many tokens",
                "maximum context",
            )
        )

    @staticmethod
    def _is_truncated(data: dict[str, Any]) -> bool:
        """True, если модель оборвала ответ на лимите токенов."""
        reason = ""
        if "candidates" in data:
            candidates = data.get("candidates") or []
            if candidates:
                reason = str(candidates[0].get("finishReason") or "")
        else:
            choices = data.get("choices") or []
            if choices:
                reason = str(choices[0].get("finish_reason") or "")
        return reason.lower() in {"length", "max_tokens", "max_tokens_reached"}

    async def _call(
        self,
        *,
        model: str,
        history: list[dict[str, str]],
        text: str,
        prompt: str,
        image: bytes | None,
        image_mime: str,
        assistant_prefix: str | None = None,
        timeout: float | None = None,
    ) -> tuple[str, bool]:
        settings = self._settings
        await self.start()
        assert self._session is not None

        budget = max(500, int(settings.ai_max_tokens or 4000))
        # Провайдер может не принять большой лимит: тогда повторяем с
        # проверенными 4000 токенами, а не роняем ответ целиком.
        limits = [budget] + ([4000] if budget > 4000 else [])
        # Мёртвый провайдер должен отвалиться быстро: иначе пользователь ждёт
        # впустую, пока живой резерв простаивает.
        request_timeout = (
            aiohttp.ClientTimeout(total=timeout, connect=min(15.0, timeout))
            if timeout
            else None
        )

        data: dict[str, Any] | None = None
        async with self._semaphore:
            for attempt, limit in enumerate(limits):
                if settings.ai_provider == "gemini":
                    url, headers, payload = self._gemini_request(
                        history,
                        text,
                        model,
                        prompt,
                        image,
                        image_mime,
                        max_tokens=limit,
                        assistant_prefix=assistant_prefix,
                    )
                else:
                    url, headers, payload = self._openai_request(
                        history,
                        text,
                        model,
                        prompt,
                        image,
                        image_mime,
                        max_tokens=limit,
                        assistant_prefix=assistant_prefix,
                    )
                try:
                    async with self._session.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=request_timeout,
                    ) as resp:
                        raw = await resp.text()
                        if resp.status != 200:
                            log.warning(
                                "AI HTTP %s (%s): %s", resp.status, model, raw[:400]
                            )
                            if (
                                resp.status == 400
                                and attempt + 1 < len(limits)
                                and self._token_limit_error(raw)
                            ):
                                log.info(
                                    "Провайдер не принял max_tokens=%s — повторяю с 4000",
                                    limit,
                                )
                                continue
                            message, retryable = self._explain_status(
                                resp.status, raw, settings.ai_provider
                            )
                            # 401 — ключ неверный для всех моделей. 403 у шлюзов
                            # часто про конкретную модель (скоуп/модерация), поэтому
                            # его пробуем на следующей модели.
                            fatal = resp.status == 401
                            if resp.status == 403:
                                low = raw.lower()
                                fatal = any(
                                    marker in low
                                    for marker in (
                                        "insufficient_scope",
                                        "invalid_api_key",
                                        "invalid api key",
                                    )
                                )
                                retryable = retryable or not fatal
                            raise AIError(
                                message,
                                retryable=retryable,
                                fatal=fatal,
                                status=resp.status,
                                raw=raw,
                            )
                        data = json.loads(raw)
                except TimeoutError as exc:
                    log.warning(
                        "AI timeout (%s) — переключаюсь на другую модель", model
                    )
                    raise AIError(
                        "Модель думает слишком долго. Пробую другую.",
                        retryable=True,
                        model_level=True,
                    ) from exc
                except aiohttp.ClientError as exc:
                    log.warning("AI network error: %r", exc)
                    raise AIError(
                        "Сервис ИИ сейчас недоступен. Попробуй через минуту.",
                        retryable=True,
                    ) from exc
                except json.JSONDecodeError as exc:
                    log.warning("AI вернул не JSON: %s", raw[:300])
                    raise AIError(
                        "Сервис ИИ ответил невнятно. Попробуй ещё раз.",
                        retryable=True,
                        model_level=True,
                    ) from exc
                break

        if data is None:
            raise AIError(
                "Сервис ИИ ответил невнятно. Попробуй ещё раз.", retryable=True
            )
        return self._extract_text(data), self._is_truncated(data)

    # ------------------------------------------------------------------ запросы
    def _gemini_request(
        self,
        history: list[dict[str, str]],
        text: str,
        model: str,
        prompt: str,
        image: bytes | None,
        image_mime: str,
        *,
        max_tokens: int | None = None,
        assistant_prefix: str | None = None,
    ) -> tuple[str, dict[str, str], dict[str, Any]]:
        s = self._settings
        base = (s.ai_base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        # AI_BASE_URL часто копируют из доков Google вместе с /v1beta.
        if base.endswith("/v1beta"):
            base = base[: -len("/v1beta")]
        url = f"{base}/v1beta/models/{model}:generateContent"
        headers = {"x-goog-api-key": s.ai_api_key, "Content-Type": "application/json"}

        contents: list[dict[str, Any]] = [
            {
                "role": "user" if m["role"] == "user" else "model",
                "parts": [{"text": m["content"]}],
            }
            for m in history
        ]

        if assistant_prefix:
            contents.append(
                {"role": "model", "parts": [{"text": assistant_prefix}]}
            )
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
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": max(
                    500, int(max_tokens or s.ai_max_tokens or 4000)
                ),
            },
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
        *,
        max_tokens: int | None = None,
        assistant_prefix: str | None = None,
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
        if assistant_prefix:
            messages.append({"role": "assistant", "content": assistant_prefix})

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
            "max_tokens": max(500, int(max_tokens or s.ai_max_tokens or 4000)),
        }
        if s.ai_provider == "openrouter":
            # Не просим и не показываем reasoning: ответ должен быть готовым текстом.
            payload["reasoning"] = {"exclude": True}
        return url, headers, payload

    # ------------------------------------------------------------------ разбор
    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        # Некоторые шлюзы отвечают HTTP 200 с объектом ошибки вместо ответа.
        error = data.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or "").strip()
            raise AIError(
                detail or "Сервис ИИ вернул ошибку. Попробуй ещё раз.",
                retryable=True,
                model_level=True,
            )
        if "candidates" in data:  # Gemini
            candidates = data.get("candidates") or []
            if not candidates:
                blocked = (data.get("promptFeedback") or {}).get("blockReason")
                hint = f" (причина: {blocked})" if blocked else ""
                raise AIError(
                    f"Модель отказалась отвечать{hint}. Попробуй переформулировать.",
                    model_level=True,
                )
            parts = (candidates[0].get("content") or {}).get("parts") or []
            answer = "".join(p.get("text", "") for p in parts).strip()
        else:  # OpenAI-совместимые
            choices = data.get("choices") or []
            if not choices:
                raise AIError(
                    "Модель вернула пустой ответ. Попробуй ещё раз.",
                    retryable=True,
                    model_level=True,
                )
            message = choices[0].get("message") or {}
            answer = (message.get("content") or "").strip()
            if not answer:
                # Ход рассуждений показывать нельзя вообще: это не ответ.
                # Если модель вернула только reasoning — пробуем ещё раз.
                raise AIError(
                    "Модель не дала готовый ответ. Попробуй ещё раз через минуту.",
                    retryable=True,
                    model_level=True,
                )

        if not answer:
            raise AIError(
                "Модель вернула пустой ответ. Попробуй переформулировать.",
                retryable=True,
                model_level=True,
            )
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

        if "location is not supported" in lowered or (
            "not available in your" in lowered and "region" in lowered
        ):
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