"""
core/logging.py — Логирование установщика.

Предоставляет функции info(), success(), warn(), die(), dim().
Вывод идёт как в stdout, так и в лог-файл.

Правило: этот модуль НЕ создаёт лог-файл при импорте.
Инициализация выполняется через setup_logging(), вызываемую из main.py.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

_log_file: Optional[Path] = None

_RED     = '\033[0;31m'
_GREEN   = '\033[0;32m'
_YELLOW  = '\033[1;33m'
_CYAN    = '\033[0;36m'
_BOLD    = '\033[1m'
_DIM     = '\033[2m'
_WHITE   = '\033[1;37m'
_NC      = '\033[0m'


def setup_logging(log_path: Path, light_theme: bool = False) -> None:
    """
    Инициализирует логирование: создаёт лог-файл, устанавливает цвета темы.
    Вызывается один раз из main.py до начала любых операций.

    Args:
        log_path:    Путь к лог-файлу установщика.
        light_theme: True — светлая тема терминала (белый фон).
    """
    global _log_file, _RED, _GREEN, _YELLOW, _CYAN, _BOLD, _DIM, _WHITE, _NC

    _log_file = log_path
    try:
        _log_file.parent.mkdir(parents=True, exist_ok=True)
        _log_file.touch()
        _log_file.chmod(0o600)
    except Exception:
        pass

    if light_theme:
        _CYAN  = '\033[0;34m'
        _WHITE = '\033[0;30m'


def log_to_file(level: str, msg: str) -> None:
    """Пишет строку в лог-файл. Молчит при любых ошибках записи."""
    if _log_file is None:
        return
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with _log_file.open('a') as f:
            f.write(f"[{ts}] [{level}] {msg}\n")
    except Exception:
        pass


def info(msg: str) -> None:
    """Информационное сообщение (голубой [INFO])."""
    print(f"{_CYAN}[INFO]{_NC}  {msg}")
    log_to_file("INFO", msg)


def success(msg: str) -> None:
    """Успешное завершение операции (зелёный [OK])."""
    print(f"{_GREEN}[OK]{_NC}    {msg}")
    log_to_file("SUCCESS", msg)


def warn(msg: str) -> None:
    """Предупреждение (жёлтый [WARN])."""
    print(f"{_YELLOW}[WARN]{_NC}  {msg}")
    log_to_file("WARN", msg)


def dim(msg: str) -> None:
    """Приглушённое сообщение (не пишется в лог)."""
    print(f"{_DIM}{msg}{_NC}")


def die(msg: str) -> None:
    """
    Критическая ошибка: выводит сообщение в stderr, пишет в лог и завершает процесс.

    Не используй die() внутри сервисных модулей — только в main-флоу.
    В сервисах бросай исключения, перехватывай наверху.
    """
    print(f"{_RED}[ERROR]{_NC} {msg}", file=sys.stderr)
    log_to_file("ERROR", msg)
    sys.exit(1)


def get_colors() -> dict[str, str]:
    """
    Возвращает словарь текущих ANSI-кодов цветов для использования в UI.
    Используется в модулях, которым нужен доступ к цветам без прямого импорта констант.
    """
    return {
        "RED": _RED, "GREEN": _GREEN, "YELLOW": _YELLOW,
        "CYAN": _CYAN, "BOLD": _BOLD, "DIM": _DIM,
        "WHITE": _WHITE, "NC": _NC,
    }

