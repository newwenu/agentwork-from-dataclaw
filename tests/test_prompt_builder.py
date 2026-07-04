"""Prompt Builder 测试 — 验证 system prompt 的分层组装逻辑。"""

import pytest
from pathlib import Path

from core.prompt_builder import (
    _strip_frontmatter,
    _load_identity,
    _load_soul,
    _load_user_memory,
    _load_long_term_memory,
    build_system_prompt,
)


class TestStripFrontmatter:
    def test_no_frontmatter(self):
        assert _strip_frontmatter("hello world") == "hello world"

    def test_yaml_frontmatter_removed(self):
        raw = "---\ntitle: test\n---\nactual content"
        assert _strip_frontmatter(raw) == "actual content"

    def test_unclosed_frontmatter_returns_as_is(self):
        raw = "---\ntitle: test\nno closing"
        assert _strip_frontmatter(raw) == raw.strip()

    def test_empty_after_frontmatter(self):
        raw = "---\ntitle: test\n---\n"
        assert _strip_frontmatter(raw) == ""

    def test_whitespace_handling(self):
        raw = "  ---\nkey: val\n---\n  content  "
        assert _strip_frontmatter(raw) == "content"


class TestLoadIdentity:
    def test_existing_file(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("I am DataClaw", encoding="utf-8")
        assert _load_identity(tmp_path) == "I am DataClaw"

    def test_missing_file_returns_fallback(self, tmp_path):
        result = _load_identity(tmp_path / "nonexistent")
        assert "DataClaw" in result

    def test_empty_after_strip_returns_fallback(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("---\nkey: val\n---\n", encoding="utf-8")
        result = _load_identity(tmp_path)
        assert "DataClaw" in result

    def test_frontmatter_stripped(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("---\ntitle: id\n---\nReal identity", encoding="utf-8")
        assert _load_identity(tmp_path) == "Real identity"


class TestLoadSoul:
    def test_existing_file(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("Professional and concise", encoding="utf-8")
        assert _load_soul(tmp_path) == "Professional and concise"

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_soul(tmp_path / "nonexistent") == ""

    def test_frontmatter_stripped(self, tmp_path):
        (tmp_path / "SOUL.md").write_text("---\nlayout: page\n---\nSoul content", encoding="utf-8")
        assert _load_soul(tmp_path) == "Soul content"


class TestLoadUserMemory:
    def test_extracts_target_sections(self, tmp_path):
        content = (
            "# 用户信息\n\n"
            "## 基本信息\n- 名字: Test\n\n"
            "## 使用偏好\n- 简洁回答\n\n"
            "## 兴趣爱好\n- 编程\n\n"
            "## 其他区块\n- 忽略\n"
        )
        (tmp_path / "USER.md").write_text(content, encoding="utf-8")
        result = _load_user_memory(tmp_path)
        assert "基本信息" in result
        assert "使用偏好" in result
        assert "兴趣爱好" in result
        assert "其他区块" not in result

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_user_memory(tmp_path / "nonexistent") == ""

    def test_no_target_sections(self, tmp_path):
        (tmp_path / "USER.md").write_text("# 用户信息\n\n## 其他\n- something\n", encoding="utf-8")
        assert _load_user_memory(tmp_path) == ""


class TestLoadLongTermMemory:
    def test_existing_file(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("# 长期记忆\n- 偏好: Python", encoding="utf-8")
        assert "偏好: Python" in _load_long_term_memory(tmp_path)

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_long_term_memory(tmp_path / "nonexistent") == ""

    def test_strips_whitespace(self, tmp_path):
        (tmp_path / "MEMORY.md").write_text("  content  \n", encoding="utf-8")
        assert _load_long_term_memory(tmp_path) == "content"


class TestBuildSystemPrompt:
    def test_identity_always_present(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("I am DataClaw", encoding="utf-8")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = build_system_prompt(tmp_path, skills_dir)
        assert "I am DataClaw" in result

    def test_soul_appended_when_present(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("Identity", encoding="utf-8")
        (tmp_path / "SOUL.md").write_text("Soul content", encoding="utf-8")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = build_system_prompt(tmp_path, skills_dir)
        assert "Identity" in result
        assert "Soul content" in result

    def test_soul_absent_not_appended(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("Identity", encoding="utf-8")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = build_system_prompt(tmp_path, skills_dir)
        assert result.startswith("Identity")

    def test_user_memory_appended_with_header(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("Identity", encoding="utf-8")
        (tmp_path / "USER.md").write_text("## 基本信息\n- Test user", encoding="utf-8")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = build_system_prompt(tmp_path, skills_dir)
        assert "## 用户档案" in result
        assert "基本信息" in result

    def test_long_term_memory_injected_when_enabled(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("Identity", encoding="utf-8")
        (tmp_path / "MEMORY.md").write_text("重要偏好: Python", encoding="utf-8")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = build_system_prompt(tmp_path, skills_dir, inject_long_term_memory=True)
        assert "## 长期记忆" in result
        assert "重要偏好: Python" in result

    def test_long_term_memory_not_injected_when_disabled(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("Identity", encoding="utf-8")
        (tmp_path / "MEMORY.md").write_text("重要偏好: Python", encoding="utf-8")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = build_system_prompt(tmp_path, skills_dir, inject_long_term_memory=False)
        assert "## 长期记忆" not in result

    def test_fallback_identity_when_no_files(self, tmp_path):
        empty_memory = tmp_path / "memory"
        empty_memory.mkdir()
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = build_system_prompt(empty_memory, skills_dir)
        assert "DataClaw" in result

    def test_assembly_order(self, tmp_path):
        (tmp_path / "IDENTITY.md").write_text("L1_IDENTITY", encoding="utf-8")
        (tmp_path / "SOUL.md").write_text("L2_SOUL", encoding="utf-8")
        (tmp_path / "USER.md").write_text("## 基本信息\nL4_USER", encoding="utf-8")
        (tmp_path / "MEMORY.md").write_text("L5_MEMORY", encoding="utf-8")
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        result = build_system_prompt(tmp_path, skills_dir, inject_long_term_memory=True)
        assert result.index("L1_IDENTITY") < result.index("L2_SOUL")
        assert result.index("L2_SOUL") < result.index("L4_USER")
        assert result.index("L4_USER") < result.index("L5_MEMORY")
        
