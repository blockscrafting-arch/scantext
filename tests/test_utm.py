"""
Тесты парсинга UTM из /start payload.
"""
from bot.routers.start import _parse_start_payload, _parse_utm_from_payload


def test_parse_start_payload_empty():
    assert _parse_start_payload("") is None
    assert _parse_start_payload("/start") is None
    assert _parse_start_payload("  /start  ") is None


def test_parse_start_payload_with_text():
    assert _parse_start_payload("/start ref123") == "ref123"
    assert _parse_start_payload("/start utm_source=telegram") == "utm_source=telegram"


def test_parse_utm_from_payload():
    assert _parse_utm_from_payload(None) == {}
    assert _parse_utm_from_payload("") == {}
    out = _parse_utm_from_payload("utm_source=ads&utm_medium=cpc")
    assert "utm_source" in out
    assert out["utm_source"] == ["ads"]  # parse_qs returns lists
    out2 = _parse_utm_from_payload("single_ref")
    assert "raw" in out2


def test_parse_utm_from_payload_term_content():
    """Парсинг utm_term и utm_content."""
    out = _parse_utm_from_payload(
        "utm_source=s&utm_medium=m&utm_campaign=c&utm_term=keyword&utm_content=block"
    )
    assert out.get("utm_source") == ["s"]
    assert out.get("utm_medium") == ["m"]
    assert out.get("utm_campaign") == ["c"]
    assert out.get("utm_term") == ["keyword"]
    assert out.get("utm_content") == ["block"]


def test_parse_utm_telegram_format_double_underscore():
    """Telegram-формат: source-xxx__medium-yyy__campaign-zzz (разделитель __)."""
    out = _parse_utm_from_payload("source-gramads__medium-AI__campaign-bun")
    assert out.get("utm_source") == ["gramads"]
    assert out.get("utm_medium") == ["AI"]
    assert out.get("utm_campaign") == ["bun"]


def test_parse_utm_telegram_format_single_param():
    """Один параметр в Telegram-формате."""
    out = _parse_utm_from_payload("source-telegram")
    assert out.get("utm_source") == ["telegram"]


def test_parse_utm_telegram_format_value_with_hyphen():
    """Значение с дефисом (split по первому '-')."""
    out = _parse_utm_from_payload("source-gram-ads__medium-cpc")
    assert out.get("utm_source") == ["gram-ads"]
    assert out.get("utm_medium") == ["cpc"]


def test_parse_utm_short_prefixes_s_m_c():
    """Короткие префиксы s, m, c (как в инструкции для заказчика)."""
    out = _parse_utm_from_payload("s-gramads_m-AI_c-bun")
    assert out.get("utm_source") == ["gramads"]
    assert out.get("utm_medium") == ["AI"]
    assert out.get("utm_campaign") == ["bun"]
