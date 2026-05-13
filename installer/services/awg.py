"""
services/awg.py — Установка и управление AmneziaWG (WireGuard с обфускацией).

AWG используется в Режиме B как зашифрованный транспорт между
российским VPS (клиент AWG) и зарубежным VPS (сервер AWG).

Обфускация AmneziaWG делает WireGuard-трафик неотличимым от случайного,
обходя системы глубокой инспекции пакетов (DPI).

Параметры обфускации (JC, JMIN, JMAX, S1, S2, H1-H4) — на усмотрение пользователя,
рекомендуемые значения устанавливаются по умолчанию.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Optional

from installer.core.shell import run, run_capture, command_exists
from installer.core.logging import info, success, warn, log_to_file
from installer.core.constants import (
    AWG_DEFAULT_PORT, AWG_DEFAULT_MTU, AWG_INTERFACE_NAME,
    AWG_FWMARK, AWG_ROUTE_TABLE,
    AWG_DEFAULT_JC, AWG_DEFAULT_JMIN, AWG_DEFAULT_JMAX,
)
from installer.core.state import AwgConfig


def generate_awg_keys() -> tuple[str, str, str, str, str]:
    """
    Генерирует ключи для AmneziaWG.

    Returns:
        (server_privkey, server_pubkey, client_privkey, client_pubkey, preshared_key)
    """
    def _gen_key() -> tuple[str, str]:
        r = run_capture(["awg", "genkey"])
        if r.returncode != 0:
            r = run_capture(["wg", "genkey"])
        privkey = r.stdout.strip()
        r2 = run_capture(["awg", "pubkey"], )
        import subprocess
        r2 = subprocess.run(
            ["awg", "pubkey"],
            input=privkey, capture_output=True, text=True
        )
        if r2.returncode != 0:
            r2 = subprocess.run(
                ["wg", "pubkey"],
                input=privkey, capture_output=True, text=True
            )
        return privkey, r2.stdout.strip()

    import subprocess
    def _gen_psk() -> str:
        r = subprocess.run(["awg", "genpsk"], capture_output=True, text=True)
        if r.returncode != 0:
            r = subprocess.run(["wg", "genpsk"], capture_output=True, text=True)
        return r.stdout.strip()

    server_priv, server_pub = _gen_key()
    client_priv, client_pub = _gen_key()
    psk = _gen_psk()

    return server_priv, server_pub, client_priv, client_pub, psk


def build_server_config(cfg: AwgConfig) -> str:
    """
    Генерирует текст конфига AWG-сервера.

    Args:
        cfg: Заполненный AwgConfig с ключами и параметрами.

    Returns:
        Текст конфига в формате WireGuard/AmneziaWG.
    """
    return textwrap.dedent(f"""\
        [Interface]
        Address = {cfg.server_ip},{cfg.server_ipv6}
        ListenPort = {cfg.exit_port}
        PrivateKey = {cfg.server_privkey}
        DNS = 1.1.1.1
        MTU = {cfg.mtu}
        Jc = {cfg.jc}
        Jmin = {cfg.jmin}
        Jmax = {cfg.jmax}
        S1 = {cfg.s1}
        S2 = {cfg.s2}
        H1 = {cfg.h1}
        H2 = {cfg.h2}
        H3 = {cfg.h3}
        H4 = {cfg.h4}

        [Peer]
        PublicKey = {cfg.client_pubkey}
        PresharedKey = {cfg.preshared_key}
        AllowedIPs = {cfg.client_ip},{cfg.client_ipv6}
        PersistentKeepalive = 25
    """)


def build_client_config(cfg: AwgConfig) -> str:
    """
    Генерирует текст конфига AWG-клиента (для российского VPS).

    Args:
        cfg: Заполненный AwgConfig с ключами и адресом сервера.

    Returns:
        Текст конфига в формате WireGuard/AmneziaWG.
    """
    return textwrap.dedent(f"""\
        [Interface]
        Address = {cfg.client_ip},{cfg.client_ipv6}
        PrivateKey = {cfg.client_privkey}
        DNS = 1.1.1.1
        MTU = {cfg.mtu}
        Jc = {cfg.jc}
        Jmin = {cfg.jmin}
        Jmax = {cfg.jmax}
        S1 = {cfg.s1}
        S2 = {cfg.s2}
        H1 = {cfg.h1}
        H2 = {cfg.h2}
        H3 = {cfg.h3}
        H4 = {cfg.h4}

        [Peer]
        PublicKey = {cfg.server_pubkey}
        PresharedKey = {cfg.preshared_key}
        Endpoint = {cfg.exit_host}:{cfg.exit_port}
        AllowedIPs = 0.0.0.0/0,::/0
        PersistentKeepalive = 25
    """)


def apply_policy_routing(
    client_ip: str,
    interface: str = AWG_INTERFACE_NAME,
    fwmark: int = AWG_FWMARK,
    route_table: int = AWG_ROUTE_TABLE,
    ssh_client_ip: str = "",
) -> None:
    """
    Настраивает policy routing для AWG-туннеля.

    Весь трафик Xray (помечен fwmark) идёт через AWG-интерфейс.
    SSH-клиент исключается — чтобы не потерять доступ к серверу.

    Args:
        client_ip:     Локальный IP клиента AWG (для маршрута).
        interface:     Имя AWG-интерфейса.
        fwmark:        Метка пакетов Xray.
        route_table:   Таблица маршрутизации для AWG-трафика.
        ssh_client_ip: IP SSH-клиента — исключается из AWG.
    """
    info(f"Настройка policy routing для AWG ({interface})...")

    run(["ip", "rule", "add", "fwmark", str(fwmark),
         "table", str(route_table)], check=False, quiet=True)
    run(["ip", "route", "add", "default", "dev", interface,
         "table", str(route_table)], check=False, quiet=True)

    if ssh_client_ip:
        _ensure_ssh_exclusion(ssh_client_ip)

    success(f"Policy routing для AWG настроен (fwmark={fwmark}, table={route_table})")


def _ensure_ssh_exclusion(ssh_ip: str) -> None:
    """
    Добавляет маршрут для SSH-клиента через основной интерфейс (не AWG).
    Критично для сохранения доступа к серверу.
    """
    try:
        r = run_capture(["ip", "route", "show", "default"])
        import re
        m = re.search(r'via\s+(\S+)\s+dev\s+(\S+)', r.stdout)
        if m:
            gateway = m.group(1)
            dev = m.group(2)
            run(["ip", "route", "add", ssh_ip, "via", gateway, "dev", dev],
                check=False, quiet=True)
            log_to_file("INFO", f"SSH {ssh_ip} исключён из AWG маршрутизации")
    except Exception as e:
        warn(f"Не удалось исключить SSH из AWG: {e}")


def verify_tunnel(
    server_ip: str,
    interface: str = AWG_INTERFACE_NAME,
) -> bool:
    """
    Проверяет, что AWG-туннель работает: пингует сервер через интерфейс.

    Returns:
        True если туннель активен.
    """
    r = run_capture([
        "ping", "-c", "3", "-W", "3",
        "-I", interface, server_ip,
    ])
    if r.returncode == 0:
        success(f"AWG туннель активен (ping {server_ip} через {interface})")
        return True
    warn(f"AWG туннель не отвечает (ping {server_ip} через {interface})")
    return False


def is_awg_available() -> bool:
    """Проверяет наличие awg/awg-quick бинарников."""
    return command_exists("awg") or command_exists("awg-quick")

