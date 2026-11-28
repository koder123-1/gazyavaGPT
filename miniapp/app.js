/* Mini App кабинет: данные — из /app/api/*, авторизация — initData Telegram. */
(function () {
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;

  var THEME_BG = { dark: "#05060b", light: "#eef1ff" };

  // 13 тем оформления. dot — мини-градиент для свотча в настройках.
  var THEMES = [
    { id: "aurora", dot: "linear-gradient(135deg,#6366f1,#22d3ee)" },
    { id: "sunset", dot: "linear-gradient(135deg,#f97316,#ec4899)" },
    { id: "ocean", dot: "linear-gradient(135deg,#0ea5e9,#14b8a6)" },
    { id: "forest", dot: "linear-gradient(135deg,#10b981,#84cc16)" },
    { id: "candy", dot: "linear-gradient(135deg,#ec4899,#a855f7)" },
    { id: "midnight", dot: "linear-gradient(135deg,#1d4ed8,#6366f1)" },
    { id: "gold", dot: "linear-gradient(135deg,#f59e0b,#fbbf24)" },
    { id: "cherry", dot: "linear-gradient(135deg,#ef4444,#ec4899)" },
    { id: "mint", dot: "linear-gradient(135deg,#2dd4bf,#34d399)" },
    { id: "lavender", dot: "linear-gradient(135deg,#a78bfa,#f0abfc)" },
    { id: "matrix", dot: "linear-gradient(135deg,#15803d,#4ade80)" },
    { id: "ice", dot: "linear-gradient(135deg,#38bdf8,#a5f3fc)" },
    { id: "mono", dot: "linear-gradient(135deg,#64748b,#cbd5e1)" }
  ];

  function prefGet(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function prefSet(key, value) {
    try { localStorage.setItem(key, value); } catch (e) {}
  }

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
    var skin = (state && state._skin) || "aurora";
    var bg = light ? THEME_BG.light : THEME_BG.dark;
    document.documentElement.setAttribute("data-theme", light ? "light" : "dark");
    document.documentElement.setAttribute("data-skin", skin);
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

  function confetti(x, y) {
    var colors = ["#6366f1","#8b5cf6","#06b6d4","#f59e0b","#ec4899","#10b981","#fbbf24"];
    for (var i = 0; i < 24; i++) {
      var p = document.createElement("div");
      p.className = "confetti-piece";
      p.style.left = (x + (Math.random()-0.5)*80) + "px";
      p.style.top = (y + (Math.random()-0.5)*40) + "px";
      p.style.background = colors[Math.floor(Math.random()*colors.length)];
      p.style.animationDelay = (Math.random()*0.3) + "s";
      p.style.width = (5+Math.random()*6) + "px";
      p.style.height = (5+Math.random()*6) + "px";
      document.body.appendChild(p);
      setTimeout(function(el){return function(){el.remove()}}(p), 1600);
    }
  }

  function ripple(e, el) {
    var rect = el.getBoundingClientRect();
    var r = document.createElement("span");
    r.className = "ripple";
    var size = Math.max(rect.width, rect.height);
    r.style.width = r.style.height = size + "px";
    r.style.left = (e.clientX - rect.left - size/2) + "px";
    r.style.top = (e.clientY - rect.top - size/2) + "px";
    el.appendChild(r);
    setTimeout(function(){r.remove()}, 600);
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
      saved: "Сохранено", theme_switch: "Тема",
      theme_title: "Оформление", theme_auto: "Авто", theme_light: "Светлая", theme_dark: "Тёмная",
      themes: { aurora: "Аврора", sunset: "Закат", ocean: "Океан", forest: "Лес", candy: "Карамель", midnight: "Полночь", gold: "Золото", cherry: "Вишня", mint: "Мята", lavender: "Лаванда", matrix: "Матрица", ice: "Лёд", mono: "Монохром" },
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
      support_title: "💎 Поддержать автора", support_short: "Поддержать",
      support_hint: "Отправь любую сумму GRAM на кошелёк ниже — это благодарность автору. Запросы за донат не начисляются.",
      support_address: "Кошелёк",
      support_copy: "Копировать", support_copied: "Скопировано",
      support_note: "В кошельке выбери токен GRAM и отправь любую сумму на этот адрес.",
      promo_title: "🎟 Промокод", promo_ph: "Код", promo_apply: "Активировать",
      promo_hint: "Введи код — запросы и генерации зачислятся сразу.",
      promo_ok: "🎉 +{n} запросов", promo_ok_img: "🎉 Генерации картинок: +{n}",
      promo_ok_both: "🎉 +{r} запросов · +{i} 🖼",
      promo_bad: "Такого промокода нет", promo_used: "Код уже активирован",
      promo_expired: "Срок действия кода истёк", promo_exhausted: "Код уже разобрали",
      promo_empty: "Введи промокод",
      paid: "Оплата получена, спасибо!", pay_failed: "Оплата не прошла", already_owned: "Уже куплено",
      added: "Добавлено", limit_reached: "Достигнут предел",
      tab_profile: "Профиль", profile_title: "Профиль",
      leaks: "Сливы", leaks_title: "🗂 Сливы", leaks_hint: "Файлы и материалы от админов",
      leaks_empty: "Пока ничего не выложили.", leak_download: "Скачать",
      leak_downloading: "Скачиваю…", leak_failed: "Не удалось скачать файл",
      leak_share: "Поделиться", leak_link_copied: "Ссылка скопирована",
      level: "Уровень {n}", rank: "Ранг", xp: "Опыт", total_xp: "Всего XP",
      xp_left: "До уровня {n} осталось {x} XP", xp_max: "Максимальный уровень",
      achievements: "Достижения", ach_progress: "{a} из {b}", ach_locked: "Закрыто",
      quick_access: "Быстрый доступ", streak_title: "Серия входов", streak_days: "{n} дн.",
      season_title: "Сезон {season}", season_short: "Сезон", season_rank: "Место в сезоне",
      season_xp: "XP за сезон", season_top: "Топ сезона", season_you: "ты",
      season_empty: "Пока пусто — задай вопрос и стань первым.",
      freezes: "Заморозки серии", freezes_hint: "Спасают серию при пропуске дня",
      challenge_title: "Челлендж дня", challenge_text: "Задай {n} вопросов сегодня",
      challenge_progress: "{a} / {b}", challenge_done: "Челлендж выполнен!",
      challenge_reward: "+{x} XP за выполнение", challenges_done: "Выполнено сегодня",
      ach_unlocked: "Новое достижение: {name}", level_up: "Новый уровень: {n}!",
      ranks: ["Новичок", "Ученик", "Знаток", "Мастер", "Эксперт", "Гуру", "Легенда"],
      ach: {
        first: "Первый шаг", first_d: "Задать первый вопрос",
        ten: "Разогрев", ten_d: "10 вопросов",
        fifty: "Полсотни", fifty_d: "50 вопросов",
        hundred: "Сотка", hundred_d: "100 вопросов",
        streak3: "Три дня подряд", streak3_d: "Серия 3 дня",
        streak7: "Неделя силы", streak7_d: "Серия 7 дней",
        invite1: "Друг пришёл", invite1_d: "Пригласить друга",
        bonus: "Ранняя птица", bonus_d: "Забрать бонус дня",
        streak30: "Месяц дисциплины", streak30_d: "Серия 30 дней",
        invite5: "Команда", invite5_d: "Пригласить 5 друзей",
        images10: "Художник", images10_d: "10 картинок",
        voice: "Голос", voice_d: "Задать вопрос голосом",
        night: "Полуночник", night_d: "Спросить после полуночи",
        season_top: "В топе сезона", season_top_d: "Войти в топ-10 сезона"
      },
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
      saved: "Збережено", theme_switch: "Тема",
      theme_title: "Оформлення", theme_auto: "Авто", theme_light: "Світла", theme_dark: "Темна",
      themes: { aurora: "Аврора", sunset: "Захід", ocean: "Океан", forest: "Ліс", candy: "Карамель", midnight: "Опівніч", gold: "Золото", cherry: "Вишня", mint: "М'ята", lavender: "Лаванда", matrix: "Матриця", ice: "Лід", mono: "Монохром" },
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
      support_title: "💎 Підтримати автора", support_short: "Підтримати",
      support_hint: "Надішли будь-яку суму GRAM на гаманець нижче — це подяка автору. Запити за донат не нараховуються.",
      support_address: "Гаманець",
      support_copy: "Копіювати", support_copied: "Скопійовано",
      support_note: "У гаманці вибери токен GRAM і надішли будь-яку суму на цю адресу.",
      promo_title: "🎟 Промокод", promo_ph: "Код", promo_apply: "Активувати",
      promo_hint: "Введи код — запити й генерації нарахуються одразу.",
      promo_ok: "🎉 +{n} запитів", promo_ok_img: "🎉 Генерації зображень: +{n}",
      promo_ok_both: "🎉 +{r} запитів · +{i} 🖼",
      promo_bad: "Такого промокоду немає", promo_used: "Код уже активовано",
      promo_expired: "Термін дії коду минув", promo_exhausted: "Код уже розібрали",
      promo_empty: "Введи промокод",
      paid: "Оплату отримано, дякую!", pay_failed: "Оплата не пройшла", already_owned: "Уже куплено",
      added: "Додано", limit_reached: "Досягнуто межі",
      tab_profile: "Профіль", profile_title: "Профіль",
      leaks: "Зливи", leaks_title: "🗂 Зливи", leaks_hint: "Файли й матеріали від адмінів",
      leaks_empty: "Поки нічого не виклали.", leak_download: "Завантажити",
      leak_downloading: "Завантажую…", leak_failed: "Не вдалося завантажити файл",
      leak_share: "Поділитися", leak_link_copied: "Посилання скопійовано",
      level: "Рівень {n}", rank: "Ранг", xp: "Досвід", total_xp: "Усього XP",
      xp_left: "До рівня {n} залишилось {x} XP", xp_max: "Максимальний рівень",
      achievements: "Досягнення", ach_progress: "{a} з {b}", ach_locked: "Закрито",
      quick_access: "Швидкий доступ", streak_title: "Серія входів", streak_days: "{n} дн.",
      season_title: "Сезон {season}", season_short: "Сезон", season_rank: "Місце в сезоні",
      season_xp: "XP за сезон", season_top: "Топ сезону", season_you: "ти",
      season_empty: "Поки порожньо — постав питання і стань першим.",
      freezes: "Заморозки серії", freezes_hint: "Рятують серію при пропуску дня",
      challenge_title: "Челендж дня", challenge_text: "Постав {n} питань сьогодні",
      challenge_progress: "{a} / {b}", challenge_done: "Челендж виконано!",
      challenge_reward: "+{x} XP за виконання", challenges_done: "Виконано сьогодні",
      ach_unlocked: "Нове досягнення: {name}", level_up: "Новий рівень: {n}!",
      ranks: ["Новачок", "Учень", "Знавець", "Майстер", "Експерт", "Гуру", "Легенда"],
      ach: {
        first: "Перший крок", first_d: "Поставити перше питання",
        ten: "Розігрів", ten_d: "10 питань",
        fifty: "Півсотні", fifty_d: "50 питань",
        hundred: "Сотня", hundred_d: "100 питань",
        streak3: "Три дні поспіль", streak3_d: "Серія 3 дні",
        streak7: "Тиждень сили", streak7_d: "Серія 7 днів",
        invite1: "Друг прийшов", invite1_d: "Запросити друга",
        bonus: "Ранній птах", bonus_d: "Забрати бонус дня",
        streak30: "Місяць дисципліни", streak30_d: "Серія 30 днів",
        invite5: "Команда", invite5_d: "Запросити 5 друзів",
        images10: "Художник", images10_d: "10 картинок",
        voice: "Голос", voice_d: "Поставити питання голосом",
        night: "Опівнічник", night_d: "Запитати після півночі",
        season_top: "У топі сезону", season_top_d: "Увійти в топ-10 сезону"
      },
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
      saved: "Захавана", theme_switch: "Тэма",
      theme_title: "Афармленне", theme_auto: "Аўта", theme_light: "Светлая", theme_dark: "Цёмная",
      themes: { aurora: "Аўрора", sunset: "Закат", ocean: "Акіян", forest: "Лес", candy: "Карамель", midnight: "Поўнач", gold: "Золата", cherry: "Вішня", mint: "Мята", lavender: "Лаванда", matrix: "Матрыца", ice: "Лёд", mono: "Манахром" },
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
      support_title: "💎 Падтрымаць аўтара", support_short: "Падтрымаць",
      support_hint: "Адпраў любую суму GRAM на кашалёк ніжэй — гэта падзяка аўтару. Запыты за донат не налічваюцца.",
      support_address: "Кашалёк",
      support_copy: "Капіяваць", support_copied: "Скапіявана",
      support_note: "У кашальку выберы токен GRAM і адпраў любую суму на гэты адрас.",
      promo_title: "🎟 Промокод", promo_ph: "Код", promo_apply: "Актываваць",
      promo_hint: "Увядзі код — запыты і генерацыі налічацца адразу.",
      promo_ok: "🎉 +{n} запытаў", promo_ok_img: "🎉 Генерацыі малюнкаў: +{n}",
      promo_ok_both: "🎉 +{r} запытаў · +{i} 🖼",
      promo_bad: "Такога промокода няма", promo_used: "Код ужо актываваны",
      promo_expired: "Тэрмін дзеяння кода скончыўся", promo_exhausted: "Код ужо разабралі",
      promo_empty: "Увядзі промокод",
      paid: "Аплату атрымана, дзякуй!", pay_failed: "Аплата не прайшла", already_owned: "Ужо куплена",
      added: "Дададзена", limit_reached: "Дасягнута мяжа",
      tab_profile: "Профіль", profile_title: "Профіль",
      leaks: "Злівы", leaks_title: "🗂 Злівы", leaks_hint: "Файлы і матэрыялы ад адмінаў",
      leaks_empty: "Пакуль нічога не выклалі.", leak_download: "Спампаваць",
      leak_downloading: "Спампоўваю…", leak_failed: "Не ўдалося спампаваць файл",
      leak_share: "Падзяліцца", leak_link_copied: "Спасылка скапіяваная",
      level: "Узровень {n}", rank: "Ранг", xp: "Вопыт", total_xp: "Усяго XP",
      xp_left: "Да ўзроўню {n} засталося {x} XP", xp_max: "Максімальны ўзровень",
      achievements: "Дасягненні", ach_progress: "{a} з {b}", ach_locked: "Закрыта",
      quick_access: "Хуткі доступ", streak_title: "Серыя ўваходаў", streak_days: "{n} дз.",
      season_title: "Сезон {season}", season_short: "Сезон", season_rank: "Месца ў сезоне",
      season_xp: "XP за сезон", season_top: "Топ сезона", season_you: "ты",
      season_empty: "Пакуль пуста — задай пытанне і стань першым.",
      freezes: "Замарожванні серыі", freezes_hint: "Ратуе серыю пры пропуску дня",
      challenge_title: "Чэлендж дня", challenge_text: "Задай {n} пытанняў сёння",
      challenge_progress: "{a} / {b}", challenge_done: "Чэлендж выкананы!",
      challenge_reward: "+{x} XP за выкананне", challenges_done: "Выканана сёння",
      ach_unlocked: "Новае дасягненне: {name}", level_up: "Новы ўзровень: {n}!",
      ranks: ["Навічок", "Вучань", "Знаўца", "Майстар", "Эксперт", "Гуру", "Легенда"],
      ach: {
        first: "Першы крок", first_d: "Задаць першае пытанне",
        ten: "Размінка", ten_d: "10 пытанняў",
        fifty: "Паўсотні", fifty_d: "50 пытанняў",
        hundred: "Сотка", hundred_d: "100 пытанняў",
        streak3: "Тры дні запар", streak3_d: "Серыя 3 дні",
        streak7: "Тыдзень сілы", streak7_d: "Серыя 7 дзён",
        invite1: "Сябар прыйшоў", invite1_d: "Запрасіць сябра",
        bonus: "Ранняя птушка", bonus_d: "Забраць бонус дня",
        streak30: "Месяц дысцыпліны", streak30_d: "Серыя 30 дзён",
        invite5: "Каманда", invite5_d: "Запрасіць 5 сяброў",
        images10: "Мастак", images10_d: "10 малюнкаў",
        voice: "Голас", voice_d: "Задаць пытанне голасам",
        night: "Паўночнік", night_d: "Спытаць пасля поўначы",
        season_top: "У топе сезона", season_top_d: "Увайсці ў топ-10 сезона"
      },
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
      saved: "Saved", theme_switch: "Theme",
      theme_title: "Appearance", theme_auto: "Auto", theme_light: "Light", theme_dark: "Dark",
      themes: { aurora: "Aurora", sunset: "Sunset", ocean: "Ocean", forest: "Forest", candy: "Candy", midnight: "Midnight", gold: "Gold", cherry: "Cherry", mint: "Mint", lavender: "Lavender", matrix: "Matrix", ice: "Ice", mono: "Mono" },
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
      support_title: "💎 Support the author", support_short: "Support",
      support_hint: "Send any amount of GRAM to the wallet below — it is a thank-you to the author. Donations do not add requests.",
      support_address: "Wallet",
      support_copy: "Copy", support_copied: "Copied",
      support_note: "In your wallet pick the GRAM token and send any amount to this address.",
      promo_title: "🎟 Promo code", promo_ph: "Code", promo_apply: "Activate",
      promo_hint: "Enter the code — requests and generations are added instantly.",
      promo_ok: "🎉 +{n} requests", promo_ok_img: "🎉 Image generations: +{n}",
      promo_ok_both: "🎉 +{r} requests · +{i} 🖼",
      promo_bad: "No such promo code", promo_used: "Code already activated",
      promo_expired: "Code has expired", promo_exhausted: "Code is used up",
      promo_empty: "Enter a promo code",
      paid: "Payment received, thank you!", pay_failed: "Payment failed", already_owned: "Already owned",
      added: "Added", limit_reached: "Limit reached",
      tab_profile: "Profile", profile_title: "Profile",
      leaks: "Leaks", leaks_title: "🗂 Leaks", leaks_hint: "Files and materials from admins",
      leaks_empty: "Nothing posted yet.", leak_download: "Download",
      leak_downloading: "Downloading…", leak_failed: "Could not download the file",
      leak_share: "Share", leak_link_copied: "Link copied",
      level: "Level {n}", rank: "Rank", xp: "XP", total_xp: "Total XP",
      xp_left: "{x} XP to level {n}", xp_max: "Max level",
      achievements: "Achievements", ach_progress: "{a} of {b}", ach_locked: "Locked",
      quick_access: "Quick access", streak_title: "Login streak", streak_days: "{n} d",
      season_title: "Season {season}", season_short: "Season", season_rank: "Season rank",
      season_xp: "Season XP", season_top: "Season top", season_you: "you",
      season_empty: "Empty so far — ask a question and take the lead.",
      freezes: "Streak freezes", freezes_hint: "Save your streak after a missed day",
      challenge_title: "Daily challenge", challenge_text: "Ask {n} questions today",
      challenge_progress: "{a} / {b}", challenge_done: "Challenge complete!",
      challenge_reward: "+{x} XP for completing", challenges_done: "Completed today",
      ach_unlocked: "Achievement unlocked: {name}", level_up: "Level up: {n}!",
      ranks: ["Rookie", "Learner", "Adept", "Master", "Expert", "Guru", "Legend"],
      ach: {
        first: "First step", first_d: "Ask your first question",
        ten: "Warm-up", ten_d: "10 questions",
        fifty: "Half a hundred", fifty_d: "50 questions",
        hundred: "Century", hundred_d: "100 questions",
        streak3: "Three in a row", streak3_d: "3-day streak",
        streak7: "Week of power", streak7_d: "7-day streak",
        invite1: "A friend joined", invite1_d: "Invite a friend",
        bonus: "Early bird", bonus_d: "Claim the daily bonus",
        streak30: "Month of discipline", streak30_d: "30-day streak",
        invite5: "Team", invite5_d: "Invite 5 friends",
        images10: "Artist", images10_d: "10 images",
        voice: "Voice", voice_d: "Ask a question by voice",
        night: "Night owl", night_d: "Ask after midnight",
        season_top: "Season top", season_top_d: "Reach the season top 10"
      },
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
    adminScreen: "dash",
    adminData: null,
    adminUser: null,
    adminTicket: null,
    adminLoading: false,
    adminError: null,
    adminEdit: null,
    adminBcastConfirm: false,
    adminLeakEdit: null,
    adminLeakUploading: false,
    adminChannel: null,
    adminUsersOffset: 0,
    adminTicketsOffset: 0,
    leaks: null,
    leaksError: null,
    leakBusy: 0,
    _langReady: false,
    _skin: "aurora"
  };

  // применяем сохранённые тему и скин до первого рендера
  (function loadPrefs() {
    var skin = prefGet("gz_skin");
    if (skin) {
      for (var i = 0; i < THEMES.length; i++) {
        if (THEMES[i].id === skin) { state._skin = skin; break; }
      }
    }
    var mode = prefGet("gz_mode");
    if (mode === "light" || mode === "dark") state._themeOverride = mode;
  })();

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

  function renderTabs() {
    // friends/settings живут как подэкраны профиля, поэтому подсвечиваем «Профиль»
    var activeKey = state.tab;
    if (state.screen === "friends" || state.screen === "settings" || state.screen === "season") activeKey = "profile";
    var keys = ["home", "stats", "tasks", "games", "leaks", "profile"];
    if (state.me && (state.me.is_admin || state.me.is_staff)) keys.push("admin");
    if (keys.indexOf(activeKey) === -1) activeKey = "home";
    var icons = { home: "🏠", stats: "📈", tasks: "🎯", games: "🎲", leaks: "🗂", profile: "👤", admin: "🛠" };

    // Пересобираем док только при смене языка или состава вкладок — иначе сохраняем
    // «пилюлю» живой, чтобы её позиция плавно перетекала между вкладками.
    var sig = keys.join(",") + "|" + state.lang;
    var hadTabs = !!tabsEl.querySelector(".tab");
    if (!hadTabs || state._dockSig !== sig) {
      tabsEl.innerHTML = keys.map(function (key) {
        var label = key === "profile" ? t("tab_profile") : (key === "admin" ? "Админ" : t(key));
        return '<button class="tab" data-action="tab" data-value="' + key +
          '" role="tab" aria-selected="false">' +
          '<span class="tab-icon">' + icons[key] + '</span>' +
          '<span class="tab-label">' + esc(label) + "</span></button>";
      }).join("") + '<span class="dock-pill" aria-hidden="true"></span>';
      state._dockSig = sig;
      state._dockLang = state.lang;
      state._dockAdmin = keys.length > 6;
      tabsEl.setAttribute("data-count", String(keys.length));
      hadTabs = false;
    }

    var buttons = tabsEl.querySelectorAll(".tab");
    for (var i = 0; i < buttons.length; i++) {
      var on = buttons[i].getAttribute("data-value") === activeKey;
      if (on) buttons[i].classList.add("active");
      else buttons[i].classList.remove("active");
      buttons[i].setAttribute("aria-selected", on ? "true" : "false");
    }

    if (!hadTabs) {
      positionPill(true);
      requestAnimationFrame(function () { positionPill(true); });
      setTimeout(function () { positionPill(false); }, 60);
    } else {
      positionPill(false);
    }
  }

  function positionPill(instant) {
    var pill = tabsEl.querySelector(".dock-pill");
    if (!pill) return;
    var active = tabsEl.querySelector(".tab.active");
    if (!active) { pill.style.opacity = "0"; return; }
    if (instant) {
      pill.style.transition = "none";
      clearTimeout(pill._restore);
      pill._restore = setTimeout(function () {
        if (pill.isConnected) pill.style.transition = "";
      }, 90);
    }
    pill.style.opacity = "1";
    pill.style.width = active.offsetWidth + "px";
    pill.style.transform = "translate3d(" + active.offsetLeft + "px,0,0)";
  }

  function statCard(value, label) {
    return '<div class="stat"><div class="stat-value">' + esc(value) +
      '</div><div class="stat-label">' + esc(label) + "</div></div>";
  }

  // ---------------------------------------------------------------- профиль / XP
  function xpOf(me) {
    if (!me) return 0;
    // Серверный XP — источник истины; старый расчёт оставлен для совместимости.
    if (me.gamification && typeof me.gamification.xp === "number") {
      return Math.max(0, me.gamification.xp);
    }
    var xp = (me.total_requests || 0) * 10;
    xp += (me.bonus_requests || 0) * 5;
    xp += (me.invites || 0) * 40;
    xp += (me.bonus_streak || 0) * 20;
    return Math.max(0, xp);
  }

  function levelInfo(xp) {
    var level = 1, need = 300, base = 0;
    while (xp >= base + need && level < 50) {
      base += need; level++; need = Math.round(need * 1.16);
    }
    var into = Math.max(0, xp - base);
    return {
      level: level, into: into, need: need, base: base,
      pct: Math.min(1, into / need), maxed: level >= 50
    };
  }

  function rankOf(level) {
    var ranks = dict().ranks || I18N.ru.ranks;
    var idx = Math.min(ranks.length - 1, Math.floor((level - 1) / 4));
    return ranks[idx];
  }

  function achievementsOf(me) {
    if (me && me.gamification && Array.isArray(me.gamification.achievements) &&
        me.gamification.achievements.length) {
      return me.gamification.achievements;
    }
    var a = dict().ach || I18N.ru.ach;
    function mk(id, icon, done) {
      return { id: id, icon: icon, done: !!done, title: a[id] || id, desc: a[id + "_d"] || "" };
    }
    return [
      mk("first", "🌱", me.total_requests >= 1),
      mk("ten", "🔥", me.total_requests >= 10),
      mk("fifty", "⚡", me.total_requests >= 50),
      mk("hundred", "🏆", me.total_requests >= 100),
      mk("streak3", "📅", me.bonus_streak >= 3),
      mk("streak7", "🗓️", me.bonus_streak >= 7),
      mk("invite1", "🤝", me.invites >= 1),
      mk("bonus", "🎁", me.bonus_claimed_today)
    ];
  }

  // Челлендж дня: детерминирован по дате, чтобы не «прыгал» при перерисовке
  function challengeOf(me) {
    var now = new Date();
    var seed = now.getFullYear() * 372 + now.getMonth() * 31 + now.getDate();
    var goals = [3, 5, 7, 10];
    var goal = goals[seed % goals.length];
    var used = Math.max(0, me.used_today || 0);
    return {
      goal: goal,
      done: Math.min(used, goal),
      complete: used >= goal,
      xp: goal * 10
    };
  }

  function subHeader(title) {
    return '<div class="head"><button class="back" data-action="back">← ' + esc(t("back")) +
      "</button></div><h1>" + esc(title) + "</h1>";
  }

  function renderHome() {
    var me = state.me;
    var name = (me.user.first_name || me.user.username || "").trim();
    var lvl = levelInfo(xpOf(me));
    var ch = challengeOf(me);
    var usedPct = (me.unlimited || !me.daily_limit) ? 100
      : Math.max(4, Math.min(100, Math.round((me.used_today / (me.used_today + Math.max(1, me.remaining))) * 100)));

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
        "</div></div><div class='ok-badge'>✓</div></div>";
    } else {
      bonus = '<button class="btn" data-action="claim"' + (state.busy ? " disabled" : "") +
        ">" + esc(t("bonus_claim")) + "</button>" +
        '<div class="muted center" style="margin-top:8px">' +
        esc(t("bonus_hint", { max: me.bonus_max })) + "</div>";
    }

    var challenge =
      "<h2>⚡ " + esc(t("challenge_title")) + "</h2>" +
      '<div class="card challenge' + (ch.complete ? " done" : "") + '">' +
      '<div class="row"><div><div class="row-title">' +
      esc(ch.complete ? t("challenge_done") : t("challenge_text", { n: ch.goal })) +
      '</div><div class="row-sub">' + esc(t("challenge_reward", { x: ch.xp })) + "</div></div>" +
      '<div class="ch-badge">' + (ch.complete ? "✓" : ch.done + "/" + ch.goal) + "</div></div>" +
      '<div class="ch-bar"><span style="width:' + Math.round(ch.done / ch.goal * 100) + '%"></span></div>' +
      "</div>";

    var styleMeta = dict().styles[me.style] || [];
    view.innerHTML =
      '<div class="card hero">' +
      '<div class="hero-glow" aria-hidden="true"></div>' +
      '<div class="hero-top">' +
      '<div class="hero-label">' + esc(t("hello", { name: name })) + "</div>" +
      '<span class="hero-chip" data-action="tab" data-value="profile" role="button" tabindex="0">⚡ ' + esc(t("level", { n: lvl.level })) + "</span>" +
      "</div>" +
      '<div class="value">' + (me.unlimited ? "∞" : esc(me.remaining)) + "</div>" +
      '<div class="sub">' + (me.unlimited ? esc(t("unlimited")) : esc(t("left"))) + "</div>" +
      '<div class="hero-bar"><span style="width:' + usedPct + '%"></span></div>' +
      '<div class="hero-foot">' +
      '<span>🔥 ' + esc(t("streak_days", { n: me.bonus_streak })) + "</span>" +
      '<span>🏅 ' + esc(rankOf(lvl.level)) + "</span>" +
      "</div>" +
      "</div>" +
      tiles +
      challenge +
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
        if (el) { countUp(el, me.remaining, 900); state._heroAnimated = true; }
      }, 120);
    }
  }

  function renderProfile() {
    var me = state.me;
    var xp = xpOf(me);
    var lvl = levelInfo(xp);
    var ach = achievementsOf(me);
    var unlocked = ach.filter(function (a) { return a.done; }).length;
    var name = (me.user.first_name || me.user.username || "—").trim();
    var handle = me.user.username ? "@" + me.user.username : "";
    var initials = (name || "?").slice(0, 1).toUpperCase();
    var deg = Math.round(lvl.pct * 360);
    var g = me.gamification || {};
    var season = g.season || {};
    var freezes = typeof g.freezes === "number" ? g.freezes : 0;
    var photo = "";
    try {
      photo = (tg && tg.initDataUnsafe && tg.initDataUnsafe.user && tg.initDataUnsafe.user.photo_url) || "";
    } catch (e) { photo = ""; }

    var ring =
      '<div class="lv-ring" style="background:conic-gradient(var(--acc) ' + deg + 'deg, rgba(var(--acc-rgb),.16) ' + deg + 'deg)">' +
      '<div class="lv-avatar">' +
      (photo
        ? '<img src="' + esc(photo) + '" alt="" referrerpolicy="no-referrer">'
        : '<span class="lv-initial">' + esc(initials) + "</span>") +
      "</div>" +
      '<span class="lv-num">' + lvl.level + "</span>" +
      "</div>";

    var achHtml = ach.map(function (a) {
      return '<div class="ach' + (a.done ? " on" : "") + '" title="' + esc(a.desc) + '">' +
        '<span class="ach-ico">' + (a.done ? a.icon : "🔒") + "</span>" +
        '<span class="ach-name">' + esc(a.title) + "</span></div>";
    }).join("");

    var quick =
      '<div class="quick-grid">' +
      '<button class="quick" data-action="open" data-value="season"><span>🏆</span>' + esc(t("season_short")) + "</button>" +
      '<button class="quick" data-action="open" data-value="friends"><span>👥</span>' + esc(t("friends")) + "</button>" +
      '<button class="quick" data-action="open" data-value="settings"><span>⚙️</span>' + esc(t("settings")) + "</button>" +
      '<button class="quick" data-action="open" data-value="history"><span>💬</span>' + esc(t("history_title")) + "</button>" +
      (me.payments_enabled
        ? '<button class="quick" data-action="open" data-value="buy"><span>⭐</span>' + esc(t("tile_buy")) + "</button>"
        : "") +
      (me.support_enabled
        ? '<button class="quick" data-action="open" data-value="buy" data-anchor="support-card"><span>💎</span>' + esc(t("support_short")) + "</button>"
        : "") +
      "</div>";

    view.innerHTML =
      "<h1>" + esc(t("profile_title")) + "</h1>" +
      '<div class="card profile-card">' +
      '<div class="profile-top">' + ring +
      '<div class="profile-id"><div class="profile-name">' + esc(name) + "</div>" +
      (handle ? '<div class="profile-handle">' + esc(handle) + "</div>" : "") +
      '<div class="rank-chip">🏅 ' + esc(rankOf(lvl.level)) + "</div></div></div>" +
      '<div class="xp-line"><span>' + esc(t("xp")) + "</span><span>" +
      esc(lvl.into) + " / " + esc(lvl.need) + " XP</span></div>" +
      '<div class="xp-bar"><span style="width:0"></span></div>' +
      '<div class="profile-meta">' +
      '<div class="pmeta"><b>' + esc(xp) + "</b><span>" + esc(t("total_xp")) + "</span></div>" +
      '<div class="pmeta"><b>' + esc(me.total_requests) + "</b><span>" + esc(t("stat_total")) + "</span></div>" +
      '<div class="pmeta"><b>' + esc(me.invites) + "</b><span>" + esc(t("stat_invites")) + "</span></div>" +
      "</div></div>" +

      '<div class="streak-card">' +
      '<div class="streak-ico">🔥</div>' +
      '<div class="streak-body"><div class="row-title">' + esc(t("streak_title")) + "</div>" +
      '<div class="row-sub">' + esc(t("streak_days", { n: me.bonus_streak })) +
      (freezes ? " · ❄️ " + esc(freezes) : "") + "</div></div>" +
      '<div class="streak-days">' +
      Array.apply(null, Array(7)).map(function (_, i) {
        return '<span class="sd' + (i < Math.min(7, me.bonus_streak) ? " on" : "") + '"></span>';
      }).join("") +
      "</div></div>" +

      '<div class="card season-card" data-action="open" data-value="season" role="button" tabindex="0">' +
      '<div class="row"><div><div class="row-title">🏆 ' +
      esc(t("season_title", { season: season.key || "—" })) + "</div>" +
      '<div class="row-sub">' + esc(t("season_rank")) + ": <b>#" +
      esc(season.rank || "—") + "</b> · " + esc(season.xp || 0) + " XP</div></div>" +
      '<span class="season-go">→</span></div></div>' +

      "<h2>🏆 " + esc(t("achievements")) + " · " + esc(t("ach_progress", { a: unlocked, b: ach.length })) + "</h2>" +
      '<div class="ach-grid">' + achHtml + "</div>" +

      "<h2>🚀 " + esc(t("quick_access")) + "</h2>" +
      quick +
      "<h2>🎟 " + esc(t("promo_title")) + "</h2>" +
      '<div class="card">' +
      '<div class="row-sub" style="margin-bottom:8px">' + esc(t("promo_hint")) + "</div>" +
      '<div class="field"><input class="input" id="promo-input" placeholder="' +
      esc(t("promo_ph")) + '" autocapitalize="characters" autocomplete="off">' +
      '<button class="btn small" data-action="promo-apply">' +
      esc(t("promo_apply")) + "</button></div></div>";

    setTimeout(function () {
      var bar = document.querySelector(".xp-bar > span");
      if (bar) bar.style.width = Math.round(lvl.pct * 100) + "%";
    }, 60);
  }

  function renderSeason() {
    var me = state.me;
    var g = me.gamification || {};
    var season = g.season || {};
    var top = season.top || [];
    var rows = top.map(function (row, index) {
      return '<div class="season-row' + (row.me ? " me" : "") + '">' +
        '<div class="season-place">' + (index + 1) + "</div>" +
        '<div class="season-name">' + esc(row.name) +
        (row.me ? ' <span class="you-badge">' + esc(t("season_you")) + "</span>" : "") +
        "</div>" +
        '<div class="season-xp">' + esc(row.xp) + " XP</div></div>";
    }).join("");

    view.innerHTML =
      subHeader(t("season_short")) +
      '<div class="card season-hero">' +
      '<div class="hero-label">' + esc(t("season_title", { season: season.key || "—" })) + "</div>" +
      '<div class="season-stats">' +
      '<div class="pmeta"><b>#' + esc(season.rank || "—") + "</b><span>" + esc(t("season_rank")) + "</span></div>" +
      '<div class="pmeta"><b>' + esc(season.xp || 0) + "</b><span>" + esc(t("season_xp")) + "</span></div>" +
      '<div class="pmeta"><b>' + esc(g.freezes || 0) + "</b><span>❄️ " + esc(t("freezes")) + "</span></div>" +
      "</div></div>" +
      "<h2>🏆 " + esc(t("season_top")) + "</h2>" +
      '<div class="card">' +
      (rows || '<div class="muted center">' + esc(t("season_empty")) + "</div>") +
      "</div>";
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

  function renderFriends(withBack) {
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
      (withBack ? subHeader(t("friends_title")) : "<h1>" + esc(t("friends_title")) + "</h1>") +
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

  function renderSettings(withBack) {
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

      // оформление — 13 тем + режим светлая/тёмная/авто
      var themeNames = dict().themes || {};
      var themeChips = THEMES.map(function (th) {
        var name = themeNames[th.id] || th.id;
        return '<button class="chip' + (th.id === (state._skin || "aurora") ? " active" : "") +
          '" data-action="set-skin" data-value="' + th.id + '">' +
          '<span class="theme-dot" style="background:' + th.dot + '"></span>' +
          '<span class="chip-name">' + esc(name) + "</span></button>";
      }).join("");

      var modeChips = [
        { v: "auto", icon: "🔄", key: "theme_auto" },
        { v: "light", icon: "☀️", key: "theme_light" },
        { v: "dark", icon: "🌙", key: "theme_dark" }
      ].map(function (m) {
        var active = m.v === "auto" ? !state._themeOverride : state._themeOverride === m.v;
        return '<button class="chip' + (active ? " active" : "") +
          '" data-action="set-mode" data-value="' + m.v + '">' +
          m.icon + " " + esc(t(m.key)) + "</button>";
      }).join("");

      view.innerHTML =
        (withBack ? subHeader(t("settings_title")) : "<h1>" + esc(t("settings_title")) + "</h1>") +
        "<h2>" + esc(t("language")) + "</h2>" +
        '<div class="card"><div class="chips">' + langs + "</div></div>" +
        "<h2>" + esc(t("theme_title")) + "</h2>" +
        '<div class="card"><div class="theme-grid">' + themeChips +
        '</div><div class="seg">' + modeChips + "</div></div>" +
        "<h2>" + esc(t("style_title")) + "</h2>" +
        '<div class="card">' + styles + "</div>" +
        "<h2>" + esc(t("model")) + "</h2>" +
        '<div class="card"><div class="chips">' + models + "</div></div>";
    }

  // ---------------------------------------------------------------- игры
  var DICE_PIPS = {
    1: ["2/2"],
    2: ["1/1", "3/3"],
    3: ["1/1", "2/2", "3/3"],
    4: ["1/1", "3/1", "1/3", "3/3"],
    5: ["1/1", "3/1", "2/2", "1/3", "3/3"],
    6: ["1/1", "3/1", "1/2", "3/2", "1/3", "3/3"]
  };
  // как повернуть куб, чтобы нужная грань смотрела на игрока
  var DICE_ROT = { 1: [0, 0], 2: [-90, 0], 3: [0, -90], 4: [0, 90], 5: [90, 0], 6: [0, 180] };
  var SLOT_SYMBOLS = ["🍒", "🍋", "🍊", "🍇", "⭐", "💎", "7️⃣"];
  var WHEEL_PRIZES = ["🎁 +5", "⭐ Удача", "🍀 Клевер", "💎 Алмаз", "🔥 Огонь", "🌈 Радуга", "🎯 Точка", "🍕 Пицца", "🚀 Ракета", "👑 Корона"];
  var WHEEL_COLORS = ["#6366f1", "#8b5cf6", "#ec4899", "#f43f5e", "#f59e0b", "#fbbf24", "#10b981", "#14b8a6", "#22d3ee", "#3b82f6"];
  // Раскраска: неверный цвет не закрашивает клетку, а подсвечивает её красным.
  var PAINT_COLORS = ["#ef4444", "#3b82f6", "#22c55e", "#f59e0b"];
  var PAINT_SIZE = 16;

  function diceFace(n) {
    return '<div class="cf f' + n + '">' + DICE_PIPS[n].map(function (pos) {
      var rc = pos.split("/");
      return '<span style="grid-area:' + rc[0] + "/" + rc[1] + '"></span>';
    }).join("") + "</div>";
  }

  function reelHtml(start) {
    var cells = "";
    for (var i = 0; i < 42; i++) {
      cells += '<div class="reel-cell">' + SLOT_SYMBOLS[i % SLOT_SYMBOLS.length] + "</div>";
    }
    return '<div class="reel"><div class="reel-strip" style="transform:translateY(' +
      (11 - start * 34) + 'px)">' + cells + "</div></div>";
  }

  // ---------------------------------------------------------------- 5D-эффекты
  function shakeScreen() {
    var app = document.getElementById("app");
    if (!app) return;
    app.classList.remove("screen-shake");
    void app.offsetWidth;
    app.classList.add("screen-shake");
    setTimeout(function () { app.classList.remove("screen-shake"); }, 520);
  }

  function burst(x, y) {
    var ring = document.createElement("div");
    ring.className = "shock-ring";
    ring.style.left = x + "px";
    ring.style.top = y + "px";
    document.body.appendChild(ring);
    setTimeout(function () { ring.remove(); }, 900);

    var colors = ["#fbbf24", "#f472b6", "#22d3ee", "#a78bfa", "#34d399"];
    for (var i = 0; i < 16; i++) {
      (function (i) {
        var spark = document.createElement("i");
        spark.className = "spark";
        var angle = (Math.PI * 2 * i) / 16 + Math.random() * 0.5;
        var dist = 42 + Math.random() * 74;
        spark.style.left = x + "px";
        spark.style.top = y + "px";
        spark.style.background = colors[i % colors.length];
        spark.style.color = colors[i % colors.length];
        spark.style.setProperty("--dx", (Math.cos(angle) * dist).toFixed(1) + "px");
        spark.style.setProperty("--dy", (Math.sin(angle) * dist).toFixed(1) + "px");
        spark.style.animationDelay = (Math.random() * 0.08).toFixed(2) + "s";
        document.body.appendChild(spark);
        setTimeout(function () { spark.remove(); }, 950);
      })(i);
    }
  }

  function celebrate(el, big) {
    if (!el) return;
    var rect = el.getBoundingClientRect();
    burst(rect.left + rect.width / 2, rect.top + rect.height / 2);
    el.classList.remove("win-glow");
    void el.offsetWidth;
    el.classList.add("win-glow");
    setTimeout(function () { el.classList.remove("win-glow"); }, 1200);
    if (big) {
      var flash = document.createElement("div");
      flash.className = "win-flash";
      document.body.appendChild(flash);
      setTimeout(function () { flash.remove(); }, 760);
      shakeScreen();
      confetti(window.innerWidth / 2, window.innerHeight / 2.4);
      haptic("success");
    }
  }

  function gameCard(el) {
    return el && el.closest ? el.closest(".game-card") : null;
  }

  function renderGames() {
    // Цели раскраски готовим до разметки: в клетках видны номера цветов.
    resetPaint();
    view.innerHTML =
      "<h1>🎲 " + esc(t("games")) + "</h1>" +
      '<div class="games-grid">' +

      '<div class="card game-card center" data-action="game-dice">' +
      '<div class="g-stage dice-stage"><div class="cube" id="dice-cube">' +
      diceFace(1) + diceFace(2) + diceFace(3) + diceFace(4) + diceFace(5) + diceFace(6) +
      "</div></div><div class=\"game-label\">Кубик</div></div>" +

      '<div class="card game-card center" data-action="game-coin">' +
      '<div class="g-stage coin-stage"><div class="coin3d" id="coin3d">' +
      '<div class="cface front">🦅</div><div class="cface back">🪙</div>' +
      "</div></div><div class=\"game-label\">Монетка</div></div>" +

      '<div class="card game-card center" data-action="game-num">' +
      '<div class="g-stage"><div class="odo-empty" id="num-slot">?</div></div>' +
      '<div class="game-label">Число</div></div>' +

      '<div class="card game-card center" data-action="game-slots">' +
      '<div class="reels" id="slots-reels">' + reelHtml(0) + reelHtml(1) + reelHtml(2) + "</div>" +
      '<div class="game-label">Слоты</div></div>' +

      '<div class="card game-card center" data-action="game-8ball">' +
      '<div class="g-stage"><div class="ball8" id="ball-answer">8</div></div>' +
      '<div class="game-label" id="ball-text">Шар</div></div>' +

      '<div class="card game-card center">' +
      '<div class="g-stage"><div class="rps" id="rps-result">✊</div></div>' +
      '<div class="game-label">КНБ</div>' +
      '<div class="rps-row"><button class="chip rps-btn" data-action="rps-pick" data-value="0">✊</button>' +
      '<button class="chip rps-btn" data-action="rps-pick" data-value="1">✋</button>' +
      '<button class="chip rps-btn" data-action="rps-pick" data-value="2">✌️</button></div></div>' +

      '<div class="card game-card center" data-action="game-react">' +
      '<div class="g-stage"><div class="react-orb" id="react-box">⚡</div></div>' +
      '<div class="game-label" id="react-label">Реакция</div></div>' +

      '<div class="card game-card center" data-action="game-wheel">' +
      '<div class="wheel-stage"><div class="wheel-tilt">' +
      '<div class="wheel" id="wheel" style="background:' + wheelGradient() + '">' +
      '<span class="wheel-hub">🎯</span></div></div>' +
      '<span class="wheel-pointer" aria-hidden="true"></span></div>' +
      '<div class="game-label" id="wheel-text">Колесо</div></div>' +

      '<div class="card game-card center">' +
      '<div class="g-stage"><div class="guess-num" id="guess-hint">🔢</div></div>' +
      '<div class="game-label">Угадай</div>' +
      '<div class="guess-row"><input id="guess-input" class="input" type="number" min="1" max="100" placeholder="1–100">' +
      '<button class="chip rps-btn" data-action="guess-submit">→</button></div></div>' +

      '<div class="card game-card center">' +
      '<div class="g-stage paint-stage"><div class="paint-grid" id="paint-grid">' +
      paintGridHtml() + "</div></div>" +
      '<div class="game-label" id="paint-label">Раскраска</div>' +
      '<div class="paint-row">' + paintPaletteHtml() + "</div></div>" +

      "</div>";
    state._guessTarget = Math.floor(Math.random() * 100) + 1;
    state._guessAttempts = 0;
    state._reactState = "idle";
    state._slotsBusy = false;
    state._slotK = [0, 1, 2];
    state._wheelAngle = 0;
  }

  // ---------------------------------------------------------------- раскраска
  function resetPaint() {
    state._paintColor = 0;
    state._paintDone = 0;
    state._paintTargets = [];
    for (var i = 0; i < PAINT_SIZE; i++) {
      state._paintTargets.push(Math.floor(Math.random() * PAINT_COLORS.length));
    }
  }

  function paintGridHtml() {
    var cells = "";
    for (var i = 0; i < PAINT_SIZE; i++) {
      // Раскраска по номерам: цифра подсказывает, каким цветом закрашивать.
      cells += '<button class="paint-cell" data-action="paint-cell" data-value="' + i +
        '"><span class="paint-num">' + (state._paintTargets[i] + 1) + "</span></button>";
    }
    return cells;
  }

  function paintPaletteHtml() {
    return PAINT_COLORS.map(function (color, i) {
      var active = i === state._paintColor ? " active" : "";
      return '<button class="paint-dot' + active + '" data-action="paint-pick" data-value="' +
        i + '" style="--dot:' + color + '" aria-label="цвет ' + (i + 1) + '">' +
        (i + 1) + "</button>";
    }).join("");
  }

  function pickPaint(node, index) {
    if (!node) return;
    state._paintColor = index;
    var dots = node.parentNode ? node.parentNode.querySelectorAll(".paint-dot") : [];
    for (var i = 0; i < dots.length; i++) dots[i].classList.remove("active");
    node.classList.add("active");
    haptic("select");
  }

  function paintCell(node, index) {
    if (!node || node.classList.contains("done")) return;
    var target = state._paintTargets[index];
    if (state._paintColor === target) {
      node.style.background = PAINT_COLORS[target];
      node.classList.add("done");
      state._paintDone += 1;
      haptic("light");
      if (state._paintDone >= PAINT_SIZE) {
        toast("Раскрашено! 🎨");
        haptic("success");
        celebrate(node.closest(".game-card"), true);
      }
      return;
    }
    // Неверный цвет: клетка остаётся пустой и вспыхивает красным.
    node.classList.remove("wrong");
    void node.offsetWidth;
    node.classList.add("wrong");
    setTimeout(function () { node.classList.remove("wrong"); }, 480);
    haptic("error");
  }

  function wheelGradient() {
    var seg = 360 / WHEEL_PRIZES.length;
    var stops = WHEEL_PRIZES.map(function (_, i) {
      var from = (i * seg).toFixed(2);
      var to = ((i + 1) * seg).toFixed(2);
      return WHEEL_COLORS[i % WHEEL_COLORS.length] + " " + from + "deg " + to + "deg";
    }).join(",");
    return "conic-gradient(from 0deg," + stops + ")";
  }

  function rollDice() {
    var cube = document.getElementById("dice-cube");
    if (!cube || state._diceBusy) return;
    state._diceBusy = true;
    var result = 1 + Math.floor(Math.random() * 6);
    var rot = DICE_ROT[result];
    var spinX = 360 * (2 + Math.floor(Math.random() * 3)) + rot[0];
    var spinY = 360 * (2 + Math.floor(Math.random() * 3)) + rot[1];

    var stage = cube.parentNode;
    stage.classList.add("throwing");
    cube.classList.add("spinning");
    cube.style.transform = "rotateX(" + spinX + "deg) rotateY(" + spinY + "deg)";
    haptic("light");

    setTimeout(function () {
      cube.classList.remove("spinning");
      stage.classList.remove("throwing");
      state._diceBusy = false;
      haptic("success");
      celebrate(gameCard(cube), result === 6);
    }, 1200);
  }

  function flipCoin() {
    var coin = document.getElementById("coin3d");
    if (!coin || state._coinBusy) return;
    state._coinBusy = true;
    var heads = Math.random() < 0.5;
    var spins = 4 + Math.floor(Math.random() * 3);
    coin.classList.add("spinning");
    coin.style.transform = "rotateY(" + (360 * spins + (heads ? 0 : 180)) + "deg)";
    haptic("light");

    setTimeout(function () {
      coin.classList.remove("spinning");
      // нормализуем угол без анимации, чтобы следующий бросок не «прыгал»
      coin.style.transition = "none";
      coin.style.transform = "rotateY(" + (heads ? 0 : 180) + "deg)";
      setTimeout(function () { coin.style.transition = ""; }, 60);
      state._coinBusy = false;
      toast(heads ? "Орёл! 🦅" : "Решка! 🪙");
      haptic("success");
      celebrate(gameCard(coin), false);
    }, 1560);
  }

  function randNum() {
    var slot = document.getElementById("num-slot");
    if (!slot || state._numBusy) return;
    state._numBusy = true;
    var target = Math.floor(Math.random() * 100) + 1;
    var digits = ("00" + target).slice(-3).split("");
    var cell = 42;

    slot.className = "odo";
    slot.innerHTML = digits.map(function () {
      var cells = "";
      for (var i = 0; i < 40; i++) cells += '<div class="odo-cell">' + (i % 10) + "</div>";
      return '<div class="odo-col"><div class="odo-strip">' + cells + "</div></div>";
    }).join("");

    var strips = slot.querySelectorAll(".odo-strip");
    void slot.offsetHeight; // фиксируем стартовую позицию, чтобы сработал переход
    for (var i = 0; i < strips.length; i++) {
      var d = parseInt(digits[i], 10);
      var loops = 3 + i;
      strips[i].style.transitionDelay = (i * 90) + "ms";
      strips[i].style.transform = "translateY(" + (-(loops * 10 + d) * cell) + "px)";
    }
    haptic("light");

    setTimeout(function () {
      state._numBusy = false;
      haptic("success");
      celebrate(gameCard(slot), target === 100);
    }, 1350);
  }

  function playRPS(choice) {
    var el = document.getElementById("rps-result");
    if (!el || state._rpsBusy) return;
    state._rpsBusy = true;
    var hands = ["✊", "✋", "✌️"];
    var cpu = Math.floor(Math.random() * 3);
    el.classList.add("shaking");
    haptic("light");

    setTimeout(function () {
      el.classList.remove("shaking");
      el.classList.add("reveal");
      el.innerHTML = hands[choice] + '<span class="vs">vs</span>' + hands[cpu];
      var win = (choice === 0 && cpu === 2) || (choice === 1 && cpu === 0) || (choice === 2 && cpu === 1);
      var draw = choice === cpu;
      state._rpsBusy = false;
      haptic(draw ? "warning" : win ? "success" : "error");
      toast(draw ? "Ничья!" : win ? "Ты победил! 🎉" : "Компьютер выиграл 🤖");
      if (win) celebrate(gameCard(el), true);
      else if (!draw) celebrate(gameCard(el), false);
      setTimeout(function () {
        el.classList.remove("reveal");
        el.innerHTML = "✊";
      }, 1400);
    }, 780);
  }

  function playSlots() {
    var reelsEl = document.getElementById("slots-reels");
    if (!reelsEl || state._slotsBusy) return;
    state._slotsBusy = true;

    var reels = reelsEl.querySelectorAll(".reel");
    var strips = reelsEl.querySelectorAll(".reel-strip");
    var results = [0, 0, 0];
    var delays = [0, 240, 480];
    var durs = [1150, 1400, 1700];
    var cell = 34, pad = 11;

    for (var r = 0; r < results.length; r++) {
      results[r] = Math.floor(Math.random() * SLOT_SYMBOLS.length);
    }
    // если первые два совпали — третья крутится дольше (саспенс)
    if (results[0] === results[1]) durs[2] += 550;

    for (var i = 0; i < strips.length; i++) {
      (function (i) {
        var base = state._slotK[i] || 0;
        var k = base + 7 + ((results[i] - (base % 7) + 7) % 7);
        state._slotK[i] = k;
        var strip = strips[i], reel = reels[i];
        strip.style.transitionDuration = durs[i] + "ms";
        strip.style.transitionDelay = delays[i] + "ms";
        reel.classList.remove("landed", "win");
        reel.classList.add("spinning");
        strip.style.transform = "translateY(" + (pad - k * cell) + "px)";

        setTimeout(function () {
          reel.classList.remove("spinning");
          reel.classList.add("landed");
          haptic("light");
          if (i === strips.length - 1) finishSlots(results, reels, strips, pad, cell);
        }, delays[i] + durs[i] + 40);
      })(i);
    }
    haptic("light");
  }

  function finishSlots(results, reels, strips, pad, cell) {
    state._slotsBusy = false;
    var jackpot = results[0] === results[1] && results[1] === results[2];
    var winIdx = [];
    if (results[0] === results[1]) winIdx = [0, 1];
    else if (results[1] === results[2]) winIdx = [1, 2];
    else if (results[0] === results[2]) winIdx = [0, 2];

    // нормализуем позиции, чтобы следующее вращение снова шло вверх
    for (var i = 0; i < strips.length; i++) {
      strips[i].style.transitionDuration = "0ms";
      strips[i].style.transitionDelay = "0ms";
      strips[i].style.transform = "translateY(" + (pad - (7 + results[i]) * cell) + "px)";
      state._slotK[i] = 7 + results[i];
    }
    setTimeout(function () {
      for (var j = 0; j < strips.length; j++) {
        strips[j].style.transitionDuration = "";
        strips[j].style.transitionDelay = "";
      }
    }, 70);

    var card = gameCard(reels[0]);
    if (jackpot) {
      for (var w = 0; w < reels.length; w++) reels[w].classList.add("win");
      toast("ДЖЕКПОТ! " + SLOT_SYMBOLS[results[0]] + SLOT_SYMBOLS[results[0]] + SLOT_SYMBOLS[results[0]] + " 🎉");
      haptic("success");
      celebrate(card, true);
    } else if (winIdx.length) {
      for (var p = 0; p < winIdx.length; p++) reels[winIdx[p]].classList.add("win");
      toast("Почти! Две совпали ✨");
      haptic("warning");
      celebrate(card, false);
    } else {
      haptic("light");
    }
    setTimeout(function () {
      for (var c = 0; c < reels.length; c++) reels[c].classList.remove("win");
    }, 2000);
  }

  function play8Ball() {
    var el = document.getElementById("ball-answer");
    var txt = document.getElementById("ball-text");
    if (!el || state._ballBusy) return;
    state._ballBusy = true;
    var answers = ["Да!", "Нет.", "Возможно…", "Определённо да", "Спроси позже", "Не рассчитывай", "Знаки говорят да", "Мой ответ — нет", "Без сомнений", "Перспективы хороши", "Сконцентрируйся и спроси снова", "Даже не думай", "Звёзды говорят да", "Туманно, попробуй ещё"];
    el.classList.add("shaking");
    txt.textContent = "Думаю…";
    txt.classList.remove("answer-pop");
    haptic("light");

    setTimeout(function () {
      el.classList.remove("shaking");
      el.classList.add("revealed");
      txt.textContent = answers[Math.floor(Math.random() * answers.length)];
      txt.classList.add("answer-pop");
      state._ballBusy = false;
      haptic("success");
      celebrate(gameCard(el), false);
      setTimeout(function () {
        el.classList.remove("revealed");
        txt.classList.remove("answer-pop");
      }, 1800);
    }, 900);
  }

  function playReact() {
    var box = document.getElementById("react-box");
    var label = document.getElementById("react-label");
    if (!box) return;
    if (state._reactState === "waiting") {
      state._reactState = "idle";
      box.textContent = "⚡"; box.style.color = "var(--hint)";
      label.textContent = "Рано! Ещё раз";
      haptic("error");
      return;
    }
    if (state._reactState === "ready") {
      var ms = Date.now() - state._reactStart;
      state._reactState = "idle";
      box.textContent = ms + "мс"; box.style.color = ms < 250 ? "#00c9a7" : ms < 400 ? "var(--ink)" : "#ff8c42";
      label.textContent = ms < 200 ? "Молния! ⚡" : ms < 300 ? "Быстро! 🔥" : ms < 450 ? "Нормально 👍" : "Медленно 🐢";
      haptic(ms < 300 ? "success" : "light");
      return;
    }
    state._reactState = "waiting";
    box.textContent = "⏳"; box.style.color = "#ff8c42";
    label.textContent = "Жди зелёный…";
    var delay = 1000 + Math.floor(Math.random()*3000);
    state._reactTimer = setTimeout(function () {
      if (state._reactState !== "waiting") return;
      state._reactState = "ready";
      state._reactStart = Date.now();
      box.textContent = "ЖМИ!"; box.style.color = "#00c9a7";
      label.textContent = "Сейчас!";
      haptic("warning");
    }, delay);
  }

  function playWheel() {
    var wheel = document.getElementById("wheel");
    var txt = document.getElementById("wheel-text");
    if (!wheel || state._wheelBusy) return;
    state._wheelBusy = true;

    var seg = 360 / WHEEL_PRIZES.length;
    var idx = Math.floor(Math.random() * WHEEL_PRIZES.length);
    var jitter = (Math.random() * (seg - 12) - (seg - 12) / 2);
    var turns = 5 + Math.floor(Math.random() * 3);
    // сегмент idx должен оказаться под указателем (сверху)
    var base = state._wheelAngle || 0;
    var target = -(idx * seg + seg / 2) + jitter;
    var minTarget = base + 360 * turns;
    target += Math.ceil((minTarget - target) / 360) * 360;
    state._wheelAngle = target;

    wheel.style.transform = "rotate(" + target + "deg)";
    txt.textContent = "Крутится…";
    haptic("light");

    setTimeout(function () {
      state._wheelBusy = false;
      txt.textContent = WHEEL_PRIZES[idx];
      txt.classList.add("answer-pop");
      haptic("success");
      celebrate(gameCard(wheel), idx === 0 || idx === 9);
      setTimeout(function () { txt.classList.remove("answer-pop"); }, 1600);
    }, 3700);
  }

  function submitGuess() {
    var input = document.getElementById("guess-input");
    var hint = document.getElementById("guess-hint");
    if (!input || !hint) return;
    var val = parseInt(input.value, 10);
    if (!val || val < 1 || val > 100) { toast("Введи число 1–100"); return; }
    state._guessAttempts = (state._guessAttempts || 0) + 1;
    if (val === state._guessTarget) {
      hint.textContent = "🎉"; hint.style.color = "#00c9a7";
      hint.classList.add("answer-pop");
      toast("Угадал за " + state._guessAttempts + " попыток! 🎉");
      haptic("success");
      celebrate(gameCard(hint), state._guessAttempts <= 3);
      setTimeout(function () { hint.classList.remove("answer-pop"); }, 1500);
      state._guessTarget = Math.floor(Math.random()*100)+1;
      state._guessAttempts = 0;
      input.value = "";
    } else if (val < state._guessTarget) {
      hint.textContent = "⬆️"; hint.style.color = "var(--ink)";
      toast("Больше! Попытка " + state._guessAttempts);
      haptic("light");
    } else {
      hint.textContent = "⬇️"; hint.style.color = "var(--ink)";
      toast("Меньше! Попытка " + state._guessAttempts);
      haptic("light");
    }
    input.value = "";
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
    var head = state.screen === "tools"
      ? subHeader(t("tools_title"))
      : "<h1>" + esc(t("tools_title")) + "</h1>";
    if (state.tools === null) {
      view.innerHTML = head + '<div class="skeleton"></div>';
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
      head +
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

  function humanSize(n) {
    n = Number(n) || 0;
    if (n >= 1024 * 1024 * 1024) return (n / 1024 / 1024 / 1024).toFixed(2) + " ГБ";
    if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + " МБ";
    if (n >= 1024) return Math.round(n / 1024) + " КБ";
    return n + " Б";
  }

  function renderLeaks() {
    var head = '<h1>' + esc(t("leaks_title")) + "</h1>";
    if (state.leaksError) {
      view.innerHTML = head + '<div class="card"><div class="muted">' + esc(state.leaksError) +
        '</div><button class="btn secondary" data-action="leaks-reload">↻ ' + esc(t("retry")) + "</button></div>";
      return;
    }
    if (!state.leaks) {
      view.innerHTML = head + '<div class="skeleton"></div><div class="skeleton"></div>';
      return;
    }
    var items = state.leaks.items || [];
    if (!items.length) {
      view.innerHTML = head + '<div class="card center"><div style="font-size:36px">🗂</div>' +
        '<div class="muted">' + esc(t("leaks_empty")) + "</div></div>";
      return;
    }
    var cards = items.map(function (it) {
      var busy = state.leakBusy === it.id;
      var meta = [humanSize(it.file_size), when(it.created_at)];
      if (it.downloads) meta.push("⬇ " + it.downloads);
      return '<div class="card leak-card">' +
        '<div class="row-title">' + esc(it.title || it.file_name || ("#" + it.id)) + "</div>" +
        '<div class="row-sub">' + esc(meta.filter(Boolean).join(" · ")) + "</div>" +
        (it.comment ? '<div class="leak-comment">' + esc(it.comment) + "</div>" : "") +
        '<div class="leak-actions">' +
        '<button class="btn small' + (busy ? "" : "") + '" data-action="leak-download" data-value="' + it.id + '"' +
        (busy ? ' disabled' : "") + ">" +
        (busy ? "⏳ " + esc(t("leak_downloading")) : "⬇ " + esc(t("leak_download"))) + "</button>" +
        (it.share_url
          ? '<button class="btn small secondary" data-action="leak-share" data-value="' + it.id + '">🔗 ' +
            esc(t("leak_share")) + "</button>"
          : "") +
        "</div>" +
        "</div>";
    }).join("");
    view.innerHTML = head +
      '<div class="muted leaks-hint">' + esc(t("leaks_hint")) + "</div>" +
      '<div class="leaks-list">' + cards + "</div>";
  }

  function loadLeaks(force) {
    if (state.leaks && !force) return Promise.resolve(state.leaks);
    state.leaksError = null;
    if (force) { state.leaks = null; if (state.tab === "leaks") render(); }
    return api("leaks").then(function (data) {
      state.leaks = data;
      if (state.tab === "leaks") render();
      return data;
    }).catch(function (err) {
      if (err.status === 403 && err.data && err.data.error === "subscription") {
        state.paywall = err.data;
        render();
        return null;
      }
      state.leaksError = err.message || t("error_text");
      if (state.tab === "leaks") render();
      return null;
    });
  }

  function downloadLeak(id) {
    if (state.leakBusy) return;
    var list = (state.leaks && state.leaks.items) || [];
    var item = null;
    for (var i = 0; i < list.length; i++) if (list[i].id === id) item = list[i];
    state.leakBusy = id;
    render();
    var initData = tg ? (tg.initData || "") : "";
    fetch("/app/api/leaks/" + id + "/file", { headers: { "X-Init-Data": initData } })
      .then(function (res) {
        if (!res.ok) throw new Error(t("leak_failed"));
        return res.blob();
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = (item && item.file_name) || "leak-" + id;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
        if (item) item.downloads = (item.downloads || 0) + 1;
        haptic("success");
      })
      .catch(function (err) { toast((err && err.message) || t("leak_failed")); })
      .then(function () {
        state.leakBusy = 0;
        render();
      });
  }

  function shareLeak(id, list) {
    var items = list || (state.leaks && state.leaks.items) || [];
    var item = null;
    for (var i = 0; i < items.length; i++) if (items[i].id === id) item = items[i];
    if (!item || !item.share_url) { toast(t("leak_failed")); return; }
    haptic("light");
    if (tg && tg.openTelegramLink) tg.openTelegramLink(item.share_url);
    else window.open(item.share_url, "_blank");
  }

  function copyText(text) {
    if (!text) return;
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        toast(t("leak_link_copied"));
        haptic("success");
      });
    }
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

    var support = data.support || {};
    var supportBlock = "";
    if (support.enabled) {
      supportBlock =
        "<h2>" + esc(t("support_title")) + "</h2>" +
        '<div class="card support-card">' +
        '<div class="support-head"><span class="support-chip">GRAM</span>' +
        '<span class="support-net">TON</span></div>' +
        '<div class="muted">' + esc(t("support_hint")) + "</div>" +
        '<div class="support-row"><span class="support-k">' + esc(t("support_address")) + "</span>" +
        '<code class="support-v" id="support-address">' + esc(support.wallet) + "</code>" +
        '<button class="chip support-copy" data-action="support-copy" data-copy="' +
        esc(support.wallet) + '">' + esc(t("support_copy")) + "</button></div>" +
        '<div class="support-note">💛 ' + esc(t("support_note")) + "</div>" +
        "</div>";
    }

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
      supportBlock +
      (models ? "<h2>" + esc(t("buy_models")) + '</h2><div class="card">' + models + "</div>" : "");

    if (state.anchor) {
      var target = view.querySelector("." + state.anchor);
      state.anchor = null;
      if (target) {
        setTimeout(function () { target.scrollIntoView({ block: "center" }); }, 60);
      }
    }
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

  // ---------------------------------------------------------------- админ-панель
  var ADMIN_TITLES = {
    dash: "Админ-панель", stats: "Статистика", users: "Пользователи",
    user: "Пользователь", payments: "Платежи", promos: "Промокоды",
    settings: "Настройки", roles: "Роли", broadcast: "Рассылка",
    aitest: "Проверка ИИ", tickets: "Тикеты", ticket: "Обращение",
    channels: "Каналы", giveaways: "Розыгрыши", leaks: "Сливы"
  };

  function adminApi(op, payload) {
    return api("admin", Object.assign({ op: op }, payload || {})).then(function (data) {
      if (data && data.ok === false) {
        var err = new Error(data.error || "Ошибка");
        err.admin = true;
        throw err;
      }
      return data || {};
    });
  }

  function adminApply(screen, data) {
    if (screen === "user") state.adminUser = data;
    else if (screen === "ticket") state.adminTicket = data;
    else state.adminData = data;
    state.adminScreen = screen;
    state.adminLoading = false;
    if (data && data.notice) toast(data.notice);
    render();
    return data;
  }

  function adminGo(screen, opts) {
    opts = opts || {};
    state.adminScreen = screen;
    state.adminLoading = true;
    state.adminError = null;
    if (screen === "user") state.adminUser = null;
    if (screen === "ticket") state.adminTicket = null;
    if (screen !== "users") state.adminUsersOffset = state.adminUsersOffset || 0;
    setDir(opts.back ? "back" : "fwd");
    render();
    adminApi(opts.op || screen, opts.payload).then(function (data) {
      adminApply(screen, data);
    }).catch(function (err) {
      state.adminLoading = false;
      state.adminError = err.message || t("error_text");
      toast(state.adminError);
      render();
    });
  }

  function adminMutate(op, payload, screen) {
    return adminApi(op, payload).then(function (data) {
      adminApply(screen || state.adminScreen, data);
    }).catch(function (err) {
      toast(err.message || t("error_text"));
    });
  }

  function adminRefresh() {
    var s = state.adminScreen;
    if (s === "user" && state.adminUser && state.adminUser.card) {
      return adminGo("user", { payload: { id: state.adminUser.card.user.id } });
    }
    if (s === "ticket" && state.adminTicket && state.adminTicket.ticket) {
      return adminGo("ticket", { payload: { id: state.adminTicket.ticket.id } });
    }
    if (s === "broadcast") return adminGo("broadcast", { op: "broadcast.count" });
    if (s === "aitest") return adminGo("aitest", { op: "aitest" });
    return adminGo(s || "dash");
  }

  function adminBack() {
    var s = state.adminScreen;
    if (s === "user") {
      return adminGo("users", { payload: { offset: state.adminUsersOffset || 0 }, back: true });
    }
    if (s === "ticket") {
      return adminGo("tickets", { payload: { offset: state.adminTicketsOffset || 0 }, back: true });
    }
    return adminGo("dash", { back: true });
  }

  function adminHead(title) {
    var back = state.adminScreen === "dash"
      ? ""
      : '<button class="back" data-action="admin-back">← Назад</button>';
    return '<div class="head">' + back + '<span class="admin-role">' +
      esc((state.me && state.me.role_title) || "сотрудник") + "</span></div>" +
      "<h1>" + esc(title) + "</h1>";
  }

  function adminTile(icon, title, section, sub) {
    return '<button class="admin-tile" data-action="admin-nav" data-value="' + section + '">' +
      '<span class="admin-tile-ico">' + icon + "</span>" +
      '<span class="admin-tile-title">' + esc(title) + "</span>" +
      (sub ? '<span class="admin-tile-sub">' + esc(sub) + "</span>" : "") + "</button>";
  }

  function adminSectionAllowed(section) {
    if (!state.me) return false;
    if (state.me.is_admin) return true;
    return section === "dash" || section === "tickets" || section === "ticket";
  }

  function renderAdmin() {
    if (!state.me || (!state.me.is_admin && !state.me.is_staff)) {
      view.innerHTML = '<div class="card"><div class="row-title">Нет доступа</div>' +
        '<div class="muted">Раздел доступен только сотрудникам.</div></div>';
      return;
    }
    var screen = state.adminScreen || "dash";
    if (!adminSectionAllowed(screen)) { screen = "dash"; state.adminScreen = screen; }
    if (state.adminLoading) {
      view.innerHTML = adminHead(ADMIN_TITLES[screen] || "Админ-панель") +
        '<div class="skeleton"></div><div class="skeleton"></div>';
      return;
    }
    if (state.adminError && !state.adminData && !state.adminUser && !state.adminTicket) {
      view.innerHTML = adminHead(ADMIN_TITLES[screen] || "Админ-панель") +
        '<div class="card"><div class="muted">' + esc(state.adminError) + "</div>" +
        '<button class="btn secondary" data-action="admin-refresh">↻ Повторить</button></div>';
      return;
    }
    if (screen === "stats") renderAdminStats();
    else if (screen === "users") renderAdminUsers();
    else if (screen === "user") renderAdminUser();
    else if (screen === "payments") renderAdminPayments();
    else if (screen === "promos") renderAdminPromos();
    else if (screen === "settings") renderAdminSettings();
    else if (screen === "roles") renderAdminRoles();
    else if (screen === "broadcast") renderAdminBroadcast();
    else if (screen === "aitest") renderAdminAiTest();
    else if (screen === "tickets") renderAdminTickets();
    else if (screen === "ticket") renderAdminTicket();
    else if (screen === "channels") renderAdminChannels();
    else if (screen === "giveaways") renderAdminGiveaways();
    else if (screen === "leaks") renderAdminLeaks();
    else renderAdminDash();
  }

  function renderAdminDash() {
    var d = state.adminData || {};
    var s = d.stats || {};
    var pay = d.payments || {};
    var tickets = d.tickets || {};
    var promos = d.promos || {};
    var admin = !!(state.me && state.me.is_admin);
    var tiles = "";
    if (admin) {
      tiles += adminTile("👥", "Пользователи", "users", (s.users || 0) + " чел.");
      tiles += adminTile("📊", "Статистика", "stats", (s.requests_today || 0) + " сегодня");
      tiles += adminTile("⭐", "Платежи", "payments", (pay.stars || 0) + " ⭐");
      tiles += adminTile("🎟", "Промокоды", "promos", (promos.active || 0) + " активных");
      tiles += adminTile("⚙️", "Настройки", "settings");
      tiles += adminTile("📣", "Рассылка", "broadcast");
      if (state.me && state.me.can_manage_roles) tiles += adminTile("👑", "Роли", "roles");
      tiles += adminTile("📢", "Каналы", "channels");
      tiles += adminTile("🎉", "Розыгрыши", "giveaways");
      tiles += adminTile("🗂", "Сливы", "leaks");
      tiles += adminTile("🧪", "Проверка ИИ", "aitest");
    }
    tiles += adminTile("🎫", "Тикеты", "tickets", (tickets.open || 0) + " открыто");

    var kpi = '<div class="grid">' +
      statCard(s.users || 0, "пользователей") +
      statCard(s.requests_today || 0, "сегодня") +
      statCard(s.active_today || 0, "активных") +
      statCard(s.banned || 0, "забанено") +
      statCard(tickets.open || 0, "тикетов") +
      statCard(promos.active || 0, "промокодов") +
      "</div>";

    var gift = admin
      ? "<h2>🎁 Подарить всем</h2>" +
        '<div class="card"><div class="muted">Начислит бонусные запросы каждому пользователю.</div>' +
        '<div class="field"><input class="input" id="admin-gift-count" type="number" min="1" max="10000" placeholder="Сколько запросов">' +
        '<button class="btn small" data-action="admin-giftall">Выдать</button></div></div>'
      : "";

    view.innerHTML = adminHead("Админ-панель") +
      (admin ? '<div class="card"><div class="row"><div><div class="row-title">' +
        esc(d.role_title || "Сотрудник") + '</div><div class="row-sub">Модель: ' +
        esc((d.runtime && d.runtime.model) || "—") + '</div></div>' +
        '<button class="chip" data-action="admin-refresh">↻</button></div></div>' : "") +
      kpi +
      "<h2>Разделы</h2>" +
      '<div class="admin-grid">' + tiles + "</div>" +
      gift;
  }

  function renderAdminStats() {
    var d = state.adminData || {};
    var s = d.stats || {};
    var pay = d.payments || {};
    var tickets = d.tickets || {};
    var fb = d.feedback || {};
    var rt = d.runtime || {};
    var top = (d.top || []).map(function (row, i) {
      return '<div class="item"><div class="body"><b>' + (i + 1) + ". " + esc(row.name) +
        '</b><div class="when">ID ' + row.user_id + "</div></div>" +
        '<span class="admin-count">' + esc(row.total) + "</span></div>";
    }).join("") || '<div class="empty">Пока пусто</div>';
    var max = 1;
    (d.activity || []).forEach(function (a) { if (a.total > max) max = a.total; });
    var bars = (d.activity || []).map(function (a) {
      var h = Math.max(4, Math.round((a.total / max) * 100));
      return '<div class="admin-bar" title="' + esc(a.day) + ": " + a.total + '">' +
        '<span style="height:' + h + '%"></span><em>' + esc(a.day.slice(5)) + "</em></div>";
    }).join("");

    view.innerHTML = adminHead("Статистика") +
      '<div class="grid">' +
      statCard(s.users || 0, "пользователей") +
      statCard(s.banned || 0, "забанено") +
      statCard(s.active_today || 0, "активных") +
      statCard(s.requests_today || 0, "запросов сегодня") +
      statCard(tickets.open || 0, "тикетов") +
      statCard(pay.stars || 0, "звёзд") +
      "</div>" +
      "<h2>Активность за 7 дней</h2>" +
      '<div class="card"><div class="admin-chart">' + bars + "</div></div>" +
      "<h2>Обратная связь</h2>" +
      '<div class="card"><div class="row"><div class="row-title">👍 / 👎</div>' +
      '<div class="admin-count">' + (fb.up || 0) + " / " + (fb.down || 0) + "</div></div>" +
      '<div class="muted" style="margin-top:6px">Оценено ответов: ' + (fb.total || 0) + "</div></div>" +
      "<h2>Топ по запросам</h2>" +
      '<div class="card">' + top + "</div>" +
      "<h2>Сейчас</h2>" +
      '<div class="card"><div class="row"><div class="row-title">Модель</div><div class="admin-count">' +
      esc(rt.model || "—") + '</div></div><div class="row"><div class="row-title">Лимит в день</div>' +
      '<div class="admin-count">' + (rt.daily_limit > 0 ? rt.daily_limit : "∞") + "</div></div>" +
      '<div class="row"><div class="row-title">Контекст</div><div class="admin-count">' +
      (rt.max_context || 0) + "</div></div></div>";
  }

  function renderAdminUsers() {
    var d = state.adminData || { items: [], total: 0, offset: 0 };
    state.adminUsersOffset = d.offset || 0;
    var rows = (d.items || []).map(function (u) {
      return '<button class="admin-item" data-action="admin-user-open" data-value="' + u.user_id + '">' +
        '<span class="admin-item-ico">' + (u.banned ? "🚫" : "👤") + "</span>" +
        '<span class="admin-item-main"><b>' + esc(u.name) + "</b>" +
        '<span class="admin-sub">ID ' + u.user_id + " · сегодня " + u.used_today + "</span></span>" +
        '<span class="admin-chev">›</span></button>';
    }).join("") || '<div class="empty">Пользователей пока нет</div>';
    var nav = "";
    if ((d.offset || 0) > 0) {
      nav += '<button class="chip" data-action="admin-users-page" data-value="' +
        Math.max(0, d.offset - (d.page || 20)) + '">← Назад</button>';
    }
    if ((d.offset || 0) + (d.page || 20) < (d.total || 0)) {
      nav += '<button class="chip" data-action="admin-users-page" data-value="' +
        (d.offset + (d.page || 20)) + '">Дальше →</button>';
    }
    view.innerHTML = adminHead("Пользователи") +
      '<div class="card"><div class="field"><input class="input" id="admin-user-search" type="number" inputmode="numeric" placeholder="ID пользователя">' +
      '<button class="btn small" data-action="admin-user-find">Найти</button></div>' +
      '<div class="muted" style="margin-top:8px">Всего: ' + (d.total || 0) + "</div></div>" +
      '<div class="admin-list">' + rows + "</div>" +
      (nav ? '<div class="field admin-pager">' + nav + "</div>" : "");
  }

  function renderAdminUser() {
    var data = state.adminUser || {};
    var card = data.card || {};
    var u = card.user || {};
    var models = card.models || [];
    var uid = u.id || 0;
    var roleChips = (card.assignable || []).filter(function (o) {
      return o.allowed;
    }).map(function (o) {
      var on = o.role === card.role ? " active" : "";
      return '<button class="chip' + on + '" data-action="admin-user-role" data-value="' +
        o.role + '">' + esc(o.title) + "</button>";
    }).join("");
    var modelRows = models.map(function (m) {
      var mark = m.owned ? "✅" : "⬜";
      if (m.free) {
        return '<div class="row"><div><div class="row-title">' + mark + " " + esc(m.title) +
          '</div><div class="row-sub">бесплатная</div></div>' +
          (m.chosen ? '<span class="admin-badge">выбрана</span>' : "") + "</div>";
      }
      return '<div class="row"><div><div class="row-title">' + mark + " " + esc(m.title) +
        '</div><div class="row-sub">' + (m.stars || 0) + ' ⭐</div></div>' +
        '<button class="chip" data-action="admin-model" data-value="' + esc(m.id) +
        '" data-grant="' + (m.owned ? "0" : "1") + '">' + (m.owned ? "Закрыть" : "Открыть") + "</button></div>";
    }).join("");

    view.innerHTML = adminHead("Пользователь") +
      '<div class="card">' +
      '<div class="row"><div><div class="row-title">' + esc(u.name || ("ID " + uid)) +
      '</div><div class="row-sub">ID ' + uid + (u.username ? " · @" + esc(u.username) : "") +
      "</div></div>" +
      '<span class="admin-badge ' + (u.banned ? "bad" : "ok") + '">' +
      (u.banned ? "забанен" : "активен") + "</span></div>" +
      '<div class="row"><div class="row-title">Роль</div><div class="admin-count">' +
      esc(card.role_title || "обычный") + "</div></div>" +
      '<div class="row"><div class="row-title">Сегодня / всего</div><div class="admin-count">' +
      (u.used_today || 0) + " / " + (u.total_requests || 0) + "</div></div>" +
      '<div class="row"><div class="row-title">Бонусные запросы</div><div class="admin-count">' +
      (u.bonus_requests || 0) + "</div></div>" +
      '<div class="row"><div class="row-title">Генерации картинок</div><div class="admin-count">' +
      (u.image_credits || 0) + "</div></div>" +
      '<div class="row"><div class="row-title">История</div><div class="admin-count">' +
      (u.history_len || 0) + " сообщений</div></div>" +
      '<div class="row"><div class="row-title">Подписка</div><div class="admin-count">' +
      (u.subscription_until ? esc(when(u.subscription_until)) : "—") + "</div></div>" +
      "</div>" +

      '<div class="card"><div class="row"><div class="row-title">Действия</div></div>' +
      '<button class="btn ' + (u.banned ? "" : "secondary") + '" data-action="admin-user-ban" data-value="' +
      (u.banned ? "0" : "1") + '">' + (u.banned ? "✅ Разбанить" : "🚫 Забанить") + "</button>" +
      '<button class="btn secondary" data-action="admin-user-reset">🧹 Сбросить контекст</button></div>' +

      '<div class="card"><div class="row"><div class="row-title">⭐ Выдать запросы</div></div>' +
      '<div class="field"><input class="input" id="admin-bonus" type="number" min="1" max="100000" placeholder="Сколько запросов">' +
      '<button class="btn small" data-action="admin-user-bonus">Выдать</button></div></div>' +

      '<div class="card"><div class="row"><div class="row-title">🖼 Выдать генерации</div></div>' +
      '<div class="field"><input class="input" id="admin-images" type="number" min="1" max="10000" placeholder="Сколько генераций">' +
      '<button class="btn small" data-action="admin-user-images">Выдать</button></div></div>' +

      (card.can_manage_roles && roleChips
        ? '<div class="card"><div class="row"><div class="row-title">👑 Роль</div></div>' +
          '<div class="chips">' + roleChips + "</div>" +
          (card.role
            ? '<button class="btn secondary" data-action="admin-user-role-clear">Снять роль</button>'
            : "") + "</div>"
        : "") +

      '<div class="card"><div class="row"><div class="row-title">🧠 Модели</div></div>' +
      modelRows + "</div>";
  }

  function renderAdminPayments() {
    var d = state.adminData || { stats: {}, items: [] };
    var s = d.stats || {};
    var rows = (d.items || []).map(function (p) {
      var what;
      if (p.kind === "sub") what = "💎 подписка · " + p.requests + " дн.";
      else if (p.kind === "model") what = "🧠 " + (p.model_title || p.model);
      else what = "+" + p.requests + " запросов";
      return '<div class="item"><div class="body"><b>' + esc(what) + "</b>" +
        '<div class="when">' + esc(p.name) + " · " + (p.stars || 0) + " ⭐ · " +
        esc(when(p.created_at)) + (p.refunded ? " · ↩️ возвращён" : "") + "</div></div>" +
        (p.refunded ? "" : '<button class="chip admin-danger" data-action="admin-refund" data-value="' +
          p.id + '">↩️</button>') + "</div>";
    }).join("") || '<div class="empty">Покупок пока не было</div>';

    view.innerHTML = adminHead("Платежи") +
      '<div class="grid">' +
      statCard(s.count || 0, "платежей") +
      statCard(s.stars || 0, "звёзд") +
      statCard(s.requests || 0, "продано") +
      "</div>" +
      "<h2>Последние</h2>" +
      '<div class="card">' + rows + "</div>";
  }

  function renderAdminPromos() {
    var d = state.adminData || { stats: {}, items: [] };
    var s = d.stats || {};
    var rows = (d.items || []).map(function (p) {
      var reward = [];
      if (p.requests) reward.push("+" + p.requests + " зап.");
      if (p.image_credits) reward.push("+" + p.image_credits + " 🖼");
      var limit = p.max_uses > 0 ? (p.uses + "/" + p.max_uses) : (p.uses + " без лимита");
      var expiry = p.expires_at ? ("до " + when(p.expires_at)) : "бессрочно";
      return '<div class="item"><div class="body"><b>' + esc(p.code) + "</b>" +
        '<div class="when">' + esc(reward.join(" · ") || "—") + " · " + esc(limit) +
        " · " + esc(expiry) + (p.expired ? " · истёк" : "") + "</div></div>" +
        '<button class="chip admin-danger" data-action="admin-promo-del" data-value="' +
        esc(p.code) + '">🗑</button></div>';
    }).join("") || '<div class="empty">Промокодов пока нет</div>';

    view.innerHTML = adminHead("Промокоды") +
      '<div class="card"><div class="row"><div><div class="row-title">Всего ' + (s.total || 0) +
      '</div><div class="row-sub">Активных: ' + (s.active || 0) + " · активаций: " + (s.uses || 0) +
      "</div></div></div>" +
      '<div class="field"><input class="input" id="admin-promo-code" placeholder="КОД" autocapitalize="characters"></div>' +
      '<div class="field"><input class="input" id="admin-promo-req" type="number" min="0" placeholder="Запросы">' +
      '<input class="input" id="admin-promo-img" type="number" min="0" placeholder="Картинки"></div>' +
      '<div class="field"><input class="input" id="admin-promo-uses" type="number" min="0" placeholder="Лимит (0 — без)">' +
      '<input class="input" id="admin-promo-days" type="number" min="0" placeholder="Дней (0 — бессрочно)"></div>' +
      '<button class="btn" data-action="admin-promo-create">➕ Создать промокод</button></div>' +
      "<h2>Список</h2>" +
      '<div class="card">' + rows + "</div>";
  }

  function renderAdminSettings() {
    var d = state.adminData || {};
    var s = d.settings || {};
    var items = s.items || [];
    var rows = items.map(function (it) {
      var html = '<div class="admin-setting"><div class="row"><div><div class="row-title">' +
        esc(it.label) + '</div><div class="row-sub">' + esc(it.hint || "") + "</div></div>" +
        '<button class="chip" data-action="admin-setting-edit" data-value="' + esc(it.key) + '">✏️</button></div>';
      if (state.adminEdit === it.key) {
        html += it.multiline
          ? '<textarea class="input admin-textarea" id="admin-set-' + it.key + '">' + esc(it.value) + "</textarea>"
          : '<input class="input admin-input" id="admin-set-' + it.key + '" value="' + esc(it.value) + '">';
        html += '<div class="field"><button class="btn small" data-action="admin-setting-save" data-value="' +
          esc(it.key) + '">Сохранить</button>' +
          '<button class="btn small secondary" data-action="admin-setting-cancel">Отмена</button></div>';
      } else {
        html += '<div class="admin-value">' + esc(it.value || "—") +
          (it.override ? ' <span class="admin-badge">из админки</span>' : "") + "</div>";
      }
      return html + "</div>";
    }).join("");

    var providers = d.providers || [];
    var providerChips = providers.map(function (p) {
      var mark = p.active ? "✅ " : (p.reserve ? "🛟 " : "");
      var cls = "chip" + (p.active ? " chip-active" : "");
      var state = p.cooling > 0
        ? " · 💤 " + p.cooling + " с"
        : (p.key_state && p.key_state !== "свой ключ" ? " · " + p.key_state : "");
      return '<button class="' + cls + '" data-action="admin-provider" data-value="' +
        esc(p.id) + '">' + mark + esc(p.label) + state + "</button>";
    }).join(" ");
    var providerCard = providers.length
      ? '<div class="card"><div class="row-title">🔌 Провайдер ИИ</div>' +
        '<div class="row-sub">Выбранный отвечает первым, резервные (🛟) — по порядку</div>' +
        '<div class="admin-chips">' + providerChips + "</div></div>"
      : "";

    view.innerHTML = adminHead("Настройки") + providerCard +
      '<div class="card"><div class="row"><div><div class="row-title">🔐 Гейт в чатах</div>' +
      '<div class="row-sub">' + (s.group_gate ? "включён" : "выключен") + "</div></div>" +
      '<button class="btn small secondary" data-action="admin-gate">' +
      (s.group_gate ? "Выключить" : "Включить") + "</button></div></div>" +
      '<div class="card">' + rows + "</div>" +
      '<button class="btn secondary" data-action="admin-setting-reset">♻️ Вернуть значения из env</button>';
  }

  function renderAdminRoles() {
    var d = state.adminData || {};
    var rows = (d.items || []).map(function (r) {
      return '<div class="item"><div class="body"><b>' + esc(r.name) + "</b>" +
        '<div class="when">' + esc(r.role_title) + " · ID " + r.user_id + "</div></div>" +
        '<button class="chip admin-danger" data-action="admin-role-clear" data-value="' +
        r.user_id + '">Снять</button></div>';
    }).join("") || '<div class="empty">Ролей из бота пока нет</div>';
    var env = (d.env_admins || []).map(function (id) {
      return '<div class="item"><div class="body"><b>ID ' + id + "</b>" +
        '<div class="when">🛡 админ из ADMIN_IDS</div></div></div>';
    }).join("");
    var chips = (d.assignable || []).map(function (o) {
      return '<button class="chip" data-action="admin-role-grant" data-value="' +
        o.role + '">' + esc(o.title) + "</button>";
    }).join("");

    view.innerHTML = adminHead("Роли") +
      '<div class="card"><div class="row"><div class="row-title">👑 Владелец</div>' +
      '<div class="admin-count">' + (d.owner_id || "не задан") + "</div></div>" +
      '<div class="muted" style="margin-top:6px">Владелец задаётся только через OWNER_ID.</div></div>' +
      '<div class="card"><div class="row"><div class="row-title">➕ Выдать роль по ID</div></div>' +
      '<div class="field"><input class="input" id="admin-role-id" type="number" inputmode="numeric" placeholder="Telegram ID"></div>' +
      '<div class="chips">' + chips + "</div>" +
      '<div class="muted" style="margin-top:8px">Пользователь должен хотя бы раз написать боту, иначе уведомление не дойдёт.</div></div>' +
      "<h2>Назначенные роли</h2>" +
      '<div class="card">' + rows + env + "</div>";
  }

  function renderAdminBroadcast() {
    var d = state.adminData || {};
    if (d.count != null) state.adminBcastCount = d.count;
    var count = state.adminBcastCount || 0;
    view.innerHTML = adminHead("Рассылка") +
      '<div class="card"><div class="row"><div><div class="row-title">Получатели</div>' +
      '<div class="row-sub">активные пользователи</div></div>' +
      '<div class="admin-count">' + count + "</div></div>" +
      '<textarea class="input admin-textarea" id="admin-bcast-text" placeholder="Текст рассылки">' +
      esc(state.adminBcastText || "") + "</textarea>" +
      '<button class="btn" data-action="admin-bcast-send">' +
      (state.adminBcastConfirm ? "✅ Подтвердить отправку" : "📣 Отправить") + "</button>" +
      (state.adminBcastConfirm ? '<div class="muted" style="margin-top:8px">Нажми ещё раз, чтобы подтвердить.</div>' : "") +
      "</div>";
  }

  function renderAdminAiTest() {
    var d = state.adminData || {};
    var body;
    if (d.success === true) {
      body = '<div class="card"><div class="row"><div class="row-title">✅ ИИ отвечает</div>' +
        '<div class="admin-count">' + esc(d.elapsed || 0) + " с</div></div>" +
        '<div class="admin-value">' + esc(d.answer || "") + "</div></div>";
    } else if (d.success === false) {
      body = '<div class="card"><div class="row"><div class="row-title">⚠️ ИИ не ответил</div>' +
        '<div class="admin-count">' + esc(d.elapsed || 0) + " с</div></div>" +
        '<div class="admin-value">' + esc(d.error || "") + "</div></div>";
    } else {
      body = '<div class="skeleton"></div>';
    }
    view.innerHTML = adminHead("Проверка ИИ") + body +
      '<button class="btn secondary" data-action="admin-refresh">🔄 Проверить снова</button>';
  }

  function renderAdminTickets() {
    var d = state.adminData || { stats: {}, items: [] };
    state.adminTicketsOffset = d.offset || 0;
    var s = d.stats || {};
    var rows = (d.items || []).map(function (t) {
      return '<button class="admin-item" data-action="admin-ticket-open" data-value="' + t.id + '">' +
        '<span class="admin-item-ico">🎫</span>' +
        '<span class="admin-item-main"><b>#' + t.id + " · " + esc(t.topic_title) + "</b>" +
        '<span class="admin-sub">' + esc(t.name) + " · " + esc(when(t.updated_at)) + "</span></span>" +
        '<span class="admin-chev">›</span></button>';
    }).join("") || '<div class="empty">Открытых обращений нет</div>';
    var nav = "";
    if ((d.offset || 0) > 0) {
      nav += '<button class="chip" data-action="admin-tickets-page" data-value="' +
        Math.max(0, d.offset - (d.limit || 20)) + '">← Назад</button>';
    }
    if ((d.items || []).length >= (d.limit || 20)) {
      nav += '<button class="chip" data-action="admin-tickets-page" data-value="' +
        (d.offset + (d.limit || 20)) + '">Дальше →</button>';
    }
    view.innerHTML = adminHead("Тикеты") +
      '<div class="grid">' +
      statCard(s.open || 0, "открыто") +
      statCard(s.closed || 0, "закрыто") +
      statCard(s.total || 0, "всего") +
      "</div>" +
      '<div class="admin-list">' + rows + "</div>" +
      (nav ? '<div class="field admin-pager">' + nav + "</div>" : "");
  }

  function renderAdminTicket() {
    var data = state.adminTicket || {};
    var t = data.ticket || {};
    var msgs = (data.messages || []).map(function (m) {
      return '<div class="admin-msg' + (m.from_staff ? " staff" : "") + '">' +
        '<div class="admin-msg-head">' + (m.from_staff ? "🛡 Поддержка" : "👤 Пользователь") +
        " · " + esc(when(m.created_at)) + "</div>" +
        '<div class="admin-msg-text">' + esc(m.text) + "</div></div>";
    }).join("") || '<div class="empty">Сообщений нет</div>';
    var open = t.status === "open";
    view.innerHTML = adminHead("Обращение #" + (t.id || "")) +
      '<div class="card"><div class="row"><div><div class="row-title">' + esc(t.topic_title || "") +
      '</div><div class="row-sub">' + esc(t.name || "") + " · ID " + (t.user_id || "") +
      "</div></div><span class='admin-badge " + (open ? "ok" : "") + "'>" +
      (open ? "открыто" : "закрыто") + "</span></div></div>" +
      '<div class="card">' + msgs + "</div>" +
      (open
        ? '<div class="card"><textarea class="input admin-textarea" id="admin-ticket-reply" placeholder="Ответ пользователю"></textarea>' +
          '<button class="btn" data-action="admin-ticket-send">✍️ Ответить</button>' +
          '<button class="btn secondary" data-action="admin-ticket-close">✅ Закрыть обращение</button></div>'
        : "");
  }

  function renderAdminChannels() {
    var d = state.adminData || { items: [] };
    var items = d.items || [];
    if (state.adminChannel == null) state.adminChannel = items.length ? 0 : -1;
    if (state.adminChannel >= items.length) state.adminChannel = items.length ? 0 : -1;
    var list = items.map(function (ch) {
      return '<div class="item"><div class="body"><b>' + esc(ch.title) + "</b>" +
        '<div class="when">' + esc(ch.channel) + " · " + (ch.members || 0) + " подписчиков" +
        (ch.required ? " · проверка подписки" : "") + (ch.ok ? "" : " · ⚠️ нет доступа") + "</div></div>" +
        (ch.required ? "" : '<button class="chip admin-danger" data-action="admin-channel-del" data-value="' +
          ch.index + '">🗑</button>') + "</div>";
    }).join("") || '<div class="empty">Каналы не подключены</div>';
    var chips = items.map(function (ch) {
      return '<button class="chip' + (ch.index === state.adminChannel ? " active" : "") +
        '" data-action="admin-channel-pick" data-value="' + ch.index + '">' + esc(ch.title) + "</button>";
    }).join("");

    view.innerHTML = adminHead("Каналы") +
      '<div class="card"><div class="row"><div class="row-title">Подключённые каналы</div>' +
      '<div class="admin-count">' + items.length + "/" + (d.max || 8) + "</div></div>" + list +
      '<div class="muted" style="margin-top:8px">Бот должен быть администратором канала.</div></div>' +
      '<div class="card"><div class="row"><div class="row-title">➕ Подключить</div></div>' +
      '<div class="field"><input class="input" id="admin-channel-input" placeholder="@username или ссылка">' +
      '<button class="btn small" data-action="admin-channel-add">Добавить</button></div></div>' +
      (items.length
        ? '<div class="card"><div class="row"><div class="row-title">📝 Пост в канал</div></div>' +
          '<div class="chips">' + chips + "</div>" +
          '<textarea class="input admin-textarea" id="admin-channel-text" placeholder="Текст поста"></textarea>' +
          '<button class="btn" data-action="admin-channel-publish">📤 Опубликовать</button></div>'
        : "");
  }

  function renderAdminGiveaways() {
    var d = state.adminData || { stats: {}, items: [] };
    var s = d.stats || {};
    var rows = (d.items || []).map(function (g) {
      return '<div class="item"><div class="body"><b>' + esc(g.prize) + "</b>" +
        '<div class="when">до ' + esc(when(g.ends_at)) + " · участников: " + g.entries +
        " · победителей: " + g.winners + "</div></div>" +
        '<button class="chip admin-danger" data-action="admin-giveaway-cancel" data-value="' +
        g.id + '">Отменить</button></div>';
    }).join("") || '<div class="empty">Активных розыгрышей нет</div>';
    view.innerHTML = adminHead("Розыгрыши") +
      '<div class="grid">' +
      statCard(s.active || 0, "активных") +
      statCard(s.finished || 0, "завершено") +
      "</div>" +
      '<div class="card">' + rows + "</div>";
  }

  function renderAdminLeaks() {
    var d = state.adminData || { items: [] };
    var rows = (d.items || []).map(function (it) {
      var editing = state.adminLeakEdit === it.id;
      var body = editing
        ? '<textarea class="input admin-textarea" id="admin-leak-comment-' + it.id +
          '" placeholder="Комментарий">' + esc(it.comment || "") + "</textarea>" +
          '<div class="row" style="gap:8px;margin-top:8px">' +
          '<button class="btn small" data-action="admin-leak-save" data-value="' + it.id + '">Сохранить</button>' +
          '<button class="btn small secondary" data-action="admin-leak-edit-cancel">Отмена</button></div>'
        : (it.comment ? '<div class="admin-value">' + esc(it.comment) + "</div>" : "") +
          '<div class="row" style="gap:8px;margin-top:8px">' +
          '<button class="chip" data-action="admin-leak-edit" data-value="' + it.id + '">✏️ Комментарий</button>' +
          '<button class="chip" data-action="admin-leak-link" data-value="' + it.id + '">🔗 Ссылка</button>' +
          '<button class="chip admin-danger" data-action="admin-leak-del" data-value="' + it.id + '">Удалить</button></div>';
      return '<div class="admin-setting"><div class="row-title">' + esc(it.title) + "</div>" +
        '<div class="admin-sub">' + esc(it.file_name) + " · " + esc(humanSize(it.file_size)) +
        " · " + esc(when(it.created_at)) + " · ⬇ " + (it.downloads || 0) + "</div>" + body + "</div>";
    }).join("") || '<div class="empty">Файлов пока нет</div>';
    var upload = state.adminLeakUploading
      ? '<div class="muted">Загружаю и сохраняю в Telegram…</div>'
      : '<div class="field"><input class="input admin-file" id="admin-leak-file" type="file"></div>' +
        '<div class="field"><input class="input" id="admin-leak-title" placeholder="Название (необязательно)"></div>' +
        '<div class="field"><textarea class="input admin-textarea" id="admin-leak-comment" placeholder="Комментарий к файлу"></textarea></div>' +
        '<button class="btn" data-action="admin-leak-upload">📤 Загрузить файл</button>' +
        '<div class="muted" style="margin-top:8px">До 20 МБ. Файл хранится в Telegram, в чате загрузившего админа.</div>';
    view.innerHTML = adminHead("Сливы") +
      '<div class="card">' + upload + "</div>" +
      '<div class="card">' + rows + "</div>";
  }

  function adminUploadLeak() {
    if (state.adminLeakUploading) return;
    var input = document.getElementById("admin-leak-file");
    var file = input && input.files && input.files[0];
    if (!file) { toast("Выбери файл"); return; }
    var fd = new FormData();
    fd.append("file", file);
    fd.append("title", val("admin-leak-title").trim());
    fd.append("comment", val("admin-leak-comment").trim());
    var initData = tg ? (tg.initData || "") : "";
    state.adminLeakUploading = true;
    render();
    fetch("/app/api/admin/leak", {
      method: "POST",
      headers: { "X-Init-Data": initData },
      body: fd
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok || data.ok === false) {
          throw new Error(data.error || "Не удалось загрузить файл");
        }
        return data;
      });
    }).then(function (data) {
      state.adminLeakUploading = false;
      state.adminLeakEdit = null;
      adminApply("leaks", data);
    }).catch(function (err) {
      state.adminLeakUploading = false;
      render();
      toast(err.message || "Не удалось загрузить файл");
    });
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
    else if (state.screen === "friends") renderFriends(true);
    else if (state.screen === "settings") renderSettings(true);
    else if (state.screen === "season") renderSeason();
    else if (state.tab === "admin") renderAdmin();
    else if (state.tab === "stats") renderStats();
    else if (state.tab === "tasks") renderTools();
    else if (state.tab === "games") renderGames();
    else if (state.tab === "leaks") renderLeaks();
    else if (state.tab === "profile") renderProfile();
    else renderHome();
    renderTabs();
  }

  // Направление анимации перехода между экранами
  var TAB_ORDER = ["home", "stats", "tasks", "games", "leaks", "profile"];
  function setDir(dir) {
    view.setAttribute("data-dir", dir || "fwd");
  }
  function tabDir(from, to) {
    var a = TAB_ORDER.indexOf(from), b = TAB_ORDER.indexOf(to);
    if (a === -1 || b === -1) return "fwd";
    return b >= a ? "fwd" : "back";
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
    setDir("fwd");
    render();
    if (name === "history" && state.history === null) {
      api("history").then(function (data) { state.history = data.items || []; }).catch(function () {
        state.history = [];
      }).then(render);
    } else if (name === "tools" && state.tools === null) {
      ensureTools();
    } else if (name === "buy" && state.buy === null) {
      api("buy").then(function (data) { state.buy = data; }).catch(function () {
        toast(t("error_text"));
      }).then(render);
    } else if (name === "friends" && state.top == null) {
      loadTop().then(render);
    }
  }

  function ensureTools() {
    if (state.tools !== null || state._toolsLoading) return;
    state._toolsLoading = true;
    api("tools", { action: "load" }).then(function (data) {
      state.tools = data;
    }).catch(function () {
      state.tools = { todos: [], cards: [], reminders: [], limits: {} };
      toast(t("error_text"));
    }).then(function () {
      state._toolsLoading = false;
      render();
    });
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
        if (data.gamification) state.me.gamification = data.gamification;
      }
      toast(data.claimed ? t("bonus_claimed", { amount: data.amount }) : t("bonus_already"));
      haptic(data.claimed ? "success" : "warning");
      if (data.claimed) confetti(window.innerWidth/2, window.innerHeight/3);

      // «Второй тост»: новый уровень или достижение — по данным сервера.
      if (data.claimed) {
        var ev = data.event || {};
        var notice = "";
        if (ev.level_up) {
          notice = t("level_up", { n: ev.level });
        } else if (ev.unlocks && ev.unlocks.length) {
          var byId = {};
          ((data.gamification || {}).achievements || []).forEach(function (a) {
            byId[a.id] = a;
          });
          var first = byId[ev.unlocks[0]];
          if (first) notice = t("ach_unlocked", { name: first.title });
        }
        if (notice) setTimeout(function () { toast(notice); haptic("success"); }, 2100);
      }
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

  // ---------------------------------------------------------------- поддержка автора
  function copyText(text) {
    function done() { toast(t("support_copied")); haptic("success"); }
    function fallback() {
      try {
        var area = document.createElement("textarea");
        area.value = text;
        area.style.position = "fixed";
        area.style.opacity = "0";
        document.body.appendChild(area);
        area.focus();
        area.select();
        document.execCommand("copy");
        area.remove();
        done();
      } catch (e) { toast(text); }
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(fallback);
    } else fallback();
  }

  // ---------------------------------------------------------------- события
  function onEnter(event) {
    if (event.key !== "Enter") return;
    var id = event.target && event.target.id;
    if (id === "todo-input") { event.preventDefault(); toolsAction({ action: "todo.add", text: val("todo-input") }, t("added")); }
    else if (id === "card-a") { event.preventDefault(); toolsAction({ action: "card.add", question: val("card-q"), answer: val("card-a") }, t("added")); }
    else if (id === "rem-dur") { event.preventDefault(); toolsAction({ action: "rem.add", text: val("rem-text"), duration: val("rem-dur") }, t("added")); }
    else if (id === "buy-stars") { event.preventDefault(); buyCustom(); }
    else if (id === "promo-input") { event.preventDefault(); applyPromo(); }
    else if (id === "admin-user-search") {
      event.preventDefault();
      var aid = parseInt(val("admin-user-search"), 10);
      if (aid) adminGo("user", { payload: { id: aid } });
    }
  }

  function buyCustom() {
    var stars = parseInt(val("buy-stars"), 10);
    var buy = state.buy || {};
    if (!stars || !buy.rate) { toast(t("pay_failed")); return; }
    pay({ stars: stars, requests: stars * buy.rate });
  }

  function applyPromo() {
    var code = (val("promo-input") || "").trim();
    if (!code) { toast(t("promo_empty")); return; }
    api("promo", { code: code }).then(function (res) {
      if (!res || res.status !== "ok") {
        var map = {
          used: "promo_used", expired: "promo_expired",
          exhausted: "promo_exhausted", empty: "promo_empty"
        };
        toast(t(map[res && res.status] || "promo_bad"));
        return;
      }
      if (state.me) {
        state.me.bonus_requests = res.balance;
        state.me.image_credits = res.image_balance;
      }
      var reqs = res.requests || 0;
      var imgs = res.image_credits || 0;
      if (reqs && imgs) toast(t("promo_ok_both", { r: reqs, i: imgs }));
      else if (reqs) toast(t("promo_ok", { n: reqs }));
      else toast(t("promo_ok_img", { n: imgs }));
      render();
    }).catch(function () {
      toast(t("promo_bad"));
    });
  }

  document.addEventListener("click", function (event) {
    var node = event.target.closest("[data-action]");
    if (!node) return;
    var action = node.getAttribute("data-action");
    var value = node.getAttribute("data-value");

    ripple(event, node);
    haptic(action === "tab" || action === "set-lang" || action === "set-style" ? "select" : "light");

    if (action === "tab") {
      var fromTab = state.tab;
      setDir(tabDir(fromTab, value));
      state.screen = null;
      state.tab = value;
      if (value === "friends" && state.top == null) loadTop().then(render);
      else if (value === "leaks") { render(); if (state.leaks == null) loadLeaks(); }
      else if (value === "tasks" && state.tools === null) { render(); ensureTools(); }
      else if (value === "admin") {
        if (state.adminData || state.adminUser || state.adminTicket) render();
        else adminGo(state.adminScreen || "dash");
      }
      else render();
    } else if (action === "open") {
      state.anchor = node.getAttribute("data-anchor") || null;
      openScreen(value);
    } else if (action === "back") {
      state.screen = null;
      setDir("back");
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
    } else if (action === "promo-apply") {
      applyPromo();
    } else if (action === "support-copy") {
      copyText(node.getAttribute("data-copy") || "");
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
    } else if (action === "game-react") {
      playReact();
    } else if (action === "game-wheel") {
      playWheel();
    } else if (action === "paint-pick") {
      pickPaint(node, parseInt(value, 10));
    } else if (action === "paint-cell") {
      paintCell(node, parseInt(value, 10));
    } else if (action === "guess-submit") {
      submitGuess();
    } else if (action === "set-model") {
      saveSettings({ model: value });
    } else if (action === "set-skin") {
      state._skin = value || "aurora";
      prefSet("gz_skin", state._skin);
      applyTheme();
      haptic("select");
      render();
    } else if (action === "set-mode") {
      state._themeOverride = value === "auto" ? null : value;
      prefSet("gz_mode", state._themeOverride || "auto");
      applyTheme();
      haptic("select");
      render();
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
    } else if (action === "leak-download") {
      downloadLeak(parseInt(value, 10));
    } else if (action === "leak-share") {
      shareLeak(parseInt(value, 10));
    } else if (action === "admin-leak-link") {
      var items = (state.adminData && state.adminData.items) || [];
      for (var li = 0; li < items.length; li++) {
        if (items[li].id === parseInt(value, 10)) { copyText(items[li].deep_link); break; }
      }
    } else if (action === "leaks-reload") {
      loadLeaks(true);
    } else if (action === "admin-nav") {
      state.adminEdit = null;
      state.adminLeakEdit = null;
      state.adminBcastConfirm = false;
      state.adminBcastText = "";
      if (value === "broadcast") adminGo("broadcast", { op: "broadcast.count" });
      else if (value === "aitest") adminGo("aitest", { op: "aitest" });
      else if (value === "tickets") adminGo("tickets", { payload: { offset: 0 } });
      else adminGo(value);
    } else if (action === "admin-back") {
      state.adminEdit = null;
      adminBack();
    } else if (action === "admin-refresh") {
      adminRefresh();
    } else if (action === "admin-user-open") {
      adminGo("user", { payload: { id: parseInt(value, 10) } });
    } else if (action === "admin-user-find") {
      var findId = parseInt(val("admin-user-search"), 10);
      if (!findId) { toast("Введи числовой ID"); return; }
      adminGo("user", { payload: { id: findId } });
    } else if (action === "admin-users-page") {
      adminGo("users", { payload: { offset: parseInt(value, 10) } });
    } else if (action === "admin-user-ban") {
      var banId = state.adminUser && state.adminUser.card ? state.adminUser.card.user.id : 0;
      if (banId) adminMutate("user.ban", { id: banId, banned: value === "1" }, "user");
    } else if (action === "admin-user-reset") {
      var resetId = state.adminUser && state.adminUser.card ? state.adminUser.card.user.id : 0;
      if (resetId) adminMutate("user.reset", { id: resetId }, "user");
    } else if (action === "admin-user-bonus") {
      var bonusId = state.adminUser && state.adminUser.card ? state.adminUser.card.user.id : 0;
      var bonusCount = parseInt(val("admin-bonus"), 10);
      if (!bonusId) return;
      if (!bonusCount || bonusCount < 1) { toast("Введи число запросов"); return; }
      adminMutate("user.bonus", { id: bonusId, count: bonusCount }, "user");
    } else if (action === "admin-user-images") {
      var imgId = state.adminUser && state.adminUser.card ? state.adminUser.card.user.id : 0;
      var imgCount = parseInt(val("admin-images"), 10);
      if (!imgId) return;
      if (!imgCount || imgCount < 1) { toast("Введи число генераций"); return; }
      adminMutate("user.images", { id: imgId, count: imgCount }, "user");
    } else if (action === "admin-user-role") {
      var roleId = state.adminUser && state.adminUser.card ? state.adminUser.card.user.id : 0;
      if (roleId) adminMutate("user.role", { id: roleId, role: value }, "user");
    } else if (action === "admin-user-role-clear") {
      var clearId = state.adminUser && state.adminUser.card ? state.adminUser.card.user.id : 0;
      if (clearId) adminMutate("user.role.clear", { id: clearId }, "user");
    } else if (action === "admin-model") {
      var modelId = state.adminUser && state.adminUser.card ? state.adminUser.card.user.id : 0;
      if (modelId) {
        adminMutate("user.model", {
          id: modelId, model: value, grant: node.getAttribute("data-grant") === "1"
        }, "user");
      }
    } else if (action === "admin-refund") {
      adminMutate("payment.refund", { id: parseInt(value, 10) }, "payments");
    } else if (action === "admin-promo-create") {
      adminMutate("promo.create", {
        code: val("admin-promo-code"),
        requests: parseInt(val("admin-promo-req"), 10) || 0,
        images: parseInt(val("admin-promo-img"), 10) || 0,
        max_uses: parseInt(val("admin-promo-uses"), 10) || 0,
        days: parseInt(val("admin-promo-days"), 10) || 0
      }, "promos");
    } else if (action === "admin-promo-del") {
      adminMutate("promo.delete", { code: value }, "promos");
    } else if (action === "admin-setting-edit") {
      state.adminEdit = value;
      render();
    } else if (action === "admin-setting-cancel") {
      state.adminEdit = null;
      render();
    } else if (action === "admin-setting-save") {
      var setInput = document.getElementById("admin-set-" + value);
      adminApi("setting.save", {
        key: value, value: setInput ? setInput.value : ""
      }).then(function (data) {
        state.adminEdit = null;
        adminApply("settings", data);
      }).catch(function (err) { toast(err.message || t("error_text")); });
    } else if (action === "admin-provider") {
      adminApi("settings.provider", { provider: value }).then(function (data) {
        adminApply("settings", data);
        toast((data && data.notice) || "Провайдер переключён");
      }).catch(function (err) { toast(err.message || t("error_text")); });
    } else if (action === "admin-setting-reset") {
      adminMutate("settings.reset", {}, "settings");
    } else if (action === "admin-gate") {
      adminMutate("settings.gate", {}, "settings");
    } else if (action === "admin-bcast-send") {
      state.adminBcastText = val("admin-bcast-text");
      if (!state.adminBcastConfirm) {
        if (!state.adminBcastText || state.adminBcastText.length < 2) {
          toast("Текст слишком короткий");
          return;
        }
        state.adminBcastConfirm = true;
        render();
        return;
      }
      state.adminBcastConfirm = false;
      var bcastText = state.adminBcastText;
      if (!bcastText || bcastText.length < 2) { toast("Текст слишком короткий"); return; }
      state.adminBcastText = "";
      adminMutate("broadcast", { text: bcastText }, "broadcast");
    } else if (action === "admin-role-grant") {
      var grantId = parseInt(val("admin-role-id"), 10);
      if (!grantId) { toast("Введи Telegram ID"); return; }
      adminApi("user.role", { id: grantId, role: value }).then(function (data) {
        if (data.notice) toast(data.notice);
        adminGo("roles");
      }).catch(function (err) { toast(err.message || t("error_text")); });
    } else if (action === "admin-role-clear") {
      adminApi("user.role.clear", { id: parseInt(value, 10) }).then(function (data) {
        if (data.notice) toast(data.notice);
        adminGo("roles");
      }).catch(function (err) { toast(err.message || t("error_text")); });
    } else if (action === "admin-tickets-page") {
      adminGo("tickets", { payload: { offset: parseInt(value, 10) } });
    } else if (action === "admin-ticket-open") {
      adminGo("ticket", { payload: { id: parseInt(value, 10) } });
    } else if (action === "admin-ticket-send") {
      var ticketId = state.adminTicket && state.adminTicket.ticket
        ? state.adminTicket.ticket.id : 0;
      var replyText = val("admin-ticket-reply");
      if (!ticketId) return;
      if (!replyText) { toast("Введи текст ответа"); return; }
      adminMutate("ticket.reply", { id: ticketId, text: replyText }, "ticket");
    } else if (action === "admin-ticket-close") {
      var closeTicketId = state.adminTicket && state.adminTicket.ticket
        ? state.adminTicket.ticket.id : 0;
      if (closeTicketId) adminMutate("ticket.close", { id: closeTicketId }, "ticket");
    } else if (action === "admin-channel-add") {
      adminMutate("channel.add", { channel: val("admin-channel-input") }, "channels");
    } else if (action === "admin-channel-del") {
      adminMutate("channel.remove", { index: parseInt(value, 10) }, "channels");
    } else if (action === "admin-channel-pick") {
      state.adminChannel = parseInt(value, 10);
      render();
    } else if (action === "admin-channel-publish") {
      adminMutate("channel.publish", {
        index: state.adminChannel == null ? 0 : state.adminChannel,
        text: val("admin-channel-text")
      }, "channels");
    } else if (action === "admin-giveaway-cancel") {
      adminMutate("giveaway.cancel", { id: parseInt(value, 10) }, "giveaways");
    } else if (action === "admin-leak-upload") {
      adminUploadLeak();
    } else if (action === "admin-leak-edit") {
      state.adminLeakEdit = parseInt(value, 10);
      render();
    } else if (action === "admin-leak-edit-cancel") {
      state.adminLeakEdit = null;
      render();
    } else if (action === "admin-leak-save") {
      var leakId = parseInt(value, 10);
      var leakInput = document.getElementById("admin-leak-comment-" + leakId);
      adminMutate("leak.update", {
        id: leakId, comment: leakInput ? leakInput.value : ""
      }, "leaks").then(function () { state.adminLeakEdit = null; render(); });
    } else if (action === "admin-leak-del") {
      adminMutate("leak.delete", { id: parseInt(value, 10) }, "leaks");
    } else if (action === "admin-giftall") {
      var giftCount = parseInt(val("admin-gift-count"), 10);
      if (!giftCount || giftCount < 1) { toast("Введи число запросов"); return; }
      adminApi("giftall", { count: giftCount }).then(function (data) {
        toast(data.notice || "Готово");
        adminGo("dash");
      }).catch(function (err) { toast(err.message || t("error_text")); });
    }
  });

  document.addEventListener("keydown", onEnter);

  // ---------------------------------------------------------------- эффекты
  (function initFx() {
    var raf = 0, last = null;
    document.addEventListener("pointermove", function (event) {
      var target = event.target;
      var card = target && target.closest ? target.closest(".card") : null;
      if (!card) return;
      last = { card: card, x: event.clientX, y: event.clientY };
      if (raf) return;
      raf = requestAnimationFrame(function () {
        raf = 0;
        if (!last) return;
        var rect = last.card.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        last.card.style.setProperty("--mx", ((last.x - rect.left) / rect.width * 100).toFixed(1) + "%");
        last.card.style.setProperty("--my", ((last.y - rect.top) / rect.height * 100).toFixed(1) + "%");
      });
    }, { passive: true });

    var ticking = false;
    window.addEventListener("scroll", function () {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () {
        ticking = false;
        document.body.classList.toggle("scrolled", window.scrollY > 6);
      });
    }, { passive: true });

    window.addEventListener("resize", function () { positionPill(); });
    window.addEventListener("load", function () { positionPill(); });
    setTimeout(positionPill, 120);
  })();

  var langBtn = document.getElementById("lang-btn");
  if (langBtn) {
    langBtn.addEventListener("click", function () {
      state.screen = "settings";
      state.tab = "profile";
      setDir("fwd");
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
