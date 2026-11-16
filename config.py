"""Конфигурация бота: всё читается из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SYSTEM_PROMPT = (
    "Ты терпеливый и дружелюбный репетитор для участников сообщества. "
    "Отвечай кратко и по делу, без воды и вступлений. "
    "Язык ответа — язык задания: русский вопрос — русский ответ, английское "
    "упражнение — разбор и ответ на английском, украинское или белорусское — на нём. "
    "Если это учебное задание — пиши в таком виде: «📌 Условие:» (что дано и что "
    "найти), затем «🧮 Решение:» с шагами «1)», «2)», «3)» — по одному действию "
    "на строку с коротким пояснением, затем «✅ Ответ:» одной строкой. "
    "Условие с фото переписывай точно, не заменяй слова похожими. "
    "Математику записывай обычными символами (×, ÷, √, ≤, x², 1/2), без LaTeX и "
    "markdown. Не показывай ход рассуждений и черновики. Если данных не хватает — "
    "скажи, чего именно не хватает. Если не уверен — честно признай вместо выдумывания."
)

# Прозвища, на которые бот отзывается в группе (через запятую).
DEFAULT_ALIASES = "gazyava,газява,газик,газировка,газяваgpt,газикgpt"
# Команды, которые в группах молчат: их место — только в личке.
DEFAULT_PRIVATE_ONLY_COMMANDS = "buy,terms,paysupport,check,style,lang,tickets,me"

COARENA_MODELS = (
    "deepseek-v4-1-flash-1017,gemini-3-8-flash,gemini-4-argon,gemini-4-carbon,"
    "gpt-6-1-sol,gpt-6-1-terra,gpt-6-astra,gpt-6-luna,grok-4-7,kimi-k3-1-pro"
)

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
    "openrouter": "openrouter/free",
    "coarena": "deepseek-v4-1-flash-1017",
    "reformboss": "gpt-4o-mini",
}

DEFAULT_VISION_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
    "openrouter": "openrouter/free",
    "coarena": "gemini-3-8-flash",
    "reformboss": "gpt-4o-mini",
}

DEFAULT_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "coarena": "https://coarena.ai/api/v1",
    "reformboss": "https://api.reformboss.com/v1",
}


DEFAULT_WELCOME = (
    "👋 Привет, {name}! Добро пожаловать в чат.\n\n"
    "Я <b>{bot}</b> — ИИ-помощник: отвечаю на вопросы, решаю домашки по фото "
    "и проверяю твоё решение.\n\n"
    "Как пользоваться:\n"
    "• напиши вопрос — отвечу;\n"
    "• пришли фото задания — разберу;\n"
    "• <code>/ai вопрос</code> — обратиться явно;\n"
    "• <code>/style</code> — учебный или кодерский режим;\n"
    "• <code>/rules</code> — правила чата."
)

DEFAULT_RULES = (
    "<b>Правила чата</b>\n"
    "1. Уважение: без оскорблений, травли и переходов на личности.\n"
    "2. Без спама, рекламы и сторонних ссылок без разрешения админа.\n"
    "3. Домашку спрашивай у меня через <code>/ai</code> или фото — не засоряй чат "
    "одинаковыми сообщениями.\n"
    "4. Не публикуй чужие личные данные и скриншоты переписок.\n"
    "5. Флуд и капс → мут на {mute} минут.\n\n"
    "Нарушения — бан без предупреждения."
)

# Пары «сколько запросов : сколько звёзд». Меняются из /admin без рестарта.
DEFAULT_STAR_PACKAGES = ((50, 3), (150, 8), (300, 14))
# Курс для любой суммы: сколько запросов даём за 1 звезду.
DEFAULT_STAR_RATE = 10
# Канал, подписка на который обязательна. Пусто — проверка выключена.
DEFAULT_REQUIRED_CHANNEL = "gazyavaGPT"
DEFAULT_REQUIRED_CHANNEL_URL = "https://t.me/gazyavaGPT"

DEFAULT_TERMS = (
    "<b>Условия покупки</b>\n\n"
    "• Вы покупаете дополнительные запросы к ИИ-помощнику {bot}.\n"
    "• Если для бота включена обязательная подписка, нужно вступить в указанный канал.\n"
    "• Запросы не сгорают и тратятся после дневного бесплатного лимита.\n"
    "• Оплата — Telegram Stars. Возврат на карту невозможен: Telegram не проводит "
    "такие платежи за цифровые товары.\n"
    "• Курс: <b>1 ⭐ = {rate} запросов</b>. Наборы выгоднее курса.\n"
    "• Если запросы не начислились или покупка была по ошибке — напишите "
    "/paysupport, вернём звёзды.\n\n"
    "Оплачивая, вы соглашаетесь с этими условиями."
)

DEFAULT_SUPPORT = (
    "<b>Поддержка по оплате</b>\n\n"
    "Если оплата прошла, а запросы не начислились, или вы хотите вернуть звёзды — "
    "напишите администратору{contact}.\n\n"
    "В сообщении укажите: ваш ID, дату покупки и сколько звёзд списалось. "
    "Возврат делается через Telegram и возможен, пока платёж не удалён."
)


def parse_packages(raw: str, default: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    """Разбирает строку вида «50:3,150:8,300:14»."""
    if not raw or not raw.strip():
        return default
    result: list[tuple[int, int]] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.replace("=", ":").split(":")
        if len(parts) != 2:
            raise ValueError(f"ожидалось «запросы:звёзды», а получено {chunk!r}")
        requests, stars = (int(part.strip()) for part in parts)
        if requests <= 0 or stars <= 0:
            raise ValueError(f"значения должны быть больше нуля: {chunk!r}")
        result.append((requests, stars))
    if not result:
        raise ValueError("пустой список пакетов")
    return tuple(sorted(result))


def packages_to_text(packages: tuple[tuple[int, int], ...]) -> str:
    return ",".join(f"{requests}:{stars}" for requests, stars in packages)


@dataclass
class Settings:
    bot_token: str
    webhook_secret: str = "change-me"
    base_url: str = ""
    port: int = 8080

    database_url: str = ""

    ai_provider: str = "gemini"
    ai_model: str = ""
    ai_vision_model: str = ""
    ai_models: tuple[str, ...] = ()
    ai_vision_models: tuple[str, ...] = ()
    ai_model_rotate: bool = True
    ai_fallback_provider: str = ""
    ai_api_key: str = ""
    ai_base_url: str = ""
    bot_name: str = "gazyavaGPT"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    daily_limit: int = 30
    max_context: int = 12
    admin_ids: frozenset[int] = field(default_factory=frozenset)
    owner_id: int = 0

    welcome_text: str = DEFAULT_WELCOME
    rules_text: str = DEFAULT_RULES
    flood_limit: int = 8
    flood_window: int = 10
    mute_minutes: int = 10

    payments_enabled: bool = True
    star_packages: tuple[tuple[int, int], ...] = DEFAULT_STAR_PACKAGES
    star_rate: int = DEFAULT_STAR_RATE
    required_channel: str = DEFAULT_REQUIRED_CHANNEL
    required_channel_url: str = DEFAULT_REQUIRED_CHANNEL_URL
    terms_text: str = DEFAULT_TERMS
    support_text: str = DEFAULT_SUPPORT
    support_contact: str = ""

    default_lang: str = "ru"
    aliases: tuple[str, ...] = ()
    private_only_commands: frozenset[str] = frozenset()

    antispam_enabled: bool = True
    antispam_links: bool = True
    antispam_mentions: int = 5
    antispam_duplicates: bool = True
    antispam_caps: bool = True
    antispam_action: str = "mute"
    strike_limit: int = 3
    strike_window: int = 3600

    image_provider: str = "pollinations"
    image_model: str = "flux"
    image_size: int = 1024
    image_api_key: str = ""
    image_base_url: str = ""
    image_fallback: str = "pollinations"

    file_max_mb: int = 10
    file_max_chars: int = 20000
    file_max_pdf_pages: int = 60

    @property
    def use_webhook(self) -> bool:
        return bool(self.base_url)

    @property
    def unlimited(self) -> bool:
        """daily_limit <= 0 означает «без ограничений»."""
        return self.daily_limit <= 0


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} должен быть целым числом, а получено: {raw!r}") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw not in {"0", "false", "no", "off", "нет"}


def _packages_env(name: str, default: tuple[tuple[int, int], ...]) -> tuple[tuple[int, int], ...]:
    try:
        return parse_packages(os.getenv(name, ""), default)
    except ValueError as exc:
        raise SystemExit(f"{name}: {exc}. Пример: 50:3,150:8,300:14") from exc


def _parse_admin_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for chunk in raw.replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if chunk.isdigit():
            ids.add(int(chunk))
        elif chunk:
            raise SystemExit(f"ADMIN_IDS: {chunk!r} не похоже на Telegram ID (только цифры)")
    return frozenset(ids)


def _owner_id(raw: str) -> int:
    raw = raw.strip()
    if not raw:
        return 0
    if not raw.isdigit():
        raise SystemExit(f"OWNER_ID: {raw!r} не похоже на Telegram ID (только цифры)")
    return int(raw)


def _list_env(name: str, default: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip() or default
    items = [chunk.strip() for chunk in raw.replace(";", ",").split(",")]
    return tuple(item for item in items if item)


def _commands_env(name: str, default: str) -> frozenset[str]:
    return frozenset(item.lstrip("/").lower() for item in _list_env(name, default))


def _action_env(name: str, default: str) -> str:
    raw = os.getenv(name, "").strip().lower()
    return raw if raw in {"delete", "mute", "kick", "ban"} else default


def _load_dotenv(path: Path | None = None) -> None:
    """Читает .env рядом с проектом. Переменные из окружения имеют приоритет."""
    env_path = path or Path(".env")
    if not env_path.is_file():
        return
    raw_bytes = env_path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Блокнот/PowerShell на русской Windows любят сохранять в cp1251
        text = raw_bytes.decode("cp1251", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _provider_key(provider: str) -> str:
    """Ключ провайдера: сначала <PROVIDER>_API_KEY, затем общий AI_API_KEY."""
    specific = os.getenv(f"{provider.upper()}_API_KEY", "").strip()
    return specific or os.getenv("AI_API_KEY", "").strip()


def load_settings() -> Settings:
    _load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "BOT_TOKEN не задан. Добавьте переменную окружения BOT_TOKEN "
            "(Render -> Environment, либо .env локально)."
        )

    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    if provider not in DEFAULT_MODELS:
        raise SystemExit(
            f"AI_PROVIDER={provider!r} не поддерживается. "
            f"Допустимо: {', '.join(sorted(DEFAULT_MODELS))}"
        )
    image_provider = (os.getenv("IMAGE_PROVIDER", "").strip() or "pollinations").lower()

    return Settings(
        bot_token=token,
        webhook_secret=os.getenv("WEBHOOK_SECRET", "change-me").strip() or "change-me",
        base_url=(os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL") or "").rstrip("/"),
        port=_int_env("PORT", 8080),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        ai_provider=provider,
        ai_model=(os.getenv("AI_MODEL", "").strip() or DEFAULT_MODELS[provider]),
        ai_vision_model=(
            os.getenv("AI_VISION_MODEL", "").strip() or DEFAULT_VISION_MODELS[provider]
        ),
        ai_models=_list_env("AI_MODELS", ""),
        ai_vision_models=_list_env("AI_VISION_MODELS", ""),
        ai_model_rotate=_bool_env("AI_MODEL_ROTATE", True),
        ai_fallback_provider=(os.getenv("AI_FALLBACK_PROVIDER", "").strip().lower()),
        ai_api_key=_provider_key(provider),
        ai_base_url=(os.getenv("AI_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URLS[provider]),
        bot_name=os.getenv("BOT_NAME", "").strip() or "gazyavaGPT",
        system_prompt=os.getenv("AI_SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT,
        daily_limit=_int_env("DAILY_LIMIT", 30),
        max_context=_int_env("MAX_CONTEXT", 12),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        owner_id=_owner_id(os.getenv("OWNER_ID", "")),
        welcome_text=os.getenv("WELCOME_TEXT", "").strip() or DEFAULT_WELCOME,
        rules_text=os.getenv("RULES_TEXT", "").strip() or DEFAULT_RULES,
        flood_limit=_int_env("FLOOD_LIMIT", 8),
        flood_window=_int_env("FLOOD_WINDOW", 10),
        mute_minutes=_int_env("MUTE_MINUTES", 10),
        payments_enabled=_bool_env("PAYMENTS_ENABLED", True),
        star_packages=_packages_env("STAR_PACKAGES", DEFAULT_STAR_PACKAGES),
        star_rate=_int_env("STAR_RATE", DEFAULT_STAR_RATE),
        required_channel=os.getenv("REQUIRED_CHANNEL", "").strip()
        or DEFAULT_REQUIRED_CHANNEL,
        required_channel_url=os.getenv("REQUIRED_CHANNEL_URL", "").strip()
        or DEFAULT_REQUIRED_CHANNEL_URL,
        terms_text=os.getenv("TERMS_TEXT", "").strip() or DEFAULT_TERMS,
        support_text=os.getenv("PAY_SUPPORT_TEXT", "").strip() or DEFAULT_SUPPORT,
        support_contact=os.getenv("PAY_SUPPORT_CONTACT", "").strip(),
        default_lang=(os.getenv("DEFAULT_LANG", "").strip() or "ru").lower(),
        aliases=_list_env("BOT_ALIASES", DEFAULT_ALIASES),
        private_only_commands=_commands_env(
            "GROUP_DISABLED_COMMANDS", DEFAULT_PRIVATE_ONLY_COMMANDS
        ),
        antispam_enabled=_bool_env("ANTISPAM_ENABLED", True),
        antispam_links=_bool_env("ANTISPAM_LINKS", True),
        antispam_mentions=_int_env("ANTISPAM_MENTIONS", 5),
        antispam_duplicates=_bool_env("ANTISPAM_DUPLICATES", True),
        antispam_caps=_bool_env("ANTISPAM_CAPS", True),
        antispam_action=_action_env("ANTISPAM_ACTION", "mute"),
        strike_limit=_int_env("STRIKE_LIMIT", 3),
        strike_window=_int_env("STRIKE_WINDOW", 3600),
        image_provider=image_provider,
        image_model=(os.getenv("IMAGE_MODEL", "").strip() or "flux"),
        image_size=_int_env("IMAGE_SIZE", 1024),
        image_api_key=(
            os.getenv("IMAGE_API_KEY", "").strip() or _provider_key(image_provider)
        ),
        image_base_url=(os.getenv("IMAGE_BASE_URL", "").strip().rstrip("/")),
        image_fallback=(os.getenv("IMAGE_FALLBACK", "").strip() or "pollinations").lower(),
        file_max_mb=max(1, _int_env("FILE_MAX_MB", 10)),
        file_max_chars=max(2000, _int_env("FILE_MAX_CHARS", 20000)),
        file_max_pdf_pages=max(1, _int_env("FILE_MAX_PDF_PAGES", 60)),
    )