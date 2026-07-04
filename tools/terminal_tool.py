"""SafeTerminalTool — sandboxed shell execution with whitelist, blacklist, path validation and cancel handle.

安全策略:
1. 黑名单快速驳回: 明显危险命令直接拦截（借鉴 DataClaw_backup 版本）
2. 命令白名单: 只允许预定义的安全命令，并按 Windows/Unix 平台区分
3. shell=False: 禁止管道和 shell 元字符，避免命令注入
4. 工作目录锁定: 强制在 root_dir 内执行
5. 路径沙盒校验: 参数中的路径必须通过 core.path_utils.resolve_under 校验
6. 超时监控: 30 秒后返回超时提示，进程保留在后台，用户可调用 cancel() 终止
7. 可取消: 持有 subprocess.Popen 句柄，支持用户手动终止
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, PrivateAttr

from core.path_utils import resolve_under


# ═══════════════════════════════════════════════════════════════════
# 黑名单层：快速驳回明显危险命令
# ═══════════════════════════════════════════════════════════════════

# 别名说明:
# 本工具使用 shell=False 直接创建进程，CMD/PowerShell 的 alias / doskey 不会生效。
# 这里把 Linux 风格的常用命令名也加入 Windows 白名单，这样当用户安装了
# Git Bash、Cygwin、MSYS2 等环境时，ls/cat/grep 等命令可直接调用。
#
# 注意: 删除命令（rm/del/rd/rmdir）已从白名单中移除，以下黑名单模式保留作为纵深防御。
BLACKLISTED_PATTERNS = [
    # 文件系统破坏（纵深防御：rm 已从白名单移除，以下模式防止绕过）
    r"rm\s+-rf\b",            # rm -rf 任意目标
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+/\*",
    r"rm\s+-rf\s+\*",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r":\s*\(\s*\)\s*{\s*:\s*\|:\s*&\s*}\s*;\s*:",  # fork bomb
    r"chmod\s+-R\s+777\s+/",
    # 系统控制
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    # 磁盘/分区操作
    r"\bformat\s+c\s*:",
    r"\bdel\s+/f\s+/s\s+/q",
    r"\brd\s+/s\s+/q",
    r"\bdiskpart\b",
    r"\bfdisk\b",
    r"\bmkfs\b",
]

# ═══════════════════════════════════════════════════════════════════
# 白名单层：按平台拆分允许的安全命令
# ═══════════════════════════════════════════════════════════════════

if sys.platform == "win32":
    ALLOWED_COMMANDS = frozenset({
        # Windows 原生文件查看
        "dir", "type", "findstr", "where",
        # Linux 风格别名（需系统已安装对应可执行文件，如 Git Bash / MSYS2 / Cygwin）
        "ls", "cat", "head", "tail", "wc", "find", "grep", "pwd",
        "file",
        # 文本处理
        "echo", "sort", "tree", "uniq", "awk", "sed", "cut", "tr",
        # 系统信息
        "tasklist", "systeminfo", "ipconfig", "ping", "tracert", "netstat",
        "df", "du", "ps", "top", "htop", "free", "uptime",
        "whoami", "date", "uname", "which", "whereis",
        # 文件操作（删除命令已移除：rm/del/rd/rmdir，防止 Agent 误删文件）
        "copy", "move", "md", "mkdir", "ren",
        "cp", "mv", "touch", "chmod", "chown",
        # 开发环境
        "python", "python3", "pip", "pip3",
        # 版本控制
        "git", "git.exe",
        # 压缩
        "tar", "zip", "unzip", "gzip", "gunzip",
    })
else:
    ALLOWED_COMMANDS = frozenset({
        # 文件查看
        "ls", "cat", "head", "tail", "wc", "find", "grep", "pwd",
        # 文本处理
        "echo", "sort", "uniq", "awk", "sed", "cut", "tr", "file",
        # 开发环境
        "python", "python3", "pip", "pip3", "node", "npm",
        # 版本控制
        "git",
        # 系统信息
        "df", "du", "ps", "top", "htop", "free", "uptime",
        "whoami", "date", "uname", "which", "whereis",
        # 压缩
        "tar", "zip", "unzip", "gzip", "gunzip",
        # 文件操作（删除命令已移除：rm/rmdir，防止 Agent 误删文件）
        "mkdir", "touch", "cp", "mv",
        "chmod", "chown",
    })

# ═══════════════════════════════════════════════════════════════════
# 路径校验层：命令 -> 需要校验为路径的参数位置（1-based）
# ═══════════════════════════════════════════════════════════════════

COMMAND_PATH_ARGS: dict[str, list[int]] = {
    # 文件查看
    "cat": [1],
    "type": [1],
    "head": [1],
    "tail": [1],
    "wc": [1],
    "file": [1],
    # 文本过滤
    "grep": [2, 3],
    "findstr": [2, 3],
    "sort": [1],
    "uniq": [1],
    # 文件操作（删除命令已移除：rm/del/rd/rmdir）
    "cp": [1, 2],
    "copy": [1, 2],
    "mv": [1, 2],
    "move": [1, 2],
    "ren": [1, 2],
    "mkdir": [1],
    "md": [1],
    "touch": [1],
    # 目录查看
    "ls": [1],
    "dir": [1],
    "find": [1],
    "tree": [1],
    # 权限
    "chmod": [2],
    "chown": [2],
}

# 禁止的 shell 元字符（二次防御，按平台区分）
# Windows 下反斜杠是合法路径分隔符，不能列为危险字符
if sys.platform == "win32":
    DANGEROUS_CHARS = set(";|&`$(){}<>")
else:
    DANGEROUS_CHARS = set(";|&\\`$(){}<>")


def _split_windows_command(command: str) -> list[str]:
    """Windows 命令行参数拆分。

    规则:
    - 双引号内作为一个参数，双引号本身被去掉
    - 反斜杠保持原样（Windows 路径分隔符）
    - 单引号不特殊处理（CMD/PowerShell 中单引号不是引号分隔符）
    """
    parts: list[str] = []
    current: list[str] = []
    in_quote = False

    for ch in command.strip():
        if ch == '"':
            in_quote = not in_quote
            continue
        if ch.isspace() and not in_quote:
            if current:
                parts.append("".join(current))
                current = []
            continue
        current.append(ch)

    if current:
        parts.append("".join(current))
    return parts


def _split_command(command: str) -> list[str]:
    """按平台正确拆分命令字符串。

    Windows 下使用自定义拆分器，避免反斜杠被 shlex 当作转义符吃掉，
    同时正确处理 python -c "..." 这类带引号的参数。
    """
    if sys.platform == "win32":
        return _split_windows_command(command)
    return shlex.split(command.strip())


class TerminalInput(BaseModel):
    command: str = Field(
        description="The shell command to execute (single command only, no pipes or shell operators)"
    )


class SafeTerminalTool(BaseTool):
    name: str = "terminal"
    description: str = (
        "执行白名单内的 shell 命令。禁止管道和 shell 元字符，禁止删除命令(rm/del/rd/rmdir)，"
        "30秒超时后可后台运行，参数路径受沙盒限制。用于 dir/type/findstr/ls/cat/grep/ps/pip/git 等。"
    )
    args_schema: Type[BaseModel] = TerminalInput
    root_dir: str = ""

    # 当前正在执行的子进程句柄（Pydantic 私有属性，不参与序列化）
    _current_process: subprocess.Popen | None = PrivateAttr(default=None)

    # ── 黑名单快速驳回 ──
    def _check_blacklist(self, command: str) -> tuple[bool, str]:
        cmd_lower = command.lower().strip()
        for pattern in BLACKLISTED_PATTERNS:
            if re.search(pattern, cmd_lower):
                return False, f"Dangerous command blocked by blacklist: {command}"
        return True, ""

    # ── shell 元字符检查 ──
    def _check_meta_chars(self, command: str) -> tuple[bool, str]:
        """禁止裸露的 shell 元字符（不在引号内）。

        被引号包围的参数内部允许出现 ; | & 等字符，例如:
            python -c "import time; time.sleep(1)"
        """
        in_single = False
        in_double = False
        escaped = False

        for ch in command:
            if escaped:
                escaped = False
                continue
            if ch == "\\" and sys.platform != "win32":
                # Windows 下反斜杠是路径分隔符，不是转义符
                escaped = True
                continue
            # Windows 命令行只有双引号是参数分隔符
            if sys.platform != "win32" and ch == "'" and not in_double:
                in_single = not in_single
                continue
            if ch == '"' and not in_single:
                in_double = not in_double
                continue
            if not in_single and not in_double and ch in DANGEROUS_CHARS:
                return False, f"Shell meta-character '{ch}' is not allowed outside quotes"

        return True, ""

    # ── 命令白名单检查 ──
    def _check_whitelist(self, command: str) -> tuple[bool, str]:
        try:
            parts = _split_command(command)
        except ValueError as e:
            return False, f"Invalid command syntax: {e}"

        if not parts:
            return False, "Empty command"

        base_cmd = os.path.basename(parts[0]).lower()

        if base_cmd not in ALLOWED_COMMANDS:
            allowed_sample = ", ".join(sorted(ALLOWED_COMMANDS)[:20])
            return False, (
                f"Command '{base_cmd}' is not in the allowed list. "
                f"Allowed examples: {allowed_sample}, ..."
            )

        # python 命令额外限制：-c 和交互式解释器可完全绕过安全策略
        if base_cmd in ("python", "python3", "python.exe"):
            if "-c" in parts:
                return False, (
                    "python -c is not allowed in terminal; "
                    "use the python_repl tool for code execution"
                )
            if len(parts) == 1:
                return False, (
                    "Interactive python is not allowed in terminal; "
                    "use the python_repl tool for code execution"
                )

        return True, ""

    # 常见文件扩展名白名单，用于启发式识别简单文件名参数
    _PATH_EXTENSIONS = frozenset({
        "txt", "csv", "py", "md", "json", "log", "yml", "yaml", "xml", "html",
        "png", "jpg", "jpeg", "gif", "pdf", "zip", "tar", "gz", "xlsx", "xls",
    })

    # ── 路径参数识别 ──
    def _is_path_like(self, arg: str) -> bool:
        """判断参数是否像文件路径。

        注意: 不会把包含空格的代码片段（如 python -c 的参数）误判为路径。
        """
        if not arg or arg.startswith("-"):
            return False
        # Windows 绝对路径: C:\xxx 或 \\server\share
        if re.match(r"^[A-Za-z]:[/\\]", arg):
            return True
        # UNC 路径
        if arg.startswith("\\\\"):
            return True
        # Unix 绝对路径
        if arg.startswith("/"):
            return True
        # 包含路径分隔符
        if "/" in arg or "\\" in arg:
            return True
        # 简单文件名 + 已知扩展名（无空格，避免把代码片段当路径）
        if " " not in arg and "." in arg:
            ext = arg.rsplit(".", 1)[-1].lower()
            if ext in self._PATH_EXTENSIONS:
                return True
        return False

    # ── 路径沙盒校验 ──
    def _check_paths(self, command: str) -> tuple[bool, str]:
        try:
            parts = _split_command(command)
        except ValueError:
            return True, ""  # 语法错误已在白名单检查中处理

        if not parts:
            return True, ""

        base_cmd = os.path.basename(parts[0]).lower()
        path_positions = COMMAND_PATH_ARGS.get(base_cmd, [])

        for idx, arg in enumerate(parts[1:], start=1):
            if not arg:
                continue
            # 跳过选项参数
            if arg.startswith("-"):
                continue

            is_path = idx in path_positions or self._is_path_like(arg)
            if not is_path:
                continue

            try:
                resolve_under(self.root_dir, arg)
            except ValueError as e:
                return False, f"Path argument '{arg}' not allowed: {e}"

        return True, ""

    # ── 完整安全校验 ──
    def _is_safe(self, command: str) -> tuple[bool, str]:
        # 1. 黑名单快速驳回
        safe, reason = self._check_blacklist(command)
        if not safe:
            return False, reason

        # 2. 禁止 shell 元字符
        safe, reason = self._check_meta_chars(command)
        if not safe:
            return False, reason

        # 3. 白名单检查
        safe, reason = self._check_whitelist(command)
        if not safe:
            return False, reason

        # 4. 路径沙盒校验
        safe, reason = self._check_paths(command)
        if not safe:
            return False, reason

        return True, ""

    def _run(self, command: str) -> str:
        safe, reason = self._is_safe(command)
        if not safe:
            return f"❌ Command blocked for safety: {reason}"

        # 如果前一条命令仍在后台运行，先尝试清理句柄（不强制 kill）
        old_process = self._current_process
        if old_process is not None and old_process.poll() is not None:
            self._current_process = None

        cmd_parts = _split_command(command)
        try:
            process = subprocess.Popen(
                cmd_parts,
                shell=False,
                cwd=self.root_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except FileNotFoundError:
            return f"❌ Command not found: {cmd_parts[0]}"
        except Exception as e:
            return f"❌ Error starting command: {str(e)}"

        self._current_process = process
        try:
            stdout, stderr = process.communicate(timeout=30)
            output = stdout
            if stderr:
                output += f"\n[stderr]: {stderr}"
            if not output.strip():
                output = "(command completed with no output)"
            # 截断超长输出
            if len(output) > 5000:
                output = output[:5000] + "\n...[truncated]"
            return output
        except subprocess.TimeoutExpired:
            # 文档设计：超时不自动终止，保留后台运行并提示用户
            return (
                f"⏱️ 命令已运行超过 30 秒，进程仍在后台运行。\n"
                f"   PID: {process.pid}\n"
                f"   输入 /cancel 或按 Esc 可终止该进程。"
            )
        except Exception as e:
            return f"❌ Error: {str(e)}"
        finally:
            # 进程已结束则清理句柄；仍在运行则保留，供 cancel() 使用
            if self._current_process is process and process.poll() is not None:
                self._current_process = None

    def cancel(self) -> str:
        """用户手动取消当前正在执行的终端命令。"""
        process = self._current_process
        if process is None or process.poll() is not None:
            return ""

        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        finally:
            self._current_process = None
        return "✅ 已终止终端命令"


def create_terminal_tool(base_dir: Path) -> SafeTerminalTool:
    return SafeTerminalTool(root_dir=str(base_dir))