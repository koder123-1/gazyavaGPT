"""Генерация и редактирование картинок.

Провайдеры:
- pollinations — бесплатно и без ключа: генерация через Classic API, а базовые
  правки фото делаются локально через Pillow (без внешних сервисов);
- openrouter — Gemini-картинки через OpenRouter: работает без привязки к стране
  IP и с тем же ключом, что и чат (нужны кредиты OpenRouter);
- gemini — генерация и AI-редактирование напрямую через Google AI Studio;
- openai — /images/generations и /images/edits (нужен IMAGE_API_KEY);
- reformboss — тот же OpenAI-формат через api.reformboss.com (нужен ключ).

Провайдер, модель и ключ задаются через .env: код менять не нужно.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import random
import re
from urllib.parse import quote, urlencode

import aiohttp

from config import Settings

log = logging.getLogger("images")

# Сколько ждём провайдера, прежде чем включить резерв и не заставлять
# пользователя смотреть на «генерирую» две минуты.
IMAGE_TIMEOUT = 55

# Шлюзы вроде ReformBoss кэшируют картинку по тексту промпта: два одинаковых
# запроса дают байт-в-байт тот же результат. Разный знак в конце делает запрос
# уникальным и на смысл картинки не влияет.
_VARIATION_SUFFIXES = (" .", " !", " …", " ?", " ;", " ,", " :")


def fresh_prompt(prompt: str) -> str:
    """Промпт с незаметной вариацией, чтобы не попадать в кэш провайдера."""
    prompt = prompt.rstrip()
    if not prompt:
        return prompt
    return prompt + random.choice(_VARIATION_SUFFIXES)


def retry_seconds(header: str, default: int = 30) -> int:
    """Retry-After бывает числом секунд — или HTTP-датой (тогда берём default)."""
    value = (header or "").strip()
    if value.isdigit():
        return max(1, int(value))
    match = re.search(r"retry after (\d+)", value, re.I)
    if match:
        return max(1, int(match.group(1)))
    try:
        from email.utils import parsedate_to_datetime
        from datetime import datetime, timezone

        moment = parsedate_to_datetime(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        seconds = int((moment - datetime.now(timezone.utc)).total_seconds())
        return max(1, seconds)
    except (TypeError, ValueError, OverflowError):
        return max(1, default)


class ImageError(Exception):
    """Ошибка с текстом, который можно показать пользователю."""


class ImageUnsupported(ImageError):
    """Бесплатный режим не умеет такую правку — нужен AI-провайдер."""


class ImageRateLimited(ImageError):
    """Сервис просит подождать перед следующей картинкой."""

    def __init__(self, seconds: int) -> None:
        self.seconds = max(1, seconds)
        super().__init__(f"Слишком часто: подожди {self.seconds} секунд.")


class ImageNoCredits(ImageError):
    """У провайдера закончились кредиты — нужен резервный бесплатный путь."""


class ImageUnavailable(ImageError):
    """Сеть или сервер провайдера: можно попробовать другого."""


class ImageClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session: aiohttp.ClientSession | None = None

    @property
    def provider(self) -> str:
        return (self._settings.image_provider or "none").lower()

    @property
    def configured(self) -> bool:
        if self.provider == "pollinations":
            return True
        if self.provider in {"openai", "gemini", "openrouter", "reformboss"}:
            return bool(self._settings.image_api_key)
        return False

    @property
    def model(self) -> str:
        configured = (self._settings.image_model or "").strip()
        if self.provider == "gemini" and configured in {"", "flux"}:
            return "gemini-nano-banana-2.1"
        if self.provider == "openrouter" and configured in {"", "flux"}:
            return "google/gemini-nano-banana-2.1"
        if self.provider == "reformboss" and configured in {"", "flux"}:
            return "rh-gpt-image-2-5"
        if self.provider == "openai" and configured in {"", "flux"}:
            return "gpt-image-1"
        return configured or "flux"

    @property
    def models(self) -> tuple[str, ...]:
        """Модели картинок по порядку: первая рабочая и уходит в ответ."""
        configured = tuple(
            item.strip() for item in self._settings.image_models if item.strip()
        )
        if configured:
            return tuple(dict.fromkeys(configured))
        raw = (self._settings.image_model or "").strip()
        if "," in raw:
            parts = (part.strip() for part in raw.split(","))
            return tuple(dict.fromkeys(part for part in parts if part))
        return (self.model,)

    @property
    def _openai_base(self) -> str:
        """База для OpenAI-совместимых картинок."""
        configured = (self._settings.image_base_url or "").strip().rstrip("/")
        if configured:
            return configured
        if self.provider == "reformboss":
            return "https://api.reformboss.com/v1"
        return "https://api.openai.com/v1"

    @property
    def fallback(self) -> str:
        """Куда откатываться, если платный провайдер недоступен."""
        value = (self._settings.image_fallback or "").strip().lower()
        if value in {"", "none", "off", "0"} or value == self.provider:
            return ""
        return value

    def _model_for(self, provider: str) -> str:
        """Модель для выбранного провайдера (для резерва — его собственный дефолт)."""
        if provider == self.provider:
            return self.model
        defaults = {
            "gemini": "gemini-nano-banana-2.1",
            "openrouter": "google/gemini-nano-banana-2.1",
            "reformboss": "rh-gpt-image-2-5",
            "openai": "gpt-image-1",
            "pollinations": "flux",
        }
        return defaults.get(provider, "flux")

    async def start(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=180, connect=20)
            )

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    # ------------------------------------------------------------------ публично
    async def generate(self, prompt: str, *, size: int | None = None) -> bytes:
        prompt = (prompt or "").strip()
        if not prompt:
            raise ImageError("Пустое описание картинки.")
        if not self.configured:
            raise ImageError("Генерация картинок не подключена.")
        await self.start()
        size = size or self._settings.image_size
        try:
            return await self._try_models(
                self.models,
                lambda model: self._generate_with(self.provider, model, prompt, size),
            )
        except ImageUnsupported:
            raise
        except ImageError as exc:
            # Все модели провайдера не сработали — пробуем бесплатный резерв.
            return await self._fallback(prompt, size, exc, edit=False)

    async def _try_models(self, models: tuple[str, ...], call) -> bytes:
        """Пробует модели по порядку; последняя ошибка уходит в резервный провайдер."""
        error: ImageError | None = None
        for model in models:
            try:
                return await call(model)
            except ImageUnsupported:
                raise
            except ImageNoCredits:
                # Нет кредитов у провайдера целиком — остальные модели не помогут.
                raise
            except ImageError as exc:
                error = exc
                if len(models) > 1:
                    log.warning("Модель картинок %s не сработала: %s", model, exc)
        assert error is not None
        raise error

    async def edit(self, image: bytes, mime: str, instruction: str) -> bytes:
        instruction = (instruction or "").strip()
        if not instruction:
            raise ImageError("Не указано, что изменить.")
        if not image:
            raise ImageError("Не вижу изображения.")
        if not self.configured:
            raise ImageError("Редактирование картинок не подключено.")
        await self.start()
        try:
            return await self._try_models(
                self.models,
                lambda model: self._edit_with(self.provider, model, image, mime, instruction),
            )
        except ImageUnsupported:
            raise
        except ImageError as exc:
            return await self._fallback(
                instruction, 0, exc, edit=True, image=image, mime=mime
            )

    async def _generate_with(
        self, provider: str, model: str, prompt: str, size: int
    ) -> bytes:
        if provider == "pollinations":
            return await self._pollinations(prompt, size=size)
        if provider == "gemini":
            return await self._gemini(prompt, model=model)
        if provider == "openrouter":
            return await self._openrouter(prompt, size=size, model=model)

        payload = {
            "model": model,
            "prompt": prompt,
            "n": 1,
            "size": f"{size}x{size}",
        }
        if self.provider == "reformboss":
            # Шлюз кэширует ответ по промпту: без вариации одинаковые запросы
            # возвращают одну и ту же картинку.
            payload["prompt"] = fresh_prompt(prompt)
            payload["seed"] = random.randint(1, 2**31 - 1)
        data = await self._openai_json("/images/generations", payload)
        return await self._decode_openai_image(data)

    async def _edit_with(
        self, provider: str, model: str, image: bytes, mime: str, instruction: str
    ) -> bytes:
        if provider == "openai" or provider == "reformboss":
            return await self._openai_edit(image, mime, instruction, model=model)
        if provider == "gemini":
            return await self._gemini(
                "Отредактируй это изображение по просьбе: "
                + instruction
                + ". Сохрани композицию и персонажей, измени только то, о чём просят.",
                image=image,
                mime=mime,
                model=model,
            )
        if provider == "openrouter":
            return await self._openrouter(instruction, image=image, mime=mime, model=model)

        # pollinations не умеет img2img без платного ключа, зато базовые
        # правки можно сделать локально, бесплатно и без отправки фото наружу.
        # PIL — тяжёлый CPU: не блокируем событийный цикл.
        return await asyncio.to_thread(self._local_edit, image, instruction)

    async def _fallback(
        self,
        prompt: str,
        size: int,
        exc: ImageError,
        *,
        edit: bool,
        image: bytes | None = None,
        mime: str = "image/png",
    ) -> bytes:
        target = self.fallback
        if not target:
            raise exc
        log.warning(
            "Провайдер %s не смог %s (%s) -> резерв %s",
            self.provider,
            "изменить фото" if edit else "нарисовать",
            exc,
            target,
        )
        if edit and image is not None:
            return await self._edit_with(
                target, self._model_for(target), image, mime, prompt
            )
        return await self._generate_with(
            target, self._model_for(target), prompt, size
        )

    # ------------------------------------------------------------------ pollinations
    async def _pollinations(self, prompt: str, *, size: int = 1024) -> bytes:
        assert self._session is not None
        # Classic API отдаёт не больше 768×768 и всегда JPEG.
        side = max(256, min(int(size), 768))
        # nologo=true обязателен: без него Pollinations кладёт водяной знак.
        params = {
            "width": side,
            "height": side,
            "nologo": "true",
            "model": "flux",
            "seed": random.randint(1, 10**6),
        }
        url = (
            "https://image.pollinations.ai/prompt/"
            + quote(prompt[:900], safe="")
            + "?"
            + urlencode(params)
        )
        try:
            async with asyncio.timeout(IMAGE_TIMEOUT):
                async with self._session.get(url) as resp:
                    raw = await resp.read()
                    if resp.status in {402, 429}:
                        seconds = retry_seconds(
                            resp.headers.get("Retry-After", ""), 45
                        )
                        if not resp.headers.get("Retry-After"):
                            body_retry = re.search(
                                r"retry after (\d+)",
                                raw.decode("utf-8", "ignore"),
                                re.I,
                            )
                            if body_retry:
                                seconds = max(1, int(body_retry.group(1)))
                        log.info("pollinations limit: ждём %s с", seconds)
                        raise ImageRateLimited(seconds)
                    if resp.status != 200:
                        log.warning("pollinations HTTP %s: %s", resp.status, raw[:200])
                        if resp.status >= 500:
                            raise ImageUnavailable("Сервис картинок временно недоступен.")
                        raise ImageError("Сервис картинок ответил ошибкой. Попробуй позже.")
                    content_type = resp.headers.get("Content-Type", "")
        except TimeoutError as exc:
            log.warning("pollinations timeout")
            raise ImageUnavailable("Сервис картинок не ответил вовремя.") from exc
        except aiohttp.ClientError as exc:
            log.warning("pollinations network error: %r", exc)
            raise ImageUnavailable("Сервис картинок недоступен. Попробуй позже.") from exc
        if not raw or not content_type.startswith("image/"):
            raise ImageError("Сервис картинок вернул не картинку. Попробуй другой запрос.")
        return raw

    # ------------------------------------------------------------------ gemini
    @property
    def _gemini_uses_interactions(self) -> bool:
        """Новые image-модели работают через /interactions, старые — через generateContent."""
        model = self.model.lower()
        return "nano-banana" in model or model.startswith("gemini-3")

    async def _gemini(
        self,
        prompt: str,
        *,
        image: bytes | None = None,
        mime: str = "image/png",
        model: str | None = None,
    ) -> bytes:
        model = (model or self.model).strip()
        if self._gemini_uses_interactions_for(model):
            return await self._gemini_interactions(prompt, image=image, mime=mime, model=model)
        return await self._gemini_generate_content(prompt, image=image, mime=mime, model=model)

    @staticmethod
    def _gemini_uses_interactions_for(model: str) -> bool:
        model = model.lower()
        return "nano-banana" in model or model.startswith("gemini-3")

    async def _gemini_interactions(
        self,
        prompt: str,
        *,
        image: bytes | None = None,
        mime: str = "image/png",
        model: str | None = None,
    ) -> bytes:
        assert self._session is not None
        model = (model or self.model).strip()
        base = self._settings.image_base_url or "https://generativelanguage.googleapis.com/v1beta"
        headers = {
            "x-goog-api-key": self._settings.image_api_key,
            "Content-Type": "application/json",
            "Api-Revision": "2026-05-20",
        }
        inputs: list[dict] = [{"type": "text", "text": prompt}]
        if image is not None:
            inputs.append(
                {
                    "type": "image",
                    "mime_type": mime or "image/png",
                    "data": base64.b64encode(image).decode("ascii"),
                }
            )
        payload = {
            "model": model,
            "input": inputs,
            "response_format": {"type": "image", "mime_type": "image/png"},
        }
        data = await self._gemini_post(base + "/interactions", payload, headers)
        encoded = self._find_gemini_image(data)
        if encoded:
            return base64.b64decode(encoded)
        raise ImageError("Сервис не вернул картинку. Попробуй другой запрос.")

    async def _gemini_generate_content(
        self,
        prompt: str,
        *,
        image: bytes | None = None,
        mime: str = "image/png",
        model: str | None = None,
    ) -> bytes:
        assert self._session is not None
        model = (model or self.model).strip()
        base = self._settings.image_base_url or "https://generativelanguage.googleapis.com/v1beta"
        headers = {
            "x-goog-api-key": self._settings.image_api_key,
            "Content-Type": "application/json",
        }
        parts: list[dict] = [{"text": prompt}]
        if image is not None:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime or "image/png",
                        "data": base64.b64encode(image).decode("ascii"),
                    }
                }
            )
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        data = await self._gemini_post(
            f"{base}/models/{model}:generateContent", payload, headers
        )
        encoded = self._find_gemini_image(data)
        if encoded:
            return base64.b64decode(encoded)
        raise ImageError("Сервис не вернул картинку. Попробуй другой запрос.")

    async def _gemini_post(self, url: str, payload: dict, headers: dict) -> dict:
        assert self._session is not None
        try:
            async with asyncio.timeout(IMAGE_TIMEOUT):
                async with self._session.post(
                    url, json=payload, headers=headers
                ) as resp:
                    raw = await resp.text()
                    if resp.status != 200:
                        log.warning("gemini image HTTP %s: %s", resp.status, raw[:300])
                        if resp.status >= 500:
                            raise ImageUnavailable("Сервис картинок временно недоступен.")
                        raise ImageError("Сервис картинок отклонил запрос. Проверь ключ и модель.")
                    return json.loads(raw)
        except TimeoutError as exc:
            raise ImageUnavailable("Сервис картинок не ответил вовремя.") from exc
        except aiohttp.ClientError as exc:
            raise ImageUnavailable("Сервис картинок недоступен. Попробуй позже.") from exc
        except json.JSONDecodeError as exc:
            raise ImageError("Сервис картинок ответил непонятно.") from exc

    @classmethod
    def _find_gemini_image(cls, node: object) -> str | None:
        """Ищет base64 картинки в ответе Gemini (interactions или generateContent)."""
        if isinstance(node, dict):
            for key in ("inlineData", "inline_data", "output_image", "outputImage"):
                value = node.get(key)
                if isinstance(value, dict) and isinstance(value.get("data"), str):
                    return value["data"]
            for value in node.values():
                found = cls._find_gemini_image(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = cls._find_gemini_image(item)
                if found:
                    return found
        return None

    # ------------------------------------------------------------------ openrouter
    @staticmethod
    def _openrouter_payload(
        model: str,
        prompt: str,
        *,
        size: int | None = None,
        image: bytes | None = None,
        mime: str = "image/png",
    ) -> dict:
        payload: dict = {"model": model, "prompt": prompt, "n": 1}
        if size:
            payload["resolution"] = "512" if size <= 640 else ("768" if size <= 900 else "1K")
            payload["aspect_ratio"] = "1:1"
        if image:
            payload["input_references"] = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:"
                        + (mime or "image/png")
                        + ";base64,"
                        + base64.b64encode(image).decode("ascii"),
                    },
                }
            ]
        return payload

    async def _openrouter(
        self,
        prompt: str,
        *,
        size: int | None = None,
        image: bytes | None = None,
        mime: str = "image/png",
        model: str | None = None,
    ) -> bytes:
        """Gemini-картинки через OpenRouter: без геоблокировки Google."""
        assert self._session is not None
        model = (model or self.model).strip()
        base = self._settings.image_base_url or "https://openrouter.ai/api/v1"
        headers = {
            "Authorization": f"Bearer {self._settings.image_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://t.me/",
            "X-Title": "gazyavaGPT",
        }
        full_prompt = prompt
        if image is not None:
            full_prompt = (
                "Измени это изображение по просьбе: "
                + prompt
                + ". Сохрани композицию и персонажей, измени только то, о чём просят."
            )
        payload = self._openrouter_payload(
            model, full_prompt, size=size, image=image, mime=mime
        )
        try:
            async with asyncio.timeout(IMAGE_TIMEOUT):
                async with self._session.post(
                    base + "/images", json=payload, headers=headers
                ) as resp:
                    raw = await resp.text()
                    status = resp.status
                    retry_after = resp.headers.get("Retry-After", "")
        except TimeoutError as exc:
            raise ImageUnavailable("Сервис картинок не ответил вовремя.") from exc
        except aiohttp.ClientError as exc:
            raise ImageUnavailable("Сервис картинок недоступен. Попробуй позже.") from exc

        if status == 402:
            log.warning("openrouter: нет кредитов на картинки")
            raise ImageNoCredits("У провайдера картинок закончились кредиты.")
        if status == 429:
            seconds = retry_seconds(retry_after, 30)
            raise ImageRateLimited(seconds)
        if status >= 500:
            log.warning("openrouter image HTTP %s: %s", status, raw[:300])
            raise ImageUnavailable("Сервис картинок временно недоступен.")
        if status != 200:
            log.warning("openrouter image HTTP %s: %s", status, raw[:300])
            raise ImageError("Сервис картинок отклонил запрос. Проверь ключ и модель.")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ImageError("Сервис картинок ответил непонятно.") from exc
        # Ответ может быть и с b64_json, и с url — единый разбор.
        return await self._decode_openai_image(data)

    # ------------------------------------------------------------------ openai
    async def _openai_json(self, path: str, payload: dict) -> dict:
        assert self._session is not None
        base = self._openai_base
        headers = {
            "Authorization": f"Bearer {self._settings.image_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with asyncio.timeout(IMAGE_TIMEOUT):
                async with self._session.post(
                    base + path, json=payload, headers=headers
                ) as resp:
                    raw = await resp.text()
                    if resp.status != 200:
                        log.warning("image API HTTP %s: %s", resp.status, raw[:300])
                        if resp.status == 429:
                            seconds = retry_seconds(
                                resp.headers.get("Retry-After", ""), 30
                            )
                            raise ImageRateLimited(seconds)
                        if resp.status == 402:
                            raise ImageNoCredits("У провайдера картинок закончились кредиты.")
                        if resp.status >= 500:
                            raise ImageUnavailable("Сервис картинок временно недоступен.")
                        raise ImageError("Сервис картинок отклонил запрос. Проверь ключ и модель.")
                    return json.loads(raw)
        except TimeoutError as exc:
            raise ImageUnavailable("Сервис картинок не ответил вовремя.") from exc
        except aiohttp.ClientError as exc:
            raise ImageUnavailable("Сервис картинок недоступен. Попробуй позже.") from exc
        except json.JSONDecodeError as exc:
            raise ImageError("Сервис картинок ответил непонятно.") from exc

    async def _openai_edit(
        self, image: bytes, mime: str, instruction: str, *, model: str | None = None
    ) -> bytes:
        assert self._session is not None
        base = self._openai_base
        model = (model or self.model).strip()
        if self.provider == "reformboss":
            # ReformBoss не принимает multipart: правка идёт через generations
            # с исходником в поле image (data URL).
            payload = {
                "model": model,
                "prompt": fresh_prompt(instruction),
                "n": 1,
                "seed": random.randint(1, 2**31 - 1),
                "image": "data:"
                + (mime or "image/png")
                + ";base64,"
                + base64.b64encode(image).decode("ascii"),
            }
            data = await self._openai_json("/images/generations", payload)
            return await self._decode_openai_image(data)
        headers = {"Authorization": f"Bearer {self._settings.image_api_key}"}
        form = aiohttp.FormData()
        form.add_field("model", model)
        form.add_field("prompt", instruction)
        form.add_field(
            "image",
            image,
            filename="photo.png",
            content_type=mime or "image/png",
        )
        try:
            async with asyncio.timeout(IMAGE_TIMEOUT):
                async with self._session.post(
                    base + "/images/edits", data=form, headers=headers
                ) as resp:
                    raw = await resp.text()
                    if resp.status != 200:
                        log.warning("image edit HTTP %s: %s", resp.status, raw[:300])
                        if resp.status == 429:
                            seconds = retry_seconds(
                                resp.headers.get("Retry-After", ""), 30
                            )
                            raise ImageRateLimited(seconds)
                        if resp.status == 402:
                            raise ImageNoCredits("У провайдера картинок закончились кредиты.")
                        if resp.status >= 500:
                            raise ImageUnavailable("Сервис картинок временно недоступен.")
                        raise ImageError("Сервис не смог изменить фото. Попробуй другой запрос.")
                    return await self._decode_openai_image(json.loads(raw))
        except TimeoutError as exc:
            raise ImageUnavailable("Сервис картинок не ответил вовремя.") from exc
        except aiohttp.ClientError as exc:
            raise ImageUnavailable("Сервис картинок недоступен. Попробуй позже.") from exc
        except (ValueError, TypeError) as exc:
            raise ImageError("Сервис картинок ответил непонятно.") from exc

    async def _decode_openai_image(self, data: dict) -> bytes:
        items = data.get("data") or []
        if not items:
            raise ImageError("Сервис не вернул картинку.")
        item = items[0]
        if item.get("b64_json"):
            try:
                return base64.b64decode(item["b64_json"], validate=False)
            except (ValueError, TypeError) as exc:
                raise ImageError("Сервис вернул повреждённую картинку.") from exc
        if item.get("url"):
            url = str(item["url"]).strip()
            # Шлюзы вроде ReformBoss отдают картинку прямо в data URL.
            if url.startswith("data:"):
                _, _, payload = url.partition(",")
                payload = "".join(payload.split())
                payload += "=" * (-len(payload) % 4)
                try:
                    return base64.b64decode(payload, validate=False)
                except (ValueError, TypeError) as exc:
                    raise ImageError("Сервис вернул повреждённую картинку.") from exc
            assert self._session is not None
            try:
                async with asyncio.timeout(IMAGE_TIMEOUT):
                    async with self._session.get(url) as resp:
                        if resp.status != 200:
                            raise ImageError("Не удалось скачать готовую картинку.")
                        return await resp.read()
            except TimeoutError as exc:
                raise ImageUnavailable("Сервис не отдал картинку вовремя.") from exc
            except aiohttp.ClientError as exc:
                raise ImageUnavailable("Не удалось скачать готовую картинку.") from exc
        raise ImageError("Сервис не вернул картинку.")

    # ------------------------------------------------------------------ локальные правки
    _GRAY_RE = re.compile(r"ч[её]рно-?бел|grayscale|black\s*(?:and|&)\s*white|чорно-біл", re.I)
    _SEPIA_RE = re.compile(r"сепи[яи]|sepia", re.I)
    _INVERT_RE = re.compile(r"инверт|негатив|invert|negative", re.I)
    _BLUR_RE = re.compile(r"размы|заблюр|blur|soften", re.I)
    _SHARPEN_RE = re.compile(r"резк|чётк|четк|sharpen|sharp", re.I)
    _BRIGHT_UP_RE = re.compile(r"ярч|светле|bright", re.I)
    _BRIGHT_DOWN_RE = re.compile(r"темне|темн|darker|darken", re.I)
    _CONTRAST_UP_RE = re.compile(r"контраст|contrast", re.I)
    _SAT_UP_RE = re.compile(r"насыщен|цветност|saturat|vibrant", re.I)
    _SAT_DOWN_RE = re.compile(r"блёкл|блекл|desaturat|muted", re.I)
    _MIRROR_RE = re.compile(r"отзеркал|зеркал|отрази|mirror|flip", re.I)
    _ROTATE_RE = re.compile(r"поверн|поверни|rotate|turn", re.I)
    _CROP_RE = re.compile(r"обреж|обрез|кроп|crop", re.I)
    _RESIZE_RE = re.compile(r"уменьш|увелич|размер|resize|smaller|bigger|enlarge|scale", re.I)

    def _local_edit(self, data: bytes, instruction: str) -> bytes:
        """Базовый «фотошоп» без внешних сервисов: цвет, фильтры, геометрия."""
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps

        try:
            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            raise ImageError("Не удалось открыть фото для редактирования.") from exc

        text = instruction.lower()
        touched = False

        if self._ROTATE_RE.search(text):
            angle = 90
            number = re.search(r"(90|180|270)", text)
            if number:
                angle = int(number.group(1))
            if re.search(r"направо|вправо|clockwise|right", text):
                angle = -angle
            img = img.rotate(angle, expand=True)
            touched = True

        if self._MIRROR_RE.search(text):
            if re.search(r"вертикал|vertical|вверх", text):
                img = ImageOps.flip(img)
            else:
                img = ImageOps.mirror(img)
            touched = True

        if self._GRAY_RE.search(text):
            img = ImageOps.grayscale(img).convert("RGB")
            touched = True
        elif self._SEPIA_RE.search(text):
            gray = ImageOps.grayscale(img)
            img = ImageOps.colorize(gray, black="#3b2412", white="#ffe8c0")
            touched = True
        elif self._INVERT_RE.search(text):
            img = ImageOps.invert(img)
            touched = True

        if self._BLUR_RE.search(text):
            img = img.filter(ImageFilter.GaussianBlur(radius=3))
            touched = True
        if self._SHARPEN_RE.search(text):
            img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
            touched = True

        if self._BRIGHT_UP_RE.search(text):
            img = ImageEnhance.Brightness(img).enhance(1.3)
            touched = True
        elif self._BRIGHT_DOWN_RE.search(text):
            img = ImageEnhance.Brightness(img).enhance(0.7)
            touched = True

        if self._CONTRAST_UP_RE.search(text):
            img = ImageEnhance.Contrast(img).enhance(1.3)
            touched = True

        if self._SAT_UP_RE.search(text):
            img = ImageEnhance.Color(img).enhance(1.4)
            touched = True
        elif self._SAT_DOWN_RE.search(text):
            img = ImageEnhance.Color(img).enhance(0.55)
            touched = True

        if self._CROP_RE.search(text):
            width, height = img.size
            box = (
                int(width * 0.08),
                int(height * 0.08),
                int(width * 0.92),
                int(height * 0.92),
            )
            img = img.crop(box)
            touched = True

        if self._RESIZE_RE.search(text):
            factor = 0.5 if re.search(r"уменьш|smaller|shrink", text) else 1.5
            number = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:x|раз|times)", text)
            if number:
                try:
                    factor = float(number.group(1).replace(",", "."))
                except ValueError:
                    pass
                if re.search(r"уменьш|smaller|shrink", text) and factor > 1:
                    factor = 1 / factor
            width, height = img.size
            factor = max(0.1, min(factor, 3.0))
            size = (max(16, int(width * factor)), max(16, int(height * factor)))
            if size[0] > 2048 or size[1] > 2048:
                ratio = min(2048 / size[0], 2048 / size[1])
                size = (int(size[0] * ratio), int(size[1] * ratio))
            img = img.resize(size, Image.LANCZOS)
            touched = True

        if not touched:
            raise ImageUnsupported("unsupported")

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=92, optimize=True)
        return buffer.getvalue()