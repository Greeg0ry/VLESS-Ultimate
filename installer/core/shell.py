"""
core/shell.py — Единый безопасный wrapper для выполнения системных команд.

Все subprocess-вызовы в проекте должны идти через run() или run_capture().
Это обеспечивает:
  - единое логирование команд и ошибок
  - предсказуемое поведение при отсутствии бинарника (FileNotFoundError)
  - контроль environment (PATH, locale и т.д.)
  - простое мокирование в тестах

Правило: не импортировать этот модуль на уровне модуля в бизнес-логике.
Импортируй там, где реально вызывается команда.
"""

from __future__ import annotations

import os
import subprocess
from typing import Optional

from installer.core.logging import log_to_file


def run(
    args: list[str],
    check: bool = True,
    quiet: bool = False,
    capture: bool = False,
    input_text: Optional[str] = None,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """
    Выполняет системную команду.

    Args:
        args:       Список аргументов команды, например ["systemctl", "restart", "xray"].
        check:      Если True — бросает CalledProcessError при ненулевом returncode.
        quiet:      Если True — подавляет вывод команды (capture_output=True).
        capture:    Если True — захватывает stdout/stderr для дальнейшего разбора.
        input_text: Передать текст на stdin команды.
        env:        Дополнительные переменные окружения (мержатся поверх os.environ).
        cwd:        Рабочая директория для команды.
        timeout:    Таймаут в секундах (None = без ограничения).

    Returns:
        CompletedProcess с полями returncode, stdout, stderr.

    Raises:
        subprocess.CalledProcessError: если check=True и returncode != 0.
        FileNotFoundError:             если check=True и бинарник не найден.
    """
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)

    log_to_file("CMD", " ".join(str(a) for a in args))

    try:
        result = subprocess.run(
            args,
            capture_output=(capture or quiet),
            text=True,
            input=input_text,
            env=merged_env,
            cwd=cwd,
            timeout=timeout,
        )
    except FileNotFoundError:
        log_to_file("CMD_ERR", f"command not found: {args[0]}")
        if check:
            raise
        return subprocess.CompletedProcess(args, 127, stdout="", stderr=f"command not found: {args[0]}")
    except subprocess.TimeoutExpired:
        log_to_file("CMD_ERR", f"timeout after {timeout}s: {args[0]}")
        raise

    if result.returncode != 0:
        log_to_file("CMD_FAIL", f"exit={result.returncode}: {' '.join(str(a) for a in args)}")
        if check:
            raise subprocess.CalledProcessError(
                result.returncode, args, result.stdout, result.stderr
            )

    return result


def run_capture(
    args: list[str],
    check: bool = False,
    env: Optional[dict[str, str]] = None,
    cwd: Optional[str] = None,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    """
    Удобная обёртка: выполняет команду и всегда захватывает вывод.
    check=False по умолчанию — вызывающий сам проверяет returncode.
    """
    return run(args, check=check, capture=True, env=env, cwd=cwd, timeout=timeout)


def command_exists(cmd: str) -> bool:
    """Проверяет, доступна ли команда в PATH."""
    import shutil
    return shutil.which(cmd) is not None


def find_binary(*candidates: str) -> Optional[str]:
    """
    Ищет первый существующий бинарник из списка кандидатов.
    Полезно для поиска certbot (/snap/bin/certbot или /usr/bin/certbot).
    """
    import shutil
    from pathlib import Path
    for c in candidates:
        found = shutil.which(c)
        if found:
            try:
                if Path(found).resolve().exists():
                    return found
            except Exception:
                return found
    return None


def service_is_active(service: str) -> bool:
    """Возвращает True, если systemd-сервис находится в состоянии active."""
    r = run(["systemctl", "is-active", service], check=False, capture=True)
    return r.stdout.strip() == "active"


def service_restart(service: str, check: bool = True) -> bool:
    """
    Перезапускает systemd-сервис.
    Returns: True при успехе, False при ошибке (если check=False).
    """
    r = run(["systemctl", "restart", service], check=check, quiet=True)
    return r.returncode == 0


def service_reload(service: str, check: bool = True) -> bool:
    """Перезагружает конфигурацию сервиса без остановки."""
    r = run(["systemctl", "reload", service], check=check, quiet=True)
    return r.returncode == 0

