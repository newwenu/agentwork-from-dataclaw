"""path_utils 安全测试 — 验证沙盒路径校验的完整性。

测试覆盖:
1. 路径遍历攻击拦截 (../)
2. Null 字节注入拦截
3. 符号链接拦截
4. 绝对路径逃逸拦截
5. 正常路径放行
"""

import os
from pathlib import Path

import pytest

from core.path_utils import resolve_under


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    root = tmp_path / "sandbox"
    root.mkdir()
    (root / "data").mkdir()
    (root / "data" / "file.csv").write_text("hello", encoding="utf-8")
    (root / "readme.md").write_text("readme", encoding="utf-8")
    return root


class TestNullByteInjection:
    def test_null_byte_in_path(self, sandbox: Path):
        with pytest.raises(ValueError, match="null"):
            resolve_under(sandbox, "file\x00.csv")

    def test_null_byte_at_end(self, sandbox: Path):
        with pytest.raises(ValueError, match="null"):
            resolve_under(sandbox, "data\x00")


class TestPathTraversal:
    def test_double_dot_leading(self, sandbox: Path):
        with pytest.raises(ValueError, match="escapes"):
            resolve_under(sandbox, "../etc/passwd")

    def test_double_dot_intermediate(self, sandbox: Path):
        with pytest.raises(ValueError, match="escapes"):
            resolve_under(sandbox, "data/../../etc/passwd")

    def test_double_dot_only(self, sandbox: Path):
        with pytest.raises(ValueError, match="escapes"):
            resolve_under(sandbox, "..")

    def test_double_dot_with_prefix(self, sandbox: Path):
        with pytest.raises(ValueError, match="escapes"):
            resolve_under(sandbox, "data/../..")

    def test_mixed_traversal(self, sandbox: Path):
        with pytest.raises(ValueError, match="escapes"):
            resolve_under(sandbox, "data/./../../etc/shadow")


class TestAbsoluteEscape:
    def test_absolute_path_outside_root(self, sandbox: Path):
        with pytest.raises(ValueError, match="escapes"):
            resolve_under(sandbox, "/etc/passwd")

    def test_windows_absolute_path_outside(self, sandbox: Path):
        if os.name == "nt":
            with pytest.raises(ValueError, match="escapes"):
                resolve_under(sandbox, "C:\\Windows\\System32")


class TestSymlinkRejection:
    def test_symlink_target_outside(self, sandbox: Path, tmp_path: Path):
        outside = tmp_path / "outside"
        outside.mkdir()
        link = sandbox / "evil_link"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("Symlink creation not supported")

        with pytest.raises(ValueError, match="[Ss]ymlink"):
            resolve_under(sandbox, "evil_link")


class TestValidPaths:
    def test_simple_relative_path(self, sandbox: Path):
        result = resolve_under(sandbox, "readme.md")
        assert result == sandbox / "readme.md"

    def test_nested_relative_path(self, sandbox: Path):
        result = resolve_under(sandbox, "data/file.csv")
        assert result == sandbox / "data" / "file.csv"

    def test_dot_slash_prefix(self, sandbox: Path):
        result = resolve_under(sandbox, "./readme.md")
        assert result == sandbox / "readme.md"

    def test_absolute_path_inside_root(self, sandbox: Path):
        abs_path = str(sandbox / "readme.md")
        result = resolve_under(sandbox, abs_path)
        assert result == sandbox / "readme.md"

    def test_must_exist_with_existing_file(self, sandbox: Path):
        result = resolve_under(sandbox, "readme.md", must_exist=True)
        assert result.exists()

    def test_must_exist_with_missing_file(self, sandbox: Path):
        with pytest.raises(ValueError, match="not found"):
            resolve_under(sandbox, "nonexistent.txt", must_exist=True)


class TestBackslashNormalization:
    def test_backslash_normalized_on_windows(self, sandbox: Path):
        result = resolve_under(sandbox, "data\\file.csv")
        assert result == sandbox / "data" / "file.csv"


class TestTrashProtection:
    def test_trash_path_rejected(self, sandbox: Path):
        (sandbox / ".trash").mkdir()
        (sandbox / ".trash" / "old_file.txt").write_text("trashed", encoding="utf-8")
        with pytest.raises(ValueError, match=r"\.trash"):
            resolve_under(sandbox, ".trash/old_file.txt")

    def test_trash_subdirectory_rejected(self, sandbox: Path):
        (sandbox / ".trash").mkdir()
        (sandbox / ".trash" / "sub").mkdir()
        (sandbox / ".trash" / "sub" / "deep.txt").write_text("deep", encoding="utf-8")
        with pytest.raises(ValueError, match=r"\.trash"):
            resolve_under(sandbox, ".trash/sub/deep.txt")

    def test_trash_path_with_backslash_rejected(self, sandbox: Path):
        (sandbox / ".trash").mkdir()
        (sandbox / ".trash" / "file.txt").write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match=r"\.trash"):
            resolve_under(sandbox, ".trash\\file.txt")

    def test_non_trash_path_still_works(self, sandbox: Path):
        result = resolve_under(sandbox, "readme.md")
        assert result == sandbox / "readme.md"