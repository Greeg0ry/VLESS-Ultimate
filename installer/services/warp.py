"""
services/warp.py — Интеграция с Cloudflare WARP.

WARP используется как outbound для обхода блокировок или выхода через Cloudflare.

Режимы маршрутизации WARP:
  full      — весь трафик через WARP (кроме SSH-клиента)
  selective — только указанные IP/домены
  runet     — заблокированные в РФ ресурсы (из списков runetfreedom)

ВАЖНО: SSH-клиент (IP клиента, который подключился к серверу) всегда
исключается из WARP-маршрутизации — иначе можно потерять доступ к серверу.
"""

from __future__ import annotations

from installer.core.shell import run, run_capture, command_exists
from installer.core.logging import info, success, warn
from installer.core.paths import WARP_MDM_FILE
from installer.core.constants import (
    WARP_SERVICE_NAME, WARP_MODE_FULL, WARP_MODE_SELECTIVE, WARP_MODE_RUNET,
)


def install_warp() -> bool:
    """
    Устанавливает Cloudflare WARP клиент.

    Returns:
        True если установка прошла успешно.
    """
    if command_exists("warp-cli"):
        info("WARP уже установлен")
        return True

    info("Установка Cloudflare WARP...")

    run(["curl", "-fsSL", "https://pkg.cloudflareclient.com/pubkey.gpg",
         "-o", "/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg"],
        check=False, quiet=True)

    import subprocess
    arch_r = subprocess.run(["dpkg", "--print-architecture"],
                            capture_output=True, text=True)
    arch = arch_r.stdout.strip()

    r = run_capture(["lsb_release", "-cs"])
    codename = r.stdout.strip() if r.returncode == 0 else "focal"

    repo_line = (
        f"deb [arch={arch} signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] "
        f"https://pkg.cloudflareclient.com/ {codename} main"
    )
    from pathlib import Path
    Path("/etc/apt/sources.list.d/cloudflare-client.list").write_text(repo_line + "\n")

    run(["apt-get", "update", "-qq"], check=False, quiet=True)
    run(["apt-get", "install", "-y", "-q", "cloudflare-warp"],
        env={"DEBIAN_FRONTEND": "noninteractive"},
        check=False, quiet=True)

    if not command_exists("warp-cli"):
        warn("WARP не удалось установить")
        return False

    success("Cloudflare WARP установлен")
    return True


def connect_warp() -> bool:
    """
    Регистрирует и подключает WARP.

    Returns:
        True если подключение успешно.
    """
    if not command_exists("warp-cli"):
        return False

    info("Подключение к Cloudflare WARP...")

    run(["systemctl", "start", WARP_SERVICE_NAME], check=False, quiet=True)

    import time
    time.sleep(2)

    r = run_capture(["warp-cli", "status"])
    if "Connected" in r.stdout:
        success("WARP уже подключён")
        return True

    run(["warp-cli", "register"], check=False, quiet=True)
    time.sleep(3)
    run(["warp-cli", "connect"], check=False, quiet=True)
    time.sleep(5)

    r = run_capture(["warp-cli", "status"])
    if "Connected" in r.stdout:
        success("WARP подключён")
        return True

    warn("WARP не удалось подключить")
    return False


def configure_warp_routing(
    mode: str,
    ssh_client_ip: str = "",
    custom_ips: list[str] | None = None,
    custom_domains: list[str] | None = None,
) -> None:
    """
    Настраивает режим маршрутизации через WARP.

    Args:
        mode:           "full", "selective" или "runet".
        ssh_client_ip:  IP SSH-клиента — всегда исключается из WARP.
        custom_ips:     IP/CIDR для selective-режима.
        custom_domains: Домены для selective-режима.
    """
    if not command_exists("warp-cli"):
        warn("warp-cli не найден — маршрутизация не настроена")
        return

    info(f"Настройка WARP режим: {mode}")

    if ssh_client_ip:
        _exclude_from_warp(ssh_client_ip)

    if mode == WARP_MODE_FULL:
        run(["warp-cli", "set-mode", "warp"], check=False, quiet=True)

    elif mode == WARP_MODE_SELECTIVE:
        run(["warp-cli", "set-mode", "tunnel_only"], check=False, quiet=True)
        for ip in (custom_ips or []):
            run(["warp-cli", "add-excluded-route", ip], check=False, quiet=True)
        for domain in (custom_domains or []):
            run(["warp-cli", "add-excluded-route", domain], check=False, quiet=True)

    elif mode == WARP_MODE_RUNET:
        run(["warp-cli", "set-mode", "tunnel_only"], check=False, quiet=True)
        info("WARP runet-маршрутизация применяется через Xray routing rules")

    success(f"WARP режим {mode} настроен")


def _exclude_from_warp(ip: str) -> None:
    """Исключает IP из WARP-туннеля (защита SSH-соединения)."""
    run(["warp-cli", "add-excluded-route", ip], check=False, quiet=True)


def get_warp_status() -> dict:
    """
    Возвращает статус WARP: {'connected': bool, 'ip': str, 'mode': str}.
    """
    if not command_exists("warp-cli"):
        return {"connected": False, "ip": "", "mode": ""}

    r = run_capture(["warp-cli", "status"])
    connected = "Connected" in r.stdout
    ip = ""
    if connected:
        r2 = run_capture(["warp-cli", "warp-stats"])
        import re
        m = re.search(r'IP[:\s]+(\S+)', r2.stdout)
        if m:
            ip = m.group(1)

    return {"connected": connected, "ip": ip, "mode": ""}

