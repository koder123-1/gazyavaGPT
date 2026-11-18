"""Точка входа: webhook-сервер для Render (или polling локально)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from html import escape
from typing import Any

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    MenuButtonWebApp,
    TelegramObject,
    WebAppInfo,
)
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from ai import AIClient
from admin import router as admin_router
from config import Settings, load_settings
from groupadmin import MutedMiddleware
from groupadmin import router as group_router
from handlers import router as user_router
from images import ImageClient
from moderation import FloodMiddleware, PrivateOnlyMiddleware, SpamMiddleware
from moderation import router as moderation_router
from payments import router as payments_router
from runtime import load_runtime
from store import Store, create_store
from subscription import SubscriptionMiddleware, probe_channel
from subscription import router as subscription_router
from tickets import router as tickets_router
from toolbox import router as toolbox_router
import autopost
import channelkit
import giveaways
import keepalive
import miniapp
import reminders

WEBHOOK_PATH = "/webhook"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
log = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="start", description="Запустить ассистента"),
    BotCommand(command="app", description="Личный кабинет (Mini App)"),
    BotCommand(command="ai", description="Задать вопрос ИИ"),
    BotCommand(command="reset", description="Очистить контекст диалога"),
    BotCommand(command="check", description="Проверить моё решение"),
    BotCommand(command="imagine", description="Нарисовать картинку"),
    BotCommand(command="files", description="Чтение и создание файлов"),
    BotCommand(command="pin", description="Закрепить сообщение в ответе"),
    BotCommand(command="unpin", description="Открепить сообщение"),
    BotCommand(command="lang", description="Сменить язык"),
    BotCommand(command="model", description="Выбрать модель ИИ"),
    BotCommand(command="style", description="Стиль ответов: учёба или код"),
    BotCommand(command="buy", description="Пополнить запросы за звёзды"),
    BotCommand(command="terms", description="Условия покупки"),
    BotCommand(command="support", description="Написать в поддержку"),
    BotCommand(command="tickets", description="Мои обращения и тикеты"),
    BotCommand(command="paysupport", description="Поддержка по оплате"),
    BotCommand(command="bonus", description="Бонус дня за ежедневный вход"),
    BotCommand(command="invite", description="Пригласить друга и получить запросы"),
    BotCommand(command="me", description="Мой ID и остаток лимита"),
    BotCommand(command="tools", description="Все быстрые команды"),
    BotCommand(command="calc", description="Калькулятор: /calc 2+2*2"),
    BotCommand(command="random", description="Случайное число или выбор"),
    BotCommand(command="coin", description="Орёл или решка"),
    BotCommand(command="dice", description="Кубик: /dice 20"),
    BotCommand(command="password", description="Сгенерировать пароль"),
    BotCommand(command="uuid", description="Сгенерировать UUID"),
    BotCommand(command="hash", description="SHA-256 от текста"),
    BotCommand(command="base64", description="Кодировать/раскодировать Base64"),
    BotCommand(command="count", description="Символы, слова и строки в тексте"),
    BotCommand(command="id", description="ID пользователя и чата"),
    BotCommand(command="ping", description="Проверить задержку"),
    BotCommand(command="time", description="Время UTC и МСК"),
    BotCommand(command="todo", description="Список дел"),
    BotCommand(command="stats", description="Моя статистика"),
    BotCommand(command="remind", description="Напоминание: /remind 10м текст"),
    BotCommand(command="reminders", description="Мои напоминания"),
    BotCommand(command="unremind", description="Отменить напоминание"),
    BotCommand(command="timer", description="Таймер: /timer 10м"),
    BotCommand(command="poll", description="Опрос: /poll Вопрос | A | B"),
    BotCommand(command="card", description="Карточки: /card add Вопрос | Ответ"),
    BotCommand(command="cards", description="Все мои карточки"),
    BotCommand(command="translate", description="Перевести текст"),
    BotCommand(command="summary", description="Краткий пересказ текста"),
    BotCommand(command="explain", description="Объяснить простыми словами"),
    BotCommand(command="quiz", description="Тест из 5 вопросов по теме"),
    BotCommand(command="rules", description="Правила чата"),
    BotCommand(command="help", description="Справка"),
]

# В группах — другой набор: без покупок и личного кабинета, зато с модерацией.
GROUP_COMMANDS = [
    BotCommand(command="ai", description="Спросить ИИ"),
    BotCommand(command="imagine", description="Нарисовать картинку"),
    BotCommand(command="reset", description="Очистить контекст"),
    BotCommand(command="tools", description="Все быстрые команды"),
    BotCommand(command="calc", description="Калькулятор: /calc 2+2*2"),
    BotCommand(command="random", description="Случайное число или выбор"),
    BotCommand(command="coin", description="Орёл или решка"),
    BotCommand(command="dice", description="Кубик: /dice 20"),
    BotCommand(command="count", description="Символы, слова и строки"),
    BotCommand(command="id", description="ID чата и автора"),
    BotCommand(command="ping", description="Задержка ответа"),
    BotCommand(command="time", description="Время UTC и МСК"),
    BotCommand(command="translate", description="Перевести текст"),
    BotCommand(command="summary", description="Краткий пересказ"),
    BotCommand(command="explain", description="Объяснить просто"),
    BotCommand(command="quiz", description="Тест из 5 вопросов"),
    BotCommand(command="remind", description="Напоминание: /remind 10м текст"),
    BotCommand(command="reminders", description="Мои напоминания"),
    BotCommand(command="unremind", description="Отменить напоминание"),
    BotCommand(command="timer", description="Таймер: /timer 10м"),
    BotCommand(command="poll", description="Опрос: /poll Вопрос | A | B"),
    BotCommand(command="card", description="Карточки: /card add Вопрос | Ответ"),
    BotCommand(command="cards", description="Все карточки"),
    BotCommand(command="rules", description="Правила чата"),
    BotCommand(command="help", description="Справка"),
    BotCommand(command="group", description="Управление чатом"),
    BotCommand(command="giveaway", description="Розыгрыш в этом чате"),
    BotCommand(command="pin", description="Закрепить сообщение в ответе"),
    BotCommand(command="unpin", description="Открепить сообщение"),
    BotCommand(command="warn", description="Предупреждение"),
    BotCommand(command="mute", description="Мут: /mute 1час причина"),
    BotCommand(command="unmute", description="Снять мут"),
    BotCommand(command="kick", description="Исключить участника"),
    BotCommand(command="ban", description="Заблокировать"),
    BotCommand(command="unban", description="Разблокировать"),
    BotCommand(command="promote", description="Дать админку"),
    BotCommand(command="demote", description="Снять админку"),
    BotCommand(command="del", description="Удалить сообщение"),
    BotCommand(command="purge", description="Удалить последние сообщения"),
    BotCommand(command="info", description="Информация об участнике"),
]


# --------------------------------------------------------------------------- lifecycle
async def on_startup(
    bot: Bot,
    dispatcher: Dispatcher,
    settings: Settings,
    store: Store,
    ai: AIClient,
    images: ImageClient,
) -> None:
    await store.start()
    await ai.start()
    await images.start()
    giveaways.start_loop(bot, store)
    autopost.start_loop(bot, store, settings)
    channelkit.start_loop(bot, store)
    reminders.start_loop(bot, store, settings)
    keepalive.start_loop(settings)
    await bot.set_my_commands(COMMANDS)
    with contextlib.suppress(TelegramAPIError):
        await bot.set_my_commands(GROUP_COMMANDS, scope=BotCommandScopeAllGroupChats())
    with contextlib.suppress(TelegramAPIError):
        # Админам групп и каналов — тот же набор: в канале пишут только они.
        await bot.set_my_commands(
            GROUP_COMMANDS, scope=BotCommandScopeAllChatAdministrators()
        )

    # Кнопка Mini App рядом с полем ввода. Без публичного адреса (polling)
    # открывать нечего, поэтому молча пропускаем.
    app_url = miniapp.webapp_url(settings)
    if app_url:
        with contextlib.suppress(TelegramAPIError):
            me = await bot.me()
            miniapp.set_bot_username(me.username)
        with contextlib.suppress(TelegramAPIError):
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🚀 Кабинет", web_app=WebAppInfo(url=app_url + "?v=7")
                )
            )

    if not ai.configured:
        log.error("AI_API_KEY не задан — бот ответит пользователям, что ИИ не настроен")
    if not settings.admin_ids and not settings.owner_id:
        log.warning(
            "ADMIN_IDS и OWNER_ID не заданы — админки и ролей не будет ни у кого"
        )
    if not settings.owner_id:
        log.warning(
            "OWNER_ID не задан — управлять ролями некому. Добавь свой Telegram ID."
        )

    if settings.use_webhook:
        url = f"{settings.base_url}{WEBHOOK_PATH}"
        await bot.set_webhook(
            url=url,
            secret_token=settings.webhook_secret,
            # НЕ drop_pending_updates: Render free засыпает через 15 минут без
            # трафика, и всё, что написали боту за это время, должно доехать
            # после пробуждения, а не быть стёртым при старте.
            drop_pending_updates=False,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
        log.info("Webhook установлен: %s", url)
    else:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("RENDER_EXTERNAL_URL не задан -> режим polling")

    runtime = await load_runtime(store, settings)
    if not await probe_channel(bot, runtime.required_channel) and settings.owner_id:
        with contextlib.suppress(TelegramAPIError):
            await bot.send_message(
                settings.owner_id,
                "⚠️ <b>Подписка на канал не проверяется</b>\n\n"
                f"Бот не может посмотреть участников {escape(runtime.required_channel or 'канала')}. "
                "Добавь бота в администраторы канала — и гейт заработает. "
                "Сменить канал можно в /admin → ⚙️ Настройки → ✏️ Канал подписки.",
            )


async def on_shutdown(bot: Bot, store: Store, ai: AIClient, images: ImageClient) -> None:
    await giveaways.stop_loop()
    await autopost.stop_loop()
    await channelkit.stop_loop()
    await reminders.stop_loop()
    await keepalive.stop_loop()
    await ai.close()
    await images.close()
    await store.close()
    await bot.session.close()
    log.info("Бот остановлен")


class CallbackAnswerGuard(BaseMiddleware):
    """Отвечает на нажатие кнопки, даже если обработчик упал.

    Сообщение с кнопками мог удалить сам пользователь или админ чата — тогда
    `call.message` недоступен (`InaccessibleMessage`/None), и любой
    `edit_text` бросает AttributeError. Без ответа у клиента навсегда
    остаются «часики», а обновление теряется.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        try:
            return await handler(event, data)
        except TelegramAPIError:
            raise
        except Exception:  # noqa: BLE001 — кнопка не должна «зависать»
            log.exception("Ошибка обработки кнопки %s", getattr(event, "data", ""))
            with contextlib.suppress(TelegramAPIError):
                await event.answer("⚠️ Не получилось. Попробуй ещё раз.")
            return None


# --------------------------------------------------------------------------- приложение
def create_dispatcher(
    settings: Settings, store: Store, ai: AIClient, images: ImageClient | None = None
) -> Dispatcher:
    # FSM: админ-панель ждёт ввода текста (рассылка, настройки).
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["settings"] = settings
    dispatcher["store"] = store
    dispatcher["ai"] = ai
    dispatcher["images"] = images or ImageClient(settings)
    # Гейт подписки — до всех: без подписки в личку не пускает.
    dispatcher.include_router(subscription_router)
    # Админ-роутер первым: его фильтр по роли отсекает остальных.
    dispatcher.include_router(admin_router)
    dispatcher.include_router(channelkit.router)
    dispatcher.include_router(tickets_router)
    dispatcher.include_router(giveaways.router)
    dispatcher.include_router(autopost.router)
    dispatcher.include_router(group_router)
    dispatcher.include_router(moderation_router)
    dispatcher.include_router(payments_router)
    dispatcher.include_router(reminders.router)
    dispatcher.include_router(toolbox_router)
    dispatcher.include_router(user_router)
    # Спам, антифлуд и «личные» команды — до всех хендлеров.
    # Guard первым: он ловит падения всех кнопок, включая гейт подписки.
    dispatcher.callback_query.outer_middleware(CallbackAnswerGuard())
    dispatcher.message.outer_middleware(SubscriptionMiddleware())
    dispatcher.callback_query.outer_middleware(SubscriptionMiddleware())
    dispatcher.message.outer_middleware(PrivateOnlyMiddleware(settings))
    dispatcher.message.outer_middleware(MutedMiddleware())
    dispatcher.message.outer_middleware(FloodMiddleware(settings))
    dispatcher.message.outer_middleware(SpamMiddleware(settings))
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    return dispatcher


def create_app(
    settings: Settings,
    dispatcher: Dispatcher,
    bot: Bot,
    store: Store,
) -> web.Application:
    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret,
    ).register(app, path=WEBHOOK_PATH)
    setup_application(app, dispatcher, bot=bot)

    async def health(_: web.Request) -> web.Response:
        db_ok = await store.ping()
        return web.json_response(
            {"status": "ok", "db": "up" if db_ok else "down"},
            status=200 if db_ok else 503,
        )

    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    miniapp.setup(app, settings, store, bot)
    return app


def main() -> None:
    settings = load_settings()
    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    store = create_store(settings)
    ai = AIClient(settings)
    images = ImageClient(settings)
    dispatcher = create_dispatcher(settings, store, ai, images)

    if settings.use_webhook:
        app = create_app(settings, dispatcher, bot, store)
        web.run_app(app, host="0.0.0.0", port=settings.port, print=None)
    else:
        asyncio.run(dispatcher.start_polling(bot))


if __name__ == "__main__":
    main()