"""DeleteFileTool — move files to .trash/ directory instead of permanent deletion.

安全策略:
1. 源文件路径必须通过沙盒校验（resolve_under），且不能在 .trash/ 内
2. 目标位置为工作目录下的 .trash/ 目录，使用时间戳避免文件名冲突
3. 只能删除单个文件，不能删除目录
4. .trash/ 目录受 resolve_under 保护，其他工具无法读取/修改/运行其中的内容
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from core.path_utils import resolve_under


class DeleteFileInput(BaseModel):
    file_path: str = Field(
        description="Relative path of the file to delete (relative to root directory)"
    )


class DeleteFileTool(BaseTool):
    """Move a file into .trash/ directory (not permanent deletion)."""

    name: str = "delete_file"
    description: str = "将文件移入 .trash/ 目录（非永久删除）。仅支持单个文件。"
    args_schema: Type[BaseModel] = DeleteFileInput
    root_dir: str = ""

    def _run(self, file_path: str) -> str:
        try:
            root = Path(self.root_dir).resolve()

            # resolve_under 会拒绝 .trash/ 内的路径，确保不能删除已回收的文件
            full_path = resolve_under(root, file_path, must_exist=True)

            if not full_path.is_file():
                return f"❌ Not a file: {file_path} (directories are not supported)"

            # 准备 .trash/ 目录
            trash_dir = root / ".trash"
            trash_dir.mkdir(exist_ok=True)

            # 使用时间戳生成唯一文件名，避免冲突
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            stem = full_path.stem
            suffix = full_path.suffix
            dest_name = f"{timestamp}_{stem}{suffix}"
            dest_path = trash_dir / dest_name

            # 处理极罕见的同名冲突
            counter = 1
            while dest_path.exists():
                dest_name = f"{timestamp}_{stem}_{counter}{suffix}"
                dest_path = trash_dir / dest_name
                counter += 1

            # 移动文件
            shutil.move(str(full_path), str(dest_path))

            return f"✅ File moved to .trash/: {file_path} → .trash/{dest_name}（如需恢复，请提示用户手动从 .trash/ 目录取回）"

        except ValueError as e:
            return f"❌ Access denied: {e}"
        except Exception as e:
            return f"❌ Error deleting file: {str(e)}"


def create_delete_file_tool(base_dir: Path) -> DeleteFileTool:
    """Create a delete_file tool instance."""
    return DeleteFileTool(root_dir=str(base_dir))