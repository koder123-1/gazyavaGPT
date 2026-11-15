"""Локализация интерфейса: русский, украинский, белорусский, английский.

Правило: ответы ИИ идут на языке задания, а интерфейс — на выбранном языке.
Пропущенный ключ автоматически берётся из русского, чтобы бот никогда не молчал.
"""

from __future__ import annotations

import re

LANGS = ("ru", "uk", "be", "en")
LANG_NAMES = {"ru": "Русский", "uk": "Українська", "be": "Беларуская", "en": "English"}
LANG_FLAGS = {"ru": "🇷🇺", "uk": "🇺🇦", "be": "🇧🇾", "en": "🇬🇧"}
LANG_HUMAN = {
    "ru": "русский",
    "uk": "украинский",
    "be": "белорусский",
    "en": "английский",
}

TR: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ общее
    "lang.pick": {
        "ru": "🌍 <b>Выбери язык общения</b>\n\nНа нём будет интерфейс. Ответы на задания бот даёт на языке самого задания.",
        "uk": "🌍 <b>Обери мову спілкування</b>\n\nНею буде інтерфейс. Відповіді на завдання бот дає мовою самого завдання.",
        "be": "🌍 <b>Абяры мову зносін</b>\n\nНа ёй будзе інтэрфейс. Адказы на заданні бот дае мовай самога задання.",
        "en": "🌍 <b>Choose your language</b>\n\nThe interface will use it. Task answers follow the language of the task itself.",
    },
    "lang.saved": {
        "ru": "✅ Язык сохранён: {name}",
        "uk": "✅ Мову збережено: {name}",
        "be": "✅ Мова захавана: {name}",
        "en": "✅ Language saved: {name}",
    },
    "lang.current": {
        "ru": "🌍 Текущий язык: <b>{name}</b>",
        "uk": "🌍 Поточна мова: <b>{name}</b>",
        "be": "🌍 Бягучая мова: <b>{name}</b>",
        "en": "🌍 Current language: <b>{name}</b>",
    },
    "btn.lang": {"ru": "🌍 Язык", "uk": "🌍 Мова", "be": "🌍 Мова", "en": "🌍 Language"},
    "btn.model": {"ru": "🧠 Модель ИИ", "uk": "🧠 Модель ШІ", "be": "🧠 Мадэль ШІ", "en": "🧠 AI model"},
    "model.title": {
        "ru": (
            "🧠 <b>Выбор модели ИИ</b>\n\n"
            "Сейчас отвечает: <b>{current}</b>\n\n"
            "Бесплатная модель доступна всем. Платные открываются один раз за звёзды "
            "и остаются у тебя навсегда — доплат за запросы нет.\n\n"
            "Если модель недоступна, бот сам переключится на запасную. "
            "На фото и картинки это не влияет."
        ),
        "uk": (
            "🧠 <b>Вибір моделі ШІ</b>\n\n"
            "Зараз відповідає: <b>{current}</b>\n\n"
            "Безкоштовна модель доступна всім. Платні відкриваються один раз за зірки "
            "й залишаються у тебе назавжди — доплат за запити немає.\n\n"
            "Якщо модель недоступна, бот сам переключиться на запасну. "
            "На фото й картинки це не впливає."
        ),
        "be": (
            "🧠 <b>Выбар мадэлі ШІ</b>\n\n"
            "Зараз адказвае: <b>{current}</b>\n\n"
            "Бясплатная мадэль даступная ўсім. Платныя адкрываюцца адзін раз за зоркі "
            "і застаюцца ў цябе назаўжды — даплат за запыты няма.\n\n"
            "Калі мадэль недаступная, бот сам пераключыцца на запасную. "
            "На фота і малюнкі гэта не ўплывае."
        ),
        "en": (
            "🧠 <b>Choose an AI model</b>\n\n"
            "Currently answering: <b>{current}</b>\n\n"
            "The free model is available to everyone. Paid models are unlocked once "
            "with Stars and stay yours forever — no per-request charges.\n\n"
            "If a model is unavailable, the bot switches to a backup automatically. "
            "Photos and images are not affected."
        ),
    },
    "model.free": {
        "ru": "бесплатно",
        "uk": "безкоштовно",
        "be": "бясплатна",
        "en": "free",
    },
    "model.price": {
        "ru": "{stars} ⭐",
        "uk": "{stars} ⭐",
        "be": "{stars} ⭐",
        "en": "{stars} ⭐",
    },
    "model.bought": {
        "ru": "✅ Модель {name} открыта!",
        "uk": "✅ Модель {name} відкрито!",
        "be": "✅ Мадэль {name} адкрыта!",
        "en": "✅ Model {name} unlocked!",
    },
    "model.off": {
        "ru": "🔒 открыть за {stars} ⭐",
        "uk": "🔒 відкрити за {stars} ⭐",
        "be": "🔒 адкрыць за {stars} ⭐",
        "en": "🔒 unlock for {stars} ⭐",
    },
    "model.invoice": {
        "ru": "Не смог выставить счёт. Попробуй ещё раз или напиши в /paysupport.",
        "uk": "Не зміг виставити рахунок. Спробуй ще раз або напиши в /paysupport.",
        "be": "Не змог выставіць рахунак. Паспрабуй яшчэ раз або напішы ў /paysupport.",
        "en": "I couldn't create the invoice. Try again or contact /paysupport.",
    },
    "model.not_owned": {
        "ru": "Сначала открой модель за {stars} ⭐",
        "uk": "Спочатку відкрий модель за {stars} ⭐",
        "be": "Спачатку адкрый мадэль за {stars} ⭐",
        "en": "Unlock this model for {stars} ⭐ first",
    },
    "model.buy_disabled": {
        "ru": "Оплата сейчас отключена — открой модель позже.",
        "uk": "Оплата зараз вимкнена — відкрий модель пізніше.",
        "be": "Аплата зараз выключана — адкрый мадэль пазней.",
        "en": "Payments are disabled right now — unlock the model later.",
    },
    "model.auto": {
        "ru": "🔄 Как у всех (по умолчанию)",
        "uk": "🔄 Як у ўсіх (за замаўчаннем)",
        "be": "🔄 Як у ўсіх (па змаўчанні)",
        "en": "🔄 Default",
    },
    "model.saved": {
        "ru": "✅ Модель: {name}",
        "uk": "✅ Модель: {name}",
        "be": "✅ Мадэль: {name}",
        "en": "✅ Model: {name}",
    },
    "model.stale": {
        "ru": "Список моделей изменился — открой /model заново",
        "uk": "Список моделей змінився — відкрий /model заново",
        "be": "Спіс мадэляў змяніўся — адкрый /model зноў",
        "en": "The model list changed — open /model again",
    },
    "btn.back": {"ru": "⬅️ Назад", "uk": "⬅️ Назад", "be": "⬅️ Назад", "en": "⬅️ Back"},
    "btn.buy": {
        "ru": "⭐ Запросы и подписка",
        "uk": "⭐ Запити й підписка",
        "be": "⭐ Запыты і падпіска",
        "en": "⭐ Requests & plans",
    },
    "btn.support": {
        "ru": "🆘 Поддержка",
        "uk": "🆘 Підтримка",
        "be": "🆘 Падтрымка",
        "en": "🆘 Support",
    },
    "btn.tickets": {
        "ru": "🎫 Тикеты",
        "uk": "🎫 Тікети",
        "be": "🎫 Тыкеты",
        "en": "🎫 Tickets",
    },
    "btn.menu": {"ru": "⬅️ В меню", "uk": "⬅️ У меню", "be": "⬅️ У меню", "en": "⬅️ Menu"},
    "btn.profile": {"ru": "🎓 Профиль", "uk": "🎓 Профіль", "be": "🎓 Профіль", "en": "🎓 Profile"},
    "btn.simple": {"ru": "🧩 Проще", "uk": "🧩 Простіше", "be": "🧩 Прасьцей", "en": "🧩 Simpler"},
    "btn.deep": {
        "ru": "📚 Подробнее",
        "uk": "📚 Докладніше",
        "be": "📚 Падрабязней",
        "en": "📚 More detail",
    },
    "btn.check": {
        "ru": "✅ Проверить моё решение",
        "uk": "✅ Перевірити моє рішення",
        "be": "✅ Праверыць маё рашэнне",
        "en": "✅ Check my solution",
    },
    "btn.practice": {
        "ru": "🧠 Похожая задача",
        "uk": "🧠 Схожа задача",
        "be": "🧠 Падобнае заданне",
        "en": "🧠 Similar task",
    },
    "btn.thanks_up": {"ru": "👍 Спасибо!", "uk": "👍 Дякую!", "be": "👍 Дзякуй!", "en": "👍 Thanks!"},
    "btn.thanks_down": {"ru": "👎 Учту", "uk": "👎 Враху́ю", "be": "👎 Улічу", "en": "👎 Noted"},
    "fb.saved_up": {
        "ru": "Спасибо! Стало понятнее 👍",
        "uk": "Дякую! Стало зрозуміліше 👍",
        "be": "Дзякуй! Стала зразумела 👍",
        "en": "Thanks! Glad it helped 👍",
    },
    "fb.saved_down": {
        "ru": "Понял, буду лучше 👎",
        "uk": "Зрозумів, буду краще 👎",
        "be": "Зразумеў, буду лепш 👎",
        "en": "Got it, I'll do better 👎",
    },
    "fb.already": {"ru": "Уже учтено 🙂", "uk": "Уже враховано 🙂", "be": "Ужо ўлічана 🙂", "en": "Already noted 🙂"},
    "fb.not_yours": {
        "ru": "Кнопка принадлежит автору вопроса",
        "uk": "Кнопка належить автору питання",
        "be": "Кнопка належыць аўтару пытання",
        "en": "This button belongs to the person who asked",
    },
    "fb.gone": {
        "ru": "Этот ответ уже недоступен",
        "uk": "Ця відповідь уже недоступна",
        "be": "Гэты адказ ужо недаступны",
        "en": "This answer is no longer available",
    },
    "fb.working": {"ru": "Готовлю…", "uk": "Готую…", "be": "Гатоўлю…", "en": "Working…"},
    # ------------------------------------------------------------------ старт
    "start.body": {
        "ru": (
            "👋 Привет! Я <b>{bot}</b> — ИИ-помощник этого сообщества.\n\n"
            "Просто напиши вопрос — отвечу. Помню контекст последних сообщений, "
            "так что можно уточнять и продолжать диалог.\n\n"
            "📷 Пришли фото задания — разберу условие, решу по шагам и объясню.\n"
            "✅ <code>/check</code> — пришли своё решение, и я проверю, где ошибка.\n"
            "🎓 <code>/profile</code> — укажи класс и предмет, подстрою объяснения.\n"
            "🖌 <code>/imagine</code> — нарисую картинку по описанию.\n"
            "🌍 <code>/lang</code> — сменить язык интерфейса.\n\n"
        ),
        "uk": (
            "👋 Привіт! Я <b>{bot}</b> — ШІ-помічник цієї спільноти.\n\n"
            "Просто напиши питання — відповім. Пам'ятаю контекст останніх повідомлень, "
            "тож можна уточнювати й продовжувати діалог.\n\n"
            "📷 Надішли фото завдання — розберу умову, розв'яжу покроково й поясню.\n"
            "✅ <code>/check</code> — надішли своє рішення, і я перевірю, де помилка.\n"
            "🎓 <code>/profile</code> — вкажи клас і предмет, підлаштую пояснення.\n"
            "🖌 <code>/imagine</code> — намалюю картинку за описом.\n"
            "🌍 <code>/lang</code> — змінити мову інтерфейсу.\n\n"
        ),
        "be": (
            "👋 Прывітанне! Я <b>{bot}</b> — ШІ-памочнік гэтай супольнасці.\n\n"
            "Проста напішы пытанне — адкажу. Памятаю кантэкст апошніх паведамленняў, "
            "таму можна ўдакладняць і працягваць дыялог.\n\n"
            "📷 Дашлі фота задання — разаберу ўмову, развяжу па кроках і паясьню.\n"
            "✅ <code>/check</code> — дашлі сваё рашэнне, і я правяру, дзе памылка.\n"
            "🎓 <code>/profile</code> — укажы клас і прадмет, падладжу паясьненні.\n"
            "🖌 <code>/imagine</code> — намалюю малюнак па апісанні.\n"
            "🌍 <code>/lang</code> — змяніць мову інтэрфейсу.\n\n"
        ),
        "en": (
            "👋 Hi! I'm <b>{bot}</b> — the AI assistant of this community.\n\n"
            "Just send your question and I'll answer. I remember the recent context, "
            "so you can keep asking follow-ups.\n\n"
            "📷 Send a photo of a task — I'll read it, solve it step by step and explain.\n"
            "✅ <code>/check</code> — send your own solution and I'll find the mistake.\n"
            "🎓 <code>/profile</code> — set your grade and subject for tailored explanations.\n"
            "🖌 <code>/imagine</code> — I'll draw a picture from your description.\n"
            "🌍 <code>/lang</code> — change the interface language.\n\n"
        ),
    },
    "start.commands": {
        "ru": (
            "Команды:\n"
            "/ai — задать вопрос явно (в группе тоже работает)\n"
            "/reset — очистить контекст диалога\n"
            "/me — твой ID и остаток лимита\n"
            "/support — поддержка и обращения\n"
            "/rules — правила чата\n"
            "/help — справка\n\n"
        ),
        "uk": (
            "Команди:\n"
            "/ai — поставити питання явно (у групі теж працює)\n"
            "/reset — очистити контекст діалогу\n"
            "/me — твій ID і залишок ліміту\n"
            "/support — підтримка та звернення\n"
            "/rules — правила чату\n"
            "/help — довідка\n\n"
        ),
        "be": (
            "Каманды:\n"
            "/ai — задаць пытанне яўна (у групе таксама працуе)\n"
            "/reset — ачысціць кантэкст дыялогу\n"
            "/me — твой ID і рэшта ліміту\n"
            "/support — падтрымка і звароты\n"
            "/rules — правілы чату\n"
            "/help — даведка\n\n"
        ),
        "en": (
            "Commands:\n"
            "/ai — ask explicitly (works in groups too)\n"
            "/reset — clear the dialog context\n"
            "/me — your ID and remaining limit\n"
            "/support — support and requests\n"
            "/rules — chat rules\n"
            "/help — help\n\n"
        ),
    },
    "start.limit_unlimited": {
        "ru": "Твой лимит: <b>без ограничений</b>.",
        "uk": "Твій ліміт: <b>без обмежень</b>.",
        "be": "Твой ліміт: <b>без абмежаванняў</b>.",
        "en": "Your limit: <b>unlimited</b>.",
    },
    "start.limit_daily": {
        "ru": "Твой лимит: <b>{limit} сообщений в день</b>.",
        "uk": "Твій ліміт: <b>{limit} повідомлень на день</b>.",
        "be": "Твой ліміт: <b>{limit} паведамленняў у дзень</b>.",
        "en": "Your limit: <b>{limit} messages per day</b>.",
    },
    "start.limit_staff": {
        "ru": "Твой лимит: <b>без ограничений</b> (роль: {role}).",
        "uk": "Твій ліміт: <b>без обмежень</b> (роль: {role}).",
        "be": "Твой ліміт: <b>без абмежаванняў</b> (роля: {role}).",
        "en": "Your limit: <b>unlimited</b> (role: {role}).",
    },
    "start.admin_extra": {
        "ru": "\n\n🛠 Твоя роль: {role}. Панель управления: /admin",
        "uk": "\n\n🛠 Твоя роль: {role}. Панель керування: /admin",
        "be": "\n\n🛠 Твая роля: {role}. Панэль кіравання: /admin",
        "en": "\n\n🛠 Your role: {role}. Control panel: /admin",
    },
    "start.support_extra": {
        "ru": "\n\n🎫 Твоя роль: {role}. Обращения пользователей: /tickets",
        "uk": "\n\n🎫 Твоя роль: {role}. Звернення користувачів: /tickets",
        "be": "\n\n🎫 Твая роля: {role}. Звароты карыстальнікаў: /tickets",
        "en": "\n\n🎫 Your role: {role}. User requests: /tickets",
    },
    # ------------------------------------------------------------------ справка
    "help.body": {
        "ru": (
            "<b>Как пользоваться</b>\n"
            "• Напиши любой вопрос — я отвечу.\n"
            "• 📎 Пришли документ (TXT, MD, CSV, JSON, DOCX, PDF, XLSX) — прочитаю и помогу, "
            "а по просьбе соберу готовый файл. Подробнее: /files.\n"
            "• Контекст диалога сохраняется, поэтому можно писать «а подробнее?».\n"
            "• /reset — начать разговор с чистого листа.\n\n"
            "<b>Домашка и фото</b>\n"
            "Пришли фотографию задания — прочитаю условие, решу по шагам и объясню.\n"
            "Подпись к фото считается вопросом: «проверь решение», «объясни 3-й шаг».\n"
            "Работают jpg/png и файлы-картинки до 8 МБ.\n\n"
            "<b>Проверка решения</b>\n"
            "<code>/check</code> → пришли текст или фото своего решения — найду ошибку, "
            "не решая заново.\n\n"
            "<b>Профиль</b>\n"
            "<code>/profile</code> → класс, предмет и стиль объяснений.\n\n"
            "<b>Картинки</b>\n"
            "<code>/imagine описание</code> → нарисую картинку.\n"
            "Фото с подписью «измени / перерисуй» → переделаю по описанию.\n\n"
        ),
        "uk": (
            "<b>Як користуватися</b>\n"
            "• Напиши будь-яке питання — я відповім.\n"
            "• 📎 Надішли документ (TXT, MD, CSV, JSON, DOCX, PDF, XLSX) — прочитаю й допоможу, "
            "а на прохання зберу готовий файл. Детальніше: /files.\n"
            "• Контекст діалогу зберігається, тож можна писати «а докладніше?».\n"
            "• /reset — почати розмову з чистого аркуша.\n\n"
            "<b>Домашка й фото</b>\n"
            "Надішли фотографію завдання — прочитаю умову, розв'яжу покроково й поясню.\n"
            "Підпис до фото вважається питанням: «перевір рішення», «поясни 3-й крок».\n"
            "Працюють jpg/png і файли-картинки до 8 МБ.\n\n"
            "<b>Перевірка рішення</b>\n"
            "<code>/check</code> → надішли текст або фото свого рішення — знайду помилку, "
            "не розв'язуючи заново.\n\n"
            "<b>Профіль</b>\n"
            "<code>/profile</code> → клас, предмет і стиль пояснень.\n\n"
            "<b>Картинки</b>\n"
            "<code>/imagine опис</code> → намалюю картинку.\n"
            "Фото з підписом «зміни / перемалюй» → перероблю за описом.\n\n"
        ),
        "be": (
            "<b>Як карыстацца</b>\n"
            "• Напішы любое пытанне — я адкажу.\n"
            "• 📎 Дашлі дакумент (TXT, MD, CSV, JSON, DOCX, PDF, XLSX) — прачытаю і дапамагу, "
            "а па просьбе збяру гатовы файл. Падрабязней: /files.\n"
            "• Кантэкст дыялогу захоўваецца, таму можна пісаць «а падрабязней?».\n"
            "• /reset — пачаць размову з чыстага аркуша.\n\n"
            "<b>Дамашка і фота</b>\n"
            "Дашлі фотаграфію задання — прачытаю ўмову, развяжу па кроках і паясьню.\n"
            "Подпіс да фота лічыцца пытаннем: «правер рашэнне», «паясьні 3-і крок».\n"
            "Працуюць jpg/png і файлы-малюнкі да 8 МБ.\n\n"
            "<b>Праверка рашэння</b>\n"
            "<code>/check</code> → дашлі тэкст або фота свайго рашэння — знойду памылку, "
            "не развязваючы нанова.\n\n"
            "<b>Профіль</b>\n"
            "<code>/profile</code> → клас, прадмет і стыль паясьненняў.\n\n"
            "<b>Малюнкі</b>\n"
            "<code>/imagine апісанне</code> → намалюю малюнак.\n"
            "Фота з подпісам «змяні / перамалюй» → перараблю па апісанні.\n\n"
        ),
        "en": (
            "<b>How to use</b>\n"
            "• Ask any question — I'll answer.\n"
            "• 📎 Send a document (TXT, MD, CSV, JSON, DOCX, PDF, XLSX) — I'll read it and help, "
            "and build a ready file on request. More: /files.\n"
            "• The dialog context is kept, so you can ask follow-ups.\n"
            "• /reset — start over.\n\n"
            "<b>Homework and photos</b>\n"
            "Send a photo of the task — I'll read it, solve step by step and explain.\n"
            "The caption counts as your question (\u201ccheck my solution\u201d, \u201cexplain step 3\u201d).\n"
            "jpg/png and image files up to 8 MB are supported.\n\n"
            "<b>Checking a solution</b>\n"
            "<code>/check</code> → send your solution as text or photo — I'll find the mistake "
            "without solving it from scratch.\n\n"
            "<b>Profile</b>\n"
            "<code>/profile</code> → grade, subject and explanation style.\n\n"
            "<b>Images</b>\n"
            "<code>/imagine description</code> → I'll draw a picture.\n"
            "A photo captioned \u201cchange / redraw\u201d → I'll redo it from the description.\n\n"
        ),
    },
    "help.tail": {
        "ru": "<b>Модель:</b> {model}\n<b>Язык:</b> {lang} · <b>Защита:</b> анти-jailbreak включена",
        "uk": "<b>Модель:</b> {model}\n<b>Мова:</b> {lang} · <b>Захист:</b> анти-jailbreak увімкнено",
        "be": "<b>Мадэль:</b> {model}\n<b>Мова:</b> {lang} · <b>Абарона:</b> анты-jailbreak уключана",
        "en": "<b>Model:</b> {model}\n<b>Language:</b> {lang} · <b>Protection:</b> anti-jailbreak on",
    },
    # ------------------------------------------------------------------ ошибки и лимиты
    "err.private_only": {
        "ru": "Личка со мной: @{username} — там эта команда работает.",
        "uk": "Особисті повідомлення: @{username} — там ця команда працює.",
        "be": "Асабістыя паведамленні: @{username} — там гэтая каманда працуе.",
        "en": "Message me privately: @{username} — the command works there.",
    },
    "err.empty_question": {
        "ru": "Напиши вопрос после команды, например: <code>/ai что такое Webhook?</code>",
        "uk": "Напиши питання після команди, наприклад: <code>/ai що таке Webhook?</code>",
        "be": "Напішы пытанне пасля каманды, напрыклад: <code>/ai што такое Webhook?</code>",
        "en": "Send a question after the command, e.g. <code>/ai what is a webhook?</code>",
    },
    "err.no_user": {
        "ru": "Не вижу, кто спрашивает — напиши из своего аккаунта.",
        "uk": "Не бачу, хто питає — напиши зі свого акаунта.",
        "be": "Не бачу, хто пытае — напішы са свайго акаўнта.",
        "en": "I can't see who is asking — write from your own account.",
    },
    "err.banned": {
        "ru": "🚫 Доступ к ассистенту закрыт администратором.",
        "uk": "🚫 Доступ до помічника закрито адміністратором.",
        "be": "🚫 Доступ да памочніка зачынены адміністратарам.",
        "en": "🚫 Access to the assistant was blocked by an admin.",
    },
    "err.ai": {
        "ru": "⚠️ {message}",
        "uk": "⚠️ {message}",
        "be": "⚠️ {message}",
        "en": "⚠️ {message}",
    },
    "err.generic": {
        "ru": "⚠️ Что-то сломалось на нашей стороне. Попробуй ещё раз.",
        "uk": "⚠️ Щось зламалося на нашій стороні. Спробуй ще раз.",
        "be": "⚠️ Нешта зламалася на нашым баку. Паспрабуй яшчэ раз.",
        "en": "⚠️ Something broke on our side. Please try again.",
    },
    "err.retry": {
        "ru": "⚠️ Не получилось. Попробуй ещё раз.",
        "uk": "⚠️ Не вдалося. Спробуй ще раз.",
        "be": "⚠️ Не атрымалася. Паспрабуй яшчэ раз.",
        "en": "⚠️ That didn't work. Please try again.",
    },
    "err.truncated": {
        "ru": "Вопрос обрезан до {limit} символов.",
        "uk": "Питання обрізано до {limit} символів.",
        "be": "Пытанне абрэзана да {limit} сімвалаў.",
        "en": "The question was trimmed to {limit} characters.",
    },
    "limit.exhausted": {
        "ru": (
            "Дневной лимит — <b>{limit}</b> сообщений — исчерпан.\n"
            "Лимит обнулится в полночь по UTC."
        ),
        "uk": (
            "Денний ліміт — <b>{limit}</b> повідомлень — вичерпано.\n"
            "Ліміт обнулиться опівночі за UTC."
        ),
        "be": (
            "Дзённы ліміт — <b>{limit}</b> паведамленняў — вычарпаны.\n"
            "Ліміт абнуліцца апоўначы па UTC."
        ),
        "en": (
            "The daily limit of <b>{limit}</b> messages is used up.\n"
            "It resets at midnight UTC."
        ),
    },
    "limit.buy_hint": {
        "ru": "\n\nМожно купить дополнительные запросы: /buy",
        "uk": "\n\nМожна купити додаткові запити: /buy",
        "be": "\n\nМожна купіць дадатковыя запыты: /buy",
        "en": "\n\nYou can buy extra requests: /buy",
    },
    # ------------------------------------------------------------------ /me, /profile, /check
    "me.body": {
        "ru": (
            "🪪 ID: <code>{user_id}</code>\n{role_line}{sub_line}"
            "💬 Лимит на сегодня: {limit}\n"
            "⭐ Бонусные запросы: <b>{bonus}</b>\n"
            "🎓 Профиль: {profile}\n"
            "🧠 Модель: {model}{note}"
        ),
        "uk": (
            "🪪 ID: <code>{user_id}</code>\n{role_line}{sub_line}"
            "💬 Ліміт на сьогодні: {limit}\n"
            "⭐ Бонусні запити: <b>{bonus}</b>\n"
            "🎓 Профіль: {profile}\n"
            "🧠 Модель: {model}{note}"
        ),
        "be": (
            "🪪 ID: <code>{user_id}</code>\n{role_line}{sub_line}"
            "💬 Ліміт на сёння: {limit}\n"
            "⭐ Бонусныя запыты: <b>{bonus}</b>\n"
            "🎓 Профіль: {profile}\n"
            "🧠 Мадэль: {model}{note}"
        ),
        "en": (
            "🪪 ID: <code>{user_id}</code>\n{role_line}{sub_line}"
            "💬 Today's limit: {limit}\n"
            "⭐ Bonus requests: <b>{bonus}</b>\n"
            "🎓 Profile: {profile}\n"
            "🧠 Model: {model}{note}"
        ),
    },
    "me.sub_active": {
        "ru": "💎 Подписка: активна до <b>{date}</b> · GPT-6, Claude, Gemini, Grok, Kimi\n",
        "uk": "💎 Підписка: активна до <b>{date}</b> · GPT-6, Claude, Gemini, Grok, Kimi\n",
        "be": "💎 Падпіска: актыўная да <b>{date}</b> · GPT-6, Claude, Gemini, Grok, Kimi\n",
        "en": "💎 Subscription: active until <b>{date}</b> · GPT-6, Claude, Gemini, Grok, Kimi\n",
    },
    "me.role_line": {
        "ru": "🎖 Роль: {role}\n",
        "uk": "🎖 Роль: {role}\n",
        "be": "🎖 Роля: {role}\n",
        "en": "🎖 Role: {role}\n",
    },
    "me.banned_note": {
        "ru": "\n🚫 Доступ закрыт администратором.",
        "uk": "\n🚫 Доступ закрито адміністратором.",
        "be": "\n🚫 Доступ зачынены адміністратарам.",
        "en": "\n🚫 Access blocked by an admin.",
    },
    "me.limit_staff": {
        "ru": "∞ ({role})",
        "uk": "∞ ({role})",
        "be": "∞ ({role})",
        "en": "∞ ({role})",
    },
    "me.limit_left": {
        "ru": "осталось {left} из {total}",
        "uk": "залишилось {left} з {total}",
        "be": "засталося {left} з {total}",
        "en": "{left} of {total} left",
    },
    "me.limit_unlimited": {
        "ru": "без ограничений",
        "uk": "без обмежень",
        "be": "без абмежаванняў",
        "en": "unlimited",
    },
    "me.profile_empty": {
        "ru": "не задан (/profile)",
        "uk": "не задано (/profile)",
        "be": "не зададзены (/profile)",
        "en": "not set (/profile)",
    },
    "profile.title": {
        "ru": "🎓 <b>Профиль ученика</b>",
        "uk": "🎓 <b>Профіль учня</b>",
        "be": "🎓 <b>Профіль вучня</b>",
        "en": "🎓 <b>Student profile</b>",
    },
    "profile.grade": {"ru": "Класс", "uk": "Клас", "be": "Клас", "en": "Grade"},
    "profile.subject": {"ru": "Предмет", "uk": "Предмет", "be": "Прадмет", "en": "Subject"},
    "profile.style": {"ru": "Стиль", "uk": "Стиль", "be": "Стыль", "en": "Style"},
    "profile.hint": {
        "ru": "Выбери, что поменять — под это подстроятся объяснения:",
        "uk": "Обери, що змінити — під це підлаштуються пояснення:",
        "be": "Абяры, што змяніць — пад гэта падладуюцца паясьненні:",
        "en": "Pick what to change — explanations will adapt:",
    },
    "profile.reset": {
        "ru": "♻️ Сбросить профиль",
        "uk": "♻️ Скинути профіль",
        "be": "♻️ Скінуць профіль",
        "en": "♻️ Reset profile",
    },
    "profile.saved": {"ru": "Сохранено: {value}", "uk": "Збережено: {value}", "be": "Захавана: {value}", "en": "Saved: {value}"},
    "profile.unknown": {"ru": "Неизвестное значение", "uk": "Невідоме значення", "be": "Невядомае значэнне", "en": "Unknown value"},
    "check.hint": {
        "ru": (
            "✅ <b>Проверка решения</b>\n\n"
            "Пришли своё решение: текстом или фото тетради. Я не буду решать заново — "
            "найду ошибку, объясню, почему она возникла, и покажу правильный шаг.\n\n"
            "Отмена: /cancel"
        ),
        "uk": (
            "✅ <b>Перевірка рішення</b>\n\n"
            "Надішли своє рішення: текстом або фото зошита. Я не буду розв'язувати наново — "
            "знайду помилку, поясню, чому вона виникла, і покажу правильний крок.\n\n"
            "Скасування: /cancel"
        ),
        "be": (
            "✅ <b>Праверка рашэння</b>\n\n"
            "Дашлі сваё рашэнне: тэкстам або фота сшытка. Я не буду развязваць нанова — "
            "знойду памылку, паясьню, чаму яна ўзнікла, і пакажу правільны крок.\n\n"
            "Адмена: /cancel"
        ),
        "en": (
            "✅ <b>Solution check</b>\n\n"
            "Send your solution as text or a photo of your notebook. I won't solve it again — "
            "I'll find the mistake, explain why it happened and show the right step.\n\n"
            "Cancel: /cancel"
        ),
    },
    "check.need_solution": {
        "ru": "Нужно решение текстом или фото. Попробуй ещё раз через /check.",
        "uk": "Потрібне рішення текстом або фото. Спробуй ще раз через /check.",
        "be": "Патрэбна рашэнне тэкстам або фота. Паспрабуй яшчэ раз праз /check.",
        "en": "I need a solution as text or a photo. Try again with /check.",
    },
    "check.prompt": {
        "ru": "Пришли своё решение (текст или фото) — проверю и найду ошибку.",
        "uk": "Надішли своє рішення (текст або фото) — перевірю й знайду помилку.",
        "be": "Дашлі сваё рашэнне (тэкст або фота) — правяру і знойду памылку.",
        "en": "Send your solution (text or photo) and I'll check it.",
    },
    "reset.done": {
        "ru": "🧹 Контекст очищен. Начинаем с чистого листа.",
        "uk": "🧹 Контекст очищено. Починаємо з чистого аркуша.",
        "be": "🧹 Кантэкст ачышчаны. Пачынаем з чыстага аркуша.",
        "en": "🧹 Context cleared. Starting fresh.",
    },
    "cancel.done": {"ru": "Отменено.", "uk": "Скасовано.", "be": "Скасавана.", "en": "Cancelled."},
    "other.only_text": {
        "ru": "Пока понимаю только текст и картинки. Напиши вопрос или пришли фото задания 🙂",
        "uk": "Поки розумію лише текст і картинки. Напиши питання або надішли фото завдання 🙂",
        "be": "Пакуль разумею толькі тэкст і малюнкі. Напішы пытанне або дашлі фота задання 🙂",
        "en": "I only understand text and images for now. Ask a question or send a photo of the task 🙂",
    },
    "image.checking": {
        "ru": "🔍 Смотрю изображение…",
        "uk": "🔍 Дивлюся зображення…",
        "be": "🔍 Гляджу малюнак…",
        "en": "🔍 Looking at the image…",
    },
    "image.too_big": {
        "ru": "Файл больше 8 МБ — пришли, пожалуйста, поменьше.",
        "uk": "Файл більший за 8 МБ — надішли, будь ласка, менший.",
        "be": "Файл большы за 8 МБ — дашлі, калі ласка, меншы.",
        "en": "The file is over 8 MB — please send a smaller one.",
    },
    "image.not_image": {
        "ru": "Я понимаю текст и изображения. Пришли фото задания или напиши вопрос 🙂",
        "uk": "Я розумію текст і зображення. Надішли фото завдання або напиши питання 🙂",
        "be": "Я разумею тэкст і малюнкі. Дашлі фота задання або напішы пытанне 🙂",
        "en": "I understand text and images. Send a photo of the task or ask a question 🙂",
    },
    "image.no_image": {
        "ru": "Не вижу изображения. Пришли фото ещё раз.",
        "uk": "Не бачу зображення. Надішли фото ще раз.",
        "be": "Не бачу малюнка. Дашлі фота яшчэ раз.",
        "en": "I don't see an image. Please send the photo again.",
    },
    "image.download_failed": {
        "ru": "Не смог скачать изображение. Отправь его ещё раз.",
        "uk": "Не вдалося завантажити зображення. Надішли його ще раз.",
        "be": "Не атрымалася спампаваць малюнак. Дашлі яго яшчэ раз.",
        "en": "Couldn't download the image. Please send it again.",
    },
    "image.empty_file": {
        "ru": "Файл пришёл пустым, попробуй ещё раз.",
        "uk": "Файл надійшов порожнім, спробуй ще раз.",
        "be": "Файл прыйшоў пустым, паспрабуй яшчэ раз.",
        "en": "The file came empty, please try again.",
    },
    # ------------------------------------------------------------------ изображения
    "img.need_prompt": {
        "ru": (
            "🖌 Напиши, что нарисовать, после команды. Например:\n"
            "<code>/imagine кот-космонавт в скафандре, акварель</code>"
        ),
        "uk": (
            "🖌 Напиши, що намалювати, після команди. Наприклад:\n"
            "<code>/imagine кіт-космонавт у скафандрі, акварель</code>"
        ),
        "be": (
            "🖌 Напішы, што намаляваць, пасля каманды. Напрыклад:\n"
            "<code>/imagine кот-касманаўт у скафандры, акварэль</code>"
        ),
        "en": (
            "🖌 Describe what to draw after the command. For example:\n"
            "<code>/imagine a cat astronaut in a spacesuit, watercolor</code>"
        ),
    },
    "img.generating": {
        "ru": "🎨 Рисую… Обычно это занимает 10–40 секунд.",
        "uk": "🎨 Малюю… Зазвичай це триває 10–40 секунд.",
        "be": "🎨 Малюю… Звычайна гэта займае 10–40 секунд.",
        "en": "🎨 Drawing… This usually takes 10–40 seconds.",
    },
    "img.done": {
        "ru": "🖼 <b>Готово</b>\n<i>{prompt}</i>",
        "uk": "🖼 <b>Готово</b>\n<i>{prompt}</i>",
        "be": "🖼 <b>Гатовa</b>\n<i>{prompt}</i>",
        "en": "🖼 <b>Done</b>\n<i>{prompt}</i>",
    },
    "img.more": {
        "ru": "🖼 Ещё вариант",
        "uk": "🖼 Ще варіант",
        "be": "🖼 Яшчэ варыянт",
        "en": "🖼 One more",
    },
    "img.not_configured": {
        "ru": (
            "🖌 Генерация картинок пока не подключена.\n"
            "Администратору: задай <code>IMAGE_PROVIDER</code> и ключ, "
            "если сервис его требует."
        ),
        "uk": (
            "🖌 Генерація картинок поки не підключена.\n"
            "Адміністратору: задай <code>IMAGE_PROVIDER</code> і ключ, "
            "якщо сервіс його потребує."
        ),
        "be": (
            "🖌 Генерацыя малюнкаў пакуль не падключана.\n"
            "Адміністратару: задай <code>IMAGE_PROVIDER</code> і ключ, "
            "калі сэрвіс яго патрабуе."
        ),
        "en": (
            "🖌 Image generation isn't connected yet.\n"
            "Admin: set <code>IMAGE_PROVIDER</code> and a key if the service needs one."
        ),
    },
    "img.failed": {
        "ru": "⚠️ Не получилось нарисовать. Попробуй другой запрос или позже.",
        "uk": "⚠️ Не вдалося намалювати. Спробуй інший запит або пізніше.",
        "be": "⚠️ Не атрымалася намаляваць. Паспрабуй іншы запыт або пазней.",
        "en": "⚠️ Couldn't generate the image. Try another prompt or later.",
    },
    "img.rate_limited": {
        "ru": "⏳ Бесплатная генерация — одна картинка за раз. Попробуй через {seconds} с.",
        "uk": "⏳ Безкоштовна генерація — одна картинка за раз. Спробуй через {seconds} с.",
        "be": "⏳ Бясплатная генерацыя — адна карцінка за раз. Паспрабуй праз {seconds} с.",
        "en": "⏳ Free generation allows one image at a time. Try again in {seconds} s.",
    },
    "img.no_credits": {
        "ru": (
            "💳 У сервиса картинок закончились кредиты.\n"
            "Бесплатная генерация продолжает работать, а для Gemini "
            "администратору нужно пополнить баланс провайдера."
        ),
        "uk": (
            "💳 У сервісу картинок закінчилися кредити.\n"
            "Безкоштовна генерація продовжує працювати, а для Gemini "
            "адміністратору треба поповнити баланс провайдера."
        ),
        "be": (
            "💳 У сэрвіса карцінак скончыліся крэдыты.\n"
            "Бясплатная генерацыя працягвае працаваць, а для Gemini "
            "адміністратару трэба папоўніць баланс правайдэра."
        ),
        "en": (
            "💳 The image service is out of credits.\n"
            "Free generation keeps working; for Gemini the admin needs "
            "to top up the provider balance."
        ),
    },
    "img.edit_hint": {
        "ru": (
            "🖌 Пришли фото с подписью, что изменить.\n"
            "Бесплатно работают базовые правки: «сделай чёрно-белым», «размой», "
            "«поверни на 90», «отзеркаль», «увеличь», «добавь резкости».\n"
            "AI-правки вроде «замени фон на закат» — при подключённом "
            "IMAGE_PROVIDER=gemini или openai."
        ),
        "uk": (
            "🖌 Надішли фото з підписом, що змінити.\n"
            "Безкоштовно працюють базові правки: «зроби чорно-білим», «розмий», "
            "«поверни на 90», «віддзеркаль», «збільш», «додай різкості».\n"
            "AI-правки на кшталт «заміни фон на захід сонця» — з "
            "IMAGE_PROVIDER=gemini або openai."
        ),
        "be": (
            "🖌 Дашлі фота з подпісам, што змяніць.\n"
            "Бясплатна працуюць базавыя праўкі: «зрабі чорна-белым», «размый», "
            "«павярні на 90», «адлюструй», «павяліч», «дадай рэзкасці».\n"
            "AI-праўкі накшталт «змяні фон на захад сонца» — з "
            "IMAGE_PROVIDER=gemini або openai."
        ),
        "en": (
            "🖌 Send a photo captioned with the change.\n"
            "Free basic edits: \u201cmake it black and white\u201d, \u201cblur\u201d, "
            "\u201crotate 90\u201d, \u201cmirror\u201d, \u201cenlarge\u201d, \u201csharpen\u201d.\n"
            "AI edits like \u201cchange the background to a sunset\u201d need "
            "IMAGE_PROVIDER=gemini or openai."
        ),
    },
    "img.edit_unsupported": {
        "ru": (
            "🖌 Такую правку бесплатный режим не умеет.\n"
            "Он понимает: чёрно-белое, сепия, негатив, размытие, резкость, "
            "яркость, контраст, поворот, отражение, обрезку и размер.\n"
            "Для AI-правок («замени фон») подключите IMAGE_PROVIDER=gemini "
            "или openai с ключом."
        ),
        "uk": (
            "🖌 Таку правку безкоштовний режим не вміє.\n"
            "Він розуміє: чорно-біле, сепія, негатив, розмиття, різкість, "
            "яскравість, контраст, поворот, відображення, обрізання й розмір.\n"
            "Для AI-правок («заміни фон») підключіть IMAGE_PROVIDER=gemini "
            "або openai з ключем."
        ),
        "be": (
            "🖌 Такую праўку бясплатны рэжым не ўмее.\n"
            "Ён разумее: чорна-белае, сепія, негатыў, размыццё, рэзкасць, "
            "яркасць, кантраст, паварот, адлюстраванне, абрэзку і памер.\n"
            "Для AI-правак («змяні фон») падключыце IMAGE_PROVIDER=gemini "
            "або openai з ключом."
        ),
        "en": (
            "🖌 The free mode can't do that edit.\n"
            "It supports: black and white, sepia, negative, blur, sharpen, "
            "brightness, contrast, rotate, mirror, crop and resize.\n"
            "For AI edits (\u201cchange the background\u201d) set "
            "IMAGE_PROVIDER=gemini or openai with a key."
        ),
    },
    "img.sending": {
        "ru": "🖼 Отправляю картинку…",
        "uk": "🖼 Надсилаю картинку…",
        "be": "🖼 Дасылаю малюнак…",
        "en": "🖼 Sending the image…",
    },
    "img.too_big_result": {
        "ru": "Картинка получилась слишком большой — попробуй другой запрос.",
        "uk": "Картинка вийшла завеликою — спробуй інший запит.",
        "be": "Малюнак выйшаў завялікі — паспрабуй іншы запыт.",
        "en": "The image came out too large — try another prompt.",
    },
    # ------------------------------------------------------------------ файлы
    "file.reading": {
        "ru": "📄 Читаю файл…",
        "uk": "📄 Читаю файл…",
        "be": "📄 Чытаю файл…",
        "en": "📄 Reading the file…",
    },
    "file.too_big": {
        "ru": "Файл больше {mb} МБ. Пришли документ до {mb} МБ или разбей его на части.",
        "uk": "Файл більший за {mb} МБ. Надішли документ до {mb} МБ або розбий його на частини.",
        "be": "Файл большы за {mb} МБ. Дашлі дакумент да {mb} МБ або падзялі яго на часткі.",
        "en": "The file is larger than {mb} MB. Send a document up to {mb} MB or split it.",
    },
    "file.unsupported": {
        "ru": "Не умею читать формат {ext}. Поддерживаю: TXT, MD, CSV, JSON, DOCX, PDF, XLSX.",
        "uk": "Не вмію читати формат {ext}. Підтримую: TXT, MD, CSV, JSON, DOCX, PDF, XLSX.",
        "be": "Не ўмею чытаць фармат {ext}. Падтрымліваю: TXT, MD, CSV, JSON, DOCX, PDF, XLSX.",
        "en": "I can't read the {ext} format. Supported: TXT, MD, CSV, JSON, DOCX, PDF, XLSX.",
    },
    "file.empty": {
        "ru": "В файле нет текста: он пустой или повреждён.",
        "uk": "У файлі немає тексту: він порожній або пошкоджений.",
        "be": "У файле няма тэксту: ён пусты або пашкоджаны.",
        "en": "There is no text in the file: it is empty or damaged.",
    },
    "file.scanned": {
        "ru": (
            "Похоже, это скан без текстового слоя — текст не извлекается. "
            "Пришли фото страницы или сам текст, так прочитаю точнее."
        ),
        "uk": (
            "Схоже, це скан без текстового шару — текст не витягується. "
            "Надішли фото сторінки або сам текст, так прочитаю точніше."
        ),
        "be": (
            "Падобна, гэта скан без тэкставага слоя — тэкст не вымаецца. "
            "Дашлі фота старонкі або сам тэкст, так прачытаю дакладней."
        ),
        "en": (
            "This looks like a scan without a text layer, so I can't extract the text. "
            "Send a photo of the page or the text itself — that reads much better."
        ),
    },
    "file.locked": {
        "ru": "Файл защищён паролем — не могу его открыть. Пришли файл без пароля.",
        "uk": "Файл захищений паролем — не можу його відкрити. Надішли файл без пароля.",
        "be": "Файл абаронены паролем — не магу яго адкрыць. Дашлі файл без пароля.",
        "en": "The file is password-protected — I can't open it. Send it without a password.",
    },
    "file.download_failed": {
        "ru": "Не смог скачать файл. Попробуй отправить его ещё раз.",
        "uk": "Не зміг завантажити файл. Спробуй надіслати його ще раз.",
        "be": "Не змог спампаваць файл. Паспрабуй даслаць яго яшчэ раз.",
        "en": "I couldn't download the file. Try sending it again.",
    },
    "file.default_task": {
        "ru": "Разбери этот файл: коротко перескажи содержимое и выдели главное.",
        "uk": "Розбери цей файл: коротко перекажи вміст і виділи головне.",
        "be": "Разбяры гэты файл: коратка перакажы змест і выдзелі галоўнае.",
        "en": "Go through this file: briefly summarise it and highlight the key points.",
    },
    "file.caption": {
        "ru": "📄 Готово: {name}",
        "uk": "📄 Готово: {name}",
        "be": "📄 Гатово: {name}",
        "en": "📄 Done: {name}",
    },
    "file.pdf_unavailable": {
        "ru": "PDF сейчас недоступен: на сервере нет шрифта. Пришлю DOCX.",
        "uk": "PDF зараз недоступний: на сервері немає шрифту. Надішлю DOCX.",
        "be": "PDF зараз недаступны: на серверы няма шрыфта. Дашлю DOCX.",
        "en": "PDF is unavailable right now: the server has no font. I'll send a DOCX.",
    },
    "file.build_failed": {
        "ru": "Не смог собрать {fmt}. Вот ответ текстом.",
        "uk": "Не зміг зібрати {fmt}. Ось відповідь текстом.",
        "be": "Не змог сабраць {fmt}. Вось адказ тэкстам.",
        "en": "I couldn't build the {fmt}. Here is the answer as text.",
    },
    "file.help": {
        "ru": (
            "📎 <b>Файлы</b>\n\n"
            "Пришли документ — я прочитаю его и помогу. Можно ответить на файл вопросом:\n"
            "• «сделай конспект»\n"
            "• «исправь ошибки»\n"
            "• «реши задания и оформи в PDF»\n"
            "• «переведи на английский и пришли DOCX»\n\n"
            "Можно ответить на готовый ответ «пришли в PDF» — пришлю его файлом.\n\n"
            "<b>Читаю:</b> TXT, MD, CSV, JSON, DOCX, PDF, XLSX (до {mb} МБ, PDF до {pages} страниц).\n"
            "<b>Создаю:</b> TXT, DOCX, PDF, CSV, XLSX.\n\n"
            "Скан без текстового слоя не читается — пришли фото страницы."
        ),
        "uk": (
            "📎 <b>Файли</b>\n\n"
            "Надішли документ — я прочитаю його й допоможу. Можна відповісти на файл питанням:\n"
            "• «зроби конспект»\n"
            "• «виправ помилки»\n"
            "• «розв'яжи завдання й оформи в PDF»\n"
            "• «переклади англійською й надішли DOCX»\n\n"
            "Можна відповісти на готову відповідь «надішли в PDF» — надішлю її файлом.\n\n"
            "<b>Читаю:</b> TXT, MD, CSV, JSON, DOCX, PDF, XLSX (до {mb} МБ, PDF до {pages} сторінок).\n"
            "<b>Створюю:</b> TXT, DOCX, PDF, CSV, XLSX.\n\n"
            "Скан без текстового шару не читається — надішли фото сторінки."
        ),
        "be": (
            "📎 <b>Файлы</b>\n\n"
            "Дашлі дакумент — я прачытаю яго і дапамагу. Можна адказаць на файл пытаннем:\n"
            "• «зрабі канспект»\n"
            "• «выпраў памылкі»\n"
            "• «развяжы заданні і аформі ў PDF»\n"
            "• «перакладзі на англійскую і дашлі DOCX»\n\n"
            "Можна адказаць на гатовы адказ «дашлі ў PDF» — дашлю яго файлам.\n\n"
            "<b>Чытаю:</b> TXT, MD, CSV, JSON, DOCX, PDF, XLSX (да {mb} МБ, PDF да {pages} старонак).\n"
            "<b>Ствараю:</b> TXT, DOCX, PDF, CSV, XLSX.\n\n"
            "Скан без тэкставага слоя не чытаецца — дашлі фота старонкі."
        ),
        "en": (
            "📎 <b>Files</b>\n\n"
            "Send a document and I'll read it. You can also reply to a file with a request:\n"
            "• \"make a summary\"\n"
            "• \"fix the mistakes\"\n"
            "• \"solve the tasks and export to PDF\"\n"
            "• \"translate to English and send a DOCX\"\n\n"
            "You can also reply to a finished answer with \"send it as PDF\" — I'll attach it as a file.\n\n"
            "<b>I read:</b> TXT, MD, CSV, JSON, DOCX, PDF, XLSX (up to {mb} MB, PDF up to {pages} pages).\n"
            "<b>I create:</b> TXT, DOCX, PDF, CSV, XLSX.\n\n"
            "Scans without a text layer can't be read — send a photo of the page."
        ),
    },
    # ------------------------------------------------------------------ группы
    "group.only_admins": {
        "ru": "🛡 Это только для админов чата.",
        "uk": "🛡 Це лише для адмінів чату.",
        "be": "🛡 Гэта толькі для адмінаў чату.",
        "en": "🛡 Chat admins only.",
    },
    "group.need_rights": {
        "ru": (
            "Мне не хватает прав администратора в этом чате: {rights}.\n"
            "Выдайте их боту: Управление группой → Администраторы → gazyavaGPT."
        ),
        "uk": (
            "Мені бракує прав адміністратора в цьому чаті: {rights}.\n"
            "Надайте їх боту: Керування групою → Адміністратори → gazyavaGPT."
        ),
        "be": (
            "Мне не хапае правоў адміністратара ў гэтым чаце: {rights}.\n"
            "Дайце іх боту: Кіраванне групай → Адміністратары → gazyavaGPT."
        ),
        "en": (
            "I am missing admin rights in this chat: {rights}.\n"
            "Grant them to the bot: Group management → Administrators → gazyavaGPT."
        ),
    },
    "group.need_reply": {
        "ru": "Ответь на сообщение нарушителя или укажи его ID.",
        "uk": "Дай відповідь на повідомлення порушника або вкажи його ID.",
        "be": "Адказь на паведамленне парушальніка або ўкажы яго ID.",
        "en": "Reply to the offender's message or give their ID.",
    },
    "group.no_username": {
        "ru": "Не могу найти по @username. Ответь на сообщение участника или укажи его числовой ID.",
        "uk": "Не можу знайти за @username. Дай відповідь на повідомлення учасника або вкажи його числовий ID.",
        "be": "Не магу знайсці па @username. Адказь на паведамленне ўдзельніка або ўкажы яго лікавы ID.",
        "en": "I can't look up @username. Reply to the member's message or give their numeric ID.",
    },
    "group.no_target": {
        "ru": "Не нашёл такого участника. Ответь на его сообщение.",
        "uk": "Не знайшов такого учасника. Дай відповідь на його повідомлення.",
        "be": "Не знайшоў такога ўдзельніка. Адказь на яго паведамленне.",
        "en": "Couldn't find that member. Reply to their message.",
    },
    "group.done_mute": {
        "ru": "🔇 {name} замучен на {minutes} мин.",
        "uk": "🔇 {name} замучено на {minutes} хв.",
        "be": "🔇 {name} замучаны на {minutes} хв.",
        "en": "🔇 {name} is muted for {minutes} min.",
    },
    "group.muted": {
        "ru": (
            "🔇 <b>{name}</b> — мут на {duration}.\n"
            "Сообщения удаляются, писать нельзя до конца срока."
        ),
        "uk": (
            "🔇 <b>{name}</b> — мут на {duration}.\n"
            "Повідомлення видаляються, писати не можна до кінця строку."
        ),
        "be": (
            "🔇 <b>{name}</b> — мут на {duration}.\n"
            "Паведамленні выдаляюцца, пісаць нельга да канца тэрміну."
        ),
        "en": (
            "🔇 <b>{name}</b> is muted for {duration}.\n"
            "Their messages are deleted and they can't post until it ends."
        ),
    },
    "group.muted_reason": {
        "ru": "\nПричина: {reason}",
        "uk": "\nПричина: {reason}",
        "be": "\nПрычына: {reason}",
        "en": "\nReason: {reason}",
    },
    "group.with_reason": {
        "ru": "\nПричина: {reason}",
        "uk": "\nПричина: {reason}",
        "be": "\nПрычына: {reason}",
        "en": "\nReason: {reason}",
    },
    "group.done_unmute": {
        "ru": "🔊 {name} размучен.",
        "uk": "🔊 {name} розмучено.",
        "be": "🔊 {name} размучаны.",
        "en": "🔊 {name} is unmuted.",
    },
    "group.done_kick": {
        "ru": "👋 {name} исключён из чата.",
        "uk": "👋 {name} виключено з чату.",
        "be": "👋 {name} выключаны з чату.",
        "en": "👋 {name} was kicked.",
    },
    "group.done_ban": {
        "ru": "🚫 {name} заблокирован: больше не сможет войти.",
        "uk": "🚫 {name} заблоковано: більше не зможе увійти.",
        "be": "🚫 {name} заблакаваны: больш не зможа ўвайсці.",
        "en": "🚫 {name} was banned: they can't rejoin.",
    },
    "group.done_unban": {
        "ru": "✅ {name} разблокирован.",
        "uk": "✅ {name} розблоковано.",
        "be": "✅ {name} разблакаваны.",
        "en": "✅ {name} was unbanned.",
    },
    "group.done_promote": {
        "ru": "🛡 {name} теперь админ чата.",
        "uk": "🛡 {name} тепер адмін чату.",
        "be": "🛡 {name} цяпер адмін чату.",
        "en": "🛡 {name} is now a chat admin.",
    },
    "group.done_demote": {
        "ru": "👤 {name} больше не админ.",
        "uk": "👤 {name} більше не адмін.",
        "be": "👤 {name} больш не адмін.",
        "en": "👤 {name} is no longer an admin.",
    },
    "group.failed": {
        "ru": "Не получилось выполнить действие. Проверьте права бота и повторите.",
        "uk": "Не вдалося виконати дію. Перевірте права бота та повторіть.",
        "be": "Не атрымалася выканаць дзеянне. Праверце правы бота і паўтарыце.",
        "en": "Could not complete the action. Check the bot rights and try again.",
    },
    "group.target_channel": {
        "ru": (
            "Это канал или анонимный админ, а не участник. "
            "Ответьте на сообщение самого пользователя."
        ),
        "uk": (
            "Це канал або анонімний адмін, а не учасник. "
            "Дайте відповідь на повідомлення самого користувача."
        ),
        "be": (
            "Гэта канал або ананімны адмін, а не ўдзельнік. "
            "Адкажыце на паведамленне самога карыстальніка."
        ),
        "en": (
            "That is a channel or an anonymous admin, not a member. "
            "Reply to the user's own message."
        ),
    },
    "group.target_not_found": {
        "ru": "Не нашёл этого участника в чате. Пусть напишет сообщение, и повторите команду.",
        "uk": "Не знайшов цього учасника в чаті. Хай напише повідомлення, і повторіть команду.",
        "be": "Не знайшоў гэтага ўдзельніка ў чаце. Хай напіша паведамленне, і паўтарыце каманду.",
        "en": "I could not find that member in the chat. Ask them to send a message and retry.",
    },
    "group.already_admin": {
        "ru": "Этот участник уже администратор чата.",
        "uk": "Цей учасник уже адміністратор чату.",
        "be": "Гэты ўдзельнік ужо адміністратар чата.",
        "en": "That member is already a chat admin.",
    },
    "group.owner_immutable": {
        "ru": "Владельца чата нельзя назначать или снимать.",
        "uk": "Власника чату не можна призначати або знімати.",
        "be": "Уладальніка чата нельга прызначаць або здымаць.",
        "en": "The chat owner cannot be promoted or demoted.",
    },
    "group.panel": {
        "ru": "🛡 <b>Управление чатом</b>\n\nРеплай на сообщение (или ID):\n/kick причина — исключить\n/ban причина — заблокировать\n/mute 1час причина — мут: писать нельзя, сообщения удаляются\n/mute 30 — мут на 30 минут\n/unmute — снять мут\n/warn причина — предупреждение\n/promote — дать админку\n/demote — снять админку\n/del — удалить сообщение\n/purge 20 — удалить последние сообщения\n\nСроки: 30с, 15мин, 1час, 2ч30м, 1день, 7д. Антифлуд и фильтр ссылок работают автоматически.",
        "uk": "🛡 <b>Керування чатом</b>\n\nРеплай на повідомлення (або ID):\n/kick причина — виключити\n/ban причина — заблокувати\n/mute 1час причина — мут: писати не можна, повідомлення видаляються\n/mute 30 — мут на 30 хвилин\n/unmute — зняти мут\n/warn причина — попередження\n/promote — дати адмінку\n/demote — зняти адмінку\n/del — видалити повідомлення\n/purge 20 — видалити останні повідомлення\n\nСтроки: 30с, 15хв, 1год, 2г30хв, 1день, 7д. Антифлуд і фільтр посилань працюють автоматично.",
        "be": "🛡 <b>Кіраванне чатам</b>\n\nРэплай на паведамленне (або ID):\n/kick прычына — выключыць\n/ban прычына — заблакаваць\n/mute 1час прычына — мут: пісаць нельга, паведамленні выдаляюцца\n/mute 30 — мут на 30 хвілін\n/unmute — зняць мут\n/warn прычына — папярэджанне\n/promote — даць адмінку\n/demote — зняць адмінку\n/del — выдаліць паведамленне\n/purge 20 — выдаліць апошнія паведамленні\n\nТэрміны: 30с, 15хв, 1гадз, 2г30хв, 1дзень, 7д. Антыфлуд і фільтр спасылак працуюць аўтаматычна.",
        "en": "🛡 <b>Chat management</b>\n\nReply to a message (or use an ID):\n/kick reason — remove\n/ban reason — block\n/mute 1h reason — mute: can't post, messages are deleted\n/mute 30 — mute for 30 minutes\n/unmute — unmute\n/warn reason — warning\n/promote — make admin\n/demote — remove admin\n/del — delete the message\n/purge 20 — delete recent messages\n\nDurations: 30s, 15min, 1h, 2h30m, 1d, 7d. Anti-flood and the link filter run automatically.",
    },
    "group.flood": {
        "ru": "🔇 {name}, слишком много сообщений подряд. Мут на {minutes} мин.",
        "uk": "🔇 {name}, занадто багато повідомлень підряд. Мут на {minutes} хв.",
        "be": "🔇 {name}, занадта шмат паведамленняў запар. Мут на {minutes} хв.",
        "en": "🔇 {name}, too many messages in a row. Muted for {minutes} min.",
    },
    "group.flood_nomute": {
        "ru": "🔇 {name}, слишком много сообщений подряд.",
        "uk": "🔇 {name}, занадто багато повідомлень підряд.",
        "be": "🔇 {name}, занадта шмат паведамленняў запар.",
        "en": "🔇 {name}, too many messages in a row.",
    },
    "group.spam_deleted": {
        "ru": "🧹 Удалено сообщение от {name}: {reason}",
        "uk": "🧹 Видалено повідомлення від {name}: {reason}",
        "be": "🧹 Выдалена паведамленне ад {name}: {reason}",
        "en": "🧹 Deleted a message from {name}: {reason}",
    },
    "group.reason_links": {"ru": "ссылки", "uk": "посилання", "be": "спасылкі", "en": "links"},
    "group.reason_mentions": {"ru": "массовые упоминания", "uk": "масові згадки", "be": "масавыя згадкі", "en": "mass mentions"},
    "group.reason_duplicate": {"ru": "повтор", "uk": "повтор", "be": "паўтор", "en": "duplicate"},
    "group.reason_caps": {"ru": "капс", "uk": "капс", "be": "капс", "en": "ALL CAPS"},
    "group.reason_forward": {"ru": "пересланное сообщение", "uk": "переслане повідомлення", "be": "перасланае паведамленне", "en": "forwarded message"},
    "group.reason_bot": {"ru": "бот в чате", "uk": "бот у чаті", "be": "бот у чаце", "en": "a bot in the chat"},
}


def normalize_lang(value: str | None, default: str = "ru") -> str:
    if not value:
        return default
    code = value.strip().lower().replace("_", "-")
    if code.startswith("uk") or code.startswith("ua"):
        return "uk"
    if code.startswith("be") or code.startswith("by"):
        return "be"
    if code.startswith("en"):
        return "en"
    if code.startswith("ru"):
        return "ru"
    return default


def t(language: str | None, key: str, **kwargs: object) -> str:
    """Перевод по ключу. Неизвестный язык/ключ -> русский, затем сам ключ."""
    code = normalize_lang(language)
    variants = TR.get(key, {})
    text = variants.get(code) or variants.get("ru") or key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


_UK_MARKERS = set("іїєґІЇЄҐ")
_BE_MARKERS = set("ўЎ")
# Слова, по которым белорусский виден даже без буквы «ў».
_BE_WORDS = (
    "прывітан", "дапамажы", "заданн", "дзякуй", "калі ласка", "трэба",
    "гэта", "вельмі", "будзь", "разам", "сёння", "цяпер",
)


def detect_lang(text: str | None) -> str:
    """Язык сообщения: важно для ответов на английские/украинские задания."""
    if not text:
        return "ru"
    sample = text[:1000]
    latin = sum(1 for ch in sample if "a" <= ch.lower() <= "z")
    cyrillic = sum(1 for ch in sample if "а" <= ch.lower() <= "я" or ch.lower() in "ёіїєґў")
    if latin > cyrillic * 1.2:
        return "en"
    lowered = sample.lower()
    if any(ch in _BE_MARKERS for ch in sample) or any(
        word in lowered for word in _BE_WORDS
    ):
        return "be"
    if any(ch in _UK_MARKERS for ch in sample):
        return "uk"
    return "ru"


_WORD_RE = re.compile(r"[\w\u0400-\u04FF]+")


def is_english_task(text: str | None) -> bool:
    return detect_lang(text) == "en" and len(text or "") > 2
# --------------------------------------------------------------------------- предметы и стиль
TR.update(
    {
        "subject.math": {"ru": "математика", "uk": "математика", "be": "матэматыка", "en": "math"},
        "subject.physics": {"ru": "физика", "uk": "фізика", "be": "фізіка", "en": "physics"},
        "subject.chemistry": {"ru": "химия", "uk": "хімія", "be": "хімія", "en": "chemistry"},
        "subject.biology": {"ru": "биология", "uk": "біологія", "be": "біялогія", "en": "biology"},
        "subject.russian": {"ru": "русский", "uk": "російська", "be": "руская", "en": "Russian"},
        "subject.english": {"ru": "английский", "uk": "англійська", "be": "англійская", "en": "English"},
        "subject.cs": {"ru": "информатика", "uk": "інформатика", "be": "інфарматыка", "en": "CS"},
        "subject.other": {"ru": "другое", "uk": "інше", "be": "іншае", "en": "other"},
        "style.brief": {"ru": "кратко", "uk": "коротко", "be": "коратка", "en": "brief"},
        "style.detailed": {"ru": "подробно", "uk": "докладно", "be": "падрабязна", "en": "detailed"},
        "style.examples": {"ru": "с примерами", "uk": "з прикладами", "be": "з прыкладамі", "en": "with examples"},
    }
)


TR.update(
    {
        "help.support": {
            "ru": (
                "<b>Поддержка</b>\n"
                "<code>/support</code> \u2192 написать в поддержку: оплата, ошибки, доступ. "
                "Ответ придёт в личку.\n"
                "<code>/tickets</code> \u2192 твои обращения и их статус.\n"
                "<code>/paysupport</code> \u2192 что делать, если оплата не прошла.\n\n"
                "<b>В группе</b>\n"
                "Отвечаю, если написать <code>/ai вопрос</code>, ответить реплаем на моё "
                "сообщение, упомянуть @ или назвать меня «газява», «газик», «газировка».\n\n"
            ),
            "uk": (
                "<b>Підтримка</b>\n"
                "<code>/support</code> \u2192 написати в підтримку: оплата, помилки, доступ. "
                "Відповідь прийде в особисті.\n"
                "<code>/tickets</code> \u2192 твої звернення та їхній статус.\n"
                "<code>/paysupport</code> \u2192 що робити, якщо оплата не пройшла.\n\n"
                "<b>У групі</b>\n"
                "Відповідаю, якщо написати <code>/ai питання</code>, відповісти реплаєм на моє "
                "повідомлення, згадати @ або назвати мене «газява», «газик», «газировка».\n\n"
            ),
            "be": (
                "<b>Падтрымка</b>\n"
                "<code>/support</code> \u2192 напісаць у падтрымку: аплата, памылкі, доступ. "
                "Адказ прыйдзе ў асабістыя.\n"
                "<code>/tickets</code> \u2192 твае звароты і іхні статус.\n"
                "<code>/paysupport</code> \u2192 што рабіць, калі аплата не прайшла.\n\n"
                "<b>У групе</b>\n"
                "Адказваю, калі напісаць <code>/ai пытанне</code>, адказаць рэплаем на маё "
                "паведамленне, згадаць @ або назваць мяне «газява», «газік», «газіроўка».\n\n"
            ),
            "en": (
                "<b>Support</b>\n"
                "<code>/support</code> \u2192 contact support: payments, errors, access. "
                "The answer comes in DM.\n"
                "<code>/tickets</code> \u2192 your requests and their status.\n"
                "<code>/paysupport</code> \u2192 what to do if a payment failed.\n\n"
                "<b>In groups</b>\n"
                "I answer if you write <code>/ai question</code>, reply to my message, mention "
                "@ or call me \u201cgazyava\u201d, \u201cgazik\u201d, \u201cgazirovka\u201d.\n\n"
            ),
        },
    }
)
