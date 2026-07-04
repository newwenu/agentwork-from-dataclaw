"""Prompt Builder — Agent System Prompt 的组装中心。

职责：
1. 从 memory/ 目录加载各层提示词素材（IDENTITY / SOUL / USER / MEMORY）
2. 从 skills/ 目录加载技能系统提示词
3. 按固定优先级拼接为完整的 system prompt

设计原则：
- 每个加载函数只负责读取+清洗，不做拼接决策
- build_system_prompt() 是唯一的拼接入口，控制各层组装顺序
- 对外只暴露 build_system_prompt()，内部函数均为模块私有
"""

from __future__ import annotations

from pathlib import Path

from skills_scanner import generate_skills_prompt


def _strip_frontmatter(content: str) -> str:
    """移除 YAML frontmatter（--- 包裹的头部），保留正文。"""
    stripped = content.strip()
    if not stripped.startswith("---"):
        return stripped
    lines = stripped.split("\n")
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return stripped
    return "\n".join(lines[end_idx + 1 :]).strip()


def _load_identity(memory_dir: Path) -> str:
    """加载 IDENTITY.md 作为基础身份设定。"""
    identity_file = memory_dir / "IDENTITY.md"
    if identity_file.exists():
        content = identity_file.read_text(encoding="utf-8")
        stripped = _strip_frontmatter(content)
        return stripped if stripped else "你是 DataClaw，一个拥有工具调用能力的 AI 助手。"
    return "你是 DataClaw，一个拥有工具调用能力的 AI 助手。"


def _load_soul(memory_dir: Path) -> str:
    """加载 SOUL.md 作为性格特征设定。"""
    soul_file = memory_dir / "SOUL.md"
    if soul_file.exists():
        content = soul_file.read_text(encoding="utf-8")
        stripped = _strip_frontmatter(content)
        return stripped
    return ""


def _load_user_memory(memory_dir: Path) -> str:
    """加载 USER.md 中预定义的用户相关记忆区块。

    当前提取区块: 使用偏好、兴趣爱好、基本信息。
    """
    sections = []
    user_file = memory_dir / "USER.md"
    if not user_file.exists():
        return ""

    content = user_file.read_text(encoding="utf-8")
    lines = content.split("\n")
    target_sections = {"## 使用偏好", "## 兴趣爱好", "## 基本信息"}

    for section_title in target_sections:
        for i, line in enumerate(lines):
            if line.startswith(section_title):
                section_content = [line]
                for j in range(i + 1, len(lines)):
                    if lines[j].startswith("## "):
                        break
                    section_content.append(lines[j])
                sections.append("\n".join(section_content))
                break

    return "\n\n".join(sections) if sections else ""


def _load_long_term_memory(memory_dir: Path) -> str:
    """加载 MEMORY.md 中的长期记忆。"""
    memory_file = memory_dir / "MEMORY.md"
    if memory_file.exists():
        content = memory_file.read_text(encoding="utf-8").strip()
        return content
    return ""


def build_system_prompt(
    memory_dir: Path,
    skills_dir: Path,
    *,
    inject_long_term_memory: bool = False,
) -> str:
    """构建完整的 system prompt。

    拼接优先级（从上到下）:
    1. IDENTITY.md — 基础身份与规则（必选，有 fallback）
    2. SOUL.md — 性格特征（可选）
    3. Skills — 技能系统（可选）
    4. USER.md — 用户档案（可选）
    5. MEMORY.md — 长期记忆（受 inject_long_term_memory 控制）

    Args:
        memory_dir: memory/ 目录路径
        skills_dir: skills/ 目录路径
        inject_long_term_memory: 是否注入长期记忆

    Returns:
        拼接完成的 system prompt 字符串
    """
    prompt = _load_identity(memory_dir)

    soul = _load_soul(memory_dir)
    if soul:
        prompt += "\n\n" + soul

    skills = generate_skills_prompt(skills_dir)
    if skills:
        prompt += "\n\n" + skills

    user_memory = _load_user_memory(memory_dir)
    if user_memory:
        prompt += f"\n\n## 用户档案\n{user_memory}"

    if inject_long_term_memory:
        long_term = _load_long_term_memory(memory_dir)
        if long_term:
            prompt += f"\n\n## 长期记忆\n{long_term}"

    return prompt
    
