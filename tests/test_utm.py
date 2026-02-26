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
