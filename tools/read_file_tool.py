"""ReadFileTool — unified file reading with strict sandbox support.

安全策略 (2026-07-02 优化):
1. 统一使用 core.path_utils.resolve_under() 进行沙盒路径校验
2. 默认分块读取，优先向 LLM 暴露 offset/limit 接口
3. 全量读取需显式声明 full=True，且受大小限制
4. 新增 get_file_info 工具，读取前先获取文件概要
5. 禁止跟随符号链接
"""

from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from core.path_utils import resolve_under


MAX_FULL_READ_SIZE = 100 * 1024  # 100 KB
DEFAULT_CHUNK_LINES = 100


class ReadFileInput(BaseModel):
    file_path: str = Field(
        description="Relative path of the file to read (relative to root directory)"
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="Line offset for chunked reading (0-based)",
    )
    limit: int = Field(
        default=DEFAULT_CHUNK_LINES,
        ge=1,
        le=500,
        description="Maximum lines to return in chunked mode (1-500)",
    )
    full: bool = Field(
        default=False,
        description="Read the entire file. Subject to MAX_FULL_READ_SIZE limit.",
    )


class FileInfoInput(BaseModel):
    file_path: str = Field(
        description="Relative path of the file to inspect (relative to root directory)"
    )


class SandboxedReadFileTool(BaseTool):
    """Generic file reading tool with strict sandbox support."""

    name: str = "read_file"
    description: str = ""
    args_schema: Type[BaseModel] = ReadFileInput
    root_dir: str = ""

    def _run(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = DEFAULT_CHUNK_LINES,
        full: bool = False,
    ) -> str:
        try:
            full_path = resolve_under(self.root_dir, file_path)

            if not full_path.exists():
                return f"❌ File not found: {file_path}"

            if not full_path.is_file():
                return f"❌ Not a file: {file_path}"

            size = full_path.stat().st_size

            if full:
                if size > MAX_FULL_READ_SIZE:
                    return (
                        f"❌ File too large for full read ({size} bytes > "
                        f"{MAX_FULL_READ_SIZE} bytes). Use chunked mode instead."
                    )
                content = full_path.read_text(encoding="utf-8")
                return content

            # Chunked mode by lines
            return self._read_lines(full_path, offset, limit)

        except ValueError as e:
            return f"❌ Access denied: {e}"
        except Exception as e:
            return f"❌ Error reading file: {str(e)}"

    @staticmethod
    def _read_lines(path: Path, offset: int, limit: int) -> str:
        lines: list[str] = []
        with path.open("r", encoding="utf-8") as f:
            # Skip offset lines
            for _ in range(offset):
                if not f.readline():
                    break

            for _ in range(limit):
                line = f.readline()
                if not line:
                    break
                lines.append(line.rstrip("\n").rstrip("\r"))

        if not lines:
            return "(no more lines)"

        header = f"--- Lines {offset}-{offset + len(lines) - 1} of {path.name} ---\n"
        return header + "\n".join(lines)


class SandboxedFileInfoTool(BaseTool):
    """Return structural summary of a file before reading."""

    name: str = "get_file_info"
    description: str = ""
    args_schema: Type[BaseModel] = FileInfoInput
    root_dir: str = ""

    def _run(self, file_path: str) -> str:
        try:
            full_path = resolve_under(self.root_dir, file_path)

            if not full_path.exists():
                return f"❌ File not found: {file_path}"

            if not full_path.is_file():
                return f"❌ Not a file: {file_path}"

            stat = full_path.stat()
            size = stat.st_size
            line_count = self._count_lines(full_path)
            preview_lines = []

            with full_path.open("r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= 3:
                        break
                    preview_lines.append(line.rstrip("\n").rstrip("\r"))

            preview = "\n".join(preview_lines) if preview_lines else "(empty file)"

            return (
                f"File: {file_path}\n"
                f"Absolute: {full_path}\n"
                f"Size: {size} bytes ({size / 1024:.1f} KB)\n"
                f"Lines: {line_count}\n"
                f"Modified: {stat.st_mtime}\n"
                f"Full-read limit: {MAX_FULL_READ_SIZE} bytes\n"
                f"--- First 3 lines preview ---\n"
                f"{preview}"
            )

        except ValueError as e:
            return f"❌ Access denied: {e}"
        except Exception as e:
            return f"❌ Error inspecting file: {str(e)}"

    @staticmethod
    def _count_lines(path: Path) -> int:
        count = 0
        with path.open("r", encoding="utf-8") as f:
            for _ in f:
                count += 1
        return count


def create_read_file_tool(base_dir: Path) -> SandboxedReadFileTool:
    """Create tool for reading project files."""
    tool = SandboxedReadFileTool(root_dir=str(base_dir))
    tool.description = (
        "读取项目内文件。默认分块：file_path, offset=0, limit=100。 "
        "full=True 全量读取（≤100KB）。建议先调用 get_file_info。"
    )
    return tool


def create_read_skill_tool(skills_dir: Path) -> SandboxedReadFileTool:
    """Create tool for reading SKILL.md files and skill sub-files."""
    tool = SandboxedReadFileTool(root_dir=str(skills_dir))
    tool.name = "read_skill_file"
    tool.description = (
        "读取 skills/ 目录下文件。路径相对 skills 文件夹，如 'skill_name/SKILL.md'。 "
        "支持 offset/limit 分块或 full=True 全量。"
    )
    return tool


def create_file_info_tool(base_dir: Path) -> SandboxedFileInfoTool:
    """Create tool for inspecting project file metadata."""
    tool = SandboxedFileInfoTool(root_dir=str(base_dir))
    tool.description = (
        "返回项目内文件的大小、行数、修改时间和前3行预览。 "
        "建议先于 read_file 调用，决定分块或全量读取。"
    )
    return tool
