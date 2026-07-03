"""后台任务输出捕获器。"""

import sys
from collections import deque


class BackgroundCapture:
    """捕获后台任务的 print 输出，避免和对话混在一起。"""

    def __init__(self, echo: bool = False) -> None:
        self._real_stdout = sys.__stdout__
        self.lines: deque[str] = deque(maxlen=200)
        self.echo = echo  # 是否同时输出到控制台

    def write(self, text: str) -> None:
        if text.strip():
            self.lines.append(text.rstrip())
        if self.echo:
            self._real_stdout.write(text)
            self._real_stdout.flush()

    def flush(self) -> None:
        if self.echo:
            self._real_stdout.flush()

    def drain(self) -> list[str]:
        lines = list(self.lines)
        self.lines.clear()
        return lines
