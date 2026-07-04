"""skills_scanner 测试 — 验证技能扫描与提示词生成。

测试覆盖:
1. 技能目录扫描
2. SKILL.md 元数据提取
3. XML 生成与特殊字符转义
4. 空目录/缺失文件处理
5. 提示词生成完整性
"""

from pathlib import Path

import pytest

from skills_scanner import scan_skills, generate_skills_xml, generate_skills_prompt


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    sd = tmp_path / "skills"
    sd.mkdir()

    skill_a = sd / "data_analysis"
    skill_a.mkdir()
    (skill_a / "SKILL.md").write_text(
        "name: ml_runner\ndescription: Run ML code step by step\n\n# ML Runner\n...",
        encoding="utf-8",
    )

    skill_b = sd / "weather_check"
    skill_b.mkdir()
    (skill_b / "SKILL.md").write_text(
        "name: weather\ndescription: Check weather info\n\n# Weather\n...",
        encoding="utf-8",
    )

    return sd


@pytest.fixture
def empty_dir(tmp_path: Path) -> Path:
    sd = tmp_path / "empty_skills"
    sd.mkdir()
    return sd


class TestScanSkills:
    def test_finds_all_skills(self, skills_dir: Path):
        skills = scan_skills(skills_dir)
        assert len(skills) == 2

    def test_extracts_name(self, skills_dir: Path):
        skills = scan_skills(skills_dir)
        names = {s["name"] for s in skills}
        assert "ml_runner" in names
        assert "weather" in names

    def test_extracts_description(self, skills_dir: Path):
        skills = scan_skills(skills_dir)
        descs = {s["description"] for s in skills}
        assert "Run ML code step by step" in descs

    def test_extracts_path(self, skills_dir: Path):
        skills = scan_skills(skills_dir)
        paths = {s["path"] for s in skills}
        assert "data_analysis/SKILL.md" in paths
        assert "weather_check/SKILL.md" in paths

    def test_skips_dir_without_skill_md(self, tmp_path: Path):
        sd = tmp_path / "skills"
        sd.mkdir()
        no_md = sd / "incomplete_skill"
        no_md.mkdir()
        skills = scan_skills(sd)
        assert len(skills) == 0

    def test_skips_non_dir_files(self, skills_dir: Path):
        (skills_dir / "readme.txt").write_text("not a skill", encoding="utf-8")
        skills = scan_skills(skills_dir)
        assert len(skills) == 2

    def test_empty_directory(self, empty_dir: Path):
        skills = scan_skills(empty_dir)
        assert skills == []

    def test_nonexistent_directory(self, tmp_path: Path):
        skills = scan_skills(tmp_path / "no_such_dir")
        assert skills == []


class TestGenerateSkillsXml:
    def test_xml_structure(self, skills_dir: Path):
        skills = scan_skills(skills_dir)
        xml = generate_skills_xml(skills)
        assert "<available_skills>" in xml
        assert "</available_skills>" in xml
        assert "<skill>" in xml
        assert "<name>" in xml
        assert "<path>" in xml
        assert "<description>" in xml

    def test_escapes_special_chars(self):
        skills = [{"name": "a<b>&c", "path": "x/y", "description": "d\"e'f"}]
        xml = generate_skills_xml(skills)
        assert "&lt;" in xml
        assert "&amp;" in xml
        assert "&quot;" in xml

    def test_empty_skills(self):
        xml = generate_skills_xml([])
        assert "No skills found" in xml


class TestGenerateSkillsPrompt:
    def test_prompt_contains_skill_protocol(self, skills_dir: Path):
        prompt = generate_skills_prompt(skills_dir)
        assert "技能系统" in prompt
        assert "read_skill_file" in prompt
        assert "SKILL.md" in prompt

    def test_prompt_contains_xml(self, skills_dir: Path):
        prompt = generate_skills_prompt(skills_dir)
        assert "<available_skills>" in prompt

    def test_empty_dir_returns_empty(self, empty_dir: Path):
        prompt = generate_skills_prompt(empty_dir)
        assert prompt == ""

    def test_nonexistent_dir_returns_empty(self, tmp_path: Path):
        prompt = generate_skills_prompt(tmp_path / "no_such_dir")
        assert prompt == ""
        
