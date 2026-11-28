"""Конфигурация бота: всё читается из переменных окружения."""

from __future__ import annotations

import os
import re
import secrets
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

# Некоторые шлюзы (CrowLLM, 100MilionSeek) стоят за Cloudflare, который режет
# запросы без браузерного User-Agent ошибкой 1010 «Access denied».
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Прозвища, на которые бот отзывается в группе (через запятую).
DEFAULT_ALIASES = "gazyava,газява,газик,газировка,газяваgpt,газикgpt"
# Команды, которые в группах молчат: их место — только в личке.
DEFAULT_PRIVATE_ONLY_COMMANDS = "buy,terms,paysupport,check,style,lang,tickets,me,season,voice"

COARENA_MODELS = (
    "deepseek-v4-1-flash-1017,gemini-3-8-flash,gemini-4-argon,gemini-4-carbon,"
    "gpt-6-1-sol,gpt-6-1-terra,gpt-6-astra,gpt-6-luna,grok-4-7,kimi-k3-1-pro"
)

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
    "openrouter": "openrouter/free",
    "coarena": "deepseek-v4-1-flash-1017",
    "reformboss": "deepseek-v4.1-flash",
    "crowllm": "glm-4.7-flash:free",
    "unleashedapi": "deepseek-v4.1-flash-fast",
    "milionseek": "deepseek-v4.1-flash-free",
}

DEFAULT_VISION_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
    "openrouter": "openrouter/free",
    "coarena": "gemini-3-8-flash",
    "reformboss": "deepseek-v4.1-flash",
    "crowllm": "nemotron-3.5-super-vl:free",
    "unleashedapi": "deepseek-v4.1-flash-fast",
    "milionseek": "deepseek-v4.1-flash-free",
}

DEFAULT_BASE_URLS = {
    "gemini": "https://generativelanguage.googleapis.com",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "coarena": "https://coarena.ai/api/v1",
    "reformboss": "https://api.reformboss.com/v1",
    # Шлюзы, совместимые с [OI] API (/chat/completions и /models).
    "crowllm": "https://crowllm.com/v1",
    "unleashedapi": "https://api.unleashedapi.com/v1",
    "milionseek": "https://100milionseek.top/v1",
}

# Названия для админки: по ним владелец выбирает провайдера кнопкой.
PROVIDER_LABELS = {
    "gemini": "Google Gemini",
    "openai": "[OI]",
    "openrouter": "OpenRouter",
    "coarena": "Coarena",
    "reformboss": "ReformBoss",
    "crowllm": "CrowLLM",
    "unleashedapi": "UnleashedAPI",
    "milionseek": "100MilionSeek",
}

# Шлюзы, у которых список моделей приходит из /models: имя «auto» означает
# «взять каталог у провайдера и ротировать модели».
GATEWAY_PROVIDERS = frozenset({"coarena", "reformboss", "crowllm", "unleashedapi", "milionseek"})

# Резерв по умолчанию, если AI_FALLBACK_PROVIDER не задан вовсе.
# OpenRouter доступен из большинства стран и даёт бесплатные модели.
DEFAULT_FALLBACK_PROVIDER = "openrouter"

# Ключи OpenRouter всегда начинаются с этого префикса: по нему видно, что
# общий AI_API_KEY — именно ключ OpenRouter, а не чужого шлюза.
OPENROUTER_KEY_PREFIX = "sk-or-"


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
    "5. Флуд и капс → мут на {mute} минут.\n"
    "6. Мат, оскорбления и спам-ссылки удаляются, за повтор — бан.\n\n"
    "Нарушения — бан без предупреждения."
)

# Корни мата для «антимата». Ищем подстрокой в нормализованном тексте
# (без пробелов, пунктуации и leet-подстановок), поэтому хватает корней.
DEFAULT_ANTIMAT_WORDS = (
    "хуй",
    "хуя",
    "хуе",
    "хуи",
    "пизд",
    "бляд",
    "блят",
    "ебал",
    "ебет",
    "ебут",
    "ебан",
    "ебат",
    "заеб",
    "наеб",
    "уеб",
    "отъеб",
    "долбоеб",
    "пидор",
    "пидар",
    "мудак",
    "мудил",
    "гандон",
    "шлюх",
)

# Пары «сколько запросов : сколько звёзд». Меняются из /admin без рестарта.
DEFAULT_STAR_PACKAGES = ((50, 3), (150, 8), (300, 14))
# Курс для любой суммы: сколько запросов даём за 1 звезду.
DEFAULT_STAR_RATE = 10
# Поддержка автора токеном GRAM (jetton в сети TON). Это донат: запросы
# за него не начисляются, проверка платежа не нужна — только адрес кошелька.
DEFAULT_SUPPORT_WALLET = "UQCgQE6jXUmdJh_AtN5CNQH9eBIwIeQG370ylpYymQ9vDjLF"
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
    # Молча добавлять в конец резерва всех провайдеров со своим ключом.
    ai_auto_fallback: bool = True
    ai_api_key: str = ""
    ai_base_url: str = ""
    # Сколько токенов разрешаем модели в одном ответе и сколько раз просим
    # продолжить, если ответ оборвался на лимите (для больших листингов кода).
    ai_max_tokens: int = 8000
    ai_continue_rounds: int = 2
    bot_name: str = "gazyavaGPT"
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    debug_command_secret: str = ""

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
    # Поддержка автора: адрес кошелька для GRAM. Пусто — карточка скрыта.
    support_wallet: str = DEFAULT_SUPPORT_WALLET
    required_channel: str = DEFAULT_REQUIRED_CHANNEL
    required_channel_url: str = DEFAULT_REQUIRED_CHANNEL_URL
    group_gate_enabled: bool = True
    autopost_enabled: bool = True
    autopost_channel: str = ""
    autopost_hour: int = 9
    autopost_kind: str = "mix"
    bonus_base: int = 3
    bonus_max: int = 10
    invite_reward: int = 5
    invited_reward: int = 3
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
    antimat_enabled: bool = True
    antimat_words: tuple[str, ...] = DEFAULT_ANTIMAT_WORDS

    # Капча для новых участников: кнопка, мут до проверки, кик по таймауту.
    captcha_enabled: bool = True
    captcha_timeout: int = 180

    # Анти-рейд: всплеск входов закрывает чат и режет новичков.
    raid_enabled: bool = True
    raid_threshold: int = 10
    raid_window: int = 60
    raid_lock_minutes: int = 15
    raid_kick_new: bool = True

    # Алерты админам: ошибки ИИ, вебхука, БД и анти-рейд.
    alerts_enabled: bool = True
    alert_chat_id: int = 0
    alert_cooldown: int = 600

    # Голос: распознавание речи (STT) и озвучка ответов (TTS).
    voice_enabled: bool = True
    tts_enabled: bool = True
    stt_api_key: str = ""
    stt_base_url: str = "https://api.openai.com/v1"
    stt_model: str = "whisper-1"

    image_provider: str = "pollinations"
    image_model: str = "flux"
    image_models: tuple[str, ...] = ()
    image_size: int = 1024
    image_api_key: str = ""
    image_base_url: str = ""
    image_fallback: str = "pollinations"
    image_daily_limit: int = 1

    file_max_mb: int = 20
    file_max_chars: int = 20000
    file_max_pdf_pages: int = 60

    @property
    def use_webhook(self) -> bool:
        return bool(self.base_url)

    @property
    def unlimited(self) -> bool:
        """daily_limit <= 0 означает «без ограничений»."""
        return self.daily_limit <= 0

    @property
    def support_ready(self) -> bool:
        """Карточка «Поддержать автора» видна, только если задан адрес."""
        return bool(self.support_wallet)


def _int_env(
    name: str,
    default: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError as exc:
            raise SystemExit(f"{name} должен быть целым числом, а получено: {raw!r}") from exc
    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


_TRUE_VALUES = {"1", "true", "yes", "on", "y", "t", "да", "так"}
_FALSE_VALUES = {"0", "false", "no", "off", "n", "f", "нет", "не"}


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE_VALUES:
        return True
    if raw in _FALSE_VALUES:
        return False
    # Опечатка не должна молча включать платежи или антиспам.
    return default


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
        if line.lower().startswith("export "):
            line = line[len("export ") :].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'}:
            quote = value[0]
            end = value.find(quote, 1)
            value = value[1:end] if end != -1 else value[1:]
        else:
            # Конец строки после « #» — комментарий (как в python-dotenv).
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _provider_key(provider: str) -> str:
    """Ключ провайдера: сначала <PROVIDER>_API_KEY, затем общий AI_API_KEY."""
    specific = os.getenv(f"{provider.upper()}_API_KEY", "").strip()
    return specific or os.getenv("AI_API_KEY", "").strip()


def _specific_provider_key(provider: str) -> str:
    """Только собственный ключ провайдера, без общего AI_API_KEY.

    Нужно там, где общий ключ чужой: у каждого шлюза свой адрес, и ключ
    ReformBoss на api.crowllm.com — это гарантированный 401.
    """
    return os.getenv(f"{provider.upper()}_API_KEY", "").strip()


def provider_effective_key(provider: str, main_provider: str = "") -> str:
    """Ключ, который реально подойдёт провайдеру.

    Свой <PROVIDER>_API_KEY главнее. Общий AI_API_KEY отдаём только тому, кому
    он принадлежит: основному провайдеру, OpenRouter (по префиксу sk-or-) или
    провайдеру с тем же адресом API. Иначе ключ одного шлюза уедет на чужой
    хост и вернёт 401.
    """
    specific = _specific_provider_key(provider)
    if specific:
        return specific
    main = (main_provider or os.getenv("AI_PROVIDER", "")).strip().lower()
    common = os.getenv("AI_API_KEY", "").strip()
    if not common:
        return ""
    if provider == main:
        return common
    if provider == "openrouter" and common.startswith(OPENROUTER_KEY_PREFIX):
        return common
    own_base = (_provider_base(provider) or "").rstrip("/")
    main_base = (_provider_base(main) or "").rstrip("/")
    return common if own_base and own_base == main_base else ""


def provider_key_state(provider: str) -> str:
    """Откуда возьмётся ключ провайдера: свой, общий AI_API_KEY или никакого."""
    if _specific_provider_key(provider):
        return "свой ключ"
    if provider_effective_key(provider):
        return "общий AI_API_KEY"
    return "нет ключа"


def _provider_base(provider: str) -> str:
    """Адрес API провайдера: <PROVIDER>_BASE_URL, затем AI_BASE_URL, затем стандарт."""
    specific = os.getenv(f"{provider.upper()}_BASE_URL", "").strip().rstrip("/")
    if specific:
        return specific
    common = os.getenv("AI_BASE_URL", "").strip().rstrip("/")
    if common and provider == os.getenv("AI_PROVIDER", "").strip().lower():
        return common
    return DEFAULT_BASE_URLS.get(provider, "")


def normalize_providers(raw: str) -> tuple[str, ...]:
    """Разбирает список провайдеров через запятую/точку с запятой.

    Неизвестные имена отбрасываются, повторы схлопываются: так строка из
    админки не сможет уронить запуск бота.
    """
    result: list[str] = []
    for chunk in (raw or "").replace(";", ",").split(","):
        name = chunk.strip().lower()
        if name in DEFAULT_MODELS and name not in result:
            result.append(name)
    return tuple(result)


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

    base_url = (
        os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL") or ""
    ).rstrip("/")
    webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
    if base_url and (not webhook_secret or webhook_secret == "change-me" or len(webhook_secret) < 16):
        # Без секрета webhook принимает поддельные апдейты (владелец/платежи).
        # Генерируем на запуск: set_webhook идёт с тем же значением в процессе.
        webhook_secret = secrets.token_urlsafe(32)

    from i18n import normalize_lang

    default_lang = normalize_lang(os.getenv("DEFAULT_LANG", "").strip() or "ru")

    # Ключ картинок наследуем только у того же провайдера: иначе ключ Gemini
    # уедет на api.openai.com.
    image_key = os.getenv("IMAGE_API_KEY", "").strip()
    if not image_key:
        if image_provider == provider:
            image_key = _provider_key(provider)
        elif image_provider == "openrouter":
            image_key = _provider_key("openrouter")

    return Settings(
        bot_token=token,
        webhook_secret=webhook_secret,
        base_url=base_url,
        port=_int_env("PORT", 8080, minimum=1, maximum=65535),
        database_url=os.getenv("DATABASE_URL", "").strip(),
        ai_provider=provider,
        ai_model=(os.getenv("AI_MODEL", "").strip() or DEFAULT_MODELS[provider]),
        ai_vision_model=(
            os.getenv("AI_VISION_MODEL", "").strip() or DEFAULT_VISION_MODELS[provider]
        ),
        ai_models=_list_env("AI_MODELS", ""),
        ai_vision_models=_list_env("AI_VISION_MODELS", ""),
        ai_model_rotate=_bool_env("AI_MODEL_ROTATE", True),
        ai_fallback_provider=",".join(
            normalize_providers(
                # Переменная не задана вовсе -> резерв по умолчанию OpenRouter.
                # Задана пустой -> админ осознанно отключил резерв.
                (
                    os.getenv("AI_FALLBACK_PROVIDER")
                    if os.getenv("AI_FALLBACK_PROVIDER") is not None
                    else DEFAULT_FALLBACK_PROVIDER
                )
                or ""
            )
        ),
        ai_auto_fallback=_bool_env("AI_AUTO_FALLBACK", True),
        ai_api_key=_provider_key(provider),
        ai_base_url=(_provider_base(provider) or DEFAULT_BASE_URLS[provider]),
        ai_max_tokens=_int_env("AI_MAX_TOKENS", 8000, minimum=500, maximum=32000),
        ai_continue_rounds=_int_env("AI_CONTINUE_ROUNDS", 2, minimum=0, maximum=4),
        bot_name=os.getenv("BOT_NAME", "").strip() or "gazyavaGPT",
        system_prompt=os.getenv("AI_SYSTEM_PROMPT", "").strip() or DEFAULT_SYSTEM_PROMPT,
        debug_command_secret=os.getenv("DEBUG_COMMAND_SECRET", "").strip(),
        daily_limit=_int_env("DAILY_LIMIT", 30, minimum=0),
        max_context=_int_env("MAX_CONTEXT", 12, minimum=0),
        admin_ids=_parse_admin_ids(os.getenv("ADMIN_IDS", "")),
        owner_id=_owner_id(os.getenv("OWNER_ID", "")),
        welcome_text=os.getenv("WELCOME_TEXT", "").strip() or DEFAULT_WELCOME,
        rules_text=os.getenv("RULES_TEXT", "").strip() or DEFAULT_RULES,
        flood_limit=_int_env("FLOOD_LIMIT", 8, minimum=0),
        flood_window=_int_env("FLOOD_WINDOW", 10, minimum=1),
        mute_minutes=_int_env("MUTE_MINUTES", 10, minimum=0),
        payments_enabled=_bool_env("PAYMENTS_ENABLED", True),
        star_packages=_packages_env("STAR_PACKAGES", DEFAULT_STAR_PACKAGES),
        star_rate=_int_env("STAR_RATE", DEFAULT_STAR_RATE, minimum=1),
        support_wallet=os.getenv("SUPPORT_WALLET", DEFAULT_SUPPORT_WALLET).strip(),
        required_channel=os.getenv("REQUIRED_CHANNEL", "").strip()
        or DEFAULT_REQUIRED_CHANNEL,
        required_channel_url=os.getenv("REQUIRED_CHANNEL_URL", "").strip()
        or DEFAULT_REQUIRED_CHANNEL_URL,
        group_gate_enabled=_bool_env("GROUP_GATE_ENABLED", True),
        autopost_enabled=_bool_env("AUTOPOST_ENABLED", True),
        autopost_channel=os.getenv("AUTOPOST_CHANNEL", "").strip(),
        autopost_hour=_int_env("AUTOPOST_HOUR", 9, minimum=0, maximum=23),
        autopost_kind=(
            os.getenv("AUTOPOST_KIND", "").strip().lower()
            if os.getenv("AUTOPOST_KIND", "").strip().lower() in {"task", "tip", "mix"}
            else "mix"
        ),
        bonus_base=_int_env("BONUS_BASE", 3, minimum=1, maximum=50),
        bonus_max=_int_env("BONUS_MAX", 10, minimum=1, maximum=100),
        invite_reward=_int_env("INVITE_REWARD", 5, minimum=0, maximum=100),
        invited_reward=_int_env("INVITED_REWARD", 3, minimum=0, maximum=100),
        terms_text=os.getenv("TERMS_TEXT", "").strip() or DEFAULT_TERMS,
        support_text=os.getenv("PAY_SUPPORT_TEXT", "").strip() or DEFAULT_SUPPORT,
        support_contact=os.getenv("PAY_SUPPORT_CONTACT", "").strip(),
        default_lang=default_lang,
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
        antimat_enabled=_bool_env("ANTIMAT_ENABLED", True),
        antimat_words=_list_env("ANTIMAT_WORDS", ",".join(DEFAULT_ANTIMAT_WORDS)),
        captcha_enabled=_bool_env("CAPTCHA_ENABLED", True),
        captcha_timeout=_int_env("CAPTCHA_TIMEOUT", 180, minimum=30, maximum=3600),
        raid_enabled=_bool_env("RAID_ENABLED", True),
        raid_threshold=_int_env("RAID_THRESHOLD", 10, minimum=2, maximum=1000),
        raid_window=_int_env("RAID_WINDOW", 60, minimum=5, maximum=3600),
        raid_lock_minutes=_int_env("RAID_LOCK_MINUTES", 15, minimum=1, maximum=1440),
        raid_kick_new=_bool_env("RAID_KICK_NEW", True),
        alerts_enabled=_bool_env("ALERTS_ENABLED", True),
        alert_chat_id=_int_env("ALERT_CHAT_ID", 0),
        alert_cooldown=_int_env("ALERT_COOLDOWN", 600, minimum=30, maximum=86400),
        voice_enabled=_bool_env("VOICE_ENABLED", True),
        tts_enabled=_bool_env("TTS_ENABLED", True),
        stt_api_key=(
            os.getenv("STT_API_KEY", "").strip()
            or os.getenv("OPENAI_API_KEY", "").strip()
        ),
        stt_base_url=(
            os.getenv("STT_BASE_URL", "").strip().rstrip("/")
            or "https://api.openai.com/v1"
        ),
        stt_model=(os.getenv("STT_MODEL", "").strip() or "whisper-1"),
        image_provider=image_provider,
        image_model=(os.getenv("IMAGE_MODEL", "").strip() or "flux"),
        image_models=_list_env("IMAGE_MODELS", ""),
        image_size=_int_env("IMAGE_SIZE", 1024, minimum=256, maximum=2048),
        image_api_key=image_key,
        image_base_url=(os.getenv("IMAGE_BASE_URL", "").strip().rstrip("/")),
        image_fallback=(os.getenv("IMAGE_FALLBACK", "").strip() or "pollinations").lower(),
        image_daily_limit=max(0, _int_env("IMAGE_DAILY_LIMIT", 1)),
        file_max_mb=max(1, _int_env("FILE_MAX_MB", 20)),
        file_max_chars=max(2000, _int_env("FILE_MAX_CHARS", 20000)),
        file_max_pdf_pages=max(1, _int_env("FILE_MAX_PDF_PAGES", 60)),
    )