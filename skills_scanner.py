"""Skills Scanner — 扫描和管理 Agent Skills。

修复 (2026-06-25):
1. 移除模块级 print 副作用
2. XML 生成时转义特殊字符
3. 增加错误处理
"""

from html import escape
from pathlib import Path
from typing import TypedDict


class SkillInfo(TypedDict):
    """技能信息结构。"""

    name: str
    path: str
    description: str


def scan_skills(skills_dir: Path) -> list[SkillInfo]:
    """
    扫描 skills 文件夹，提取所有可用技能。

    Args:
        skills_dir: skills 目录路径

    Returns:
        技能信息列表
    """
    skills = []

    if not skills_dir.exists():
        return skills

    for skill_folder in skills_dir.iterdir():
        if not skill_folder.is_dir():
            continue

        skill_md = skill_folder / "SKILL.md"
        if not skill_md.exists():
            continue

        try:
            content = skill_md.read_text(encoding="utf-8")
        except Exception:
            continue

        # 提取元数据 (前5行)
        name = skill_folder.name
        description = ""

        for line in content.split("\n")[:5]:
            line = line.strip()
            if line.startswith("name:"):
                name = line.replace("name:", "").strip()
            elif line.startswith("description:"):
                description = line.replace("description:", "").strip()

        skills.append(
            {
                "name": name,
                "path": f"{skill_folder.name}/SKILL.md",
                "description": description,
            }
        )

    return skills


def generate_skills_xml(skills: list[SkillInfo]) -> str:
    """
    生成 XML 格式的技能菜单。

    Args:
        skills: 技能列表

    Returns:
        XML 格式字符串
    """
    if not skills:
        return "<available_skills>No skills found.</available_skills>"

    lines = ["<available_skills>"]
    for skill in skills:
        name_escaped = escape(skill["name"])
        path_escaped = escape(skill["path"])
        desc_escaped = escape(skill["description"])
        lines.append("  <skill>")
        lines.append(f"    <name>{name_escaped}</name>")
        lines.append(f"    <path>{path_escaped}</path>")
        lines.append(f"    <description>{desc_escaped}</description>")
        lines.append("  </skill>")
    lines.append("</available_skills>")
    return "\n".join(lines)


def generate_skills_prompt(skills_dir: Path) -> str:
    """
    生成完整的技能系统提示词。

    Args:
        skills_dir: skills 目录路径

    Returns:
        技能系统提示词
    """
    skills = scan_skills(skills_dir)

    if not skills:
        return ""

    skills_xml = generate_skills_xml(skills)

    return f"""
## 技能系统 (Agent Skills)

你拥有以下专业技能，定义了你的能力边界：

{skills_xml}

### 技能执行协议 (CRITICAL)

1. **识别技能需求**：当用户请求匹配上述技能时，严禁直接猜测操作步骤
2. **读取技能定义**：第一步**必须**调用 `read_skill_file` 工具，读取对应技能的 `<path>` 文件
3. **严格执行**：按照 SKILL.md 中的步骤指导执行任务
4. **禁止偏离**：不要添加技能文档之外的额外步骤

### 工具说明

- `read_skill_file(path)` - 读取技能目录内的任意文件，path 相对于 skills/ 文件夹。
  例如: `patent_disclosure/SKILL.md`、`patent_disclosure/prompts/intake.md`、`get_weather/SKILL.md`
"""
