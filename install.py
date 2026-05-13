#!/usr/bin/env python3
"""
install.py — Точка входа VLESS Ultimate Installer.

Этот файл является тонким wrapper'ом, который делегирует запуск
модульному пакету installer/main.py.

Совместимость:
    python3 install.py              — запускает установщик
    python3 -m installer.main       — альтернативный запуск
"""

import sys
import os

# Добавляем корень проекта в sys.path для импорта пакета installer
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from installer.main import handle_cli_args, run

if __name__ == "__main__":
    # Сначала проверяем аргументы командной строки (cron-задачи)
    if handle_cli_args():
        sys.exit(0)
    # Основной запуск установщика
    run()

