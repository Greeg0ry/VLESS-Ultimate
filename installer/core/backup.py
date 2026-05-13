"""
core/backup.py — Создание резервных копий и откат (rollback).

Перед любым изменением файлов Xray/Nginx вызывай create_backup().
При неудачной установке — perform_rollback().

Правила:
  - всегда делай backup перед изменением config.json
  - rollback не ронял SSH-доступ (порт 22 восстанавливается в EXIT TRAP)
"""

from __future__ import annotations

import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from installer.core.logging import info, success, warn, log_to_file
from installer.core.paths import BACKUP_DIR, XRAY_CONFIG_FILE, XRAY_BIN, STATE_FILE
from installer.core.shell import run


def create_backup(timestamp: Optional[str] = None) -> str:
    """
    Создаёт резервную копию текущих конфигов Xray и бинарника.

    Returns:
        Временная метка бэкапа (строка вида "20240513_120000").
    """
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / ts
    backup_path.mkdir(parents=True, exist_ok=True)

    if XRAY_CONFIG_FILE.exists():
        shutil.copy2(XRAY_CONFIG_FILE, backup_path / "config.json")
        log_to_file("BACKUP", f"config.json → {backup_path}/config.json")

    if XRAY_BIN.exists():
        bin_backup = backup_path / "xray"
        shutil.copy2(XRAY_BIN, bin_backup)
        log_to_file("BACKUP", f"xray binary → {bin_backup}")

    nginx_conf_dir = Path("/etc/nginx")
    if nginx_conf_dir.exists():
        nginx_backup = backup_path / "nginx"
        try:
            shutil.copytree(
                nginx_conf_dir / "sites-available",
                nginx_backup / "sites-available",
                ignore=shutil.ignore_patterns("*~"),
                dirs_exist_ok=True,
            )
        except Exception:
            pass

    success(f"Backup создан: {backup_path}")
    return ts


def perform_rollback(timestamp: str) -> bool:
    """
    Откатывает конфигурацию к указанному бэкапу.

    Args:
        timestamp: Временная метка бэкапа (из create_backup()).

    Returns:
        True если откат прошёл успешно.
    """
    backup_path = BACKUP_DIR / timestamp
    if not backup_path.exists():
        warn(f"Backup не найден: {backup_path}")
        return False

    info(f"Откат к backup {timestamp}...")

    src_cfg = backup_path / "config.json"
    if src_cfg.exists():
        shutil.copy2(src_cfg, XRAY_CONFIG_FILE)
        log_to_file("ROLLBACK", f"{src_cfg} → {XRAY_CONFIG_FILE}")

    src_bin = backup_path / "xray"
    if src_bin.exists():
        shutil.copy2(src_bin, XRAY_BIN)
        XRAY_BIN.chmod(0o755)
        log_to_file("ROLLBACK", f"{src_bin} → {XRAY_BIN}")

    run(["systemctl", "restart", "xray"], check=False, quiet=True)
    success(f"Откат к {timestamp} выполнен")
    return True


def list_backups() -> list[str]:
    """
    Возвращает список доступных бэкапов (по дате, новые первыми).
    """
    if not BACKUP_DIR.exists():
        return []
    dirs = sorted(
        (d.name for d in BACKUP_DIR.iterdir() if d.is_dir()),
        reverse=True,
    )
    return dirs


def get_latest_backup() -> Optional[str]:
    """Возвращает временную метку последнего бэкапа или None."""
    backups = list_backups()
    return backups[0] if backups else None


def create_scheduled_backup(keep_last: int = 7) -> Optional[str]:
    """
    Создаёт плановый tar.gz-бэкап всех ключевых конфигов установщика.

    Сохраняет:
    - /etc/xray/config.json
    - /var/lib/xray-installer/state.json
    - /etc/letsencrypt/live/<домен>/ (если есть)
    - as_direct_list.json, split_tunnel_custom.json

    Старые бэкапы ротируются: хранятся последние keep_last архивов.

    Args:
        keep_last: Сколько архивов хранить.

    Returns:
        Путь к созданному .tar.gz или None при ошибке.
    """
    import tarfile
    import shutil

    from installer.core.paths import (
        XRAY_CONFIG_FILE, STATE_FILE, LETSENCRYPT_DIR,
        BACKUP_DIR, SCHEDULED_BACKUP_LOG,
        ASN_LIST_FILE,
    )
    from installer.core.constants import SCHEDULED_BACKUP_LOG as SCHED_LOG_PATH

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_name = f"vless-backup-{ts}.tar.gz"
    archive_path = BACKUP_DIR / archive_name
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    sources: list[Path] = []
    for p in [XRAY_CONFIG_FILE, STATE_FILE, ASN_LIST_FILE,
              Path("/etc/xray/split_tunnel_custom.json")]:
        if p.exists():
            sources.append(p)

    if LETSENCRYPT_DIR.exists():
        for d in LETSENCRYPT_DIR.iterdir():
            if d.is_dir():
                sources.append(d)

    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            for src in sources:
                tar.add(src, arcname=str(src).lstrip("/"))
        log_to_file("SCHEDULED_BACKUP", f"Создан архив: {archive_path}")
        success(f"Плановый бэкап создан: {archive_path}")

        sched_log = Path(SCHED_LOG_PATH)
        sched_log.parent.mkdir(parents=True, exist_ok=True)
        with sched_log.open("a") as f:
            f.write(f"{datetime.now().isoformat()} BACKUP OK: {archive_path}\n")

    except Exception as e:
        warn(f"Ошибка создания планового бэкапа: {e}")
        log_to_file("SCHEDULED_BACKUP_ERR", str(e))
        return None

    _rotate_scheduled_backups(BACKUP_DIR, keep_last)

    return str(archive_path)


def _rotate_scheduled_backups(backup_dir: Path, keep_last: int) -> None:
    """Удаляет старые tar.gz-бэкапы, оставляя только keep_last последних."""
    archives = sorted(
        backup_dir.glob("vless-backup-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in archives[keep_last:]:
        try:
            old.unlink()
            log_to_file("SCHEDULED_BACKUP", f"Удалён старый бэкап: {old}")
        except Exception:
            pass


def setup_scheduled_backup_cron(interval_days: int = 1, hour: int = 3,
                                  minute: int = 0, keep_last: int = 7) -> bool:
    """
    Устанавливает cron-задачу для автоматического планового бэкапа.

    Файл: /etc/cron.d/xray-backup
    Формат: запуск от root с перенаправлением вывода в лог.

    Args:
        interval_days: Интервал в днях (1–30).
        hour:          Час запуска (0–23).
        minute:        Минута запуска (0–59).
        keep_last:     Сколько архивов хранить.

    Returns:
        True если cron-задача установлена.
    """
    from installer.core.constants import SCHEDULED_BACKUP_CRON_FILE, SCHEDULED_BACKUP_LOG

    if not (1 <= interval_days <= 30):
        warn(f"interval_days должно быть от 1 до 30, получено: {interval_days}")
        return False
    if not (0 <= hour <= 23) or not (0 <= minute <= 59):
        warn("Некорректное время запуска")
        return False

    if interval_days == 1:
        cron_expr = f"{minute} {hour} * * *"
    else:
        cron_expr = f"{minute} {hour} */{interval_days} * *"

    cron_line = (
        f"# VLESS Ultimate Installer — автоматический бэкап\n"
        f"{cron_expr} root "
        f"/usr/bin/python3 -m installer.main --scheduled-backup --keep-last={keep_last} "
        f">> {SCHEDULED_BACKUP_LOG} 2>&1\n"
    )

    cron_path = Path(SCHEDULED_BACKUP_CRON_FILE)
    try:
        cron_path.write_text(cron_line)
        cron_path.chmod(0o644)
        success(f"Cron-задача бэкапа установлена: {cron_path} ({cron_expr})")
        return True
    except PermissionError:
        warn(f"Нет прав на запись в {SCHEDULED_BACKUP_CRON_FILE}. Запустите от root.")
        return False


def remove_scheduled_backup_cron() -> bool:
    """Удаляет cron-задачу автоматического бэкапа."""
    from installer.core.constants import SCHEDULED_BACKUP_CRON_FILE
    cron_path = Path(SCHEDULED_BACKUP_CRON_FILE)
    if cron_path.exists():
        cron_path.unlink()
        info("Cron-задача автобэкапа удалена")
        return True
    return False


