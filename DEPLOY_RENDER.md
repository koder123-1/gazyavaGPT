# gazyavaGPT в облаке: Render + Supabase

Бот работает 24/7, компьютер можно выключать. Локальный `.env` больше не нужен:
секреты лежат в Render, данные — в Supabase Postgres.

## Что уже развёрнуто

| Что | Где |
|---|---|
| Код | https://github.com/koder123-1/gazyavaGPT (публичный, без секретов) |
| Бот | https://gazyava-gpt.onrender.com (`/health` → `{"status":"ok","db":"up"}`) |
| База | Supabase, проект `gazyava-gpt`, регион Stockholm (`eu-north-1`) |
| Webhook | `https://gazyava-gpt.onrender.com/webhook` |
| Keep-alive | GitHub Actions `.github/workflows/keepalive.yml`, ping каждые 5 минут |

Render free: 512 МБ RAM, засыпает после 15 минут без запросов. Keep-alive не даёт
ему заснуть; первый запрос после ручного рестарта всё равно может идти ~40–60 секунд.

## Почему Supabase, а не Neon

Neon отдаёт «Access Blocked in Your Region» для этого IP. Supabase открывается,
даёт бесплатный Postgres 500 МБ и пулер для IPv4. Проект создан в Стокгольме.

Подключение идёт через **Session pooler**:

```
postgresql://postgres.<ref>:<password>@aws-1-eu-north-1.pooler.supabase.com:5432/postgres?sslmode=require
```

`store.py` умеет Supabase-пулер: убирает `sslmode` из DSN, включает SSL и отключает
проверку CA (у пулера самоподписанный сертификат — как `sslmode=require` в libpq).

## Переменные Render

Заданы в сервисе (Environment), в git не попадают:

- `BOT_TOKEN`, `REFORMBOSS_API_KEY`, `COARENA_API_KEY`
- `DATABASE_URL` — строка Supabase Session pooler
- `OWNER_ID`, `ADMIN_IDS`
- `WEBHOOK_SECRET` — сгенерирован Render
- `AI_PROVIDER=reformboss`, `AI_MODEL=deepseek-v4.1-flash-1017`
- `AI_MODELS` — каталог из `models.py`
- `IMAGE_PROVIDER=reformboss`, `IMAGE_MODEL=grok-imagine-image-lite`
- лимиты, язык
- `STAR_PACKAGES=50:3,150:8,300:14`, `STAR_RATE=10`
- `REQUIRED_CHANNEL=gazyavaGPT`, `REQUIRED_CHANNEL_URL=https://t.me/gazyavaGPT`

Env в Render можно менять из бота: `/admin → ⚙️ Настройки` (канал, тарифы, курс).
Через API `PUT /v1/services/<id>/env-vars` отправляйте **полный** список переменных —
этот запрос заменяет все значения сразу.

## Обновление кода

```powershell
cd D:\tg-bot-render
git add -A
git commit -m "что изменилось"
git push
```

Дальше вручную запустить деплой (для публичного репозитория авто-деплой по пушу
может не срабатывать):

```powershell
# ключ Render API лежит в файле, в чат его выводить нельзя
$key = (Get-Content "C:\Users\asus\AppData\Local\Temp\opencode-browser-5TMQsY\0\render_api_key.txt" -Raw).Trim()
$h = @{ Authorization = "Bearer $key"; Accept = "application/json" }
Invoke-RestMethod -Method Post -Headers $h -ContentType "application/json" `
  -Uri "https://api.render.com/v1/services/srv-dbstd9m7bikc73ceib5g/deploys" `
  -Body '{"clearCache":"do_not_clear"}'
```

Или в дашборде Render: сервис `gazyava-gpt` → **Manual Deploy → Deploy latest commit**.

## Проверка после деплоя

0. **Подписка на канал.** Бот требует подписку на канал, заданный в
   `/admin → ⚙️ Настройки → ✏️ Канал подписки` (по умолчанию https://t.me/gazyavaGPT).
   Канал и ссылку можно менять там без рестарта; `off` отключает гейт.
   Чтобы Telegram разрешил проверку, добавь **@gazyavagptbot** в администраторы
   канала: канал → «Управление» → «Администраторы» → «Добавить администратора».
   Без этого `getChatMember` отвечает `member list is inaccessible`, и бот
   (чтобы не запереть всех) пропускает пользователей, а владельцу пишет
   предупреждение. Проверка кешируется на 45 секунд; после смены канала в админке
   кеш сбрасывается сам.
1. `https://gazyava-gpt.onrender.com/health` → `{"status":"ok","db":"up"}`.
2. В Telegram: `/start` — короткое приветствие и постоянное меню; дальше пользуйся кнопками или командами. Проверь `/buy`, `/model` и `/admin → ⚙️ Настройки`.
3. Если бот молчит — `getWebhookInfo` и логи Render:
   - `401` — неверный `BOT_TOKEN`;
   - `409 Conflict` — где-то остался локальный polling, останови его;
   - `db: down` — проверь `DATABASE_URL`.

## Локальный запуск (для отладки)

Локальный polling и облачный webhook одновременно работать не могут: Telegram
отдаёт апдейты только одному способу. Перед локальным запуском удали webhook:

```powershell
.\.venv\Scripts\python.exe -u bot.py
```

Без `RENDER_EXTERNAL_URL` бот сам вызовет `delete_webhook` и перейдёт в polling.
После отладки снова задеплой облако, чтобы вернуть webhook.