"""
cli/banner.py — ASCII-баннер установщика и заставка при запуске.

Баннер генерируется один раз при импорте модуля (только строковая операция, без I/O).
"""

from __future__ import annotations

import re as _re

# =============================================================================
#  ANSI-КОДЫ (локальные копии, чтобы не создавать циклических импортов)
# =============================================================================
_BOLD_RED = '\033[1;31m'
_NC       = '\033[0m'

# =============================================================================
#  ГЕНЕРАЦИЯ БАННЕРА
# =============================================================================

def _make_banner() -> str:
    _OW = 64        # внутренняя ширина внешней рамки
    _IW = _OW - 6   # внутренняя ширина вложенной рамки (58)

    _blank = "║" + " " * _OW + "║"
    _top   = "╔" + "═" * _OW + "╗"
    _bot   = "╚" + "═" * _OW + "╝"
    _itop  = "║  ╔" + "═" * _IW + "╗  ║"
    _ibot  = "║  ╚" + "═" * _IW + "╝  ║"

    def _art(a: str) -> str:
        return "║  " + a + " " * (_OW - 2 - len(a)) + "║"

    def _irow(t: str) -> str:
        return "║  ║ " + t + " " * (_OW - 8 - len(t)) + " ║  ║"

    def _irow_ansi(raw: str) -> str:
        """Строка рамки с ANSI: ширина по видимым символам (без escape-кодов)."""
        visible = _re.sub(r'\033\[[0-9;]*m', '', raw)
        pad = _OW - 8 - len(visible)
        return "║  ║ " + raw + " " * max(pad, 0) + " ║  ║"

    _art_lines = [
        "██╗   ██╗██╗     ███████╗███████╗███████╗",
        "██║   ██║██║     ██╔════╝██╔════╝██╔════╝",
        "██║   ██║██║     █████╗  ███████╗███████╗",
        "╚██╗ ██╔╝██║     ██╔══╝  ╚════██║╚════██║",
        " ╚████╔╝ ███████╗███████╗███████║███████║",
        "  ╚═══╝  ╚══════╝╚══════╝╚══════╝╚══════╝",
    ]

    _info_lines = [
        "VLESS REALITY + xHTTP TLS INSTALLER v4.05",
        "IPv6 DualStack  6 Templates  SHA256 Verify",
        "Balancer: RoundRobin  LeastPing  LeastLoad",
        "Dashboard  FP Rotate  GeoCheck  Multi-User",
    ]

    _ram_lines = [
        f"{_BOLD_RED}⚠  ВНИМАНИЕ: для корректной работы всех функций   {_NC}",
        f"{_BOLD_RED}⚠  рекомендуется ОЗУ VPS от 2 ГБ!                 {_NC}",
        f"{_BOLD_RED}⚠  При меньшем объёме работа скрипта и ПО          {_NC}",
        f"{_BOLD_RED}⚠  НЕ ГАРАНТИРУЕТСЯ.                               {_NC}",
    ]

    _ram_sep = "║  ║" + "─" * _IW + "║  ║"

    rows = (
        [_top, _blank]
        + [_art(a) for a in _art_lines]
        + [_blank, _itop]
        + [_irow(il) for il in _info_lines]
        + [_ram_sep]
        + [_irow_ansi(rl) for rl in _ram_lines]
        + [_ibot, _blank, _bot]
    )
    return "\n" + "\n".join(rows) + "\n"


# Баннер вычисляется при импорте (чистая строковая операция, без I/O)
BANNER = _make_banner()


def print_banner() -> None:
    """Выводит ASCII-баннер установщика."""
    print(BANNER)

