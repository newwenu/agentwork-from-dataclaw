"""Python REPL Tool — wraps LangChain experimental PythonREPLTool with safety guardrails and cancel handle.

安全策略 (2026-06-25 修复):
1. 增加基本代码黑名单检查 (禁止 os.system, subprocess, open 文件写入等明显危险操作)
2. 明确标注此工具为 HIGH RISK，仅在受信任环境中使用
3. 限制代码长度，防止资源耗尽
4. 超时监控: 30 秒后返回超时提示，后台继续运行，用户可调用 cancel() 取消

注意: 由于 Python 的动态特性，代码黑名单无法做到 100% 安全。
如需完全隔离，请将此工具移除，或在 Docker 容器中运行整个 Agent。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from langchain_core.tools import BaseTool
from langchain_experimental.tools import PythonREPLTool
from pydantic import PrivateAttr


# 代码级黑名单: 阻止明显危险的导入和调用
# 这是"尽力而为"的防御，不能替代真正的沙盒环境
CODE_BLACKLIST_PATTERNS = [
    # 危险导入
    r"\bimport\s+os\b",
    r"\bimport\s+subprocess\b",
    r"\bimport\s+sys\b",
    r"\bimport\s+socket\b",
    r"\bimport\s+requests\b",
    r"\bimport\s+urllib\b",
    r"\bfrom\s+os\b",
    r"\bfrom\s+subprocess\b",
    r"\bfrom\s+sys\b",
    r"\bfrom\s+socket\b",
    r"\b__import__\b",
    # 危险函数调用
    r"\beval\s*\(",
    r"\bexec\s*\(",
    r"\bcompile\s*\(",
    r"\bopen\s*\(",
    r"\bos\.system\b",
    r"\bos\.remove\b",
    r"\bos\.unlink\b",
    r"\bos\.rmdir\b",
    r"\bos\.mkdir\b",
    r"\bsubprocess\.\w+",
    r"\bsocket\.\w+",
    # .trash/ 目录保护
    r"\.trash[/\\'\"]",
]

CODE_BLACKLIST_REGEX = [re.compile(p, re.IGNORECASE) for p in CODE_BLACKLIST_PATTERNS]

MAX_CODE_LENGTH = 8000  # 限制代码长度


class GuardedPythonREPLTool(BaseTool):
    """Python REPL with basic guardrails and cancel support."""

    name: str = "python_repl"
    description: str = (
        "执行 Python 代码，用于数学计算、数据处理和字符串操作。 "
        "禁止 os/subprocess/sys/socket/urllib、eval/exec/open。代码长度 ≤8000。"
    )

    # 线程池与当前执行句柄（Pydantic 私有属性）
    _executor: ThreadPoolExecutor = PrivateAttr(default_factory=lambda: ThreadPoolExecutor(max_workers=1))
    _current_future: Any = PrivateAttr(default=None)
    _repl: PythonREPLTool = PrivateAttr(default_factory=PythonREPLTool)

    def _check_code(self, code: str) -> tuple[bool, str]:
        """基本代码安全检查。"""
        if len(code) > MAX_CODE_LENGTH:
            return False, f"Code exceeds maximum length of {MAX_CODE_LENGTH} characters"

        for pattern in CODE_BLACKLIST_REGEX:
            match = pattern.search(code)
            if match:
                return False, f"Forbidden pattern detected: '{match.group()}'"

        return True, ""

    def _run(self, query: str) -> str:
        safe, reason = self._check_code(query)
        if not safe:
            return f"❌ Code execution blocked for safety: {reason}"

        # 在线程池中执行，避免阻塞主事件循环，并保留取消句柄
        self._current_future = self._executor.submit(self._repl.run, query)
        try:
            return self._current_future.result(timeout=30)
        except TimeoutError:
            # 文档设计：超时不强制中断线程，仅提示用户可 cancel()
            return (
                "⏱️ Python 代码已运行超过 30 秒，任务仍在后台运行。\n"
                "   输入 /cancel 或按 Esc 可尝试终止该任务。"
            )
        except Exception as e:
            return f"❌ Error executing code: {e}"
        finally:
            if self._current_future and self._current_future.done():
                self._current_future = None

    async def _arun(self, query: str) -> str:
        # 异步入口复用同步实现（LangChain 工具通常以 _run 为主）
        return self._run(query)

    def cancel(self) -> str:
        """用户手动取消当前正在执行的 Python 任务。

        注意: Python 线程无法被强制中断，cancel() 只能取消尚未开始的任务。
        对于已经陷入死循环的代码，此操作可能无法立即生效。
        """
        future = self._current_future
        if future is None:
            return ""

        if future.done():
            self._current_future = None
            return ""

        cancelled = future.cancel()
        if cancelled:
            self._current_future = None
            return "✅ 已取消待执行的 Python 任务"
        return "⚠️ Python 任务已在运行，无法强制中断（线程限制）"


def create_python_repl_tool() -> BaseTool:
    return GuardedPythonREPLTool()
