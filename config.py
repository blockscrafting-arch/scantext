"""
Конфигурация приложения через переменные окружения.
Валидация через Pydantic Settings.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import field_validator, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# .env всегда из корня проекта (где config.py), чтобы воркер Celery подхватывал настройки
_PROJECT_ROOT = Path(__file__).resolve().parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """Настройки приложения из .env."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Bot
    BOT_TOKEN: str = Field(default="", description="Telegram Bot API token")
    WEBHOOK_PATH: str = Field(default="/webhook", description="Path for Telegram webhook")
    WEBHOOK_HOST: str | None = Field(default=None, description="Public host for webhook (e.g. https://bot.example.com)")
    WEBHOOK_SECRET_TOKEN: str | None = Field(default=None, description="Secret token for webhook validation")

    # Database
    DATABASE_URL: str = Field(
        default="",
        description="PostgreSQL URL, e.g. postgresql+asyncpg://user:pass@localhost:5432/dbname",
    )
    DATABASE_URL_SYNC: str | None = Field(
        default=None,
        description="Synchronous PostgreSQL URL for Alembic/Celery (postgresql://...)",
    )

    # Redis
    REDIS_URL: str = Field(default="redis://localhost:6379/0", description="Redis URL for Celery broker")

    # Celery
    CELERY_BROKER_URL: str | None = Field(default=None, description="Override broker (default: REDIS_URL)")
    CELERY_RESULT_BACKEND: str | None = Field(default=None, description="Celery result backend (default: REDIS_URL)")

    # YooKassa
    YOOKASSA_SHOP_ID: str = Field(default="", description="YooKassa shop ID")
    YOOKASSA_SECRET_KEY: str = Field(default="", description="YooKassa secret key")
    # Не используется в текущем сценарии: API ЮKassa не передаёт подпись в HTTP-уведомлениях;
    # верификация выполняется через IP allowlist и GET /payments/{id}.
    YOOKASSA_WEBHOOK_SECRET: str | None = Field(default=None, description="Reserved; not used for webhook verification in current YooKassa API")
    YOOKASSA_RETURN_URL: str = Field(default="https://t.me/YourBot", description="Return URL after payment")
    # Для скриншота модерации: при ошибке создания платежа (нет ключей / 401) показать экран с ценой и кнопкой «Оплатить» с этой ссылкой (например https://t.me/YourBot). После прохождения модерации — удалить или оставить пустым.
    DEMO_PAYMENT_URL: str | None = Field(default=None, description="If set, on YooKassa error show payment screen with this button URL for moderation screenshot")

    # Limits & business
    BOT_ABOUT_TEXT: str = Field(
        default="ООО «Ромашка»\nИНН 1234567890 / ОГРН 1234567890123\nПоддержка: @support_user", 
        description="Текст раздела About (описание бота)"
    )
    FREE_LIMITS_PER_MONTH: int = Field(default=5, description="Free document processing limit per user per period")
    LIMIT_RESET_CRON: str = Field(default="0 0 1 * *", description="Cron for resetting free limits (default: 1st of month)")
    PAYMENT_PACK_SIZE: int = Field(default=10, description="Страниц в платном пакете за одну оплату")
    PAYMENT_PACK_PRICE: str = Field(default="100.00", description="Цена пакета в рублях (строка для ЮKassa)")

    # Observability
    SENTRY_DSN: str | None = Field(default=None, description="Sentry DSN for error tracking")

    # Admin (в .env: ADMIN_TG_IDS=123,456,789)
    ADMIN_TG_IDS: list[int] = Field(default_factory=list, description="Telegram user IDs of admins")

    # LLM OCR (OpenRouter)
    OPENROUTER_API_KEY: str = Field(default="", description="API key for OpenRouter (https://openrouter.ai)")
    LLM_VISION_MODEL: str = Field(
        default="google/gemini-3-flash-preview",
        description="Vision model for OCR, e.g. google/gemini-3-flash-preview, openai/gpt-4o-mini",
    )
    LLM_MAX_IMAGE_SIZE: int = Field(default=2048, ge=512, le=4096, description="Max image side (px) before sending to LLM; reduces tokens.")
    LLM_REQUEST_TIMEOUT: int = Field(default=90, ge=30, le=300, description="Timeout for single LLM request (seconds).")
    PDF_OCR_DPI: int = Field(default=200, ge=150, le=300, description="DPI for PDF pages when converting to images for LLM.")
    PDF_MAX_PAGES: int = Field(default=50, ge=1, le=200, description="Max PDF pages to process in one document (cost control).")
    PDF_MIN_CHARS_PER_PAGE: int = Field(
        default=150, ge=1, le=500,
        description="Минимум символов с страницы из pypdf — ниже порога страница уходит в LLM OCR.",
    )
    # Путь к папке bin Poppler (Windows: скачать с https://github.com/oschwartz10612/poppler-windows/releases, распаковать, указать путь к bin)
    POPPLER_PATH: str | None = Field(default=None, description="Path to poppler bin folder (required on Windows for PDF→image)")

    # 152-ФЗ: ссылки на документы (показываются при согласии и в /terms)
    PRIVACY_POLICY_URL: str | None = Field(default=None, description="URL политики конфиденциальности")
    TERMS_URL: str | None = Field(default=None, description="URL пользовательского соглашения (оферта)")
    CONSENT_PD_URL: str | None = Field(default=None, description="URL согласия на обработку персональных данных")

    @field_validator("ADMIN_TG_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v: str | list[int]) -> list[int]:
        if isinstance(v, list):
            return v
        if isinstance(v, str) and v.strip():
            parts = re.split(r"[,;\s]+", v.strip())
            return [int(x) for x in parts if x.strip()]
        return []

    def get_celery_broker_url(self) -> str:
        """URL брокера для Celery."""
        return self.CELERY_BROKER_URL or self.REDIS_URL

    def get_celery_result_backend(self) -> str:
        """URL бэкенда результатов Celery."""
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

    def get_database_url_sync(self) -> str:
        """Синхронный URL для Alembic/Celery (postgresql:// без asyncpg)."""
        if self.DATABASE_URL_SYNC:
            return self.DATABASE_URL_SYNC
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)


def get_settings() -> Settings:
    """Возвращает экземпляр настроек (singleton при повторном вызове с кэшем — опционально)."""
    return Settings()
