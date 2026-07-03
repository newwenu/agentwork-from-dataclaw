"""tui.py — 兼容入口，保留原有 `from tui import run_tui` 可用。

实际实现已迁移到 ui/ 包：
  - ui/app.py      DataClawApp + run_tui
  - ui/capture.py  BackgroundCapture
  - ui/commands.py COMMANDS 注册表 + CommandHandler
  - ui/completer.py CommandCompleter
  - ui/styles.tcss TUI 样式
"""

from ui.app import DataClawApp, run_tui
from ui.capture import BackgroundCapture
from ui.commands import COMMANDS, CommandHandler
from ui.completer import CommandCompleter

__all__ = [
    "DataClawApp",
    "run_tui",
    "BackgroundCapture",
    "COMMANDS",
    "CommandHandler",
    "CommandCompleter",
]
