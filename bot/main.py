"""
Точка входа бота: инициализация БД, диспетчера, middleware, роутеров.
Запуск long polling или webhook.
"""
from __future__ import annotations

# ruff: noqa: E402 — imports below must run after load_dotenv()
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Загружаем .env из корня проекта до любых настроек (чтобы ADMIN_TG_IDS и др. были в os.environ)
_load_env = Path(__file__).resolve().parent.parent / ".env"
if _load_env.exists():
    load_dotenv(_load_env)

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from app.db import init_db
from bot.middlewares import DbSessionMiddleware, LimitsMiddleware, PolicyMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware
from bot.routers import admin, documents, payments, start
from config import get_settings

try:
    from pythonjsonlogger import jsonlogger
    formatter = jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(name)s %(message)s')
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[handler])
except ImportError:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = get_settings()
    
    if settings.SENTRY_DSN:
        import sentry_sdk
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )
        logger.info("Sentry initialized")
        
    from app import db
    init_db(settings.DATABASE_URL)
    if db.async_session_factory is None:
        raise RuntimeError("init_db did not set async_session_factory")
    logger.info("DB session factory initialized")

    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    from redis.asyncio import Redis
    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)

    dp.message.middleware(ThrottlingMiddleware(redis=redis_client, rate_limit=1.5))
    dp.message.middleware(DbSessionMiddleware())
    dp.message.middleware(PolicyMiddleware())
    dp.message.middleware(LimitsMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(PolicyMiddleware())

    dp.include_router(admin.router)
    dp.include_router(payments.router)  # до start, чтобы кнопка «💳 Купить лимиты» не перехватывалась on_any_text
    dp.include_router(start.router)
    dp.include_router(documents.router)

    if settings.WEBHOOK_HOST:
        import secrets
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        from aiohttp import web
        
        # Генерируем или берем из конфига токен
        secret_token = settings.WEBHOOK_SECRET_TOKEN or secrets.token_urlsafe(32)
        
        await bot.set_webhook(
            f"{settings.WEBHOOK_HOST.rstrip('/')}{settings.WEBHOOK_PATH}",
            secret_token=secret_token
        )
        # Лимит размера тела запроса (анти-DoS для webhook и ЮKassa)
        app = web.Application(client_max_size=512 * 1024)
        webhook_handler = SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret_token)
        webhook_handler.register(app, path=settings.WEBHOOK_PATH)
        app["bot"] = bot
        from app.yookassa_webhook import yookassa_webhook_handler
        app.router.add_post("/yookassa/webhook", yookassa_webhook_handler)

        async def health(_: web.Request) -> web.Response:
            return web.Response(text="ok")
        app.router.add_get("/health", health)
        setup_application(app, dp, bot=bot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", 8080)
        await site.start()
        logger.info("Webhook listening on 0.0.0.0:8080")
        await asyncio.Event().wait()
    else:
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
