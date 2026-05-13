"""
installer.core — Ядро установщика.

Никаких системных вызовов при импорте.
Все операции выполняются явно из main-флоу.

Быстрый доступ к часто используемым символам:
    from installer.core import log, run, State
"""
from installer.core.logging import info, success, warn, die, log_to_file
from installer.core.shell import run, run_capture, command_exists
from installer.core.state import InstallerState as State

__all__ = ["info", "success", "warn", "die", "log_to_file", "run", "run_capture",
           "command_exists", "State"]

