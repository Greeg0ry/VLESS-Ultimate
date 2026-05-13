"""
services/logrotate.py — Управление ротацией логов Xray и установщика.

Доступные режимы (через меню):
  1. Применить настройки по умолчанию (daily, 14 архивов, gzip)
  2. Гибко изменить частоту (daily/weekly) и глубину хранения
  3. Принудительная ротация прямо сейчас (logrotate -f)
  4. Просмотр содержимого текущих конфигов /etc/logrotate.d/

Правило: никакого I/O при импорте, только при явном вызове функций.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Optional

from installer.core.constants import (
    LOGROTATE_CONF_NAME, LOGROTATE_CONF_DIR,
    LOGROTATE_DEFAULT_FREQ, LOGROTATE_DEFAULT_KEEP,
)
from installer.core.logging import info, success, warn
from installer.core.paths import LOG_FILE, CHANGE_LOG_FILE, XRAY_LOG_DIR
from installer.core.shell import run


def _build_logrotate_conf(frequency: str = LOGROTATE_DEFAULT_FREQ,
                          keep: int = LOGROTATE_DEFAULT_KEEP) -> str:
    """
    Генерирует содержимое конфига logrotate для логов Xray и установщика.

    Args:
        frequency: "daily" или "weekly".
        keep:      Количество хранимых архивных файлов.
    """
    logs = " ".join([
        str(LOG_FILE),
        str(CHANGE_LOG_FILE),
        str(XRAY_LOG_DIR / "access.log"),
        str(XRAY_LOG_DIR / "error.log"),
    ])
    return textwrap.dedent(f"""\
        # Автоматически создан VLESS Ultimate Installer
        # Управление: python3 install.py → Планировщик задач → Ротация логов
        {logs} {{
            {frequency}
            rotate {keep}
            compress
            delaycompress
            missingok
            notifempty
            sharedscripts
            postrotate
                systemctl reload xray 2>/dev/null || true
            endscript
        }}
    """)


def _conf_path() -> Path:
    """Возвращает полный путь к файлу конфига logrotate."""
    return Path(LOGROTATE_CONF_DIR) / LOGROTATE_CONF_NAME


def apply_default_logrotate() -> bool:
    """
    Устанавливает конфиг ротации логов с параметрами по умолчанию:
    daily, хранить 14 архивов, gzip.

    Returns:
        True если успешно.
    """
    conf = _build_logrotate_conf(LOGROTATE_DEFAULT_FREQ, LOGROTATE_DEFAULT_KEEP)
    try:
        _conf_path().write_text(conf)
        success(f"Logrotate конфиг применён ({LOGROTATE_DEFAULT_FREQ}, keep={LOGROTATE_DEFAULT_KEEP})")
        return True
    except PermissionError:
        warn(f"Нет прав на запись в {LOGROTATE_CONF_DIR}. Запустите от root.")
        return False


def configure_logrotate(frequency: str, keep: int) -> bool:
    """
    Применяет пользовательские параметры ротации логов.

    Args:
        frequency: "daily" или "weekly".
        keep:      Количество хранимых архивов (1–365).

    Returns:
        True если успешно.
    """
    if frequency not in ("daily", "weekly"):
        warn(f"Недопустимая частота ротации: {frequency}. Допустимые: daily, weekly")
        return False
    if not (1 <= keep <= 365):
        warn(f"Количество архивов должно быть от 1 до 365, получено: {keep}")
        return False

    conf = _build_logrotate_conf(frequency, keep)
    try:
        _conf_path().write_text(conf)
        success(f"Logrotate конфиг применён ({frequency}, keep={keep})")
        return True
    except PermissionError:
        warn(f"Нет прав на запись в {LOGROTATE_CONF_DIR}. Запустите от root.")
        return False


def force_rotate_now() -> bool:
    """
    Запускает принудительную ротацию прямо сейчас через logrotate -f.

    Returns:
        True если logrotate завершился с кодом 0.
    """
    conf = _conf_path()
    if not conf.exists():
        warn(f"Конфиг logrotate не найден: {conf}. Сначала примените настройки.")
        return False

    info("Запуск принудительной ротации логов...")
    r = run(["logrotate", "-f", str(conf)], check=False)
    if r.returncode == 0:
        success("Принудительная ротация логов выполнена ✓")
        return True
    else:
        warn(f"logrotate завершился с ошибкой (код {r.returncode})")
        return False


def show_logrotate_conf() -> None:
    """Выводит содержимое текущего конфига logrotate в терминал."""
    conf = _conf_path()
    if not conf.exists():
        info(f"Конфиг logrotate не найден: {conf}")
        return
    print(f"\n  📄 {conf}:\n")
    print(conf.read_text())


def get_logrotate_status() -> dict:
    """
    Возвращает словарь с текущим состоянием конфига logrotate.
    Используется для отображения статуса в меню.
    """
    conf = _conf_path()
    if not conf.exists():
        return {"installed": False}

    content = conf.read_text()
    freq = "daily" if "daily" in content else "weekly" if "weekly" in content else "unknown"
    keep = LOGROTATE_DEFAULT_KEEP
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("rotate "):
            try:
                keep = int(line.split()[1])
            except (IndexError, ValueError):
                pass
            break

    return {"installed": True, "frequency": freq, "keep": keep, "path": str(conf)}

