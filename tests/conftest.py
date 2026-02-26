"""Pytest fixtures and config."""
import os
import pytest

# Load .env so get_settings() works; force test values so CI and local match
os.environ["BOT_TOKEN"] = "test"
os.environ["DATABASE_URL"] = "postgresql+asyncpg://u:p@localhost/db"


@pytest.fixture
def settings():
    from config import get_settings
    return get_settings()
