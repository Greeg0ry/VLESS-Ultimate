"""
services/fail2ban.py — Установка и настройка Fail2ban для защиты Xray/Nginx.

Fail2ban блокирует IP-адреса при множественных неудачных попытках подключения,
защищая от перебора и сканирования.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from installer.core.shell import run, run_capture, command_exists
from installer.core.logging import info, success, warn
from installer.core.paths import FAIL2BAN_JAIL_CONF, XRAY_ERROR_LOG
from installer.core.constants import FAIL2BAN_SERVICE_NAME


def setup_fail2ban(server_port: int = 443) -> None:
    """
    Устанавливает и настраивает Fail2ban для защиты Xray.

    Создаёт jail xray-reality, который:
    - Мониторит лог ошибок Xray
    - Банит IP при 5+ ошибках за 10 минут на 1 час

    Args:
        server_port: Порт Xray (для дополнительного правила iptables).
    """
    if not command_exists("fail2ban-server"):
        info("Установка fail2ban...")
        run(
            ["apt-get", "install", "-y", "-q", "fail2ban"],
            env={"DEBIAN_FRONTEND": "noninteractive"},
            check=False, quiet=True,
        )

    if not command_exists("fail2ban-server"):
        warn("fail2ban не удалось установить — пропускаем")
        return

    info("Настройка Fail2ban для Xray...")

    filter_dir = Path("/etc/fail2ban/filter.d")
    filter_dir.mkdir(parents=True, exist_ok=True)
    filter_file = filter_dir / "xray-reality.conf"
    filter_file.write_text(textwrap.dedent("""\
        [Definition]
        failregex = .*\\[Warning\\].*<HOST>.*
                    .*rejected.*<HOST>.*
                    .*connection from.*<HOST>.*failed.*
        ignoreregex =
    """))

    FAIL2BAN_JAIL_CONF.parent.mkdir(parents=True, exist_ok=True)
    FAIL2BAN_JAIL_CONF.write_text(textwrap.dedent(f"""\
        [xray-reality]
        enabled   = true
        port      = {server_port}
        filter    = xray-reality
        logpath   = {XRAY_ERROR_LOG}
        maxretry  = 5
        findtime  = 600
        bantime   = 3600
        action    = iptables-multiport[name=xray, port="{server_port}", protocol=tcp]
    """))

    run(["systemctl", "enable", FAIL2BAN_SERVICE_NAME], check=False, quiet=True)
    run(["systemctl", "restart", FAIL2BAN_SERVICE_NAME], check=False, quiet=True)
    success("Fail2ban настроен")


def setup_nginx_rate_limit() -> None:
    """
    Настраивает rate limiting в Nginx через conf.d/rate-limit.conf.
    Ограничивает число запросов с одного IP.
    """
    from installer.core.paths import NGINX_RATE_LIMIT
    NGINX_RATE_LIMIT.parent.mkdir(parents=True, exist_ok=True)
    NGINX_RATE_LIMIT.write_text(textwrap.dedent("""\
        # Rate limiting zones (включается в server-блок через limit_req/limit_conn)
        limit_req_zone  $binary_remote_addr zone=general:10m rate=10r/s;
        limit_conn_zone $binary_remote_addr zone=conn_limit:10m;
    """))
    info("Nginx rate limiting настроен")

