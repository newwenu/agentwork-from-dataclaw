"""后台任务输出捕获器。"""

import sys
import threading
from collections import deque


class BackgroundCapture:
    """捕获后台任务的 print 输出，避免和对话混在一起。

    使用 threading.Lock 保护 drain() 的原子性，防止后台线程的
    write() 在 list() 和 clear() 之间插入导致行丢失。
    """

    def __init__(self, echo: bool = False) -> None:
        self._real_stdout = sys.__stdout__
        self._lines: deque[str] = deque(maxlen=200)
        self._lock = threading.Lock()
        self.echo = echo

    def write(self, text: str) -> None:
        if text.strip():
            with self._lock:
                self._lines.append(text.rstrip())
        if self.echo:
            self._real_stdout.write(text)
            self._real_stdout.flush()

    def flush(self) -> None:
        if self.echo:
            self._real_stdout.flush()

    def drain(self) -> list[str]:
        with self._lock:
            lines = list(self._lines)
            self._lines.clear()
        return lines