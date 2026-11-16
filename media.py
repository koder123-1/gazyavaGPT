"""Разбор медиа: кадры видео, стикеры, склейка кадров в одну картинку.

Видео нельзя отправить vision-модели целиком, поэтому бот достаёт несколько
кадров через ffmpeg и склеивает их в сетку. Если ffmpeg на сервере нет,
используется превью (thumbnail), которое Telegram отдаёт вместе с видео.
Стикеры-картинки конвертируются в PNG, анимированные `.tgs` (Lottie)
рендерятся в кадры через `rlottie-python`, видео-стикеры `.webm` — через ffmpeg.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("media")

# Больше Telegram всё равно не отдаст боту через getFile.
VIDEO_MAX_BYTES = 20 * 1024 * 1024
FRAME_COUNT = 4
FRAME_WIDTH = 480

try:  # Pillow нужен и для стикеров, и для сетки кадров.
    from PIL import Image, ImageOps
except Exception:  # noqa: BLE001
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]


def ffmpeg_path() -> str | None:
    """Путь к ffmpeg: FFMPEG_PATH, потом PATH, потом imageio-ffmpeg."""
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        return configured if Path(configured).is_file() else None
    found = shutil.which("ffmpeg")
    if found:
        return found
    # На Render системного ffmpeg нет, зато imageio-ffmpeg приносит свой бинарник.
    try:
        import imageio_ffmpeg

        binary = imageio_ffmpeg.get_ffmpeg_exe()
        return binary if binary and Path(binary).is_file() else None
    except Exception:  # noqa: BLE001
        return None


def _split_frames(raw: bytes) -> list[bytes]:
    """Режет MJPEG-поток ffmpeg на отдельные JPEG по маркерам SOI/EOI."""
    frames: list[bytes] = []
    start = raw.find(b"\xff\xd8")
    while start != -1:
        end = raw.find(b"\xff\xd9", start + 2)
        if end == -1:
            break
        frames.append(raw[start : end + 2])
        start = raw.find(b"\xff\xd8", end + 2)
    return frames


def video_frames(data: bytes, count: int = FRAME_COUNT) -> list[bytes]:
    """Достаёт до `count` JPEG-кадров, равномерно разнесённых по видео."""
    binary = ffmpeg_path()
    if binary is None or not data:
        return []
    with tempfile.TemporaryDirectory(prefix="gazyava-video-") as folder:
        source = Path(folder) / "input"
        source.write_bytes(data)
        command = [
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            f"fps=1/2,scale={FRAME_WIDTH}:-2",
            "-frames:v",
            str(max(count * 3, count)),
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("ffmpeg не смог разобрать видео: %s", exc)
            return []
        if result.returncode != 0:
            log.info(
                "ffmpeg вернул код %s: %s",
                result.returncode,
                (result.stderr or b"")[:200],
            )
            return []
        frames = _split_frames(result.stdout)
    if len(frames) <= count:
        return frames
    step = len(frames) / count
    return [frames[int(index * step)] for index in range(count)]


def contact_sheet(frames: list[bytes], columns: int = 2) -> bytes:
    """Склеивает кадры в одну картинку, чтобы модель увидела всё видео сразу."""
    if not frames:
        return b""
    if Image is None:
        return frames[0]
    images = []
    for frame in frames:
        try:
            images.append(Image.open(io.BytesIO(frame)).convert("RGB"))
        except Exception:  # noqa: BLE001
            continue
    if not images:
        return b""
    if len(images) == 1:
        buffer = io.BytesIO()
        images[0].save(buffer, format="JPEG", quality=88)
        return buffer.getvalue()

    width = max(image.width for image in images)
    height = max(image.height for image in images)
    columns = max(1, min(columns, len(images)))
    rows = (len(images) + columns - 1) // columns
    sheet = Image.new("RGB", (width * columns, height * rows), "white")
    for index, image in enumerate(images):
        if image.size != (width, height):
            image = ImageOps.pad(image, (width, height), color="white")
        sheet.paste(image, ((index % columns) * width, (index // columns) * height))
    buffer = io.BytesIO()
    sheet.save(buffer, format="JPEG", quality=88)
    return buffer.getvalue()


def sticker_image(data: bytes) -> bytes:
    """Стикер webp/png -> JPEG на белом фоне (vision-модели так надёжнее)."""
    if not data:
        return b""
    if Image is None:
        return data
    try:
        image = Image.open(io.BytesIO(data))
        image = ImageOps.exif_transpose(image)
        if image.mode in {"RGBA", "LA", "P"}:
            image = image.convert("RGBA")
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            image = Image.alpha_composite(background, image)
        image = image.convert("RGB")
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()
    except Exception as exc:  # noqa: BLE001
        log.info("Не удалось открыть стикер: %s", exc)
        return b""


def tgs_frames(data: bytes, count: int = 3) -> list[bytes]:
    """Кадры анимированного стикера `.tgs` (gzip + Lottie) в PNG.

    Рендерит через `rlottie-python`, если пакет установлен. Без него вернёт
    пустой список — вызывающий код возьмёт превью из Telegram.
    """
    if not data or count <= 0:
        return []
    try:
        from rlottie_python import LottieAnimation
    except Exception:  # noqa: BLE001
        return []
    try:
        with tempfile.TemporaryDirectory(prefix="gazyava-tgs-") as folder:
            source = Path(folder) / "sticker.tgs"
            source.write_bytes(data)
            with LottieAnimation.from_tgs(str(source)) as anim:
                total = int(anim.lottie_animation_get_totalframe() or 0)
                if total <= 0:
                    return []
                frames: list[bytes] = []
                for index in range(count):
                    # Берём кадры по всей длине анимации, а не только начало.
                    frame = int(total * (index + 0.5) / count)
                    image = anim.render_pillow_frame(
                        frame_num=min(max(frame, 0), total - 1)
                    )
                    buffer = io.BytesIO()
                    image.convert("RGBA").save(buffer, format="PNG")
                    frames.append(buffer.getvalue())
                return frames
    except Exception as exc:  # noqa: BLE001
        log.info("Не удалось отрисовать .tgs: %s", exc)
        return []


def tgs_text(data: bytes) -> str:
    """Текст, зашитый в Lottie-стикер: слои типа text (если они есть)."""
    if not data:
        return ""
    try:
        raw = gzip.decompress(data)
    except OSError:
        raw = data
    try:
        doc = json.loads(raw.decode("utf-8", "ignore"))
    except (ValueError, UnicodeDecodeError):
        return ""
    found: list[str] = []
    for layer in doc.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        text = layer.get("t")
        if not isinstance(text, dict):
            continue
        for item in text.get("k") or []:
            if not isinstance(item, dict):
                continue
            value = (
                (item.get("s") or {}).get("t")
                if isinstance(item.get("s"), dict)
                else None
            )
            if isinstance(value, str):
                value = " ".join(value.split())
                if value and value not in found:
                    found.append(value)
    return " · ".join(found)[:200]


def sticker_video_frames(data: bytes, count: int = 4) -> list[bytes]:
    """Кадры видео-стикера `.webm` через ffmpeg (если он доступен)."""
    binary = ffmpeg_path()
    if binary is None or not data or count <= 0:
        return []
    with tempfile.TemporaryDirectory(prefix="gazyava-sticker-") as folder:
        source = Path(folder) / "sticker.webm"
        source.write_bytes(data)
        command = [
            binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            f"fps=4,scale={FRAME_WIDTH}:-2",
            "-frames:v",
            str(max(count * 2, count)),
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=45, check=False
            )
        except (OSError, subprocess.SubprocessError) as exc:
            log.info("ffmpeg не смог разобрать видео-стикер: %s", exc)
            return []
        if result.returncode != 0:
            log.info("ffmpeg для стикера вернул %s", result.returncode)
            return []
        frames = _split_frames(result.stdout)
    if len(frames) <= count:
        return frames
    step = len(frames) / count
    return [frames[int(index * step)] for index in range(count)]