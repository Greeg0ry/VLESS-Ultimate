"""
tests/test_validators.py — Unit-тесты для чистых функций валидации.

Запуск:
    python -m pytest installer/tests/test_validators.py -v
    # или без pytest:
    python installer/tests/test_validators.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from installer.core.validators import (
    is_valid_uuid, normalize_uuid,
    is_valid_port, parse_port,
    is_valid_domain, is_valid_ipv4, is_valid_ipv6, is_valid_ip,
    is_valid_cidr, is_domain_or_ip,
    is_valid_hex, is_valid_short_id,
    is_valid_base64_url, is_valid_email_label,
    is_valid_vless_link, is_valid_http_path,
)


# =============================================================================
#  UUID
# =============================================================================

def test_uuid_valid():
    assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000")
    assert is_valid_uuid("550E8400-E29B-41D4-A716-446655440000")  # uppercase

def test_uuid_invalid():
    assert not is_valid_uuid("")
    assert not is_valid_uuid("not-a-uuid")
    assert not is_valid_uuid("550e8400-e29b-41d4-a716")  # too short

def test_normalize_uuid():
    assert normalize_uuid("550E8400-E29B-41D4-A716-446655440000") == "550e8400-e29b-41d4-a716-446655440000"
    assert normalize_uuid("invalid") is None


# =============================================================================
#  ПОРТЫ
# =============================================================================

def test_port_valid():
    assert is_valid_port(443)
    assert is_valid_port(1)
    assert is_valid_port(65535)
    assert is_valid_port("8080")

def test_port_invalid():
    assert not is_valid_port(0)
    assert not is_valid_port(65536)
    assert not is_valid_port("abc")
    assert not is_valid_port(-1)

def test_parse_port():
    assert parse_port("443") == 443
    assert parse_port("invalid", default=8080) == 8080
    assert parse_port("0", default=443) == 443


# =============================================================================
#  ДОМЕНЫ
# =============================================================================

def test_domain_valid():
    assert is_valid_domain("example.com")
    assert is_valid_domain("sub.example.com")
    assert is_valid_domain("my-server.org")

def test_domain_invalid():
    assert not is_valid_domain("1.2.3.4")
    assert not is_valid_domain("localhost")
    assert not is_valid_domain("")
    assert not is_valid_domain("-invalid.com")
    assert not is_valid_domain("no_tld")


# =============================================================================
#  IP-АДРЕСА
# =============================================================================

def test_ipv4_valid():
    assert is_valid_ipv4("1.2.3.4")
    assert is_valid_ipv4("192.168.0.1")
    assert is_valid_ipv4("255.255.255.255")

def test_ipv4_invalid():
    assert not is_valid_ipv4("256.0.0.1")
    assert not is_valid_ipv4("example.com")
    assert not is_valid_ipv4("")

def test_ipv6_valid():
    assert is_valid_ipv6("::1")
    assert is_valid_ipv6("2001:db8::1")
    assert is_valid_ipv6("fe80::1%eth0".split("%")[0])

def test_cidr_valid():
    assert is_valid_cidr("192.168.0.0/24")
    assert is_valid_cidr("10.0.0.0/8")
    assert is_valid_cidr("2001:db8::/32")

def test_cidr_invalid():
    # Python ipaddress принимает "1.2.3.4" как /32 сеть (strict=False — это корректно)
    # Проверяем явно невалидные значения
    assert not is_valid_cidr("256.0.0.0/8")
    assert not is_valid_cidr("not-a-cidr")
    assert not is_valid_cidr("")


# =============================================================================
#  HEX / SHORT ID
# =============================================================================

def test_hex_valid():
    assert is_valid_hex("deadbeef")
    assert is_valid_hex("DEADBEEF")
    assert is_valid_hex("1234567890abcdef", length=8)

def test_hex_invalid():
    assert not is_valid_hex("xyz")
    # length — это длина в БАЙТАХ (n*2 символов): deadbeef = 4 байта, length=8 = 8 байт → не совпадает
    assert not is_valid_hex("deadbeef", length=8)  # 8 символов != 16 символов (8 байт)

def test_short_id_valid():
    assert is_valid_short_id("")  # пустой — допустим
    assert is_valid_short_id("abcdef1234567890")  # 16 hex
    assert is_valid_short_id("1234")

def test_short_id_invalid():
    assert not is_valid_short_id("g" * 16)  # не hex


# =============================================================================
#  EMAIL LABEL
# =============================================================================

def test_email_label_valid():
    assert is_valid_email_label("user@example.com")
    assert is_valid_email_label("test-user")
    assert is_valid_email_label("user123")

def test_email_label_invalid():
    assert not is_valid_email_label("")
    assert not is_valid_email_label("user name")  # пробел


# =============================================================================
#  VLESS LINK / HTTP PATH
# =============================================================================

def test_vless_link():
    assert is_valid_vless_link("vless://uuid@host:443?security=reality#label")
    assert not is_valid_vless_link("vmess://...")
    assert not is_valid_vless_link("")

def test_http_path():
    assert is_valid_http_path("/vless")
    assert is_valid_http_path("/api/v1")
    assert not is_valid_http_path("vless")  # без /
    assert not is_valid_http_path("/")      # слишком короткий


# =============================================================================
#  RUNNER (без pytest)
# =============================================================================

if __name__ == "__main__":
    import traceback

    tests = [
        test_uuid_valid, test_uuid_invalid, test_normalize_uuid,
        test_port_valid, test_port_invalid, test_parse_port,
        test_domain_valid, test_domain_invalid,
        test_ipv4_valid, test_ipv4_invalid, test_ipv6_valid,
        test_cidr_valid, test_cidr_invalid,
        test_hex_valid, test_hex_invalid,
        test_short_id_valid, test_short_id_invalid,
        test_email_label_valid, test_email_label_invalid,
        test_vless_link, test_http_path,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗  {t.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗  {t.__name__}: {traceback.format_exc()}")
            failed += 1

    print(f"\n  Результат: {passed} прошло / {failed} упало")
    sys.exit(0 if failed == 0 else 1)

