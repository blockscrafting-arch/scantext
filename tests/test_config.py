"""Тесты загрузки конфигурации."""
import os
import pytest


def test_settings_loads_from_env(settings):
    assert settings.BOT_TOKEN == "test"
    assert "postgresql" in settings.DATABASE_URL or settings.DATABASE_URL


def test_admin_ids_parsed(settings):
    assert isinstance(settings.ADMIN_TG_IDS, list)


def test_payment_pack_settings(settings):
    assert settings.PAYMENT_PACK_SIZE >= 1
    assert settings.PAYMENT_PACK_PRICE
    assert "." in settings.PAYMENT_PACK_PRICE or settings.PAYMENT_PACK_PRICE.isdigit()
