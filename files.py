"""Чтение и сборка файлов: TXT, MD, CSV, JSON, DOCX, PDF, XLSX.

Бот получает документ, вытаскивает из него текст для ИИ и умеет собрать
готовый файл с ответом. Всё делается в памяти: на Render диск одноразовый,
а файлы пользователя хранить нельзя.

Тяжёлые библиотеки импортируются лениво: если какая-то не установилась,
бот продолжает работать и честно говорит, что формат недоступен.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

# Что умеем читать.
READ_EXTS = frozenset(
    {
        ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log",
        ".py", ".js", ".ts", ".html", ".htm", ".xml", ".yaml", ".yml",
        ".ini", ".cfg", ".toml", ".sql",
    }
) | {".docx", ".pdf", ".xlsx", ".pptx"}

TEXT_EXTS = READ_EXTS - {".docx", ".pdf", ".xlsx", ".pptx"}
IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"})

READ_HINT = "TXT, MD, CSV, JSON, DOCX, PDF, XLSX, PPTX"

# Telegram Bot API: getFile отдаёт боту не больше 20 МБ, отправка — до 50 МБ.
TELEGRAM_DOWNLOAD_LIMIT = 20 * 1024 * 1024
TELEGRAM_SEND_LIMIT = 50 * 1024 * 1024

OUTPUT_EXTS = {
    "txt": ".txt",
    "docx": ".docx",
    "pdf": ".pdf",
    "csv": ".csv",
    "xlsx": ".xlsx",
    "pptx": ".pptx",
    "py": ".py",
    "html": ".html",
    "css": ".css",
    "js": ".js",
}

# Обратное соответствие: по расширению присланного файла понять формат ответа.
FORMAT_BY_EXT = {ext: fmt for fmt, ext in OUTPUT_EXTS.items()}
FORMAT_BY_EXT.update(
    {".md": "txt", ".markdown": "txt", ".tsv": "csv", ".htm": "html"}
)

# Расширения по MIME: Telegram не всегда присылает file_name.
_EXT_BY_MIME = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "application/json": ".json",
    "application/xml": ".xml",
    "text/html": ".html",
}

# Заголовки решения: «📌 Условие», «🧮 Решение», «✅ Ответ».
_HEADER_RE = re.compile(r"^\s*(?:📌|🧮|✅|📄|📝)\s*(.+?)\s*:?\s*$")
_STEP_RE = re.compile(r"^\s*(?:Шаг\s*)?(\d{1,2})[).]\s+(?!\d)(.+)$", re.IGNORECASE)
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d\u20e3]"
)
_BAD_NAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')
# Управляющие символы ломают python-docx/openpyxl (ValueError/IllegalCharacterError).
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class FileError(Exception):
    """Ошибка с ключом перевода: обработчик покажет её пользователю."""

    def __init__(self, key: str, **kwargs: object) -> None:
        super().__init__(key)
        self.key = key
        self.kwargs = kwargs


def extension(filename: str | None, mime: str | None = None) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext:
        return ext
    return _EXT_BY_MIME.get((mime or "").lower(), "")


def is_image_document(filename: str | None, mime: str | None) -> bool:
    if (mime or "").lower().startswith("image/"):
        return True
    return extension(filename, mime) in IMAGE_EXTS


def is_supported(filename: str | None, mime: str | None) -> bool:
    return extension(filename, mime) in READ_EXTS


def sanitize_name(name: str, ext: str) -> str:
    base = _BAD_NAME_RE.sub("_", (name or "").strip()).strip(" ._")
    if ext and base.lower().endswith(ext.lower()):
        stem = base[: -len(ext)].strip(" ._")[:60] or "gazyavaGPT"
        return stem + ext
    if not base:
        return "gazyavaGPT" + ext
    # Длинное имя режем по основе, иначе обрезается расширение — и файл
    # превращается в «неизвестный формат».
    suffix = Path(base).suffix
    stem = base[: -len(suffix)] if suffix else base
    stem = stem.strip(" ._")[:60] or "gazyavaGPT"
    return stem + suffix + ext


# --------------------------------------------------------------------------- чтение


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _check_zip(data: bytes) -> None:
    """Защита от zip-бомбы: 20 МБ архива могут развернуться в гигабайты."""
    try:
        import zipfile

        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            total = sum(info.file_size for info in archive.infolist())
    except Exception:  # noqa: BLE001 — не архив или битый: пусть решает парсер
        return
    if total > 120 * 1024 * 1024:
        raise FileError("file.too_big", mb=20)


def extract_text(
    data: bytes, filename: str | None, mime: str | None = None, max_pages: int = 60
) -> str:
    """Достаёт текст из файла. Бросает FileError с ключом для пользователя."""
    ext = extension(filename, mime)
    if ext in {".docx", ".xlsx", ".pptx"}:
        _check_zip(data)
    try:
        if ext == ".pdf":
            return _read_pdf(data, max_pages)
        if ext == ".docx":
            return _read_docx(data)
        if ext == ".xlsx":
            return _read_xlsx(data)
        if ext == ".pptx":
            return _read_pptx(data)
        if ext in TEXT_EXTS:
            return _decode(data)
    except FileError:
        raise
    except Exception:  # noqa: BLE001 — ленивые парсеры падают уже после открытия
        raise FileError("file.empty") from None
    raise FileError("file.unsupported", ext=ext or "?")


def _read_pdf(data: bytes, max_pages: int = 60) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise FileError("file.unsupported", ext=".pdf") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            # pypdf не бросает исключение при неверном пароле, а возвращает 0.
            try:
                unlocked = reader.decrypt("")
            except Exception:  # noqa: BLE001
                unlocked = 0
            if not unlocked:
                raise FileError("file.locked")
        pages = reader.pages[: max(1, max_pages)]
        chunks: list[str] = []
        for number, page in enumerate(pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                text = ""
            if text.strip():
                chunks.append(f"[стр. {number}]\n{text.strip()}")
    except FileError:
        raise
    except Exception:  # noqa: BLE001
        raise FileError("file.empty") from None

    result = "\n\n".join(chunks).strip()
    # Нет текстового слоя вообще: почти наверняка скан из картинок. Короткий
    # текст — это нормальный документ (записка, чек), его не отбрасываем.
    if not result:
        raise FileError("file.scanned")
    return result


def _read_docx(data: bytes) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise FileError("file.unsupported", ext=".docx") from exc

    try:
        document = Document(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        raise FileError("file.empty") from None

    lines = [paragraph.text.rstrip() for paragraph in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                lines.append(" | ".join(cells))
    return "\n".join(lines).strip()


def _read_xlsx(data: bytes) -> str:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:  # pragma: no cover
        raise FileError("file.unsupported", ext=".xlsx") from exc

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:  # noqa: BLE001
        raise FileError("file.empty") from None

    chunks: list[str] = []
    rows_total = 0
    for sheet in workbook.worksheets:
        rows: list[str] = []
        for row in sheet.iter_rows(values_only=True):
            rows_total += 1
            if rows_total > 2000:
                break
            cells = [str(value).strip() for value in row if value not in (None, "")]
            if cells:
                rows.append(" | ".join(cell[:500] for cell in cells))
        if rows:
            chunks.append(f"[лист «{sheet.title}»]\n" + "\n".join(rows))
        if rows_total > 2000:
            chunks.append("…(таблица большая, показана часть)")
            break
    workbook.close()

    result = "\n\n".join(chunks).strip()
    if not result:
        raise FileError("file.empty")
    return result


def _read_pptx(data: bytes) -> str:
    try:
        from pptx import Presentation
    except ImportError as exc:  # pragma: no cover
        raise FileError("file.unsupported", ext=".pptx") from exc

    try:
        deck = Presentation(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        raise FileError("file.empty") from None

    chunks: list[str] = []
    for number, slide in enumerate(deck.slides, start=1):
        lines: list[str] = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False) and shape.text_frame is not None:
                for paragraph in shape.text_frame.paragraphs:
                    line = "".join(run.text for run in paragraph.runs).strip()
                    if line:
                        lines.append(line)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        lines.append(" | ".join(cells))
        if lines:
            chunks.append(f"[слайд {number}]\n" + "\n".join(lines))

    result = "\n\n".join(chunks).strip()
    if not result:
        raise FileError("file.empty")
    return result


def clip_text(text: str, limit: int) -> str:
    """Обрезает длинный текст и оставляет пометку."""
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n…(файл большой, показана только часть)"


# --------------------------------------------------------------------------- сборка


def build_txt(text: str) -> bytes:
    return (text or "").replace("\r\n", "\n").encode("utf-8")


def build_code(text: str) -> bytes:
    """Файл с кодом: снимаем markdown-забор, если модель его поставила."""
    body = text or ""
    blocks = re.findall(
        r"```[ \t]*[A-Za-z0-9_+.-]*[ \t]*\n(.*?)```", body, flags=re.S
    )
    if blocks:
        # В файл кладём только код: пояснения модели вокруг блоков не нужны.
        body = "\n\n".join(block.strip("\n") for block in blocks)
    else:
        body = re.sub(r"^\s*```[ \t]*[A-Za-z0-9_+.-]*\s*$", "", body, flags=re.M)
        body = re.sub(r"^\s*```\s*$", "", body, flags=re.M)
    return (body.rstrip() + "\n").replace("\r\n", "\n").encode("utf-8")


# Расширение по языку из ```-блока для файлов в архиве.
CODE_ZIP_EXTS = {
    "python": "py", "py": "py", "html": "html", "htm": "html",
    "css": "css", "scss": "scss", "js": "js", "javascript": "js",
    "ts": "ts", "typescript": "ts", "tsx": "tsx", "jsx": "jsx",
    "json": "json", "sql": "sql", "bash": "sh", "sh": "sh",
    "shell": "sh", "powershell": "ps1", "yaml": "yml", "yml": "yml",
    "xml": "xml", "java": "java", "kotlin": "kt", "go": "go",
    "rust": "rs", "c": "c", "cpp": "cpp", "c++": "cpp", "cs": "cs",
    "php": "php", "ruby": "rb", "swift": "swift", "dart": "dart",
    "dockerfile": "dockerfile", "markdown": "md", "md": "md",
}

# Имена, под которыми части проекта удобнее открывать.
CODE_DEFAULT_NAMES = {
    "py": "main.py", "html": "index.html", "css": "styles.css",
    "js": "script.js", "ts": "app.ts", "json": "data.json",
    "sql": "schema.sql", "sh": "run.sh", "yml": "config.yml",
    "md": "README.md", "xml": "data.xml",
}


def build_zip(entries: list[tuple[str, str]]) -> bytes:
    """Собирает архив из (имя файла, текст). Имена делает уникальными."""
    import zipfile

    buffer = io.BytesIO()
    used: dict[str, int] = {}
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for raw_name, body in entries:
            name = sanitize_name(raw_name, "")
            if not name:
                name = "file.txt"
            if name in used:
                used[name] += 1
                stem, dot, ext = name.partition(".")
                name = f"{stem}-{used[name]}{dot}{ext}"
            else:
                used[name] = 1
            archive.writestr(name, (body or "").rstrip() + "\n")
    return buffer.getvalue()


def _table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        if line.startswith("|") and line.endswith("|"):
            line = line.strip("|").strip()
        if "|" in line:
            cells = [cell.strip() for cell in line.split("|")]
        elif "\t" in line:
            cells = [cell.strip() for cell in line.split("\t")]
        elif ";" in line:
            cells = [cell.strip() for cell in line.split(";")]
        else:
            cells = [line]
        # Markdown-разделитель |---|---| — это оформление, а не данные.
        if cells and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def build_csv(text: str) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerows(_table_rows(text))
    # BOM, чтобы Excel на русской Windows открыл кириллицу без кракозябр.
    return buffer.getvalue().encode("utf-8-sig")


def build_xlsx(text: str) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError as exc:  # pragma: no cover
        raise FileError("file.unsupported", ext=".xlsx") from exc

    rows = _table_rows(text)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Лист1"
    for row in rows:
        sheet.append(row)
    if rows:
        header = PatternFill("solid", fgColor="DDEBF7")
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = header
        sheet.freeze_panes = "A2"
        for column in sheet.columns:
            width = max((len(str(cell.value or "")) for cell in column), default=8)
            sheet.column_dimensions[column[0].column_letter].width = min(max(10, width + 2), 40)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


_PPT_SEPARATOR = re.compile(r"^\s*(?:-{3,}|={3,})\s*$")
_PPT_TITLE = re.compile(
    r"^\s*(?:#{1,6}\s+|\[?слайд\s*\d+\]?\s*[.:—-]?\s*)(.+)$", re.IGNORECASE
)


def _pptx_sections(text: str) -> list[tuple[str, list[str]]]:
    """Делит ответ ИИ на слайды: «# Заголовок», «Слайд 2», «---»."""
    sections: list[tuple[str, list[str]]] = []
    title = ""
    body: list[str] = []

    def flush() -> None:
        nonlocal title, body
        if title or body:
            sections.append((title, body))
        title, body = "", []

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if _PPT_SEPARATOR.match(line):
            flush()
            continue
        heading = _PPT_TITLE.match(line)
        if heading and len(line) < 120:
            flush()
            title = heading.group(1).strip()
            continue
        body.append(re.sub(r"^[-•*]\s+", "", line))

    flush()
    if not sections:
        return [("Презентация", [])]

    # Разметки не было: режем текст на слайды по 10 строк.
    if len(sections) == 1 and len(sections[0][1]) > 12:
        lines = sections[0][1]
        chunks = [lines[index : index + 10] for index in range(0, len(lines), 10)]
        return [(chunks[0][0], chunks[0][1:])] + [("", chunk) for chunk in chunks[1:]]
    return sections


def build_pptx(text: str) -> bytes:
    try:
        from pptx import Presentation
        from pptx.util import Pt
    except ImportError as exc:  # pragma: no cover
        raise FileError("file.unsupported", ext=".pptx") from exc

    deck = Presentation()
    for title, body in _pptx_sections(text):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        if slide.shapes.title is not None:
            slide.shapes.title.text = (title or "Слайд")[:120]
        frame = slide.placeholders[1].text_frame
        frame.clear()
        if not body:
            frame.text = ""
        for index, item in enumerate(body):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = item[:300]
            paragraph.font.size = Pt(18)

    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def build_docx(text: str) -> bytes:
    try:
        from docx import Document
        from docx.shared import Pt
    except ImportError as exc:  # pragma: no cover
        raise FileError("file.unsupported", ext=".docx") from exc

    document = Document()
    style = document.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(12)

    for raw in (text or "").splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            document.add_paragraph("")
            continue
        header = _HEADER_RE.match(stripped)
        if header and len(stripped) < 60:
            paragraph = document.add_paragraph()
            run = paragraph.add_run(stripped)
            run.bold = True
            run.font.size = Pt(14)
            continue
        step = _STEP_RE.match(stripped)
        if step:
            paragraph = document.add_paragraph()
            paragraph.add_run(f"{step.group(1)}) ").bold = True
            paragraph.add_run(step.group(2).strip())
            continue
        document.add_paragraph(stripped)

    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _find_pdf_font() -> str | None:
    import os

    candidates: list[str] = []
    env = os.getenv("PDF_FONT_PATH", "").strip()
    if env:
        candidates.append(env)
    here = Path(__file__).resolve().parent
    candidates += [
        str(here / "assets" / "DejaVuSans.ttf"),
        str(here / "DejaVuSans.ttf"),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def build_pdf(text: str) -> bytes:
    try:
        from fpdf import FPDF
    except ImportError as exc:  # pragma: no cover
        raise FileError("file.pdf_unavailable") from exc

    font = _find_pdf_font()
    if not font:
        raise FileError("file.pdf_unavailable")

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_font("body", "", font)
    pdf.set_font("body", size=12)
    pdf.add_page()

    for raw in (text or "").splitlines():
        line = _EMOJI_RE.sub("", raw).rstrip()
        stripped = line.strip()
        if not stripped:
            pdf.ln(3)
            continue
        header = _HEADER_RE.match(_EMOJI_RE.sub("", raw).strip())
        if header and len(stripped) < 60:
            pdf.ln(2)
            pdf.set_font("body", size=15)
            pdf.multi_cell(0, 8, stripped, wrapmode="CHAR")
            pdf.set_font("body", size=12)
            pdf.ln(1)
            continue
        pdf.multi_cell(0, 6.5, stripped, wrapmode="CHAR")
        pdf.ln(0.6)

    return bytes(pdf.output())


def build_output(text: str, fmt: str, name: str | None = None) -> tuple[bytes, str]:
    """Собирает файл нужного формата. Возвращает (данные, имя файла)."""
    builders = {
        "txt": build_txt,
        "docx": build_docx,
        "pdf": build_pdf,
        "csv": build_csv,
        "xlsx": build_xlsx,
        "pptx": build_pptx,
        "py": build_code,
        "html": build_code,
        "css": build_code,
        "js": build_code,
    }
    builder = builders.get(fmt)
    if builder is None:
        raise FileError("file.unsupported", ext=fmt)
    # Управляющие символы из ответа модели или PDF ломают сборку office-файлов.
    text = _CONTROL_RE.sub("", text or "")
    ext = OUTPUT_EXTS[fmt]
    base = name or ("gazyavaGPT-код" if fmt in {"py", "html", "css", "js"} else "gazyavaGPT-решение")
    filename = sanitize_name(base, ext)
    return builder(text), filename


def edited_filename(filename: str | None, fmt: str) -> str:
    """Build a safe edited filename while preserving the source basename."""
    original = Path(filename or "document").name
    stem = Path(original).stem or "document"
    ext = OUTPUT_EXTS.get(fmt, Path(original).suffix or ".txt")
    return sanitize_name(f"{stem}-исправлено", ext)


def retarget_filename(filename: str | None, fmt: str) -> str:
    """То же имя с новым расширением: «конспект.txt» -> «конспект.pdf»."""
    original = Path(filename or "document").name
    stem = Path(original).stem or "document"
    ext = OUTPUT_EXTS.get(fmt, Path(original).suffix or ".txt")
    return sanitize_name(stem, ext)


def edit_instruction(text: str | None) -> bool:
    """True when the user asks to make changes, not just summarize the file."""
    return bool(re.search(
        r"\b(?:отредактир\w*|редактир\w*|исправ\w*|перепиш\w*|передел\w*|"
        r"измени\w*|измен\w*|улучш\w*|почини\w*|правь|поправ\w*|оформ\w*|"
        r"сократ\w*|добав\w*|дополн\w*|удал\w*|убер\w*|замен\w*|встав\w*|"
        r"correct\w*|edit\w*|fix\w*|rewrite\w*|improve\w*|translate\w*|update\w*)\b",
        text or "",
        flags=re.IGNORECASE,
    ))


def wants_echo(text: str | None) -> bool:
    """Explicitly asks to return/copy the original file without editing it."""
    return bool(re.search(
        r"\b(?:верни|вернуть|отправь|отправить|пришли|прислать|скин\w*|скопируй|копию|"
        r"return|send\s+back|resend)\b.*\b(?:файл|документ|file|document)\b",
        text or "",
        flags=re.IGNORECASE,
    ))


def build_empty(fmt: str, name: str | None = None) -> tuple[bytes, str]:
    """Пустой файл (0 байт) с правильным расширением.

    «Сделай пустой файл html» — это именно пустой файл, а не страница-заготовка
    на 188 байт и не имя вида «gazyavaGPT-код»: так пользователь сразу видит,
    что получил то, о чём просил.
    """
    if fmt not in OUTPUT_EXTS:
        raise FileError("file.unsupported", ext=fmt)
    ext = OUTPUT_EXTS[fmt]
    base = name or suggest_filename("пустой", fmt)
    return b"", sanitize_name(base, ext)


# Слова, которые не должны попадать в имя файла: это команды и формат, а не смысл.
_NAME_NOISE = re.compile(
    r"(?i)\b(?:созда\w*|сдела\w*|сгенер\w*|сформир\w*|напиш\w*|оформ\w*|сохран\w*|"
    r"пришл\w*|попрос\w*|отправ\w*|скин\w*|выгруз\w*|экспорт\w*|собер\w*|подготов\w*|"
    r"перевед\w*|конверт\w*|пожалуйста|плиз|я|мне|нужен|нужно|надо|хочу|дай\w*|"
    r"файл\w*|документ\w*|вложени\w*|"
    r"pdf|docx?|word|ворд|докс|xlsx|excel|эксель|csv|txt|текстов\w*|"
    r"pptx?|powerpoint|презентаци\w*|слайд\w*|"
    r"py|python|html|хтмл\w*|css|цсс\w*|js|javascript|джс|жаваскрипт\w*|"
    r"а|и|в|во|на|с|со|по|для|от|до|из|к|о|об|это|этот|эту|этого)\b"
)
_EMPTY_WORD = re.compile(r"(?i)\b(?:пуст\w*|пусой|empty)\b")
_PAGE_WORD = re.compile(r"(?i)\b(?:сайт\w*|страниц\w*|лендинг\w*|site|page|index)\b")


def is_empty_file_request(text: str | None) -> bool:
    """Просит именно пустой файл: «сделай пустой html», «пустой txt файл»."""
    raw = (text or "").strip()
    if not raw or not _EMPTY_WORD.search(raw):
        return False
    if detect_output_format(raw) not in {"txt", "html", "css", "js", "py", "csv"}:
        return False
    # «Пустой шаблон с формой» — это уже содержание, а не пустой файл.
    leftover = _EMPTY_WORD.sub(" ", _NAME_NOISE.sub(" ", raw))
    leftover = re.sub(r"[\W_]+", "", leftover, flags=re.UNICODE)
    return len(leftover) < 3


def suggest_filename(instruction: str | None, fmt: str) -> str:
    """Короткое осмысленное имя из просьбы вместо «gazyavaGPT-код»."""
    ext = OUTPUT_EXTS[fmt]
    text = (instruction or "").strip()
    if is_empty_file_request(text):
        base = "пустой"
    elif fmt in {"html", "css", "js"} and _PAGE_WORD.search(text):
        base = "index"
    else:
        cleaned = _NAME_NOISE.sub(" ", text)
        words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", cleaned)
        base = "-".join(words[:4])
        base = re.sub(r"-{2,}", "-", base).strip("-")[:40]
        if not base:
            base = "gazyavaGPT-код" if fmt in {"py", "html", "css", "js"} else "gazyavaGPT-решение"
    return sanitize_name(base, ext)


# --------------------------------------------------------------------------- формат ответа

_FORMAT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Код: только явные просьбы про файл с расширением, чтобы «что такое Python»
    # не превращалось в .py-вложение. Учитываем и русские написания: «хтмл», «питон».
    ("py", re.compile(
        r"\.py\b|\bpy[- ]?файл|\bpython[- ]?файл|\bпайтон\w*|\bпитон\w*|"
        r"\bфайл\w*\s+(?:на\s+)?(?:python|питон\w*|пайтон\w*)",
        re.IGNORECASE,
    )),
    ("html", re.compile(
        r"\.html?\b|\bhtml[- ]?файл|\bхтмл\w*|\bфайл\w*\s+(?:html|хтмл\w*)",
        re.IGNORECASE,
    )),
    ("css", re.compile(r"\.css\b|\bcss[- ]?файл|\bцсс\w*", re.IGNORECASE)),
    ("js", re.compile(
        r"\.js\b|\bjs[- ]?файл|\bjavascript[- ]?файл|\bджс\b|\bжаваскрипт\w*|"
        r"\bфайл\w*\s+(?:js|javascript|джс|жаваскрипт\w*)",
        re.IGNORECASE,
    )),
    ("pdf", re.compile(r"\bpdf\b|пдф|пэдэф|пдэф", re.IGNORECASE)),
    ("docx", re.compile(r"\bdocx?\b|\bword\b|ворд|докс", re.IGNORECASE)),
    ("xlsx", re.compile(r"\bxlsx\b|\bexcel\b|эксель|ексель", re.IGNORECASE)),
    ("pptx", re.compile(
        r"\bpptx?\b|\bpowerpoint\b|\bпрезентаци\w*|\bслайд\w*", re.IGNORECASE
    )),
    ("csv", re.compile(r"\bcsv\b|\bцсв\b", re.IGNORECASE)),
    ("txt", re.compile(r"\btxt\b|\bтхт\b|текстов\w*\s+файл", re.IGNORECASE)),
)
_GENERIC_FILE = re.compile(
    r"\bфайл\w*\b|\bскач\w*\b|\bсохран\w*\b|\bвыгруз\w*\b|\bэкспорт\w*\b", re.IGNORECASE
)
# Формат без слова «файл»: «создай пустой html», «напиши игру на python».
_FORMAT_WORDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("py", re.compile(r"\b(?:python|питон\w*|пайтон\w*)\b", re.IGNORECASE)),
    ("html", re.compile(r"\bhtml?\b|\bхтмл\w*", re.IGNORECASE)),
    ("css", re.compile(r"\bcss\b|\bцсс\w*", re.IGNORECASE)),
    ("js", re.compile(r"\b(?:js|javascript|джс|жаваскрипт\w*)\b", re.IGNORECASE)),
    ("pptx", re.compile(r"\b(?:презентаци\w*|слайд\w*|powerpoint)\b", re.IGNORECASE)),
)
_ASK_ABOUT = re.compile(
    r"(?i)\b(?:что такое|как работает|как сделать|почему|зачем|объясни|расскажи|подскажи)\b"
)
_FILE_VERB = re.compile(
    r"пришл|отправ|сдел|оформ|сохран|скач|выгруз|экспорт|перев|нужен|нужн|"
    r"в виде|файл",
    re.IGNORECASE,
)


def detect_output_format(instruction: str | None, *, generic: bool = True) -> str | None:
    """Если пользователь просит файл — вернуть формат. Иначе None.

    generic=False отключает «просто файл → DOCX»: при переводе или конспекте
    присланного PDF нельзя молча менять формат на DOCX.
    """
    text = (instruction or "").strip()
    if not text:
        return None
    for fmt, pattern in _FORMAT_PATTERNS:
        if pattern.search(text):
            return fmt
    if _CREATE_VERB.search(text) and not _QUESTION_START.search(text) and not _ASK_ABOUT.search(text):
        for fmt, pattern in _FORMAT_WORDS:
            if pattern.search(text):
                return fmt
    if generic and _GENERIC_FILE.search(text):
        return "docx"
    return None


def wants_file(instruction: str | None) -> bool:
    """Явная просьба собрать файл, а не просто упоминание формата.

    Отличает «пришли это в PDF» от «что такое PDF».
    """
    text = (instruction or "").strip()
    return bool(text) and bool(_FILE_VERB.search(text)) and detect_output_format(text) is not None


# Глаголы, с которых начинается просьба именно СОЗДАТЬ файл.
_CREATE_VERB = re.compile(
    r"(?i)\b(?:созда\w*|сдела\w*|сгенер\w*|сформир\w*|напиш\w*|оформ\w*|сохран\w*|пришл\w*|"
    r"отправ\w*|скин\w*|выгруз\w*|экспорт\w*|собер\w*|подготов\w*|перевед\w*|"
    r"конверт\w*|нужен|нужно|надо|хочу\w*|можно|дай\w*|пришлите|сделайте|создайте)\b"
)
_QUESTION_START = re.compile(
    r"(?i)^\s*(?:как|что|почему|зачем|где|когда|можно\s+ли|расскажи|объясни|"
    r"подскажи|how|what|why|where|when|can\s+i)\b"
)
_EXPLICIT_DOC = re.compile(r"(?i)\b(?:файл|документ|word|ворд|докс|docx?)\b")

# Слова, которые не несут содержания в просьбе «пришли файлом».
_FILE_NOISE = re.compile(
    r"(?i)\b(?:а|и|ну|мне|это|этот|эту|его|её|ее|всё|все|в|во|на|с|со|по|как|"
    r"пожалуйста|плиз|теперь|просто|можешь|можно|нужно|нужен|надо|давай|"
    r"созда\w*|сдела\w*|сгенер\w*|напиш\w*|оформ\w*|сохран\w*|пришл\w*|"
    r"отправ\w*|скин\w*|выгруз\w*|экспорт\w*|собер\w*|подготов\w*|перевед\w*|"
    r"конверт\w*|дай\w*|файл\w*|документ\w*|вложени\w*|"
    r"pdf|docx?|word|ворд|докс|xlsx|excel|эксель|csv|цсв|txt|тхт|текстов\w*|"
    r"pptx?|powerpoint|презентаци\w*|слайд\w*|"
    r"py|python|html|хтмл\w*|css|цсс\w*|js|javascript|джс|жаваскрипт\w*)\b"
)


def wants_new_file(text: str | None) -> bool:
    """Просит ли пользователь СОЗДАТЬ файл с нуля (а не спросить о файлах).

    «Сделай PDF с планом» — да. «Как отправить файл в Telegram?» — нет.
    """
    raw = (text or "").strip()
    if not raw or _QUESTION_START.match(raw):
        return False
    if detect_output_format(raw) is None or not _CREATE_VERB.search(raw):
        return False
    # Общий DOCX включаем только при явном слове «файл/документ/word».
    if detect_output_format(raw) == "docx" and not _EXPLICIT_DOC.search(raw):
        return False
    return True


def wants_document_output(text: str | None) -> bool:
    """Нужен ли файл в ответ на присланный документ.

    Здесь контекст уже есть: достаточно формата («PDF») или просьбы
    («переведи и пришли DOCX»). Вопросы «что такое PDF» отсекаются.
    """
    raw = (text or "").strip()
    if not raw or _QUESTION_START.match(raw):
        return False
    return detect_output_format(raw, generic=False) is not None


def is_pure_file_request(text: str | None) -> bool:
    """В просьбе нет содержания — только «пришли это файлом»."""
    leftover = _FILE_NOISE.sub(" ", text or "")
    leftover = re.sub(r"[\W_]+", "", leftover, flags=re.UNICODE)
    return len(leftover) < 3
