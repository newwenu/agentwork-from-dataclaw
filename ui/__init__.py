"""DataClaw TUI 组件包。"""

from __future__ import annotations

from collections.abc import Callable

import rich.cells

# ---------------------------------------------------------------------------
# 修正 rich.cells.cell_len 对 U+FE0F emoji 的宽度低估。
#
# wcwidth 会把 '❤️' (U+2764 + U+FE0F)、'☁️' (U+2601 + U+FE0F) 等 emoji
# 算成 1 格，但终端实际按 2 格渲染，导致 Textual 边框/排版错位。
# 这是一个上游 wcwidth 的临时 workaround，等 rich/wcwidth 修复后可移除。
# 相关上游问题：
#   https://sourceware.org/bugzilla/show_bug.cgi?id=32322
# ---------------------------------------------------------------------------
_orig_cell_len: Callable[[str], int] = rich.cells.cell_len


def _fixed_cell_len(
    text: str, _cell_len: Callable[[str], int] = _orig_cell_len
) -> int:
    """在原始 cell_len 基础上，对带 U+FE0F 的 emoji 补回 1 格宽度。"""
    if "\ufe0f" not in text:
        return _cell_len(text)

    width = _cell_len(text)
    extra = 0
    prev_width = 0
    for ch in text:
        if ch == "\ufe0f":
            # 基础符号被算成 1 格，但加上 VS16 后终端实际占 2 格，补 1 格
            extra += 1
            prev_width = 2
        else:
            prev_width = _cell_len(ch)
    return width + extra


rich.cells.cell_len = _fixed_cell_len
# ---------------------------------------------------------------------------

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
