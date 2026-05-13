"""
diagnostics/xray_stats.py — Получение статистики трафика Xray через Stats API.

Stats API работает на localhost:XRAY_STATS_API_PORT (10085).
Позволяет получить накопленные байты по каждому пользователю/тегу.
"""

from __future__ import annotations

from typing import Optional

from installer.core.shell import run_capture, command_exists
from installer.core.logging import warn
from installer.core.constants import XRAY_STATS_API_PORT


def is_stats_api_available() -> bool:
    """Проверяет, что Stats API xray доступен."""
    import socket
    try:
        s = socket.socket()
        s.settimeout(1)
        s.connect(("127.0.0.1", XRAY_STATS_API_PORT))
        s.close()
        return True
    except Exception:
        return False


def get_stats_via_api() -> Optional[dict[str, int]]:
    """
    Получает статистику трафика через 'xray api statsquery'.

    Returns:
        Словарь {tag: bytes} или None если Stats API недоступен.
    """
    if not command_exists("xray"):
        return None
    if not is_stats_api_available():
        return None

    try:
        r = run_capture([
            "xray", "api", "statsquery",
            "--server", f"127.0.0.1:{XRAY_STATS_API_PORT}",
        ])
        if r.returncode != 0:
            return None

        import json
        data = json.loads(r.stdout)
        stats: dict[str, int] = {}

        for entry in data.get("stat", []):
            name  = entry.get("name", "")
            value = int(entry.get("value", 0))
            if name:
                stats[name] = value

        return stats
    except Exception as e:
        warn(f"Stats API: {e}")
        return None


def format_bytes(n: int) -> str:
    """Форматирует байты в читаемый вид (KB/MB/GB)."""
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.1f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def print_traffic_stats() -> None:
    """Выводит таблицу трафика по пользователям/тегам."""
    stats = get_stats_via_api()

    if stats is None:
        warn("Stats API недоступен — статистика через лог-файл (менее точно)")
        _print_stats_from_log()
        return

    if not stats:
        print("  Статистика пуста (нет трафика или Stats API не настроен)")
        return

    print()
    print(f"  {'Имя':<40} {'↑ Upload':>12} {'↓ Download':>12}")
    print(f"  {'─'*40} {'─'*12} {'─'*12}")

    for name, value in sorted(stats.items()):
        direction = "↑" if "uplink" in name else "↓"
        label = name.replace("user>>>", "").replace(">>>uplink", "").replace(">>>downlink", "")
        print(f"  {label:<40} {format_bytes(value):>12}")
    print()


def _print_stats_from_log() -> None:
    """Fallback: грубая оценка трафика из access.log."""
    from installer.core.paths import XRAY_ACCESS_LOG
    if not XRAY_ACCESS_LOG.exists():
        print("  Лог доступа не найден")
        return

    try:
        lines = XRAY_ACCESS_LOG.read_text(errors="ignore").splitlines()
        total = len(lines)
        print(f"  Записей в access.log: {total}")
        print(f"  (Для точной статистики настройте Stats API)")
    except Exception as e:
        warn(f"Ошибка чтения лога: {e}")

