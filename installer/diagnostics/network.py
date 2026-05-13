"""
diagnostics/network.py — Сетевая диагностика: IPv6, DNS, связность, latency.
"""

from __future__ import annotations

import socket
import time
from typing import Optional

from installer.core.shell import run_capture, command_exists
from installer.core.logging import info, success, warn


def check_ipv6() -> tuple[bool, str]:
    """
    Проверяет IPv6-связность.

    Returns:
        (available, info_string)
    """
    try:
        r = run_capture(["ip", "-6", "addr", "show", "scope", "global"])
        if r.returncode == 0 and r.stdout.strip():
            r2 = run_capture(["ip", "-6", "route", "show", "default"])
            route_ok = r2.returncode == 0 and bool(r2.stdout.strip())
            msg = "IPv6 доступен" + (" (маршрут есть)" if route_ok else " (нет маршрута по умолчанию)")
            return True, msg
    except Exception:
        pass
    return False, "IPv6 недоступен"


def probe_tcp_latency(host: str, port: int, timeout: float = 3.0) -> Optional[float]:
    """
    Измеряет задержку TCP-соединения до хоста.

    Returns:
        Задержка в мс или None если соединение не удалось.
    """
    try:
        start = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            return (time.perf_counter() - start) * 1000
    except Exception:
        pass
    return None


def check_dns_resolution(domain: str) -> tuple[bool, str]:
    """
    Проверяет резолвинг домена.

    Returns:
        (ok, ip_or_error)
    """
    try:
        ip = socket.getaddrinfo(domain, None)[0][4][0]
        return True, ip
    except Exception as e:
        return False, str(e)


def check_port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """Проверяет, что порт открыт и принимает соединения."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except Exception:
        return False


def run_network_diagnostics(domain: str = "", server_port: int = 443) -> None:
    """
    Выполняет полную сетевую диагностику и выводит результаты.
    """
    info("Сетевая диагностика...")
    print()

    ipv6_ok, ipv6_msg = check_ipv6()
    if ipv6_ok:
        success(f"  IPv6: {ipv6_msg}")
    else:
        warn(f"  IPv6: {ipv6_msg}")

    if domain:
        dns_ok, dns_result = check_dns_resolution(domain)
        if dns_ok:
            success(f"  DNS {domain}: {dns_result}")
        else:
            warn(f"  DNS {domain}: {dns_result}")

    for host in ["1.1.1.1", "8.8.8.8"]:
        lat = probe_tcp_latency(host, 443)
        if lat is not None:
            success(f"  Ping {host}:443: {lat:.1f} мс")
        else:
            warn(f"  Ping {host}:443: недоступен")

    if check_port_open("127.0.0.1", server_port):
        success(f"  Порт {server_port} (локальный): открыт")
    else:
        warn(f"  Порт {server_port} (локальный): закрыт")

    print()

