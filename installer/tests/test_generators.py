"""
tests/test_generators.py — Unit-тесты для генераторов (UUID, hex, SpiderX, ссылки).
"""

import sys
import os
import re
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from installer.config_builders.client_links import (
    gen_uuid, gen_hex, gen_spiderx, gen_vless_link, parse_vless_link,
)


UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
)


def test_gen_uuid_format():
    u = gen_uuid()
    assert UUID_RE.match(u), f"Невалидный UUID: {u}"


def test_gen_uuid_unique():
    ids = {gen_uuid() for _ in range(20)}
    assert len(ids) == 20, "gen_uuid() генерирует дубликаты"


def test_gen_hex_length():
    for n in [4, 8, 16]:
        h = gen_hex(n)
        assert len(h) == n * 2, f"Ожидалась длина {n*2}, получено {len(h)}"
        assert re.match(r'^[0-9a-f]+$', h), f"Не hex: {h}"


def test_gen_spiderx_format():
    for _ in range(10):
        s = gen_spiderx()
        assert s.startswith("/"), f"spiderX должен начинаться с /: {s}"
        assert len(s) >= 7, f"spiderX слишком короткий: {s}"


def test_gen_vless_link_reality():
    link = gen_vless_link(
        host="1.2.3.4",
        uuid_str="550e8400-e29b-41d4-a716-446655440000",
        pbk="test-pubkey",
        short_id="abcdef12",
        sni="example.com",
        spiderx="/test",
        port=443,
        protocol_mode="reality",
        label="Test",
    )
    assert link.startswith("vless://")
    assert "security=reality" in link
    assert "1.2.3.4:443" in link
    assert "pbk=test-pubkey" in link


def test_gen_vless_link_xhttp():
    link = gen_vless_link(
        host="example.com",
        uuid_str="550e8400-e29b-41d4-a716-446655440000",
        pbk="",
        short_id="",
        sni="example.com",
        spiderx="",
        port=443,
        protocol_mode="xhttp",
        xhttp_path="/vless",
        label="Test",
    )
    assert "type=xhttp" in link
    assert "security=tls" in link


def test_parse_vless_link_roundtrip():
    link = gen_vless_link(
        host="1.2.3.4",
        uuid_str="550e8400-e29b-41d4-a716-446655440000",
        pbk="pubkey123",
        short_id="sid123",
        sni="example.com",
        spiderx="/abc",
        port=443,
        protocol_mode="reality",
    )
    parsed = parse_vless_link(link)
    assert parsed is not None
    assert parsed["uuid"] == "550e8400-e29b-41d4-a716-446655440000"
    assert parsed["host"] == "1.2.3.4"
    assert parsed["port"] == 443
    assert parsed["security"] == "reality"


def test_parse_vless_link_invalid():
    assert parse_vless_link("") is None
    assert parse_vless_link("vmess://something") is None
    assert parse_vless_link("http://example.com") is None


if __name__ == "__main__":
    import traceback
    tests = [
        test_gen_uuid_format, test_gen_uuid_unique, test_gen_hex_length,
        test_gen_spiderx_format, test_gen_vless_link_reality,
        test_gen_vless_link_xhttp, test_parse_vless_link_roundtrip,
        test_parse_vless_link_invalid,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗  {t.__name__}: {traceback.format_exc()}")
            failed += 1
    print(f"\n  Результат: {passed} прошло / {failed} упало")
    sys.exit(0 if failed == 0 else 1)

