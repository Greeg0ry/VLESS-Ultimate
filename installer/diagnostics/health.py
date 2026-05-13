"""
diagnostics/health.py — Проверки работоспособности Xray, Nginx, SSL и портов.

Функции возвращают bool и не вызывают sys.exit() — они предназначены
для сбора статуса, который потом показывается пользователю.
"""

from __future__ import annotations

import ssl
import socket
import time
from pathlib import Path
from typing import Optional

from installer.core.shell import run_capture, service_is_active
from installer.core.logging import info, success, warn, log_to_file
from installer.core.constants import XRAY_SERVICE_NAME, NGINX_SERVICE_NAME
from installer.core.paths import XRAY_CONFIG_FILE, XRAY_ALT_CONFIG, XRAY_BIN


def health_check_xray() -> bool:
    """
    Проверяет, что:
    1. xray.service в состоянии active
    2. xray.service не failed
    3. config.json существует

    Returns:
        True если всё в порядке.
    """
    if not service_is_active(XRAY_SERVICE_NAME):
        warn("Xray: сервис не в состоянии active")
        return False

    r = run_capture(["systemctl", "is-failed", XRAY_SERVICE_NAME])
    if r.stdout.strip() == "failed":
        warn("Xray: сервис в состоянии failed")
        return False

    cfg = XRAY_CONFIG_FILE if XRAY_CONFIG_FILE.exists() else XRAY_ALT_CONFIG
    if not cfg.exists():
        warn("Xray: config.json не найден")
        return False

    success("Xray: активен ✓")
    return True


def health_check_nginx() -> bool:
    """
    Проверяет, что Nginx активен и config валиден.
    Nginx опционален в REALITY-режиме — возвращает True если не установлен.
    """
    from installer.services.nginx import find_nginx_bin
    nginx_bin = find_nginx_bin()
    if not nginx_bin:
        return True

    if not service_is_active(NGINX_SERVICE_NAME):
        warn("Nginx: сервис не активен")
        return False

    r = run_capture([nginx_bin, "-t"])
    if r.returncode != 0:
        warn(f"Nginx: конфиг невалиден: {r.stderr.strip()[:200]}")
        return False

    success("Nginx: активен, конфиг валиден ✓")
    return True


def health_check_ssl(domain: str) -> bool:
    """
    Расширенная проверка TLS-сертификата домена.

    Проверяет:
    - Subject, Issuer, SAN
    - Срок действия (🟢 >30д, 🟡 <30д, 🔴 <7д)
    - Реальное SSL-соединение через openssl s_client (верификация цепочки)

    Returns:
        True если сертификат валиден и не истёк.
    """
    if not domain:
        return True

    from installer.core.paths import le_fullchain
    cert_file = le_fullchain(domain)
    if not cert_file.exists():
        warn(f"SSL: сертификат для {domain} не найден")
        return False

    r_text = run_capture([
        "openssl", "x509", "-text", "-noout", "-in", str(cert_file)
    ])
    if r_text.returncode == 0:
        cert_text = r_text.stdout
        for line in cert_text.splitlines():
            if "Subject:" in line:
                info(f"SSL Subject:  {line.strip()}")
                break
        for line in cert_text.splitlines():
            if "Issuer:" in line:
                info(f"SSL Issuer:   {line.strip()}")
                break
        san_lines = [l.strip() for l in cert_text.splitlines() if "DNS:" in l]
        if san_lines:
            info(f"SSL SAN:      {', '.join(san_lines[:3])}")

    r_end = run_capture(["openssl", "x509", "-enddate", "-noout", "-in", str(cert_file)])
    if r_end.returncode != 0:
        warn("SSL: не удалось прочитать срок действия сертификата")
        return False

    expiry_str = r_end.stdout.strip().replace("notAfter=", "")
    r_ts = run_capture(["date", "-d", expiry_str, "+%s"])
    if r_ts.returncode != 0:
        warn("SSL: не удалось разобрать дату истечения сертификата")
        return False

    days_left = (int(r_ts.stdout.strip()) - int(time.time())) // 86400

    if days_left < 0:
        warn(f"🔴 SSL: сертификат {domain} истёк {abs(days_left)} дней назад")
        return False
    elif days_left < 7:
        warn(f"🔴 SSL: сертификат {domain} истекает через {days_left} дней — срочно обновить!")
    elif days_left < 30:
        warn(f"🟡 SSL: сертификат {domain} истекает через {days_left} дней")
    else:
        success(f"🟢 SSL: сертификат {domain} валиден, осталось {days_left} дней ✓")

    r_chain = run_capture([
        "openssl", "s_client",
        "-connect", f"{domain}:443",
        "-servername", domain,
        "-verify_return_error",
        "-brief",
    ], timeout=10)
    if r_chain.returncode != 0:
        warn(f"SSL: openssl s_client не смог верифицировать цепочку для {domain} "
             f"(это может быть нормально если сервер не слушает 443 локально)")
    else:
        success(f"SSL: цепочка сертификатов {domain} верифицирована ✓")

    return days_left >= 0


def health_check_ports(server_port: int) -> bool:
    """
    Проверяет, что порт сервера открыт и слушается.

    Returns:
        True если порт принимает соединения.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex(("127.0.0.1", server_port))
        sock.close()
        if result == 0:
            success(f"Порт {server_port}: открыт ✓")
            return True
        else:
            warn(f"Порт {server_port}: недоступен (код {result})")
            return False
    except Exception as e:
        warn(f"Порт {server_port}: ошибка проверки — {e}")
        return False


def run_full_health_check(domain: str = "", server_port: int = 443) -> bool:
    """
    Запускает все проверки и возвращает True если всё OK.

    Используется:
    - В конце установки для итогового статуса
    - В меню диагностики
    """
    info("Запуск полной диагностики...")
    print()

    results = [
        ("Xray",  health_check_xray()),
        ("Nginx", health_check_nginx()),
        ("SSL",   health_check_ssl(domain) if domain else True),
        ("Порт",  health_check_ports(server_port)),
    ]

    all_ok = all(ok for _, ok in results)

    print()
    if all_ok:
        success("Все проверки пройдены ✓")
    else:
        failed = [name for name, ok in results if not ok]
        warn(f"Проблемы обнаружены: {', '.join(failed)}")

    return all_ok

