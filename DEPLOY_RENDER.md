# Деплой gazyavaGPT на Render + Neon (бесплатно)

Цель: бот работает 24/7, даже когда компьютер выключен. Локальный `.env` и база в памяти
больше не нужны: на сервере данные живут в Neon, а секреты — в Render.

## 0. Что уже готово в репозитории

- `render.yaml` — blueprint: web-сервис free, health-check `/health`, все настройки
  провайдеров (ReformBoss + Coarena fallback + картинки).
- `.env` в git не попадает (`.gitignore`).
- `assets/DejaVuSans.ttf` лежит в репозитории — PDF с кириллицей соберётся и на Render.
- Схему БД бот создаёт сам при первом запуске (`users`, `usage`, `messages`, `payments`,
  `roles`, `tickets`, `ticket_messages`, `model_access`).

## 1. GitHub

Репозиторий создаётся и пушится с этой машины. Нужен только вход в GitHub:

```powershell
gh auth login --hostname github.com --git-protocol https --web
```

Уже открыто отдельное окно PowerShell — следуй подсказкам: Enter → браузер → код.

## 2. Neon (база данных)

1. Открой https://neon.tech → **Sign up** → **Continue with GitHub**.
2. Создай проект:
   - Name: `gazyava-gpt`
   - Region: **AWS eu-central-1 (Frankfurt)** — ближе к Render Frankfurt.
3. На странице проекта нажми **Connect** и скопируй строку подключения.
   Бери **Pooled connection** (в хосте есть `-pooler`), она выглядит так:

   ```
   postgresql://USER:PASSWORD@ep-xxx-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```

   Пароль уже внутри строки — ничего отдельно вводить не надо.
4. Сохрани строку: она пойдёт в Render как `DATABASE_URL`.
5. Ничего в SQL-редакторе выполнять не нужно, таблицы создаст бот.

## 3. Render

1. Открой https://render.com → **Get Started** → **GitHub** → разреши доступ.
2. **New +** → **Blueprint**.
3. Выбери репозиторий `gazyavaGPT` (или как назовём) → **Connect**.
   Если Render попросит доступ к репозиторию — установи Render GitHub App
   (можно только на этот репозиторий).
4. Render прочитает `render.yaml` и спросит значения для секретов:

| Переменная | Откуда взять |
|---|---|
| `BOT_TOKEN` | `D:\tg-bot-render\.env` → `BOT_TOKEN` |
| `REFORMBOSS_API_KEY` | `.env` → `REFORMBOSS_API_KEY` |
| `COARENA_API_KEY` | `.env` → `COARENA_API_KEY` (резерв, если лимит ReformBoss) |
| `DATABASE_URL` | строка из Neon (шаг 2) |
| `OWNER_ID` | `.env` → `OWNER_ID` (твой Telegram ID) |
| `ADMIN_IDS` | `.env` → `ADMIN_IDS` |

5. **Apply** → Render соберёт и запустит сервис (3–7 минут).
6. В логах должно быть:

   ```
   Webhook установлен: https://<service>.onrender.com/webhook
   ```

7. Проверь `https://<service>.onrender.com/health` — должно быть
   `{"status":"ok","db":"up"}`.

## 4. После деплоя

- **Останови локального бота**: два процесса на одном токене конфликтуют
  (webhook и polling). На сервере бот сам ставит webhook.
- Напиши боту `/start` — должен ответить уже из облака.
- Проверь `/model`, `/files`, оплату Stars, `/admin`.

## 5. Чтобы Render free не засыпал

Free-инстанс засыпает после 15 минут без запросов. Первый запрос после сна
обрабатывается ~40–60 секунд. Чтобы этого не было:

1. Зарегистрируйся на https://cron-job.org (бесплатно).
2. Создай cron: URL `https://<service>.onrender.com/health`, интервал **каждые 5 минут**.
3. 24/7 = ~730 часов в месяц, лимит Render free — 750 часов, так что хватает.

## Если что-то пошло не так

- **`db: down` в /health** — проверь `DATABASE_URL` (должен быть pooled и с `sslmode=require`).
- **401/403 от ReformBoss** — ключ или дневной лимит; статус: `/key` в `@iishkogatewaybot`.
- **Бот молчит, в логах 409 Conflict** — где-то ещё работает polling. Останови локального бота.
- **Не собирается PDF** — проверь, что `assets/DejaVuSans.ttf` попал в репозиторий.
- **Долгий первый ответ** — сервис проснулся; настрой cron из шага 5.