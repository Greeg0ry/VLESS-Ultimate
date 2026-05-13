"""
cli/progress.py — Прогресс-бар и индикаторы выполнения.

Используй Progress для отображения хода длительных операций (установка пакетов,
скачивание Xray, настройка Nginx и т.д.).

Пример использования:
    from installer.cli.progress import PROGRESS
    PROGRESS.init(total=10, label="Установка Xray")
    PROGRESS.update(5, label="Скачивание")
    PROGRESS.update(5, label="Настройка")
"""

from __future__ import annotations


# =============================================================================
#  ANSI-КОДЫ (локальные, без зависимостей от других модулей)
# =============================================================================
_GREEN = '\033[0;32m'
_CYAN  = '\033[0;36m'
_BLUE  = '\033[0;34m'
_WHITE = '\033[1;37m'
_DIM   = '\033[2m'
_NC    = '\033[0m'


class Progress:
    """
    Простой ASCII прогресс-бар с градиентом цвета.

    Методы:
        init(total, label)  — инициализирует бар
        update(n, label)    — сдвигает прогресс на n единиц
        done()              — завершает строку (переводит строку)
    """

    def __init__(self) -> None:
        self.total:   int = 100
        self.current: int = 0
        self.label:   str = ""

    def init(self, total: int = 100, label: str = "Установка") -> None:
        """Начинает новый прогресс-бар."""
        self.total   = max(total, 1)
        self.current = 0
        self.label   = label
        print()

    def update(self, increment: int = 1, label: str = "") -> None:
        """
        Сдвигает прогресс на `increment` единиц и перерисовывает бар.
        Если передан label — обновляет подпись.
        """
        if label:
            self.label = label
        self.current = min(self.current + increment, self.total)
        percent = self.current * 100 // self.total
        width   = 40
        filled  = percent * width // 100
        empty   = width - filled

        # Цвет бара зависит от прогресса (градиент)
        if percent >= 100:
            col = _WHITE
        elif percent >= 75:
            col = _GREEN
        elif percent >= 40:
            col = _CYAN
        else:
            col = _BLUE

        bar_fill  = f"{col}{'▓' * filled}{_NC}"
        bar_empty = f"{_DIM}{'░' * empty}{_NC}"

        print(
            f"\r{_CYAN}[{self.label:<15}]{_NC} "
            f"{bar_fill}{bar_empty} {col}{percent:3d}%{_NC}\033[K",
            end="", flush=True,
        )
        if percent == 100:
            print()

    def done(self) -> None:
        """Принудительно завершает бар на 100%."""
        self.update(self.total - self.current)


# Глобальный синглтон для удобного использования без создания экземпляра
PROGRESS = Progress()

