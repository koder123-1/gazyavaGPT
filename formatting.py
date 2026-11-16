"""Приводим ответ ИИ к читаемому виду для Telegram.

Модели любят LaTeX (\\frac{1}{2}, \\sqrt{x}, $x^2$) и markdown (**шаг**).
Бот отправляет обычный текст, поэтому такие символы выглядят как мусор.
Здесь мы превращаем формулы в понятные знаки и убираем разметку.
"""

from __future__ import annotations

import re

_SUP = {
    "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
    "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
    "+": "⁺", "-": "⁻", "−": "⁻", "=": "⁼", "(": "⁽", ")": "⁾",
    "n": "ⁿ", "i": "ⁱ",
}

_SUB = {
    "0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄",
    "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
    "+": "₊", "-": "₋", "−": "₋", "=": "₌", "(": "₍", ")": "₎",
}

_SYMBOLS = {
    # арифметика и сравнения
    "times": "×", "cdot": "·", "div": "÷", "pm": "±", "mp": "∓",
    "le": "≤", "leq": "≤", "ge": "≥", "geq": "≥", "ne": "≠", "neq": "≠",
    "approx": "≈", "equiv": "≡", "sim": "∼", "propto": "∝",
    "infty": "∞", "degree": "°", "circ": "°",
    # геометрия
    "angle": "∠", "triangle": "△", "perp": "⊥", "parallel": "∥",
    "cong": "≅", "similar": "∼",
    # множества и логика
    "in": "∈", "notin": "∉", "subset": "⊂", "subseteq": "⊆",
    "supset": "⊃", "cup": "∪", "cap": "∩", "emptyset": "∅",
    "forall": "∀", "exists": "∃", "neg": "¬", "land": "∧", "lor": "∨",
    "therefore": "∴", "because": "∵",
    # стрелки
    "to": "→", "rightarrow": "→", "leftarrow": "←", "leftrightarrow": "↔",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "Leftrightarrow": "⇔",
    "uparrow": "↑", "downarrow": "↓",
    # прочее
    "sum": "Σ", "prod": "∏", "int": "∫", "partial": "∂", "nabla": "∇",
    "ldots": "…", "dots": "…", "cdots": "…", "vdots": "⋮",
    "quad": "  ", "qquad": "   ",
    # греческие буквы
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν",
    "xi": "ξ", "omicron": "ο", "pi": "π", "rho": "ρ", "sigma": "σ",
    "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ", "chi": "χ",
    "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    # функции
    "sin": "sin", "cos": "cos", "tan": "tan", "cot": "cot",
    "arcsin": "arcsin", "arccos": "arccos", "arctan": "arctan",
    "log": "log", "ln": "ln", "lg": "lg", "exp": "exp",
    "lim": "lim", "max": "max", "min": "min", "mod": "mod", "bmod": "mod",
    "abs": "abs", "gcd": "gcd", "lcm": "lcm",
}

_WRAPPERS = (
    "text", "textrm", "mathrm", "mathbf", "mathit", "mathsf", "mathtt",
    "operatorname", "boxed", "overline", "underline", "mathcal", "mathbb",
    "vec", "hat", "bar", "tilde", "dot", "ddot",
)

_COMBINING = {
    "vec": "\u20d7",
    "hat": "\u0302",
    "bar": "\u0304",
    "tilde": "\u0303",
    "dot": "\u0307",
    "ddot": "\u0308",
}

_ENV_RE = re.compile(
    r"\\begin\{(?P<env>[A-Za-z*]+)\}(?P<body>.*?)\\end\{(?P=env)\}", re.S
)
_FRAC_RE = re.compile(r"\\(?:d|t)?frac\b")
_SQRT_RE = re.compile(r"\\sqrt\b")


def _read_group(text: str, start: int) -> tuple[str, int] | None:
    """Читает {...} с учётом вложенных скобок. Возвращает (содержимое, индекс после })."""
    if start >= len(text) or text[start] != "{":
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index], index + 1
    return None


def _read_arg(text: str, start: int) -> tuple[str, int] | None:
    """Аргумент команды: {...}, \\команда или один символ."""
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text):
        return None
    if text[index] == "{":
        return _read_group(text, index)
    match = re.match(r"\\[A-Za-z]+|\S", text[index:])
    if not match:
        return None
    return match.group(0), index + len(match.group(0))


def _simple(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9A-Za-z.²³¹⁰⁴⁵⁶⁷⁸⁹⁻⁺₀₁₂₃₄₅₆₇₈₉]+", value))


def _superscript(content: str) -> str:
    if content in {"°", "∘"}:
        return "°"
    if content and all(char in _SUP for char in content):
        return "".join(_SUP[char] for char in content)
    return f"^{content}" if len(content) == 1 else f"^({content})"


def _subscript(content: str) -> str:
    if content and all(char in _SUB for char in content):
        return "".join(_SUB[char] for char in content)
    return f"_{content}" if len(content) == 1 else f"_({content})"


def _scripts(text: str) -> str:
    text = re.sub(r"\^\{([^{}]*)\}", lambda match: _superscript(match.group(1)), text)
    text = re.sub(
        r"\^([0-9]+|[A-Za-z]|[°∘])", lambda match: _superscript(match.group(1)), text
    )

    text = re.sub(r"_\{([^{}]*)\}", lambda match: _subscript(match.group(1)), text)
    # Индекс превращаем только там, где он действительно похож на индекс,
    # иначе слова вроде file_name потеряют букву.
    text = re.sub(
        r"(?<=[0-9A-Za-z)\]])_([0-9]+|[A-Za-z])(?=\s*(?:[=+\-*/·×÷),.;^]|$))",
        lambda match: _subscript(match.group(1)),
        text,
    )
    return text


def _fractions(text: str) -> str:
    while True:
        match = _FRAC_RE.search(text)
        if not match:
            return text
        first = _read_arg(text, match.end())
        if first is None:
            text = text[: match.start()] + text[match.end() :]
            continue
        numerator, index = first
        second = _read_arg(text, index)
        if second is None:
            text = text[: match.start()] + text[match.end() :]
            continue
        denominator, end = second

        numerator = _scripts(_fractions(numerator))
        denominator = _scripts(_fractions(denominator))
        if _simple(numerator) and _simple(denominator):
            replacement = f"{numerator}/{denominator}"
        else:
            replacement = f"({numerator})/({denominator})"
        # Смешанное число: 1\frac{1}{4} — это «1 1/4», а не «11/4».
        if match.start() > 0 and text[match.start() - 1].isdigit():
            replacement = " " + replacement
        text = text[: match.start()] + replacement + text[end:]


def _roots(text: str) -> str:
    while True:
        match = _SQRT_RE.search(text)
        if not match:
            return text
        index = match.end()
        degree = ""
        while index < len(text) and text[index].isspace():
            index += 1
        if index < len(text) and text[index] == "[":
            close = text.find("]", index)
            if close != -1:
                degree = text[index + 1 : close]
                index = close + 1
        argument = _read_arg(text, index)
        if argument is None:
            text = text[: match.start()] + text[match.end() :]
            continue
        content, end = argument
        content = _roots(_scripts(_fractions(content)))
        if _simple(content):
            root = f"√{content}"
        else:
            root = f"√({content})"
        if degree:
            root = f"{_scripts('^' + degree) if degree.isdigit() else degree}√{content}"
        text = text[: match.start()] + root + text[end:]


def _wrappers(text: str) -> str:
    pattern = re.compile(r"\\(" + "|".join(_WRAPPERS) + r")\s*")
    while True:
        match = pattern.search(text)
        if not match:
            return text
        command = match.group(1)
        argument = _read_arg(text, match.end())
        if argument is None:
            text = text[: match.start()] + text[match.end() :]
            continue
        content, end = argument
        if command in _COMBINING:
            content = content + _COMBINING[command]
        text = text[: match.start()] + content + text[end:]


def _environments(text: str) -> str:
    def render(match: re.Match[str]) -> str:
        env = match.group("env").lower().rstrip("*")
        body = match.group("body")
        if env == "array":
            body = re.sub(r"^\s*\{[^}]*\}", "", body, count=1)
        rows = [row.strip() for row in re.split(r"\\\\", body) if row.strip()]

        if env in {"matrix", "pmatrix", "bmatrix", "vmatrix", "smallmatrix"}:
            parsed = ["  ".join(cell.strip() for cell in row.split("&")) for row in rows]
            inner = " ; ".join(parsed)
            if env in {"pmatrix", "bmatrix"}:
                return f"[{inner}]"
            if env == "vmatrix":
                return f"|{inner}|"
            return inner
        if env == "cases":
            parsed = []
            for row in rows:
                cells = [cell.strip() for cell in row.split("&")]
                if len(cells) == 2 and re.match(
                    r"(?i)(если|при|иначе|otherwise|for)\b", cells[1]
                ):
                    parsed.append(f"{cells[0]}, {cells[1]}")
                else:
                    parsed.append(", ".join(cells))
            return "{ " + " ; ".join(parsed) + " }"
        return "\n".join(" ".join(cell.strip() for cell in row.split("&")) for row in rows)

    while True:
        updated = _ENV_RE.sub(render, text)
        if updated == text:
            return text
        text = updated


def _symbols(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        return _SYMBOLS.get(match.group(1), "")

    return re.sub(r"\\([A-Za-z]+)", replace, text)


def _markdown(text: str) -> str:
    text = re.sub(r"```[^\n]*\n?", "", text)
    text = text.replace("```", "")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"__(.+?)__", r"\1", text, flags=re.S)
    text = re.sub(r"(?<!\*)\*(?!\s)([^*\n]*[A-Za-zА-Яа-я][^*\n]*)(?<!\s)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}>\s?", "", text)
    text = re.sub(r"(?m)^\s*(?:---+|\*\*\*+|___+)\s*$", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "• ", text)
    text = re.sub(
        r"</?(?:b|i|u|s|code|pre|em|strong|br|p|div|span|a)(?:\s[^>]*)?>",
        "",
        text,
        flags=re.I,
    )
    return text


def _sections(text: str) -> str:
    text = re.sub(r"(?mi)^[ \t]*(?:📌[ \t]*)?Условие[ \t]*:", "📌 Условие:", text)
    text = re.sub(r"(?mi)^[ \t]*(?:🧮[ \t]*)?Решение[ \t]*:", "🧮 Решение:", text)
    text = re.sub(r"(?mi)^[ \t]*(?:✅[ \t]*)?Ответ[ \t]*:", "✅ Ответ:", text)
    text = re.sub(r"(?<=\S)[ \t]+(?=(?:Шаг|Step)[ \t]*\d+[ \t]*[:.)])", "\n", text)
    for marker in ("🧮 Решение:", "✅ Ответ:"):
        text = re.sub(r"\n*[ \t]*" + re.escape(marker), "\n\n" + marker, text)
    return text


_THINK_HEAD_RE = re.compile(
    r"^\s*(?:thinking\s+process|thinking|analysis|analyze\s+the\s+request|reasoning|"
    r"размышлени[ея]|ход\s+рассуждений|рассуждаю)\s*[:：]?\s*",
    re.IGNORECASE,
)
_FINAL_RE = re.compile(
    r"(?im)^\s*(?:final\s+answer|итог|итоговый\s+ответ|готовый\s+ответ|"
    r"✅\s*ответ|ответ\s+ученику)\s*[:：]"
)
_REASONING_HINTS = (
    "thinking process", "analyze the request", "let me", "let's ", "wait,",
    "the user asks", "the user wants", "looking at the", "examine the image",
    "zoom in", "rotate the image", "i need to", "this looks like",
)


def strip_thinking(text: str) -> str:
    """Убирает «Thinking Process» и английские черновики, оставляя готовый ответ.

    Возвращает пустую строку, если готового ответа нет — тогда вызывающий код
    честно просит повторить, а не показывает пользователю мусор.
    """
    if not text:
        return ""

    match = _THINK_HEAD_RE.match(text)
    if not match:
        # Заголовка нет, но текст может быть чистым черновиком: несколько
        # характерных английских фраз подряд и ни одного заголовка ответа.
        head_lines = [line.strip() for line in text.split("\n") if line.strip()][:3]
        head = " ".join(head_lines).lower()
        hints = sum(1 for hint in _REASONING_HINTS if hint in head)
        if hints >= 2 and not re.search(r"[📌🧮✅]", text):
            return ""
        return text.strip()

    rest = text[match.end() :]
    final = _FINAL_RE.search(rest)
    if final:
        # Заголовок «Final Answer:» тоже служебный — начинаем сразу с ответа.
        rest = rest[final.end() :]
    else:
        positions = [rest.find(mark) for mark in ("📌", "🧮", "✅")]
        positions = [pos for pos in positions if pos != -1]
        if positions:
            rest = rest[min(positions) :]

    kept: list[str] = []
    for line in rest.split("\n"):
        lowered = line.strip().lower()
        if lowered and any(hint in lowered for hint in _REASONING_HINTS):
            if not re.search(r"[а-яё]", lowered):
                continue
        kept.append(line)
    rest = "\n".join(kept).strip()
    if not rest or not re.search(r"[A-Za-zА-Яа-яЁё0-9]", rest):
        return ""

    # Был заголовок рассуждений, но готового финала так и не появилось:
    # англоязычный остаток — это черновик, показывать его нельзя.
    if not final and not re.search(r"[📌🧮✅]", rest) and not re.search(r"[а-яё]", rest):
        return ""
    return rest


def humanize_answer(text: str, *, code: bool = False) -> str:
    """Убирает LaTeX/markdown и делает решение читаемым в обычном тексте.

    code=True — ответ в кодерском стиле: код не трогаем, сохраняем отступы,
    решётки, обратные кавычки и HTML-теги, иначе примеры ломаются.
    """
    if not text:
        return ""
    text = strip_thinking(text)
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")

    if code:
        text = text.replace("\t", "    ")
        text = "\n".join(line.rstrip() for line in text.split("\n"))
        text = re.sub(r"\n{4,}", "\n\n\n", text)
        return text.strip()

    text = re.sub(r"\$\$(.+?)\$\$", r"\1", text, flags=re.S)
    text = re.sub(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)", r"\1", text)
    for opener, closer in (("\\[", "\\]"), ("\\(", "\\)")):
        text = text.replace(opener, "").replace(closer, "")

    text = re.sub(r"\\left\s*|\\right\s*", "", text)
    text = re.sub(r"\\(?:big|Big|bigg|Bigg)[lrm]?\s*", "", text)
    text = re.sub(r"\\(?:displaystyle|textstyle|scriptstyle)\s*", "", text)

    text = _wrappers(text)
    text = _environments(text)
    text = _fractions(text)
    text = _roots(text)
    text = _symbols(text)
    text = _scripts(text)

    text = text.replace("\\\\", "\n")
    text = re.sub(r"\\[,;:! ]", " ", text)
    text = text.replace("{,}", ",").replace("{.}", ".")
    for escaped, plain in (
        ("\\{", "{"), ("\\}", "}"), ("\\%", "%"), ("\\&", "&"),
        ("\\#", "#"), ("\\$", "$"), ("\\_", "_"),
    ):
        text = text.replace(escaped, plain)
    text = re.sub(r"\\[A-Za-z]+\s*", "", text)

    text = _markdown(text)
    text = _sections(text)

    text = text.replace("\t", "    ")
    text = re.sub(r"[ \t]+([,.;:!?])", r"\1", text)
    text = re.sub(r"(?<=\S)[ \t]{2,}", " ", text)
    text = re.sub(r"\n[ \t]+\n", "\n\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip()


# --------------------------------------------------------------------------- HTML-оформление
# Пользователь просил «как на gdz.ru»: заголовки, шаги и формулы не сливаются
# в один абзац. Telegram умеет HTML, поэтому решение отдаём блоками:
# <b> заголовок, <blockquote> условие/ответ, <code> формулы, <pre> столбики.
_SECTION_RE = re.compile(
    r"^\s*(?:(?P<emoji>[📌🧮✅])\s*)?"
    r"(?P<title>Условие|Решение|Ответ|Task|Solution|Answer|Condition)\s*:?\s*"
    r"(?P<rest>.*)$",
    re.IGNORECASE,
)
_EMOJI = {
    "условие": "📌", "task": "📌", "condition": "📌",
    "решение": "🧮", "solution": "🧮",
    "ответ": "✅", "answer": "✅",
}
_STEP_RE = re.compile(r"^(?:Шаг|Step)?\s*(\d{1,2})\s*[).:]\s*(.+)$", re.IGNORECASE)
_COLUMN_CHARS = set("0123456789 +-−×÷=.,:;/\\|()[]<>%√²³⁴⁵⁶⁷⁸⁹⁰")


def _section(line: str) -> tuple[str, str, str] | None:
    match = _SECTION_RE.match(line)
    if not match:
        return None
    title = match.group("title")
    key = title.lower()
    emoji = match.group("emoji") or _EMOJI[key]
    nice = title.capitalize() if title.isascii() else title
    return emoji, nice, match.group("rest").strip()


def _looks_like_formula(line: str) -> bool:
    if len(line) > 200:
        return False
    if not re.search(r"[=<>≤≥≠≈∈∉→]", line):
        return False
    return bool(re.search(r"[0-9A-Za-zА-Яа-яЁё]", line))


def _looks_like_column(line: str) -> bool:
    if not re.search(r"\d", line):
        return False
    if any(char.isalpha() for char in line):
        return False
    return all(char in _COLUMN_CHARS for char in line)


def _render_section_body(lines: list[str]) -> str:
    from html import escape

    out: list[str] = []
    column: list[str] = []

    def flush_column() -> None:
        if column:
            out.append("<pre>" + "\n".join(column) + "</pre>")
            column.clear()

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            flush_column()
            out.append("")
            continue
        step = _STEP_RE.match(stripped)
        if step:
            flush_column()
            out.append(f"<b>Шаг {step.group(1)}.</b> {escape(step.group(2).strip())}")
            continue
        if _looks_like_column(stripped):
            column.append(escape(line))
            continue
        flush_column()
        if _looks_like_formula(stripped):
            out.append(f"<code>{escape(stripped)}</code>")
        else:
            out.append(escape(line))
    flush_column()

    body = "\n".join(out)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def to_telegram_html(text: str, *, code: bool = False) -> str:
    """Превращает готовый текстовый ответ в аккуратные HTML-блоки Telegram."""
    if code:
        return to_code_html(text)
    from html import escape

    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    sections: list[tuple[tuple[str, str, str] | None, list[str]]] = []
    header: tuple[str, str, str] | None = None
    lines: list[str] = []
    for line in text.split("\n"):
        found = _section(line)
        if found is not None:
            if header is not None or any(item.strip() for item in lines):
                sections.append((header, lines))
            header, lines = found, []
        else:
            lines.append(line)
    sections.append((header, lines))

    parts: list[str] = []
    for head, body_lines in sections:
        body = _render_section_body(body_lines)
        if head is None:
            if body:
                parts.append(body)
            continue
        emoji, title, rest = head
        if rest:
            body = escape(rest) + (f"\n{body}" if body else "")
        parts.append(f"<b>{emoji} {escape(title)}</b>")
        if not body:
            continue
        if title.lower().rstrip(":") in {"ответ", "answer"}:
            plain = re.sub(r"</?(?:b|code|pre|i|u|s)>", "", body)
            parts.append(f"<blockquote><b>{plain}</b></blockquote>")
        elif title.lower() in {"условие", "task", "condition"}:
            parts.append(f"<blockquote>{body}</blockquote>")
        else:
            parts.append(body)

    result = "\n\n".join(part for part in parts if part.strip())
    return re.sub(r"\n{3,}", "\n\n", result).strip()


# ```язык ... ``` — блок кода в кодерском стиле.
_CODE_FENCE_RE = re.compile(r"```[ \t]*([A-Za-z0-9_+.-]*)[ \t]*\n(.*?)```", re.S)


def to_code_html(text: str) -> str:
    """HTML для кодерского стиля: код уходит в <pre>, текст — обычными блоками."""
    from html import escape

    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    if "```" not in text:
        # Модель не использовала заборы — не рискуем разметкой, отдаём как есть.
        return escape(text)

    parts: list[str] = []
    position = 0
    for match in _CODE_FENCE_RE.finditer(text):
        before = text[position : match.start()].strip()
        if before:
            parts.append(to_telegram_html(before))
        block = match.group(2).strip("\n")
        if block:
            parts.append("<pre>" + escape(block) + "</pre>")
        position = match.end()
    tail = text[position:].strip()
    if tail:
        parts.append(to_telegram_html(tail))
    return "\n\n".join(part for part in parts if part.strip())


# Код длиннее этого числа строк уходит файлом, а не сообщением.
CODE_FILE_MIN_LINES = 100


def split_big_code(
    text: str, min_lines: int = CODE_FILE_MIN_LINES
) -> tuple[str, list[tuple[str, str]]]:
    """Делит ответ на текст и большие блоки кода.

    Возвращает (текст без больших блоков, [(язык, код), ...]). Блок считается
    большим, если в нём больше min_lines строк.
    """
    source = text or ""
    blocks: list[tuple[str, str]] = []
    parts: list[str] = []
    position = 0
    for match in _CODE_FENCE_RE.finditer(source):
        code = match.group(2).strip("\n")
        if len(code.splitlines()) > min_lines:
            parts.append(source[position : match.start()])
            blocks.append((match.group(1).lower(), code))
            position = match.end()
    if not blocks:
        return source, []
    parts.append(source[position:])
    rest = "\n\n".join(part.strip() for part in parts if part.strip())
    return rest, blocks