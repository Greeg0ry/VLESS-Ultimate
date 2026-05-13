"""
services/ufw.py — Управление файерволом UFW.

ВАЖНО: любое изменение правил UFW должно СНАЧАЛА добавлять правило allow 22/tcp,
чтобы не потерять SSH-доступ к серверу. Только потом можно менять остальные правила.

Правило безопасности: никогда не закрывай порт 22 до того как убедился
что новое правило уже применилось.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from installer.core.shell import run, run_capture, command_exists
from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import UFW_MARK_FILE


def configure_firewall(
    server_port: int,
    ssh_port: int = 22,
    extra_ports: Optional[list[int]] = None,
) -> None:
    """
    Настраивает UFW для работы с Xray.

    Порядок операций:
    1. Разрешаем SSH (критично!)
    2. Разрешаем порт Xray
    3. Включаем UFW (если ещё не включён)

    Args:
        server_port:  Порт Xray (обычно 443).
        ssh_port:     Порт SSH (по умолчанию 22).
        extra_ports:  Дополнительные порты для открытия.
    """
    if not command_exists("ufw"):
        warn("UFW не найден — пропускаем настройку файервола")
        return

    info("Настройка UFW...")

    run(["ufw", "allow", f"{ssh_port}/tcp", "comment", "SSH"], check=False, quiet=True)

    run(["ufw", "allow", f"{server_port}/tcp", "comment", "VLESS/Xray"], check=False, quiet=True)

    run(["ufw", "allow", "80/tcp", "comment", "HTTP/ACME"], check=False, quiet=True)

    for port in (extra_ports or []):
        run(["ufw", "allow", f"{port}", "comment", "VLESS-extra"], check=False, quiet=True)

    r = run_capture(["ufw", "status"])
    if "inactive" in r.stdout.lower():
        run(["ufw", "--force", "enable"], check=False, quiet=True)
        success("UFW включён")
    else:
        run(["ufw", "reload"], check=False, quiet=True)
        success("UFW перезагружен")

    _save_ufw_mark(server_port, ssh_port)

    r = run_capture(["ufw", "status", "numbered"])
    log_to_file("INFO", f"UFW rules:\n{r.stdout}")


def ensure_ssh_open(ssh_port: int = 22) -> None:
    """
    Экстренное добавление правила SSH в UFW.
    Вызывается из EXIT TRAP при аварийном завершении установки.
    """
    if command_exists("ufw"):
        run(
            ["ufw", "allow", f"{ssh_port}/tcp", "comment", "SSH (emergency restore)"],
            check=False, quiet=True,
        )


def _save_ufw_mark(server_port: int, ssh_port: int) -> None:
    """Записывает установленные правила в файл (нужен для удаления при uninstall)."""
    try:
        UFW_MARK_FILE.parent.mkdir(parents=True, exist_ok=True)
        UFW_MARK_FILE.write_text(f"{ssh_port}\n{server_port}\n80\n")
    except Exception:
        pass

