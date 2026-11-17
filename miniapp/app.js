/* Mini App кабинет: данные — из /app/api/*, авторизация — initData Telegram. */
(function () {
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
  if (tg) {
    try { tg.ready(); } catch (e) {}
    try { tg.expand(); } catch (e) {}
    try { if (tg.setHeaderColor) tg.setHeaderColor("secondary_bg_color"); } catch (e) {}
    try { if (tg.setBackgroundColor) tg.setBackgroundColor("bg_color"); } catch (e) {}
  }

  var STYLE_ICON = { auto: "🌐", expert: "🚀", study: "🎓", code: "💻" };
  var STYLE_ORDER = ["auto", "expert", "study", "code"];
  var LANG_FLAG = { ru: "🇷🇺", uk: "🇺🇦", be: "🇧🇾", en: "🇬🇧" };
  var LANG_NAME = { ru: "Русский", uk: "Українська", be: "Беларуская", en: "English" };

  var I18N = {
    ru: {
      home: "Кабинет", stats: "Статистика", friends: "Друзья", settings: "Настройки",
      hello: "Привет, {name}!",
      left: "Осталось запросов", unlimited: "Без ограничений",
      today_used: "Сегодня использовано: {n}",
      bonus_title: "🎁 Бонус дня",
      bonus_claim: "Забрать бонус",
      bonus_claimed: "Бонус получен: +{amount}",
      bonus_already: "Бонус дня уже получен",
      bonus_streak: "Серия: {n} дн. подряд",
      bonus_hint: "Заходи каждый день — бонус растёт до {max}.",
      model: "Модель ИИ", style: "Стиль ответов",
      stat_today: "Запросов сегодня", stat_total: "Всего запросов",
      stat_left: "Осталось", stat_bonus: "Бонусных запросов",
      stat_streak: "Серия бонусов", stat_invites: "Приглашено друзей",
      stat_images: "Бонусных картинок", days: "дн.",
      friends_title: "👥 Приглашай друзей",
      friends_hint: "За каждого нового друга: тебе +{reward}, другу +{friend} запросов.",
      friends_link: "Твоя ссылка", copy: "Скопировать", copied: "Ссылка скопирована",
      share: "Поделиться", friends_count: "Уже приглашено: {n}",
      friends_top: "Топ приглашающих", friends_empty: "Пока никого — стань первым!",
      settings_title: "⚙️ Настройки", language: "Язык", style_title: "Стиль ответов",
      model_hint: "Модель меняется в боте командой /model.",
      saved: "Сохранено",
      sub_title: "🔒 Нужна подписка",
      sub_text: "Чтобы открыть кабинет, подпишись на канал.",
      sub_button: "📢 Подписаться", sub_check: "Я подписался",
      error_title: "Не получилось загрузить",
      error_text: "Открой кабинет заново из Telegram.",
      retry: "Повторить",
      loading: "Загрузка…",
      styles: {
        auto: ["🌐 Универсальный", "сильный эксперт во всех темах"],
        expert: ["🚀 Максимум", "максимальная глубина и варианты"],
        study: ["🎓 Учебный", "репетитор объясняет по шагам"],
        code: ["💻 Кодерский", "senior-разработчик: полный код"]
      },
      share_text: "Заходи в {bot} — ИИ-помощник по учёбе. Разбирает задачи по шагам."
    },
    uk: {
      home: "Кабінет", stats: "Статистика", friends: "Друзі", settings: "Налаштування",
      hello: "Привіт, {name}!",
      left: "Залишилось запитів", unlimited: "Без обмежень",
      today_used: "Сьогодні використано: {n}",
      bonus_title: "🎁 Бонус дня",
      bonus_claim: "Забрати бонус",
      bonus_claimed: "Бонус отримано: +{amount}",
      bonus_already: "Бонус дня вже отримано",
      bonus_streak: "Серія: {n} дн. підряд",
      bonus_hint: "Заходь щодня — бонус зростає до {max}.",
      model: "Модель ШІ", style: "Стиль відповідей",
      stat_today: "Запитів сьогодні", stat_total: "Усього запитів",
      stat_left: "Залишилось", stat_bonus: "Бонусних запитів",
      stat_streak: "Серія бонусів", stat_invites: "Запрошено друзів",
      stat_images: "Бонусних картинок", days: "дн.",
      friends_title: "👥 Запрошуй друзів",
      friends_hint: "За кожного нового друга: тобі +{reward}, другу +{friend} запитів.",
      friends_link: "Твоє посилання", copy: "Скопіювати", copied: "Посилання скопійовано",
      share: "Поділитися", friends_count: "Уже запрошено: {n}",
      friends_top: "Топ запрошуючих", friends_empty: "Поки нікого — стань першим!",
      settings_title: "⚙️ Налаштування", language: "Мова", style_title: "Стиль відповідей",
      model_hint: "Модель змінюється в боті командою /model.",
      saved: "Збережено",
      sub_title: "🔒 Потрібна підписка",
      sub_text: "Щоб відкрити кабінет, підпишись на канал.",
      sub_button: "📢 Підписатися", sub_check: "Я підписався",
      error_title: "Не вдалося завантажити",
      error_text: "Відкрий кабінет заново з Telegram.",
      retry: "Повторити",
      loading: "Завантаження…",
      styles: {
        auto: ["🌐 Універсальний", "сильний експерт у всіх темах"],
        expert: ["🚀 Максимум", "максимальна глибина й варіанти"],
        study: ["🎓 Навчальний", "репетитор пояснює покроково"],
        code: ["💻 Кодерський", "senior-розробник: повний код"]
      },
      share_text: "Заходь у {bot} — ШІ-помічник з навчання. Розбирає задачі покроково."
    },
    be: {
      home: "Кабінет", stats: "Статыстыка", friends: "Сябры", settings: "Налады",
      hello: "Прывітанне, {name}!",
      left: "Засталося запытаў", unlimited: "Без абмежаванняў",
      today_used: "Сёння выкарыстана: {n}",
      bonus_title: "🎁 Бонус дня",
      bonus_claim: "Забраць бонус",
      bonus_claimed: "Бонус атрыманы: +{amount}",
      bonus_already: "Бонус дня ўжо атрыманы",
      bonus_streak: "Серыя: {n} дз. запар",
      bonus_hint: "Заходзь штодня — бонус расце да {max}.",
      model: "Мадэль ШІ", style: "Стыль адказаў",
      stat_today: "Запытаў сёння", stat_total: "Усяго запытаў",
      stat_left: "Засталося", stat_bonus: "Бонусных запытаў",
      stat_streak: "Серыя бонусаў", stat_invites: "Запрошана сяброў",
      stat_images: "Бонусных малюнкаў", days: "дз.",
      friends_title: "👥 Запрашай сяброў",
      friends_hint: "За кожнага новага сябра: табе +{reward}, сябру +{friend} запытаў.",
      friends_link: "Тваё спасылка", copy: "Скапіраваць", copied: "Спасылка скапіравана",
      share: "Падзяліцца", friends_count: "Ужо запрошана: {n}",
      friends_top: "Топ запрашальнікаў", friends_empty: "Пакуль нікога — стань першым!",
      settings_title: "⚙️ Налады", language: "Мова", style_title: "Стыль адказаў",
      model_hint: "Мадэль змяняецца ў боце камандай /model.",
      saved: "Захавана",
      sub_title: "🔒 Патрэбна падпіска",
      sub_text: "Каб адкрыць кабінет, падпішыся на канал.",
      sub_button: "📢 Падпісацца", sub_check: "Я падпісаўся",
      error_title: "Не ўдалося загрузіць",
      error_text: "Адкрый кабінет зноў з Telegram.",
      retry: "Паўтарыць",
      loading: "Загрузка…",
      styles: {
        auto: ["🌐 Універсальны", "моцны эксперт ва ўсіх тэмах"],
        expert: ["🚀 Максімум", "максімальная глыбіня і варыянты"],
        study: ["🎓 Навучальны", "рэпетытар тлумачыць па кроках"],
        code: ["💻 Кодэрскі", "senior-распрацоўшчык: поўны код"]
      },
      share_text: "Заходзь у {bot} — ШІ-памочнік па вучобе. Разбірае задачы па кроках."
    },
    en: {
      home: "Home", stats: "Stats", friends: "Friends", settings: "Settings",
      hello: "Hi, {name}!",
      left: "Requests left", unlimited: "Unlimited",
      today_used: "Used today: {n}",
      bonus_title: "🎁 Daily bonus",
      bonus_claim: "Claim bonus",
      bonus_claimed: "Bonus claimed: +{amount}",
      bonus_already: "Today's bonus is already claimed",
      bonus_streak: "Streak: {n} day(s)",
      bonus_hint: "Come back every day — the bonus grows up to {max}.",
      model: "AI model", style: "Answer style",
      stat_today: "Requests today", stat_total: "Total requests",
      stat_left: "Left", stat_bonus: "Bonus requests",
      stat_streak: "Bonus streak", stat_invites: "Friends invited",
      stat_images: "Bonus images", days: "d",
      friends_title: "👥 Invite friends",
      friends_hint: "For each new friend: you get +{reward}, your friend gets +{friend} requests.",
      friends_link: "Your link", copy: "Copy", copied: "Link copied",
      share: "Share", friends_count: "Invited so far: {n}",
      friends_top: "Top inviters", friends_empty: "Nobody yet — be the first!",
      settings_title: "⚙️ Settings", language: "Language", style_title: "Answer style",
      model_hint: "Change the model in the bot with /model.",
      saved: "Saved",
      sub_title: "🔒 Subscription required",
      sub_text: "Subscribe to the channel to open the dashboard.",
      sub_button: "📢 Subscribe", sub_check: "I subscribed",
      error_title: "Failed to load",
      error_text: "Open the dashboard again from Telegram.",
      retry: "Retry",
      loading: "Loading…",
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
    me: null,
    top: null,
    busy: false,
    sub: null,
    fatal: null
  };

  var view = document.getElementById("view");
  var tabsEl = document.getElementById("tabs");
  var brandEl = document.getElementById("brand-name");
  var toastEl = document.getElementById("toast");
  var toastTimer = null;

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

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function toast(text) {
    toastEl.textContent = text;
    toastEl.classList.add("show");
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 1800);
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
  function tabButton(key, icon) {
    var active = state.tab === key ? " active" : "";
    return '<button class="tab' + active + '" data-action="tab" data-value="' + key +
      '" role="tab" aria-selected="' + (state.tab === key) + '">' +
      '<span class="tab-icon">' + icon + '</span><span>' + esc(t(key)) + "</span></button>";
  }

  function renderTabs() {
    tabsEl.innerHTML =
      tabButton("home", "🏠") + tabButton("stats", "📈") +
      tabButton("friends", "👥") + tabButton("settings", "⚙️");
  }

  function statCard(value, label) {
    return '<div class="stat"><div class="stat-value">' + esc(value) +
      '</div><div class="stat-label">' + esc(label) + "</div></div>";
  }

  function renderHome() {
    var me = state.me;
    var name = (me.user.first_name || me.user.username || "").trim();

    var bonus = "";
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

    view.innerHTML =
      '<div class="card hero">' +
      '<div class="muted" style="color:inherit;opacity:.9">' + esc(t("hello", { name: name })) + "</div>" +
      '<div class="value">' + (me.unlimited ? "∞" : esc(me.remaining)) + "</div>" +
      '<div class="sub">' + (me.unlimited ? esc(t("unlimited")) : esc(t("left"))) + "</div>" +
      "</div>" +
      '<h2>' + esc(t("bonus_title")) + "</h2>" +
      '<div class="card">' + bonus + "</div>" +
      '<h2>' + esc(t("model")) + " · " + esc(t("style")) + "</h2>" +
      '<div class="card"><div class="row"><div><div class="row-title">' +
      esc(me.model.title) + '</div><div class="row-sub">' + esc(t("model")) +
      '</div></div></div><div class="row"><div><div class="row-title">' +
      esc(STYLE_ICON[me.style] || "🌐") + " " + esc(dict().styles[me.style] ? dict().styles[me.style][0] : me.style) +
      '</div></div></div></div>';
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

    view.innerHTML =
      "<h1>" + esc(t("settings_title")) + "</h1>" +
      "<h2>" + esc(t("language")) + "</h2>" +
      '<div class="card"><div class="chips">' + langs + "</div></div>" +
      "<h2>" + esc(t("style_title")) + "</h2>" +
      '<div class="card">' + styles + "</div>" +
      "<h2>" + esc(t("model")) + "</h2>" +
      '<div class="card"><div class="row"><div><div class="row-title">' +
      esc(me.model.title) + '</div><div class="row-sub">' + esc(t("model_hint")) +
      "</div></div></div></div>";
  }

  function renderSubscription() {
    var url = (state.sub && state.sub.url) || "";
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
    if (state.sub) { renderSubscription(); renderTabs(); return; }
    if (!state.me) {
      view.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
      renderTabs();
      return;
    }
    if (state.tab === "stats") renderStats();
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
      state.sub = null;
      if (state.tab === "friends" && state.top == null) return loadTop();
      return null;
    }).catch(function (err) {
      if (err.status === 403 && err.data && err.data.error === "subscription") {
        state.sub = err.data;
        state.me = null;
      } else if (err.status === 401) {
        state.fatal = t("error_text");
      } else {
        state.fatal = t("error_text");
      }
    }).then(render);
  }

  function loadTop() {
    return api("top").then(function (data) { state.top = data.top || []; })
      .catch(function () { state.top = []; });
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
    }).catch(function (err) {
      toast(err.data && err.data.error === "subscription" ? t("sub_text") : t("error_text"));
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
    var url = state.sub && state.sub.url;
    if (!url) { load(); return; }
    if (tg && tg.openTelegramLink) tg.openTelegramLink(url);
    else window.open(url, "_blank");
  }

  // ---------------------------------------------------------------- события
  document.addEventListener("click", function (event) {
    var node = event.target.closest("[data-action]");
    if (!node) return;
    var action = node.getAttribute("data-action");
    var value = node.getAttribute("data-value");

    if (action === "tab") {
      state.tab = value;
      if (value === "friends" && state.top == null) loadTop().then(render);
      else render();
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
      load();
    }
  });

  var langBtn = document.getElementById("lang-btn");
  if (langBtn) {
    langBtn.addEventListener("click", function () {
      state.tab = "settings";
      render();
    });
  }

  // ---------------------------------------------------------------- старт
  state.lang = detectLang();
  if (tg && tg.onEvent) {
    try { tg.onEvent("themeChanged", function () {}); } catch (e) {}
  }
  render();
  if (!tg || !tg.initData) {
    state.fatal = t("error_text");
    render();
  } else {
    load();
  }
})();
