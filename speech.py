"""Голос: распознавание речи (STT) и озвучка ответов (TTS).

STT — любой OpenAI-совместимый `/audio/transcriptions` (Whisper). Ключ задаётся
`STT_API_KEY` (или `OPENAI_API_KEY`), поэтому шлюз чата не обязан уметь аудио.
TTS — бесплатный `edge-tts` без ключей: отдаёт mp3, который сразу шлём voice.
"""

from __future__ import annotations

import asyncio
import logging
import re
from html import unescape

import aiohttp

from config import Settings
from store import Store

log = logging.getLogger("speech")

VOICE_KEY_PREFIX = "voice:"

# edge-tts не имеет белорусского голоса — для be читаем русским.
VOICES = {
    "ru": "ru-RU-DmitryNeural",
    "uk": "uk-UA-OstapNeural",
    "be": "ru-RU-DmitryNeural",
    "en": "en-US-GuyNeural",
}

STT_LANG = {"ru": "ru", "uk": "uk", "be": "be", "en": "en"}

MAX_TTS_CHARS = 1100
MAX_STT_BYTES = 20 * 1024 * 1024


def voice_key(user_id: int) -> str:
    return f"{VOICE_KEY_PREFIX}{user_id}"


async def auto_voice(store: Store, user_id: int) -> bool:
    """Включена ли автоозвучка ответов у пользователя."""
    try:
        return (await store.get_setting(voice_key(user_id))) == "1"
    except Exception:  # noqa: BLE001 — настройка не критична
        return False


async def set_auto_voice(store: Store, user_id: int, enabled: bool) -> None:
    await store.set_setting(voice_key(user_id), "1" if enabled else "0")


def stt_ready(settings: Settings) -> bool:
    return bool(settings.stt_api_key)


def _clean_for_speech(text: str) -> str:
    """Убирает разметку, код и ссылки: вслух читаем только смысл."""
    value = text or ""
    value = re.sub(r"```.*?```", " ", value, flags=re.S)
    value = re.sub(r"`[^`]*`", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", value)
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"^[#>*\-\s]+", " ", value, flags=re.M)
    value = re.sub(r"[*_~|]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) > MAX_TTS_CHARS:
        cut = value[:MAX_TTS_CHARS]
        for mark in (". ", "! ", "? ", "; "):
            pos = cut.rfind(mark)
            if pos > MAX_TTS_CHARS // 2:
                cut = cut[: pos + 1]
                break
        value = cut
    return value


async def synthesize(text: str, lang: str, settings: Settings) -> bytes | None:
    """mp3 с озвучкой или None, если TTS выключен/не удался."""
    if not settings.tts_enabled:
        return None
    clean = _clean_for_speech(text)
    if len(clean) < 3:
        return None
    try:
        import edge_tts
    except ImportError:
        log.warning("edge-tts не установлен — озвучка недоступна")
        return None

    voice = VOICES.get(lang) or VOICES["ru"]
    data = bytearray()
    try:
        communicate = edge_tts.Communicate(clean, voice)
        async with asyncio.timeout(40):
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    data += chunk["data"]
                    if len(data) > 8 * 1024 * 1024:
                        break
    except Exception:  # noqa: BLE001 — озвучка не должна ломать ответ
        log.exception("Не удалось озвучить ответ")
        return None
    return bytes(data) if data else None


async def transcribe(
    data: bytes,
    filename: str,
    mime: str,
    lang: str,
    settings: Settings,
) -> tuple[str | None, str | None]:
    """Текст из голосового. Возвращает (текст, код ошибки)."""
    if not data:
        return None, "empty"
    if len(data) > MAX_STT_BYTES:
        return None, "too_big"
    if not settings.stt_api_key:
        return None, "not_configured"

    url = settings.stt_base_url.rstrip("/") + "/audio/transcriptions"
    form = aiohttp.FormData()
    form.add_field(
        "file",
        data,
        filename=filename or "voice.ogg",
        content_type=mime or "audio/ogg",
    )
    form.add_field("model", settings.stt_model)
    language = STT_LANG.get(lang)
    if language:
        form.add_field("language", language)
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"}
    try:
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, data=form, headers=headers) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    log.warning("STT HTTP %s: %s", resp.status, body[:300])
                    return None, "http"
                payload = await resp.json(content_type=None)
    except Exception:  # noqa: BLE001
        log.exception("Ошибка распознавания речи")
        return None, "http"

    text = ""
    if isinstance(payload, dict):
        text = str(payload.get("text") or "").strip()
    if not text:
        return None, "empty_text"
    return text, None