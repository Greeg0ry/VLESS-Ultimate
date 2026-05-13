"""
core/validators.py — Чистые функции валидации входных данных.

Все функции здесь являются чистыми (pure functions):
  - нет I/O
  - нет побочных эффектов
  - детерминированы: одинаковый вход → одинаковый выход

Это позволяет легко тестировать их без моков (см. tests/test_validators.py).
"""

from __future__ import annotations

import re
import uuid
import ipaddress
from typing import Optional


UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE
)


def is_valid_uuid(value: str) -> bool:
    """Проверяет, является ли строка валидным UUID v4."""
    return bool(UUID_RE.match(value.strip()))


def normalize_uuid(value: str) -> Optional[str]:
    """
    Возвращает UUID в нижнем регистре или None, если строка не является UUID.
    Используй для нормализации пользовательского ввода.
    """
    v = value.strip().lower()
    return v if is_valid_uuid(v) else None


def is_valid_port(value: int | str) -> bool:
    """Проверяет, является ли значение корректным TCP/UDP-портом (1–65535)."""
    try:
        port = int(value)
        return 1 <= port <= 65535
    except (ValueError, TypeError):
        return False


def parse_port(value: str, default: int = 443) -> int:
    """
    Парсит порт из строки. Возвращает default, если строка невалидна.
    """
    try:
        port = int(value.strip())
        return port if is_valid_port(port) else default
    except (ValueError, TypeError):
        return default


DOMAIN_RE = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
)


def is_valid_domain(value: str) -> bool:
    """
    Проверяет, является ли строка валидным доменным именем (не IP).
    Примеры: "example.com", "my.server.org" → True
             "1.2.3.4", "localhost", "" → False
    """
    return bool(DOMAIN_RE.match(value.strip()))


def is_valid_ipv4(value: str) -> bool:
    """Проверяет, является ли строка валидным IPv4-адресом."""
    try:
        addr = ipaddress.IPv4Address(value.strip())
        return True
    except ValueError:
        return False


def is_valid_ipv6(value: str) -> bool:
    """Проверяет, является ли строка валидным IPv6-адресом."""
    try:
        ipaddress.IPv6Address(value.strip())
        return True
    except ValueError:
        return False


def is_valid_ip(value: str) -> bool:
    """Проверяет IPv4 или IPv6."""
    return is_valid_ipv4(value) or is_valid_ipv6(value)


def is_valid_cidr(value: str) -> bool:
    """Проверяет валидность CIDR-нотации (например, "192.168.0.0/24")."""
    try:
        ipaddress.ip_network(value.strip(), strict=False)
        return True
    except ValueError:
        return False


def is_domain_or_ip(value: str) -> bool:
    """Возвращает True, если строка является доменом или IP-адресом."""
    return is_valid_domain(value) or is_valid_ip(value)


HEX_RE = re.compile(r'^[0-9a-fA-F]+$')


def is_valid_hex(value: str, length: Optional[int] = None) -> bool:
    """
    Проверяет, является ли строка валидной hex-строкой.
    Если передан length — проверяет также длину в байтах (length * 2 символов).
    """
    v = value.strip()
    if not HEX_RE.match(v):
        return False
    if length is not None:
        return len(v) == length * 2
    return True


def is_valid_short_id(value: str) -> bool:
    """Проверяет валидность REALITY shortId (hex 0–16 байт, т.е. 0–32 символа)."""
    v = value.strip()
    if not HEX_RE.match(v) and v != "":
        return False
    return len(v) <= 32


BASE64_URL_RE = re.compile(r'^[A-Za-z0-9_\-]+=*$')


def is_valid_base64_url(value: str) -> bool:
    """Проверяет, является ли строка валидным base64url (без padding или с)."""
    v = value.strip()
    return bool(BASE64_URL_RE.match(v)) if v else False


def is_valid_email_label(value: str) -> bool:
    """
    Проверяет, является ли строка допустимым email-идентификатором для Xray.
    Используется как метка пользователя, не обязательно настоящий email.
    """
    v = value.strip()
    return bool(v) and len(v) <= 128 and re.match(r'^[a-zA-Z0-9_\-@.+]+$', v) is not None


def is_valid_vless_link(value: str) -> bool:
    """Проверяет, начинается ли строка с 'vless://'."""
    return value.strip().startswith("vless://")


def is_valid_http_path(value: str) -> bool:
    """Проверяет, является ли строка валидным HTTP-путём (начинается с '/')."""
    v = value.strip()
    return v.startswith("/") and len(v) >= 2

