"""Разбор медиа: кадры видео, стикеры, склейка кадров в одну картинку.

Видео нельзя отправить vision-модели целиком, поэтому бот достаёт несколько
кадров через ffmpeg и склеивает их в сетку. Если ffmpeg на сервере нет,
используется превью (thumbnail), которое Telegram отдаёт вместе с видео.
Стикеры-картинки конвертируются в PNG, анимированные `.tgs` разобрать нельзя.
"""

from __future__ import annotations

import io
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
    """Путь к ffmpeg: сначала FFMPEG_PATH, потом PATH."""
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which("ffmpeg")


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