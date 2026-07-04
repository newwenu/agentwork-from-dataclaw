"""delete_file_tool 测试 — 验证 .trash/ 回收机制和 .trash/ 目录保护。"""

from pathlib import Path

import pytest

from tools.delete_file_tool import create_delete_file_tool


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "output").mkdir()
    (root / "output" / "chart.png").write_bytes(b"fake-png")
    (root / "output" / "report.md").write_text("# Report", encoding="utf-8")
    (root / "notes.txt").write_text("hello", encoding="utf-8")
    return root


@pytest.fixture
def delete_tool(workspace: Path):
    return create_delete_file_tool(workspace)


class TestDeleteFile:
    def test_move_to_trash(self, workspace: Path, delete_tool):
        result = delete_tool._run("notes.txt")
        assert "✅" in result
        assert ".trash/" in result
        assert not (workspace / "notes.txt").exists()
        trash_files = list((workspace / ".trash").glob("*"))
        assert len(trash_files) == 1
        assert "notes" in trash_files[0].name

    def test_nested_file(self, workspace: Path, delete_tool):
        result = delete_tool._run("output/chart.png")
        assert "✅" in result
        assert not (workspace / "output" / "chart.png").exists()
        trash_files = list((workspace / ".trash").glob("*"))
        assert len(trash_files) == 1

    def test_nonexistent_file(self, workspace: Path, delete_tool):
        result = delete_tool._run("no_such_file.txt")
        assert "❌" in result

    def test_directory_rejected(self, workspace: Path, delete_tool):
        result = delete_tool._run("output")
        assert "❌" in result

    def test_cannot_delete_from_trash(self, workspace: Path, delete_tool):
        delete_tool._run("notes.txt")
        trash_files = list((workspace / ".trash").glob("*"))
        trash_relative = f".trash/{trash_files[0].name}"
        result = delete_tool._run(trash_relative)
        assert "❌" in result

    def test_name_conflict_resolution(self, workspace: Path, delete_tool):
        (workspace / "a.txt").write_text("first", encoding="utf-8")
        delete_tool._run("a.txt")
        (workspace / "a.txt").write_text("second", encoding="utf-8")
        delete_tool._run("a.txt")
        trash_files = list((workspace / ".trash").glob("*.txt"))
        assert len(trash_files) == 2

    def test_trash_dir_auto_created(self, workspace: Path, delete_tool):
        assert not (workspace / ".trash").exists()
        delete_tool._run("notes.txt")
        assert (workspace / ".trash").is_dir()


class TestTrashProtection:
    def test_read_file_cannot_access_trash(self, workspace: Path, delete_tool):
        from tools.read_file_tool import create_read_file_tool

        delete_tool._run("notes.txt")
        read_tool = create_read_file_tool(workspace)
        trash_files = list((workspace / ".trash").glob("*"))
        trash_relative = f".trash/{trash_files[0].name}"
        result = read_tool._run(trash_relative)
        assert "❌" in result or "Access denied" in result

    def test_terminal_cannot_access_trash(self, workspace: Path, delete_tool):
        from tools.terminal_tool import create_terminal_tool

        delete_tool._run("notes.txt")
        terminal = create_terminal_tool(workspace)
        trash_files = list((workspace / ".trash").glob("*"))
        trash_relative = f".trash/{trash_files[0].name}"
        result = terminal._check_paths(f"cat {trash_relative}")
        assert not result[0]

    def test_python_repl_blocks_trash_access(self):
        from tools.python_repl_tool import GuardedPythonREPLTool

        repl = GuardedPythonREPLTool()
        safe, reason = repl._check_code("pd.read_csv('.trash/notes.txt')")
        assert not safe
        assert ".trash" in reason