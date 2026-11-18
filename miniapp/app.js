/* Mini App кабинет: данные — из /app/api/*, авторизация — initData Telegram. */
(function () {
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

  var THEME_BG = { dark: "#070a13", light: "#f3f5fd" };

  function currentScheme() {
    var scheme = "";
    try { scheme = (tg && tg.colorScheme) || ""; } catch (e) {}
    if (scheme !== "light" && scheme !== "dark") {
      try {
        scheme = (window.matchMedia &&
          window.matchMedia("(prefers-color-scheme: light)").matches) ? "light" : "dark";
      } catch (e) { scheme = "dark"; }
    }
    return scheme;
  }

  function applyTheme() {
    var over = state && state._themeOverride;
    var light = over === "light" || (over !== "dark" && currentScheme() === "light");
    var bg = light ? THEME_BG.light : THEME_BG.dark;
    document.documentElement.setAttribute("data-theme", light ? "light" : "dark");
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", bg);
    if (!tg) return;
    try { if (tg.setHeaderColor) tg.setHeaderColor(bg); } catch (e) {}
    try { if (tg.setBackgroundColor) tg.setBackgroundColor(bg); } catch (e) {}
    try { if (tg.setBottomBarColor) tg.setBottomBarColor(bg); } catch (e) {}
  }

  if (tg) {
    try { tg.ready(); } catch (e) {}
    try { tg.expand(); } catch (e) {}
    try { if (tg.onEvent) tg.onEvent("themeChanged", applyTheme); } catch (e) {}
  }

  function haptic(kind) {
    if (!tg || !tg.HapticFeedback) return;
    try {
      if (kind === "success" || kind === "error" || kind === "warning") {
        tg.HapticFeedback.notificationOccurred(kind);
      } else if (kind === "select") {
        tg.HapticFeedback.selectionChanged();
      } else {
        tg.HapticFeedback.impactOccurred(kind || "light");
      }
    } catch (e) {}
  }

  var STYLE_ORDER = ["auto", "expert", "study", "code"];
  var LANG_FLAG = { ru: "🇷🇺", uk: "🇺🇦", be: "🇧🇾", en: "🇬🇧" };
  var LANG_NAME = { ru: "Русский", uk: "Українська", be: "Беларуская", en: "English" };

  var I18N = {
    ru: {
      home: "Кабинет", stats: "Статистика", tasks: "Задачи", games: "Игры", friends: "Друзья", settings: "Настройки", back: "Назад",
      hello: "Привет, {name}!",
      left: "Осталось запросов", unlimited: "Без ограничений", today_used: "Сегодня использовано: {n}",
      bonus_title: "🎁 Бонус дня", bonus_claim: "Забрать бонус",
      bonus_claimed: "Бонус получен: +{amount}", bonus_already: "Бонус дня уже получен",
      bonus_streak: "Серия: {n} дн. подряд",
      bonus_hint: "Заходи каждый день — бонус растёт до {max}.",
      model: "Модель ИИ", style: "Стиль ответов", model_hint: "Модель меняется в боте командой /model.",
      tile_history: "История", tile_tools: "Инструменты", tile_buy: "Купить",
      stat_today: "Запросов сегодня", stat_total: "Всего запросов", stat_left: "Осталось",
      stat_bonus: "Бонусных запросов", stat_streak: "Серия бонусов", stat_invites: "Приглашено друзей",
      stat_images: "Бонусных картинок", days: "дн.",
      friends_title: "👥 Приглашай друзей",
      friends_hint: "За каждого нового друга: тебе +{reward}, другу +{friend} запросов.",
      friends_link: "Твоя ссылка", copy: "Скопировать", copied: "Ссылка скопирована",
      share: "Поделиться", friends_count: "Уже приглашено: {n}",
      friends_top: "Топ приглашающих", friends_empty: "Пока никого — стань первым!",
      settings_title: "⚙️ Настройки", language: "Язык", style_title: "Стиль ответов",
      saved: "Сохранено",
      sub_title: "🔒 Нужна подписка", sub_text: "Чтобы открыть кабинет, подпишись на канал.",
      sub_button: "📢 Подписаться", sub_check: "Я подписался",
      error_title: "Не получилось загрузить", error_text: "Открой кабинет заново из Telegram.",
      retry: "Повторить", loading: "Загрузка…",
      history_title: "💬 Последние ответы", history_empty: "Пока пусто — задай первый вопрос в чате.",
      history_note: "Показаны последние 12 ответов. Историю можно очистить командой /reset.",
      tools_title: "🧰 Инструменты",
      todos_title: "✅ Дела", todo_ph: "Новое дело…", todo_add: "Добавить", todo_clear: "Очистить",
      todo_empty: "Список пуст", todo_limit: "Достигнут предел списка",
      cards_title: "🃏 Карточки", card_q_ph: "Вопрос", card_a_ph: "Ответ", card_add: "Добавить карточку",
      card_empty: "Карточек пока нет", card_limit: "Достигнут предел карточек",
      card_need_both: "Нужны и вопрос, и ответ", card_show: "Показать ответ",
      reminders_title: "⏰ Напоминания", rem_ph: "Текст напоминания…", rem_dur_ph: "10м",
      rem_add: "Напоминание", rem_empty: "Напоминаний нет", rem_bad: "Не понял время — например 10м, 1ч30м",
      rem_limit: "Больше 10 напоминаний нельзя", rem_hint: "Время: 30с, 10м, 2ч, 1д. Придёт в этот чат.",
      buy_title: "⭐ Купить запросы", buy_disabled: "Пополнение сейчас отключено.",
      buy_balance: "Твой запас: {n} запросов", buy_packages: "Готовые наборы", pkg_requests: "запросов",
      buy_custom: "Своя сумма", buy_stars_ph: "Звёзд", buy_button: "Купить",
      buy_models: "Модели ИИ", buy_owned: "Куплено", buy_rate: "Курс: 1 ⭐ = {rate} запросов",
      paid: "Оплата получена, спасибо!", pay_failed: "Оплата не прошла", already_owned: "Уже куплено",
      added: "Добавлено", limit_reached: "Достигнут предел",
      styles: {
        auto: ["🌐 Универсальный", "сильный эксперт во всех темах"],
        expert: ["🚀 Максимум", "максимальная глубина и варианты"],
        study: ["🎓 Учебный", "репетитор объясняет по шагам"],
        code: ["💻 Кодерский", "senior-разработчик: полный код"]
      },
      share_text: "Заходи в {bot} — ИИ-помощник по учёбе. Разбирает задачи по шагам."
    },
    uk: {
      home: "Кабінет", stats: "Статистика", tasks: "Задачі", games: "Ігри", friends: "Друзі", settings: "Налаштування", back: "Назад",
      hello: "Привіт, {name}!",
      left: "Залишилось запитів", unlimited: "Без обмежень", today_used: "Сьогодні використано: {n}",
      bonus_title: "🎁 Бонус дня", bonus_claim: "Забрати бонус",
      bonus_claimed: "Бонус отримано: +{amount}", bonus_already: "Бонус дня вже отримано",
      bonus_streak: "Серія: {n} дн. підряд",
      bonus_hint: "Заходь щодня — бонус зростає до {max}.",
      model: "Модель ШІ", style: "Стиль відповідей", model_hint: "Модель змінюється в боті командою /model.",
      tile_history: "Історія", tile_tools: "Інструменти", tile_buy: "Купити",
      stat_today: "Запитів сьогодні", stat_total: "Усього запитів", stat_left: "Залишилось",
      stat_bonus: "Бонусних запитів", stat_streak: "Серія бонусів", stat_invites: "Запрошено друзів",
      stat_images: "Бонусних картинок", days: "дн.",
      friends_title: "👥 Запрошуй друзів",
      friends_hint: "За кожного нового друга: тобі +{reward}, другу +{friend} запитів.",
      friends_link: "Твоє посилання", copy: "Скопіювати", copied: "Посилання скопійовано",
      share: "Поділитися", friends_count: "Уже запрошено: {n}",
      friends_top: "Топ запрошуючих", friends_empty: "Поки нікого — стань першим!",
      settings_title: "⚙️ Налаштування", language: "Мова", style_title: "Стиль відповідей",
      saved: "Збережено",
      sub_title: "🔒 Потрібна підписка", sub_text: "Щоб відкрити кабінет, підпишись на канал.",
      sub_button: "📢 Підписатися", sub_check: "Я підписався",
      error_title: "Не вдалося завантажити", error_text: "Відкрий кабінет заново з Telegram.",
      retry: "Повторити", loading: "Завантаження…",
      history_title: "💬 Останні відповіді", history_empty: "Поки порожньо — постав перше питання в чаті.",
      history_note: "Показано останні 12 відповідей. Історію можна очистити командою /reset.",
      tools_title: "🧰 Інструменти",
      todos_title: "✅ Справи", todo_ph: "Нова справа…", todo_add: "Додати", todo_clear: "Очистити",
      todo_empty: "Список порожній", todo_limit: "Досягнуто межі списку",
      cards_title: "🃏 Картки", card_q_ph: "Питання", card_a_ph: "Відповідь", card_add: "Додати картку",
      card_empty: "Карток поки немає", card_limit: "Досягнуто межі карток",
      card_need_both: "Потрібні і питання, і відповідь", card_show: "Показати відповідь",
      reminders_title: "⏰ Нагадування", rem_ph: "Текст нагадування…", rem_dur_ph: "10х",
      rem_add: "Нагадування", rem_empty: "Нагадувань немає", rem_bad: "Не зрозумів час — наприклад 10х, 1г30х",
      rem_limit: "Більше 10 нагадувань не можна", rem_hint: "Час: 30с, 10х, 2г, 1д. Прийде в цей чат.",
      buy_title: "⭐ Купити запити", buy_disabled: "Поповнення зараз вимкнене.",
      buy_balance: "Твій запас: {n} запитів", buy_packages: "Готові набори", pkg_requests: "запитів",
      buy_custom: "Своя сума", buy_stars_ph: "Зірок", buy_button: "Купити",
      buy_models: "Моделі ШІ", buy_owned: "Куплено", buy_rate: "Курс: 1 ⭐ = {rate} запитів",
      paid: "Оплату отримано, дякую!", pay_failed: "Оплата не пройшла", already_owned: "Уже куплено",
      added: "Додано", limit_reached: "Досягнуто межі",
      styles: {
        auto: ["🌐 Універсальний", "сильний експерт у всіх темах"],
        expert: ["🚀 Максимум", "максимальна глибина й варіанти"],
        study: ["🎓 Навчальний", "репетитор пояснює покроково"],
        code: ["💻 Кодерський", "senior-розробник: повний код"]
      },
      share_text: "Заходь у {bot} — ШІ-помічник з навчання. Розбирає задачі покроково."
    },
    be: {
      home: "Кабінет", stats: "Статыстыка", tasks: "Задачы", tasks: "Задачы", games: "Гульні", friends: "Сябры", settings: "Налады", back: "Назад",
      hello: "Прывітанне, {name}!",
      left: "Засталося запытаў", unlimited: "Без абмежаванняў", today_used: "Сёння выкарыстана: {n}",
      bonus_title: "🎁 Бонус дня", bonus_claim: "Забраць бонус",
      bonus_claimed: "Бонус атрыманы: +{amount}", bonus_already: "Бонус дня ўжо атрыманы",
      bonus_streak: "Серыя: {n} дз. запар",
      bonus_hint: "Заходзь штодня — бонус расце да {max}.",
      model: "Мадэль ШІ", style: "Стыль адказаў", model_hint: "Мадэль змяняецца ў боце камандай /model.",
      tile_history: "Гісторыя", tile_tools: "Інструменты", tile_buy: "Купіць",
      stat_today: "Запытаў сёння", stat_total: "Усяго запытаў", stat_left: "Засталося",
      stat_bonus: "Бонусных запытаў", stat_streak: "Серыя бонусаў", stat_invites: "Запрошана сяброў",
      stat_images: "Бонусных малюнкаў", days: "дз.",
      friends_title: "👥 Запрашай сяброў",
      friends_hint: "За кожнага новага сябра: табе +{reward}, сябру +{friend} запытаў.",
      friends_link: "Тваё спасылка", copy: "Скапіраваць", copied: "Спасылка скапіравана",
      share: "Падзяліцца", friends_count: "Ужо запрошана: {n}",
      friends_top: "Топ запрашальнікаў", friends_empty: "Пакуль нікога — стань першым!",
      settings_title: "⚙️ Налады", language: "Мова", style_title: "Стыль адказаў",
      saved: "Захавана",
      sub_title: "🔒 Патрэбна падпіска", sub_text: "Каб адкрыць кабінет, падпішыся на канал.",
      sub_button: "📢 Падпісацца", sub_check: "Я падпісаўся",
      error_title: "Не ўдалося загрузіць", error_text: "Адкрый кабінет зноў з Telegram.",
      retry: "Паўтарыць", loading: "Загрузка…",
      history_title: "💬 Апошнія адказы", history_empty: "Пакуль пуста — задай першае пытанне ў чаце.",
      history_note: "Паказаны апошнія 12 адказаў. Гісторыю можна ачысціць камандай /reset.",
      tools_title: "🧰 Інструменты",
      todos_title: "✅ Справы", todo_ph: "Новая справа…", todo_add: "Дадаць", todo_clear: "Ачысціць",
      todo_empty: "Спіс пусты", todo_limit: "Дасягнута мяжа спісу",
      cards_title: "🃏 Карткі", card_q_ph: "Пытанне", card_a_ph: "Адказ", card_add: "Дадаць картку",
      card_empty: "Картак пакуль няма", card_limit: "Дасягнута мяжа картак",
      card_need_both: "Патрэбны і пытанне, і адказ", card_show: "Паказаць адказ",
      reminders_title: "⏰ Напаміны", rem_ph: "Тэкст напаміну…", rem_dur_ph: "10х",
      rem_add: "Напамін", rem_empty: "Напамінаў няма", rem_bad: "Не зразумеў час — напрыклад 10х, 1г30х",
      rem_limit: "Больш за 10 напамінаў нельга", rem_hint: "Час: 30с, 10х, 2г, 1д. Прыйдзе ў гэты чат.",
      buy_title: "⭐ Купіць запыты", buy_disabled: "Папаўненне зараз выключана.",
      buy_balance: "Твой запас: {n} запытаў", buy_packages: "Гатовыя наборы", pkg_requests: "запытаў",
      buy_custom: "Свая сума", buy_stars_ph: "Зорак", buy_button: "Купіць",
      buy_models: "Мадэлі ШІ", buy_owned: "Куплена", buy_rate: "Курс: 1 ⭐ = {rate} запытаў",
      paid: "Аплату атрымана, дзякуй!", pay_failed: "Аплата не прайшла", already_owned: "Ужо куплена",
      added: "Дададзена", limit_reached: "Дасягнута мяжа",
      styles: {
        auto: ["🌐 Універсальны", "моцны эксперт ва ўсіх тэмах"],
        expert: ["🚀 Максімум", "максімальная глыбіня і варыянты"],
        study: ["🎓 Навучальны", "рэпетытар тлумачыць па кроках"],
        code: ["💻 Кодэрскі", "senior-распрацоўшчык: поўны код"]
      },
      share_text: "Заходзь у {bot} — ШІ-памочнік па вучобе. Разбірае задачы па кроках."
    },
    en: {
      home: "Home", stats: "Stats", tasks: "Tasks", tasks: "Tasks", games: "Games", friends: "Friends", settings: "Settings", back: "Back",
      hello: "Hi, {name}!",
      left: "Requests left", unlimited: "Unlimited", today_used: "Used today: {n}",
      bonus_title: "🎁 Daily bonus", bonus_claim: "Claim bonus",
      bonus_claimed: "Bonus claimed: +{amount}", bonus_already: "Today's bonus is already claimed",
      bonus_streak: "Streak: {n} day(s)",
      bonus_hint: "Come back every day — the bonus grows up to {max}.",
      model: "AI model", style: "Answer style", model_hint: "Change the model in the bot with /model.",
      tile_history: "History", tile_tools: "Tools", tile_buy: "Buy",
      stat_today: "Requests today", stat_total: "Total requests", stat_left: "Left",
      stat_bonus: "Bonus requests", stat_streak: "Bonus streak", stat_invites: "Friends invited",
      stat_images: "Bonus images", days: "d",
      friends_title: "👥 Invite friends",
      friends_hint: "For each new friend: you get +{reward}, your friend gets +{friend} requests.",
      friends_link: "Your link", copy: "Copy", copied: "Link copied",
      share: "Share", friends_count: "Invited so far: {n}",
      friends_top: "Top inviters", friends_empty: "Nobody yet — be the first!",
      settings_title: "⚙️ Settings", language: "Language", style_title: "Answer style",
      saved: "Saved",
      sub_title: "🔒 Subscription required", sub_text: "Subscribe to the channel to open the dashboard.",
      sub_button: "📢 Subscribe", sub_check: "I subscribed",
      error_title: "Failed to load", error_text: "Open the dashboard again from Telegram.",
      retry: "Retry", loading: "Loading…",
      history_title: "💬 Recent answers", history_empty: "Empty so far — ask your first question in the chat.",
      history_note: "Showing the last 12 answers. You can clear history with /reset.",
      tools_title: "🧰 Tools",
      todos_title: "✅ To-dos", todo_ph: "New task…", todo_add: "Add", todo_clear: "Clear",
      todo_empty: "The list is empty", todo_limit: "List limit reached",
      cards_title: "🃏 Flashcards", card_q_ph: "Question", card_a_ph: "Answer", card_add: "Add card",
      card_empty: "No flashcards yet", card_limit: "Card limit reached",
      card_need_both: "Both question and answer are required", card_show: "Show answer",
      reminders_title: "⏰ Reminders", rem_ph: "Reminder text…", rem_dur_ph: "10m",
      rem_add: "Reminder", rem_empty: "No reminders", rem_bad: "Couldn't read the time — e.g. 10m, 1h30m",
      rem_limit: "No more than 10 reminders", rem_hint: "Time: 30s, 10m, 2h, 1d. Delivered to this chat.",
      buy_title: "⭐ Buy requests", buy_disabled: "Top-ups are disabled right now.",
      buy_balance: "Your balance: {n} requests", buy_packages: "Ready packages", pkg_requests: "requests",
      buy_custom: "Custom amount", buy_stars_ph: "Stars", buy_button: "Buy",
      buy_models: "AI models", buy_owned: "Owned", buy_rate: "Rate: 1 ⭐ = {rate} requests",
      paid: "Payment received, thank you!", pay_failed: "Payment failed", already_owned: "Already owned",
      added: "Added", limit_reached: "Limit reached",
      styles: {
        auto: ["🌐 Universal", "a strong expert in every topic"],
        expert: ["🚀 Maximum", "maximum depth and options"],
        study: ["🎓 Study", "a tutor explains step by step"],
        code: ["💻 Code", "senior developer: full code"]
      },
      share_text: "Join {bot} — an AI study helper that solves tasks step by step."
    }
  };

  var state = {
    lang: "ru",
    tab: "home",
    screen: null,
    me: null,
    top: null,
    history: null,
    tools: null,
    buy: null,
    revealed: {},
    paywall: null,
    busy: false,
    fatal: null,
    answerData: null,
    answerLoading: null,
    _langReady: false
  };

  var view = document.getElementById("view");
  var tabsEl = document.getElementById("tabs");
  var brandEl = document.getElementById("brand-name");
  var toastEl = document.getElementById("toast");
  var toastTimer = null;

  applyTheme();

  function detectLang() {
    var code = "";
    try {
      code = (tg && tg.initDataUnsafe && tg.initDataUnsafe.user &&
        tg.initDataUnsafe.user.language_code) || navigator.language || "ru";
    } catch (e) { code = "ru"; }
    code = String(code).slice(0, 2).toLowerCase();
    return I18N[code] ? code : "ru";
  }

  function dict() { return I18N[state.lang] || I18N.ru; }

  function t(key, vars) {
    var value = dict()[key];
    if (value == null) value = I18N.ru[key];
    if (value == null) return key;
    if (vars) {
      Object.keys(vars).forEach(function (k) {
        value = value.replace(new RegExp("\\{" + k + "\\}", "g"), String(vars[k]));
      });
    }
    return value;
  }

  function countUp(el, target, duration) {
    if (!el || isNaN(target) || target <= 0) return;
    var start = performance.now();
    function step(now) {
      var elapsed = now - start;
      var progress = Math.min(1, elapsed / duration);
      var eased = 1 - Math.pow(1 - progress, 3);
      el.textContent = Math.round(target * eased);
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function sanitizeHTML(text) {
    var allowed = { b:1, i:1, u:1, s:1, code:1, pre:1, br:1, strong:1, em:1, a:1, span:1, div:1, sup:1, sub:1 };
    return String(text || "").replace(/<\/?([a-zA-Z][a-zA-Z0-9]*)\b[^>]*>/g, function (m, tag) {
      return allowed[tag.toLowerCase()] ? m : m.replace(/</g, "&lt;");
    }).replace(/&(?!(?:amp|lt|gt|quot|#39);)/g, "&amp;");
  }

  function formatAnswer(html) {
    var safe = String(html || "");
    // конвертируем базовый markdown в HTML
    safe = safe.replace(/```(\w*)\n([\s\S]*?)```/g, function (_, lang, code) {
      return "<pre><code>" + code.replace(/</g, "&lt;") + "</code></pre>";
    });
    safe = safe.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    safe = safe.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
    safe = safe.replace(/\b__([^_]+)__\b/g, "<b>$1</b>");
    safe = safe.replace(/\*(.+?)\*/g, "<i>$1</i>");
    // эмодзи-заголовки секций (📌 Задание, 🧮 Решение, ✅ Ответ)
    safe = safe.replace(/(^|\n)([📌🧮✅⚠️💡📝➕➖✖️➗🔹🔸▪️▫️🔷🔶🔺🔻1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣8️⃣9️⃣🔟]\s*[^\n<]+)/g,
      '$1<div class="ans-label">$2</div>');
    // дроби: 3/8 → надстрочный вид
    safe = safe.replace(/(\d+)\s*\/\s*(\d+)/g,
      '<span class="frac"><span class="fnum">$1</span><span class="fbar"></span><span class="fden">$2</span></span>');
    return sanitizeHTML(safe);
  }

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 1900);
  }

  function val(id) {
    var node = document.getElementById(id);
    return node ? node.value : "";
  }

  function when(iso) {
    if (!iso) return "";
    var date = new Date(iso);
    if (isNaN(date.getTime())) return "";
    try {
      return date.toLocaleString([], { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
    } catch (e) { return iso; }
  }

  function api(method, payload) {
    var initData = tg ? (tg.initData || "") : "";
    return fetch("/app/api/" + method, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.assign({ init_data: initData }, payload || {}))
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          var err = new Error(data.error || "http_" + res.status);
          err.status = res.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  // ---------------------------------------------------------------- рендер
  function renderAnswerScreen() {
    if (!state.answerData) {
      view.innerHTML = subHeader("📱 Ответ") + '<div class="skeleton"></div>';
      return;
    }
    var a = state.answerData;
    view.innerHTML =
      subHeader("📱 Ответ") +
      '<div class="card">' +
      '<div class="row-sub" style="margin-bottom:6px">' + esc(t("model")) + " · " + esc(when(a.created_at)) + "</div>" +
      "<b>" + esc(a.question || "") + "</b>" +
      "</div>" +
      '<div class="card answer-body">' + formatAnswer(a.answer || "") + "</div>" +
      '<button class="btn secondary" data-action="copy-answer" style="margin-top:8px">📋 ' + esc(t("copy")) + "</button>";
  }

  function loadAnswer(id) {
    state.answerLoading = id;
    render();
    api("answer", { id: id }).then(function (data) {
      state.answerData = data;
      state.answerLoading = null;
      state.screen = "answer";
      render();
    }).catch(function () {
      state.answerLoading = null;
      toast(t("error_text"));
      state.screen = null;
      render();
    });
  }

  function tabButton(key, icon) {
    var active = state.tab === key ? " active" : "";
    return '<button class="tab' + active + '" data-action="tab" data-value="' + key +
      '" role="tab" aria-selected="' + (state.tab === key) + '">' +
      '<span class="tab-icon">' + icon + '</span><span>' + esc(t(key)) + "</span></button>";
  }

  function renderTabs() {
    tabsEl.innerHTML =
      tabButton("home", "🏠") + tabButton("stats", "📈") +
      tabButton("tasks", "🎯") +
      tabButton("friends", "👥") + tabButton("games", "🎲") + tabButton("settings", "⚙️");
  }

  function statCard(value, label) {
    return '<div class="stat"><div class="stat-value">' + esc(value) +
      '</div><div class="stat-label">' + esc(label) + "</div></div>";
  }

  function subHeader(title) {
    return '<div class="head"><button class="back" data-action="back">← ' + esc(t("back")) +
      "</button></div><h1>" + esc(title) + "</h1>";
  }

  function renderHome() {
    var me = state.me;
    var name = (me.user.first_name || me.user.username || "").trim();

    var tiles = '<div class="tiles">' +
      '<button class="tile" data-action="open" data-value="history">' +
      '<span class="tile-icon">💬</span><span>' + esc(t("tile_history")) + "</span></button>" +
      '<button class="tile" data-action="open" data-value="tools">' +
      '<span class="tile-icon">🧰</span><span>' + esc(t("tile_tools")) + "</span></button>" +
      (me.payments_enabled
        ? '<button class="tile" data-action="open" data-value="buy">' +
          '<span class="tile-icon">⭐</span><span>' + esc(t("tile_buy")) + "</span></button>"
        : "") +
      "</div>";

    var bonus;
    if (me.bonus_claimed_today) {
      bonus = '<div class="row"><div><div class="row-title">' + esc(t("bonus_already")) +
        '</div><div class="row-sub">' + esc(t("bonus_streak", { n: me.bonus_streak })) +
        "</div></div></div>";
    } else {
      bonus = '<button class="btn" data-action="claim"' + (state.busy ? " disabled" : "") +
        ">" + esc(t("bonus_claim")) + "</button>" +
        '<div class="muted center" style="margin-top:8px">' +
        esc(t("bonus_hint", { max: me.bonus_max })) + "</div>";
    }

    var styleMeta = dict().styles[me.style] || [];
    view.innerHTML =
      tiles +
      '<div class="card hero">' +
      '<div style="opacity:.9">' + esc(t("hello", { name: name })) + "</div>" +
      '<div class="value">' + (me.unlimited ? "∞" : esc(me.remaining)) + "</div>" +
      '<div class="sub">' + (me.unlimited ? esc(t("unlimited")) : esc(t("left"))) + "</div>" +
      "</div>" +
      "<h2>" + esc(t("bonus_title")) + "</h2>" +
      '<div class="card">' + bonus + "</div>" +
      "<h2>" + esc(t("model")) + " · " + esc(t("style")) + "</h2>" +
      '<div class="card"><div class="row"><div><div class="row-title">' +
      esc(me.model.title) + '</div><div class="row-sub">' + esc(t("model")) +
      '</div></div></div><div class="row"><div><div class="row-title">' +
      esc(styleMeta[0] || me.style) + '</div><div class="row-sub">' + esc(styleMeta[1] || "") +
      "</div></div></div>" +
      '<div class="model-chips">' +
      (me.models || []).map(function (m) {
        var active = m.id === me.model.id ? " active" : "";
        return '<button class="model-chip' + active + '" data-action="set-model" data-value="' + esc(m.id) + '">' + esc(m.title) + "</button>";
      }).join("") +
      "</div></div>";

    // Анимация счётчика в герое (только один раз за сессию)
    if (!state._heroAnimated && !me.unlimited && me.remaining > 0) {
      setTimeout(function () {
        var el = document.querySelector(".hero .value");
        if (el) { countUp(el, me.remaining, 700); state._heroAnimated = true; }
      }, 120);
    }
  }

  function renderStats() {
    var me = state.me;
    var left = me.unlimited ? "∞" : me.remaining;
    view.innerHTML =
      "<h1>" + esc(t("stats")) + "</h1>" +
      '<div class="grid">' +
      statCard(me.used_today, t("stat_today")) +
      statCard(me.total_requests, t("stat_total")) +
      statCard(left, t("stat_left")) +
      statCard(me.bonus_requests, t("stat_bonus")) +
      statCard(me.bonus_streak + " " + t("days"), t("stat_streak")) +
      statCard(me.invites, t("stat_invites")) +
      statCard(me.image_credits, t("stat_images")) +
      "</div>";
  }

  function renderFriends() {
    var me = state.me;
    var top = state.top || [];
    var rows = top.length
      ? top.map(function (row, i) {
          var medal = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : (i + 1);
          return '<div class="top-item"><div class="rank">' + medal + '</div><div class="who">' +
            esc(row.name) + '</div><div class="count">' + esc(row.count) + "</div></div>";
        }).join("")
      : '<div class="empty">' + esc(t("friends_empty")) + "</div>";

    view.innerHTML =
      "<h1>" + esc(t("friends_title")) + "</h1>" +
      '<div class="card">' +
      '<div class="muted">' + esc(t("friends_hint", { reward: me.invite_reward, friend: me.invited_reward })) + "</div>" +
      '<div class="muted" style="margin:12px 0 6px">' + esc(t("friends_link")) + "</div>" +
      '<div class="link-box"><code>' + esc(me.invite_link || "—") + "</code></div>" +
      '<button class="btn" data-action="copy" style="margin-top:12px">📋 ' + esc(t("copy")) + "</button>" +
      '<button class="btn secondary" data-action="share">📤 ' + esc(t("share")) + "</button>" +
      '<div class="muted center" style="margin-top:10px">' +
      esc(t("friends_count", { n: me.invites })) + "</div>" +
      "</div>" +
      "<h2>" + esc(t("friends_top")) + "</h2>" +
      '<div class="card">' + rows + "</div>";
  }

  function renderSettings() {
    var me = state.me;
    var langs = (me.langs || ["ru", "uk", "be", "en"]).map(function (code) {
      return '<button class="chip' + (code === state.lang ? " active" : "") +
        '" data-action="set-lang" data-value="' + code + '">' +
        (LANG_FLAG[code] || "") + " " + esc(LANG_NAME[code] || code) + "</button>";
    }).join("");

    var styles = STYLE_ORDER.map(function (key) {
      var meta = dict().styles[key] || [];
      return '<div class="row"><div><div class="row-title">' + esc(meta[0] || key) +
        '</div><div class="row-sub">' + esc(meta[1] || "") + '</div></div>' +
        '<button class="chip' + (key === me.style ? " active" : "") +
        '" data-action="set-style" data-value="' + key + '">' +
        (key === me.style ? "✓" : "→") + "</button></div>";
    }).join("");

      // модель ИИ — быстрая смена
      var models = (me.models || []).map(function (m) {
        return '<button class="chip' + (m.id === me.model.id ? " active" : "") +
          '" data-action="set-model" data-value="' + esc(m.id) + '">' + esc(m.title) + "</button>";
      }).join("");

      // тема — переключатель
      var themeLabel = (state._themeOverride === "light" ? "☀️" : state._themeOverride === "dark" ? "🌙" : "🔄");
      var themeBtn = '<button class="btn secondary" data-action="toggle-theme" style="margin-top:8px">' +
        themeLabel + " " + esc(t("theme_switch") || "Theme: auto") + "</button>";

      view.innerHTML =
        "<h1>" + esc(t("settings_title")) + "</h1>" +
        "<h2>" + esc(t("language")) + "</h2>" +
        '<div class="card"><div class="chips">' + langs + "</div></div>" +
        "<h2>" + esc(t("style_title")) + "</h2>" +
        '<div class="card">' + styles + "</div>" +
        "<h2>" + esc(t("model")) + "</h2>" +
        '<div class="card"><div class="chips">' + models + "</div>" + themeBtn + "</div>";
    }

  function renderGames() {
    view.innerHTML =
      "<h1>🎲 " + esc(t("games")) + "</h1>" +
      '<div class="grid">' +
      '<div class="card game-card center" data-action="game-dice"><div id="dice-face" style="font-size:44px;transition:transform .2s">🎲</div><div class="muted" style="margin-top:6px">Кубик</div></div>' +
      '<div class="card game-card center" data-action="game-coin"><div id="coin-flip" style="font-size:44px;transition:transform .2s">🪙</div><div class="muted" style="margin-top:6px">Монетка</div></div>' +
      '<div class="card game-card center" data-action="game-num"><div id="num-slot" style="font-size:32px;font-weight:800;color:var(--ink);width:64px;height:64px;display:grid;place-items:center;border-radius:14px;background:var(--s2);margin:0 auto">?</div><div class="muted" style="margin-top:6px">Число</div></div>' +
      '<div class="card game-card center" data-action="game-rps"><div id="rps-result" style="font-size:44px">✊</div><div class="muted" style="margin-top:6px">КНБ</div><div id="rps-btns" style="display:flex;gap:6px;justify-content:center;margin-top:6px"><button class="chip" data-action="rps-pick" data-value="0">✊</button><button class="chip" data-action="rps-pick" data-value="1">✋</button><button class="chip" data-action="rps-pick" data-value="2">✌️</button></div></div>' +
      '<div class="card game-card center" data-action="game-slots"><div id="slots-reels" style="font-size:36px;letter-spacing:4px">🍒🍋🍊</div><div class="muted" style="margin-top:6px">Слоты</div></div>' +
      '<div class="card game-card center" data-action="game-8ball"><div id="ball-answer" style="font-size:44px">🔮</div><div id="ball-text" class="muted" style="margin-top:6px">Шар судьбы</div></div>' +
      "</div>";
  }

  function rollDice() {
    var el = document.getElementById("dice-face"); if (!el) return;
    var faces = ["⚀","⚁","⚂","⚃","⚄","⚅"];
    var i = 0, steps = 12;
    function step() {
      el.textContent = faces[Math.floor(Math.random()*6)];
      el.style.transform = "rotate(" + (Math.random()*360) + "deg) scale(1.3)";
      i++; if (i < steps) setTimeout(step, 60 + i*8);
      else { el.textContent = faces[Math.floor(Math.random()*6)]; el.style.transform = "rotate(0deg) scale(1)"; haptic("success"); }
    }
    step();
  }

  function flipCoin() {
    var el = document.getElementById("coin-flip"); if (!el) return;
    var result = Math.random() < 0.5 ? "🦅" : "🪙";
    var i = 0, spins = 8;
    function spin() {
      el.textContent = i % 2 ? "🪙" : "🦅";
      el.style.transform = "rotateY(" + (i * 45) + "deg)";
      i++; if (i < spins) setTimeout(spin, 70 + i * 5);
      else { el.textContent = result; el.style.transform = "rotateY(0deg)"; haptic("success"); }
    }
    spin();
  }

  function randNum() {
    var el = document.getElementById("num-slot"); if (!el) return;
    var target = Math.floor(Math.random() * 100) + 1;
    var i = 0, steps = 15;
    function tick() {
      el.textContent = Math.floor(Math.random() * 100) + 1;
      el.style.transform = "scale(1.2)";
      i++; if (i < steps) setTimeout(tick, 50 + i * 6);
      else { el.textContent = target; el.style.transform = "scale(1)"; haptic("success"); }
    }
    tick();
  }

  function playRPS(choice) {
    var el = document.getElementById("rps-result"); if (!el) return;
    var hands = ["✊","✋","✌️"];
    var cpu = Math.floor(Math.random()*3);
    var i = 0, steps = 8;
    function shake() {
      el.textContent = hands[i % 3];
      el.style.transform = "scale(1.2) rotate(" + (i*15-60) + "deg)";
      i++; if (i < steps) setTimeout(shake, 80);
      else {
        el.textContent = hands[choice] + " vs " + hands[cpu];
        el.style.transform = "scale(1)";
        var win = (choice === 0 && cpu === 2) || (choice === 1 && cpu === 0) || (choice === 2 && cpu === 1);
        var draw = choice === cpu;
        haptic(draw ? "warning" : win ? "success" : "error");
        toast(draw ? "Ничья!" : win ? "Ты победил! 🎉" : "Компьютер выиграл 🤖");
      }
    }
    shake();
  }

  function playSlots() {
    var el = document.getElementById("slots-reels"); if (!el) return;
    var symbols = ["🍒","🍋","🍊","🍇","⭐","💎","7️⃣"];
    var reels = [0,0,0], stopped = [false,false,false];
    var i = 0;
    function spin() {
      for (var r = 0; r < 3; r++) {
        if (!stopped[r]) reels[r] = Math.floor(Math.random()*symbols.length);
      }
      el.textContent = symbols[reels[0]] + symbols[reels[1]] + symbols[reels[2]];
      el.style.transform = "scale(1.05)";
      i++;
      if (i === 10) stopped[0] = true;
      if (i === 16) stopped[1] = true;
      if (i === 22) { stopped[2] = true; el.style.transform = "scale(1)";
        var jackpot = reels[0] === reels[1] && reels[1] === reels[2];
        haptic(jackpot ? "success" : "light");
        if (jackpot) toast("ДЖЕКПОТ! " + symbols[reels[0]] + symbols[reels[0]] + symbols[reels[0]] + " 🎉");
        return;
      }
      setTimeout(spin, 60 + i*4);
    }
    spin();
  }

  function play8Ball() {
    var el = document.getElementById("ball-answer");
    var txt = document.getElementById("ball-text");
    if (!el) return;
    var answers = ["Да!","Нет.","Возможно…","Определённо да","Спроси позже","Не рассчитывай","Знаки говорят да","Мой ответ — нет","Без сомнений","Перспективы хороши","Сконцентрируйся и спроси снова","Даже не думай","Звёзды говорят да","Туманно, попробуй ещё"];
    var i = 0, steps = 10;
    function shake() {
      el.textContent = "🔮";
      el.style.transform = "translateX(" + (Math.random()*16-8) + "px) rotate(" + (Math.random()*20-10) + "deg)";
      i++; if (i < steps) setTimeout(shake, 70);
      else {
        el.textContent = "🎱";
        el.style.transform = "none";
        txt.textContent = answers[Math.floor(Math.random()*answers.length)];
        txt.style.color = "var(--ink)";
        txt.style.fontWeight = "700";
        haptic("success");
      }
    }
    shake();
  }

  function renderHistory() {
    if (state.history === null) {
      view.innerHTML = subHeader(t("history_title")) + '<div class="skeleton"></div>';
      return;
    }
    var items = state.history;
    var body = items.length
      ? items.map(function (item, i) {
          var open = !!state.revealed["h" + i];
          return '<div class="item flip" data-action="flip-hist" data-value="' + i + '">' +
            '<div class="body"><div><b>' + esc(item.question || "—") + "</b></div>" +
            '<div class="when">' + esc(when(item.created_at)) + "</div>" +
            (open ? '<div class="reveal">' + esc(item.answer || "") + "</div>" : "") +
            "</div><div class='del'>" + (open ? "▾" : "▸") + "</div></div>";
        }).join("")
      : '<div class="empty">' + esc(t("history_empty")) + "</div>";

    view.innerHTML =
      subHeader(t("history_title")) +
      '<div class="card">' + body + "</div>" +
      '<div class="muted center">' + esc(t("history_note")) + "</div>";
  }

  function renderTools() {
    if (state.tools === null) {
      view.innerHTML = subHeader(t("tools_title")) + '<div class="skeleton"></div>';
      return;
    }
    var data = state.tools;
    var limits = data.limits || {};

    var todos = data.todos.length
      ? data.todos.map(function (text, i) {
          return '<div class="item"><div class="body">' + esc(text) +
            '</div><button class="del" data-action="todo-del" data-value="' + (i + 1) + '">✕</button></div>';
        }).join("")
      : '<div class="empty">' + esc(t("todo_empty")) + "</div>";

    var cards = data.cards.length
      ? data.cards.map(function (card, i) {
          var open = !!state.revealed["c" + i];
          return '<div class="item"><div class="body flip" data-action="flip-card" data-value="' + i + '">' +
            "<b>" + esc(card.q) + "</b>" +
            (open ? '<div class="reveal">' + esc(card.a) + "</div>" : "") +
            '</div><button class="del" data-action="card-del" data-value="' + (i + 1) + '">✕</button></div>';
        }).join("")
      : '<div class="empty">' + esc(t("card_empty")) + "</div>";

    var rems = data.reminders.length
      ? data.reminders.map(function (item) {
          var icon = item.kind === "timer" ? "⏳" : "🔔";
          return '<div class="item"><div class="body">' + icon + " " + esc(item.text) +
            '<div class="when">' + esc(when(item.due)) + "</div></div>" +
            '<button class="del" data-action="rem-del" data-value="' + esc(item.id) + '">✕</button></div>';
        }).join("")
      : '<div class="empty">' + esc(t("rem_empty")) + "</div>";

    view.innerHTML =
      subHeader(t("tools_title")) +
      "<h2>" + esc(t("todos_title")) + " · " + data.todos.length + "/" + esc(limits.todos || "?") + "</h2>" +
      '<div class="card">' + todos +
      '<div class="field"><input class="input" id="todo-input" placeholder="' + esc(t("todo_ph")) + '">' +
      '<button class="btn small" data-action="todo-add">+</button></div>' +
      (data.todos.length ? '<button class="btn secondary" data-action="todo-clear">' + esc(t("todo_clear")) + "</button>" : "") +
      "</div>" +
      "<h2>" + esc(t("cards_title")) + " · " + data.cards.length + "/" + esc(limits.cards || "?") + "</h2>" +
      '<div class="card">' + cards +
      '<div class="field"><input class="input" id="card-q" placeholder="' + esc(t("card_q_ph")) + '"></div>' +
      '<div class="field"><input class="input" id="card-a" placeholder="' + esc(t("card_a_ph")) + '">' +
      '<button class="btn small" data-action="card-add">+</button></div>' +
      "</div>" +
      "<h2>" + esc(t("reminders_title")) + " · " + data.reminders.length + "/" + esc(limits.reminders || "?") + "</h2>" +
      '<div class="card">' + rems +
      '<div class="field"><input class="input" id="rem-text" placeholder="' + esc(t("rem_ph")) + '"></div>' +
      '<div class="field"><input class="input" id="rem-dur" placeholder="' + esc(t("rem_dur_ph")) + '">' +
      '<button class="btn small" data-action="rem-add">+</button></div>' +
      '<div class="muted" style="margin-top:8px">' + esc(t("rem_hint")) + "</div>" +
      "</div>";
  }

  function renderBuy() {
    if (state.buy === null) {
      view.innerHTML = subHeader(t("buy_title")) + '<div class="skeleton"></div>';
      return;
    }
    var data = state.buy;
    if (!data.enabled) {
      view.innerHTML = subHeader(t("buy_title")) +
        '<div class="card center"><div style="font-size:36px">⭐</div>' +
        '<div class="muted">' + esc(t("buy_disabled")) + "</div></div>";
      return;
    }

    var packages = data.packages.length
      ? '<div class="pkgs">' + data.packages.map(function (p) {
          return '<button class="pkg" data-action="invoice" data-requests="' + p.requests +
            '" data-stars="' + p.stars + '">' +
            '<span class="pkg-num">' + esc(p.requests) + "</span>" +
            '<span class="pkg-sub">' + esc(t("pkg_requests")) + "</span>" +
            '<span class="pkg-star">' + esc(p.stars) + " ⭐</span></button>";
        }).join("") + "</div>"
      : "";

    var models = data.models.map(function (m) {
      var owned = m.owned;
      return '<div class="row"><div><div class="row-title">' + esc(m.title) +
        '</div><div class="row-sub">' + esc(m.hint || "") + "</div></div>" +
        (owned
          ? '<span class="muted">' + esc(t("buy_owned")) + "</span>"
          : '<button class="btn small" data-action="invoice" data-model="' + esc(m.id) + '">' +
            esc(m.stars) + " ⭐</button>") +
        "</div>";
    }).join("");

    view.innerHTML =
      subHeader(t("buy_title")) +
      '<div class="card"><div class="row"><div class="row-title">' +
      esc(t("buy_balance", { n: data.bonus })) + '</div></div><div class="muted">' +
      esc(t("buy_rate", { rate: data.rate })) + "</div></div>" +
      "<h2>" + esc(t("buy_packages")) + "</h2>" +
      '<div class="card">' + (packages || '<div class="empty">—</div>') + "</div>" +
      "<h2>" + esc(t("buy_custom")) + "</h2>" +
      '<div class="card"><div class="field"><input class="input" id="buy-stars" type="number" min="' +
      esc(data.min_stars) + '" max="' + esc(data.max_stars) + '" placeholder="' + esc(t("buy_stars_ph")) +
      '"><button class="btn small" data-action="buy-custom">' + esc(t("buy_button")) + "</button></div></div>" +
      (models ? "<h2>" + esc(t("buy_models")) + '</h2><div class="card">' + models + "</div>" : "");
  }

  function renderSubscription() {
    var url = (state.paywall && state.paywall.url) || "";
    view.innerHTML =
      '<div class="card center" style="margin-top:24px">' +
      '<div style="font-size:40px">🔒</div>' +
      "<h2>" + esc(t("sub_title")) + "</h2>" +
      '<div class="muted">' + esc(t("sub_text")) + "</div>" +
      (url ? '<button class="btn" data-action="open-sub" style="margin-top:16px">' +
        esc(t("sub_button")) + "</button>" : "") +
      '<button class="btn secondary" data-action="retry">' + esc(t("sub_check")) + "</button>" +
      "</div>";
  }

  function renderError() {
    view.innerHTML =
      '<div class="card center" style="margin-top:24px">' +
      '<div style="font-size:40px">⚠️</div>' +
      "<h2>" + esc(t("error_title")) + "</h2>" +
      '<div class="muted">' + esc(state.fatal || t("error_text")) + "</div>" +
      '<button class="btn secondary" data-action="retry" style="margin-top:16px">↻ ' +
      esc(t("retry")) + "</button></div>";
  }

  function render() {
    if (brandEl) brandEl.textContent = state.me ? state.me.bot_name : "gazyavaGPT";
    if (state.fatal) { renderError(); renderTabs(); return; }
    if (state.paywall) { renderSubscription(); renderTabs(); return; }
    if (!state.me) {
      view.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
      renderTabs();
      return;
    }
    if (state.screen === "answer") renderAnswerScreen();
    else if (state.screen === "history") renderHistory();
    else if (state.screen === "tools") renderTools();
    else if (state.screen === "buy") renderBuy();
    else if (state.tab === "stats") renderStats();
    else if (state.tab === "tasks") renderTools();
    else if (state.tab === "games") renderGames();
    else if (state.tab === "friends") renderFriends();
    else if (state.tab === "settings") renderSettings();
    else renderHome();
    renderTabs();
  }

  // ---------------------------------------------------------------- данные
  function load() {
    state.fatal = null;
    return api("me").then(function (data) {
      state.me = data;
      if (!state._langReady) { state.lang = data.lang || state.lang; state._langReady = true; }
      state.paywall = null;
      if (state.tab === "friends" && state.top == null) return loadTop();
      return null;
    }).catch(function (err) {
      if (err.status === 403 && err.data && err.data.error === "subscription") {
        state.paywall = err.data;
        state.me = null;
      } else {
        state.fatal = t("error_text");
      }
    });
  }

  function loadTop() {
    return api("top").then(function (data) { state.top = data.top || []; })
      .catch(function () { state.top = []; });
  }

  function openScreen(name) {
    state.screen = name;
    render();
    if (name === "history" && state.history === null) {
      api("history").then(function (data) { state.history = data.items || []; }).catch(function () {
        state.history = [];
      }).then(render);
    } else if (name === "tools" && state.tools === null) {
      api("tools", { action: "load" }).then(function (data) { state.tools = data; }).catch(function () {
        toast(t("error_text"));
      }).then(render);
    } else if (name === "buy" && state.buy === null) {
      api("buy").then(function (data) { state.buy = data; }).catch(function () {
        toast(t("error_text"));
      }).then(render);
    }
  }

  function claimBonus() {
    if (state.busy) return;
    state.busy = true;
    render();
    api("bonus").then(function (data) {
      if (state.me) {
        state.me.remaining = data.remaining;
        state.me.bonus_requests = data.bonus_requests;
        state.me.bonus_streak = data.streak;
        state.me.bonus_claimed_today = true;
      }
      toast(data.claimed ? t("bonus_claimed", { amount: data.amount }) : t("bonus_already"));
      haptic(data.claimed ? "success" : "warning");
    }).catch(function () {
      toast(t("error_text"));
    }).then(function () { state.busy = false; render(); });
  }

  function saveSettings(patch) {
    return api("settings", patch).then(function (data) {
      if (state.me) {
        if (data.lang) { state.lang = data.lang; state.me.lang = data.lang; }
        if (data.style) state.me.style = data.style;
      }
      toast(t("saved"));
      render();
    }).catch(function () { toast(t("error_text")); });
  }

  function toolsAction(payload, okMessage) {
    return api("tools", payload).then(function (data) {
      state.tools = data;
      if (data.ok) { if (okMessage) { toast(okMessage); haptic("success"); } }
      else if (data.error === "rem_bad_duration") toast(t("rem_bad"));
      else if (data.error === "rem_limit") toast(t("rem_limit"));
      else if (data.error === "todo_limit") toast(t("todo_limit"));
      else if (data.error === "card_limit") toast(t("card_limit"));
      else if (data.error === "card_need_both") toast(t("card_need_both"));
      render();
    }).catch(function () { toast(t("error_text")); });
  }

  function copyLink() {
    var link = state.me ? state.me.invite_link : "";
    if (!link) return;
    var done = function () { toast(t("copied")); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(link).then(done, done);
    } else {
      var node = document.createElement("textarea");
      node.value = link; document.body.appendChild(node); node.select();
      try { document.execCommand("copy"); } catch (e) {}
      document.body.removeChild(node);
      done();
    }
  }

  function shareLink() {
    if (!state.me || !state.me.invite_link) return;
    var text = t("share_text", { bot: state.me.bot_name });
    var url = "https://t.me/share/url?url=" + encodeURIComponent(state.me.invite_link) +
      "&text=" + encodeURIComponent(text);
    if (tg && tg.openTelegramLink) tg.openTelegramLink(url);
    else window.open(url, "_blank");
  }

  function openSubscription() {
    var url = state.paywall && state.paywall.url;
    if (!url) { load().then(render); return; }
    if (tg && tg.openTelegramLink) tg.openTelegramLink(url);
    else window.open(url, "_blank");
  }

  function pay(payload) {
    api("invoice", payload).then(function (data) {
      if (!data.url) throw new Error("no_url");
      if (tg && tg.openInvoice) {
        tg.openInvoice(data.url, function (status) {
          if (status === "paid") {
            toast(t("paid"));
            haptic("success");
            load().then(function () { if (state.screen === "buy") refreshBuy(); });
          } else if (status === "failed") {
            toast(t("pay_failed"));
            haptic("error");
          }
        });
      } else {
        toast(t("error_text"));
      }
    }).catch(function (err) {
      var code = err.data && err.data.error;
      toast(code === "owned" ? t("already_owned") : t("pay_failed"));
    });
  }

  function refreshBuy() {
    state.buy = null;
    return api("buy").then(function (data) { state.buy = data; }).catch(function () {})
      .then(render);
  }

  // ---------------------------------------------------------------- события
  function onEnter(event) {
    if (event.key !== "Enter") return;
    var id = event.target && event.target.id;
    if (id === "todo-input") { event.preventDefault(); toolsAction({ action: "todo.add", text: val("todo-input") }, t("added")); }
    else if (id === "card-a") { event.preventDefault(); toolsAction({ action: "card.add", question: val("card-q"), answer: val("card-a") }, t("added")); }
    else if (id === "rem-dur") { event.preventDefault(); toolsAction({ action: "rem.add", text: val("rem-text"), duration: val("rem-dur") }, t("added")); }
    else if (id === "buy-stars") { event.preventDefault(); buyCustom(); }
  }

  function buyCustom() {
    var stars = parseInt(val("buy-stars"), 10);
    var buy = state.buy || {};
    if (!stars || !buy.rate) { toast(t("pay_failed")); return; }
    pay({ stars: stars, requests: stars * buy.rate });
  }

  document.addEventListener("click", function (event) {
    var node = event.target.closest("[data-action]");
    if (!node) return;
    var action = node.getAttribute("data-action");
    var value = node.getAttribute("data-value");

    haptic(action === "tab" || action === "set-lang" || action === "set-style" ? "select" : "light");

    if (action === "tab") {
      state.screen = null;
      state.tab = value;
      if (value === "friends" && state.top == null) loadTop().then(render);
      else render();
    } else if (action === "open") {
      openScreen(value);
    } else if (action === "back") {
      state.screen = null;
      render();
    } else if (action === "claim") {
      claimBonus();
    } else if (action === "copy") {
      copyLink();
    } else if (action === "share") {
      shareLink();
    } else if (action === "set-lang") {
      saveSettings({ lang: value });
    } else if (action === "set-style") {
      saveSettings({ style: value });
    } else if (action === "open-sub") {
      openSubscription();
    } else if (action === "retry") {
      load().then(render);
    } else if (action === "flip-hist") {
      var hi = "h" + value;
      state.revealed[hi] = !state.revealed[hi];
      renderHistory();
    } else if (action === "flip-card") {
      var ci = "c" + value;
      state.revealed[ci] = !state.revealed[ci];
      renderTools();
    } else if (action === "todo-add") {
      toolsAction({ action: "todo.add", text: val("todo-input") }, t("added"));
    } else if (action === "todo-del") {
      toolsAction({ action: "todo.del", index: parseInt(value, 10) });
    } else if (action === "todo-clear") {
      toolsAction({ action: "todo.clear" });
    } else if (action === "card-add") {
      toolsAction({ action: "card.add", question: val("card-q"), answer: val("card-a") }, t("added"));
    } else if (action === "card-del") {
      toolsAction({ action: "card.del", index: parseInt(value, 10) });
    } else if (action === "rem-add") {
      toolsAction({ action: "rem.add", text: val("rem-text"), duration: val("rem-dur") }, t("added"));
    } else if (action === "rem-del") {
      toolsAction({ action: "rem.del", id: parseInt(value, 10) });
    } else if (action === "invoice") {
      if (node.getAttribute("data-model")) pay({ model: node.getAttribute("data-model") });
      else pay({
        requests: parseInt(node.getAttribute("data-requests"), 10),
        stars: parseInt(node.getAttribute("data-stars"), 10)
      });
    } else if (action === "buy-custom") {
      buyCustom();
    } else if (action === "game-dice") {
      rollDice();
    } else if (action === "game-coin") {
      flipCoin();
    } else if (action === "game-num") {
      randNum();
    } else if (action === "game-rps") {
      // КНБ: кнопки внутри карточки handled by rps-pick
    } else if (action === "rps-pick") {
      playRPS(parseInt(value, 10));
    } else if (action === "game-slots") {
      playSlots();
    } else if (action === "game-8ball") {
      play8Ball();
    } else if (action === "set-model") {
      saveSettings({ model: value });
    } else if (action === "toggle-theme") {
      if (!state._themeOverride) state._themeOverride = "light";
      else if (state._themeOverride === "light") state._themeOverride = "dark";
      else state._themeOverride = null;
      applyTheme();
      render();
    } else if (action === "copy-answer") {
      var el = document.querySelector(".answer-body");
      if (el && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(el.innerText).then(function () {
          toast(t("copied")); haptic("success");
        });
      }
    }
  });

  document.addEventListener("keydown", onEnter);

  var langBtn = document.getElementById("lang-btn");
  if (langBtn) {
    langBtn.addEventListener("click", function () {
      state.screen = null;
      state.tab = "settings";
      render();
    });
  }

  // ---------------------------------------------------------------- старт
  state.lang = detectLang();
  render();
  if (!tg || !tg.initData) {
    state.fatal = t("error_text");
    render();
  } else {
    load().then(function () {
      // Если открыто с ?answer=<id> — сразу перейти к просмотру ответа
      try {
        var qs = window.location.search;
        var m = qs.match(/[?&]answer=(\d+)/);
        if (m) loadAnswer(parseInt(m[1], 10));
        else render();
      } catch (e) { render(); }
    });
  }
})();
