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
) | {".docx", ".pdf", ".xlsx"}

TEXT_EXTS = READ_EXTS - {".docx", ".pdf", ".xlsx"}
IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"})

READ_HINT = "TXT, MD, CSV, JSON, DOCX, PDF, XLSX"

OUTPUT_EXTS = {
    "txt": ".txt",
    "docx": ".docx",
    "pdf": ".pdf",
    "csv": ".csv",
    "xlsx": ".xlsx",
    "py": ".py",
    "html": ".html",
    "css": ".css",
    "js": ".js",
}

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
_STEP_RE = re.compile(r"^\s*(?:Шаг\s*)?(\d{1,2})\s*[).:]\s*(.+)$", re.IGNORECASE)
_EMOJI_RE = re.compile(
    "[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d\u20e3]"
)
_BAD_NAME_RE = re.compile(r'[\\/:*?"<>|\r\n\t]+')


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
    base = base[:60] or "gazyavaGPT"
    if not base.lower().endswith(ext):
        base += ext
    return base


# --------------------------------------------------------------------------- чтение


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "koi8-r"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def extract_text(
    data: bytes, filename: str | None, mime: str | None = None, max_pages: int = 60
) -> str:
    """Достаёт текст из файла. Бросает FileError с ключом для пользователя."""
    ext = extension(filename, mime)
    if ext == ".pdf":
        return _read_pdf(data, max_pages)
    if ext == ".docx":
        return _read_docx(data)
    if ext == ".xlsx":
        return _read_xlsx(data)
    if ext in TEXT_EXTS:
        return _decode(data)
    raise FileError("file.unsupported", ext=ext or "?")


def _read_pdf(data: bytes, max_pages: int = 60) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - зависит от окружения
        raise FileError("file.unsupported", ext=".pdf") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:  # noqa: BLE001
                raise FileError("file.locked") from None
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
    # Текстовый слой пустой: почти наверняка скан из картинок.
    if len(result) < 40:
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


def clip_text(text: str, limit: int) -> str:
    """Обрезает длинный текст и оставляет пометку."""
    text = (text or "").strip()
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n…(файл большой, показана только часть)"


# --------------------------------------------------------------------------- сборка


def build_txt(text: str) -> bytes:
    return (text or "").replace("\r\n", "\n").encode("utf-8")


_FENCE_ONLY_RE = re.compile(
    r"^\s*```[ \t]*[A-Za-z0-9_+.-]*[ \t]*\n(.*?)\n?```\s*$", re.S
)


def build_code(text: str) -> bytes:
    """Файл с кодом: снимаем markdown-забор, если модель его поставила."""
    body = text or ""
    match = _FENCE_ONLY_RE.match(body)
    if match:
        body = match.group(1)
    else:
        body = re.sub(r"^\s*```[ \t]*[A-Za-z0-9_+.-]*\s*$", "", body, flags=re.M)
        body = re.sub(r"^\s*```\s*$", "", body, flags=re.M)
    return (body.rstrip() + "\n").replace("\r\n", "\n").encode("utf-8")


def _table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|") and line.endswith("|"):
            line = line.strip("|").strip()
        if "|" in line:
            rows.append([cell.strip() for cell in line.split("|")])
        elif "\t" in line:
            rows.append([cell.strip() for cell in line.split("\t")])
        elif ";" in line:
            rows.append([cell.strip() for cell in line.split(";")])
        else:
            rows.append([line])
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


def build_output(text: str, fmt: str) -> tuple[bytes, str]:
    """Собирает файл нужного формата. Возвращает (данные, имя файла)."""
    builders = {
        "txt": build_txt,
        "docx": build_docx,
        "pdf": build_pdf,
        "csv": build_csv,
        "xlsx": build_xlsx,
        "py": build_code,
        "html": build_code,
        "css": build_code,
        "js": build_code,
    }
    builder = builders.get(fmt)
    if builder is None:
        raise FileError("file.unsupported", ext=fmt)
    ext = OUTPUT_EXTS[fmt]
    base = "gazyavaGPT-код" if fmt in {"py", "html", "css", "js"} else "gazyavaGPT-решение"
    name = sanitize_name(base, ext)
    return builder(text), name


# --------------------------------------------------------------------------- формат ответа

_FORMAT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Код: только явные просьбы про файл с расширением, чтобы «что такое Python»
    # не превращалось в .py-вложение.
    ("py", re.compile(
        r"\.py\b|\bpy[- ]?файл|\bpython[- ]?файл|\bфайл\w*\s+(?:на\s+)?python",
        re.IGNORECASE,
    )),
    ("html", re.compile(
        r"\.html?\b|\bhtml[- ]?файл|\bфайл\w*\s+html", re.IGNORECASE
    )),
    ("css", re.compile(r"\.css\b|\bcss[- ]?файл", re.IGNORECASE)),
    ("js", re.compile(
        r"\.js\b|\bjs[- ]?файл|\bjavascript[- ]?файл", re.IGNORECASE
    )),
    ("pdf", re.compile(r"\bpdf\b|пдф|пэдэф|пдэф", re.IGNORECASE)),
    ("docx", re.compile(r"\bdocx?\b|\bword\b|ворд|докс", re.IGNORECASE)),
    ("xlsx", re.compile(r"\bxlsx\b|\bexcel\b|эксель|ексель", re.IGNORECASE)),
    ("csv", re.compile(r"\bcsv\b", re.IGNORECASE)),
    ("txt", re.compile(r"\btxt\b|текстов\w*\s+файл", re.IGNORECASE)),
)
_GENERIC_FILE = re.compile(
    r"\bфайл\w*\b|\bскач\w*\b|\bсохран\w*\b|\bвыгруз\w*\b|\bэкспорт\w*\b", re.IGNORECASE
)
_FILE_VERB = re.compile(
    r"пришл|отправ|сдел|оформ|сохран|скач|выгруз|экспорт|перев|нужен|нужн|"
    r"в виде|файл",
    re.IGNORECASE,
)


def detect_output_format(instruction: str | None) -> str | None:
    """Если пользователь просит файл — вернуть формат. Иначе None."""
    text = (instruction or "").strip()
    if not text:
        return None
    for fmt, pattern in _FORMAT_PATTERNS:
        if pattern.search(text):
            return fmt
    if _GENERIC_FILE.search(text):
        return "docx"
    return None


def wants_file(instruction: str | None) -> bool:
    """Явная просьба собрать файл, а не просто упоминание формата.

    Отличает «пришли это в PDF» от «что такое PDF».
    """
    text = (instruction or "").strip()
    return bool(text) and bool(_FILE_VERB.search(text)) and detect_output_format(text) is not None