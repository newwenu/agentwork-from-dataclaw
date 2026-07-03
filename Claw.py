from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
# 加载环境变量
from dotenv import load_dotenv

load_dotenv()

from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage
from langchain_deepseek import ChatDeepSeek
from langchain_community.chat_models import ChatTongyi

from background_loop import BackgroundLoop
from memory_manager import MemoryManager
from skills_scanner import generate_skills_prompt
from tools import get_all_tools
from tui import run_tui


def _strip_frontmatter(content: str) -> str:
    """移除 frontmatter：跳过开头空行，从第一个 '# ' 标题开始保留。"""
    lines = content.split("\n")
    result = []
    found_title = False
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("# "):
            found_title = True
        if found_title:
            result.append(line)
    return "\n".join(result).strip()


def load_identity(memory_dir: Path) -> str:
    """加载 IDENTITY.md 作为基础身份设定。"""
    identity_file = memory_dir / "IDENTITY.md"
    if identity_file.exists():
        content = identity_file.read_text(encoding="utf-8")
        stripped = _strip_frontmatter(content)
        return stripped if stripped else "你是 CoreClaw，一个拥有工具调用能力的 AI 助手。"
    return "你是 CoreClaw，一个拥有工具调用能力的 AI 助手。"


def load_user_memory(memory_dir: Path) -> str:
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


def load_soul(memory_dir: Path) -> str:
    """加载 SOUL.md 作为性格特征设定。"""
    soul_file = memory_dir / "SOUL.md"
    if soul_file.exists():
        content = soul_file.read_text(encoding="utf-8")
        stripped = _strip_frontmatter(content)
        return stripped
    return ""


class CoreClawAgent:
    """CoreClaw Agent with tool support and memory management."""

    def __init__(self, base_dir: Path | None = None, model: str | None = None):
        self.base_dir = base_dir or Path.cwd()
        self.tools = get_all_tools(self.base_dir)
        self.work_dir: Path | None = None  # 用户工作目录（可选）

        # 模型路由：根据 MAIN_MODEL 选择 DeepSeek 或 Qwen
        main_model = os.getenv("MAIN_MODEL", "deepseek").strip().lower()

        if main_model == "qwen":
            # 初始化 Qwen (通义千问)
            qwen_api_key = os.getenv("DASHSCOPE_API_KEY")
            qwen_model = model or os.getenv("QWEN_MODEL", "qwen-plus")

            if not qwen_api_key:
                raise ValueError("DASHSCOPE_API_KEY not found in environment")

            self.llm = ChatTongyi(
                model=qwen_model,
                dashscope_api_key=qwen_api_key,
                temperature=0.2,
            )
        else:
            # 初始化模型 (默认 DeepSeek)
            api_key = os.getenv("DEEPSEEK_API_KEY")
            base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            model_name = model or os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

            if not api_key:
                raise ValueError("DEEPSEEK_API_KEY not found in environment")

            self.llm = ChatDeepSeek(
                model=model_name,
                api_key=api_key,
                base_url=base_url,
                temperature=0.2,
            )

        # 初始化记忆管理器（传入 LLM 用于主动提取记忆）
        self.memory = MemoryManager(self.base_dir, llm_client=self.llm)
        self.memory.start_watching()

        # 初始化后台定时任务（延迟启动，等事件循环准备好）
        self.bg_loop = BackgroundLoop(self.base_dir)
        self._bg_started = False

        # 加载身份设定（IDENTITY.md）
        identity_content = load_identity(self.memory.memory_dir)

        # 加载性格特征（SOUL.md）
        soul_content = load_soul(self.memory.memory_dir)

        # 加载用户记忆（USER.md）
        user_memory = load_user_memory(self.memory.memory_dir)

        # 加载技能系统
        skills_content = generate_skills_prompt(self.base_dir / "skills")

        # 构建完整 system prompt
        full_system_prompt = identity_content

        # 添加性格特征
        if soul_content:
            full_system_prompt += "\n\n" + soul_content

        # 添加技能系统
        if skills_content:
            full_system_prompt += "\n\n" + skills_content

        # 添加用户特定记忆
        if user_memory:
            full_system_prompt += f"\n\n## 用户档案\n{user_memory}"

        # # 添加长期记忆
        # memory_file = self.memory.memory_dir / "MEMORY.md"
        # if memory_file.exists():
        #     memory_content = memory_file.read_text(encoding="utf-8").strip()
        #     if memory_content:
        #         full_system_prompt += f"\n\n## 长期记忆\n{memory_content}"
        # 暂时不添加长期记忆

        # 创建 Agent
        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=full_system_prompt,
        )

        # 会话历史
        self.messages: list[Any] = []

        # 注: atexit 在异步环境中不可靠，已移除。
        # 请在使用完毕后显式调用 agent.close() 或配合 asynccontextmanager 使用。

    def close(self) -> None:
        """清理资源。"""
        if hasattr(self, 'memory') and self.memory:
            self.memory.close()
        if hasattr(self, 'bg_loop') and self.bg_loop and self._bg_started:
            self.bg_loop.stop()
            self._bg_started = False

    async def chat(self, user_input: str) -> str:
        """发送消息给 Agent 并返回回复。"""
        # 延迟启动后台任务（第一次聊天时）
        if not self._bg_started:
            self.bg_loop.start()
            self._bg_started = True

        user_msg = HumanMessage(content=user_input)
        self.messages.append(user_msg)
        self.memory.log_message(user_msg)

        # 调用 Agent
        response = await self.agent.ainvoke({"messages": self.messages}, config={"recursion_limit": 200})

        # 获取回复消息 (最后一条 AI 消息)
        ai_message = response["messages"][-1]
        self.messages = response["messages"]

        # 记录 AI 回复
        self.memory.log_message(ai_message)

        return ai_message.content

    async def stream_chat(self, user_input: str):
        """流式输出 Agent 的回复。"""
        # 延迟启动后台任务（第一次聊天时）
        if not self._bg_started:
            self.bg_loop.start()
            self._bg_started = True

        user_msg = HumanMessage(content=user_input)
        self.messages.append(user_msg)
        self.memory.log_message(user_msg)

        # 收集完整响应以更新历史
        full_messages = None
        async for chunk in self.agent.astream(
            {"messages": self.messages},
            config={"recursion_limit": 200},
        ):
            if "messages" in chunk:
                for msg in chunk["messages"]:
                    if hasattr(msg, "content"):
                        yield msg.content
                # 保留最新完整消息列表
                full_messages = chunk["messages"]

        # 更新历史并记录 AI 回复
        if full_messages:
            self.messages = full_messages
            ai_message = self.messages[-1]
            self.memory.log_message(ai_message)

    async def stream_chat_with_events(self, user_input: str):
        """流式输出 Agent 的回复及中间事件（工具调用等）。

        修复 (2026-06-25): 使用单次 astream + stream_mode="updates" 获取逐步更新，
        并在流式结束后从历史中取出最终 AI 消息，避免双重 LLM 调用。
        """
        if not self._bg_started:
            self.bg_loop.start()
            self._bg_started = True

        user_msg = HumanMessage(content=user_input)
        self.messages.append(user_msg)
        self.memory.log_message(user_msg)

        # 使用 stream_mode="updates" 获取逐步更新
        async for chunk in self.agent.astream(
            {"messages": self.messages},
            config={"recursion_limit": 200},
            stream_mode="updates",
        ):
            for node_name, update in chunk.items():
                if node_name == "agent":
                    msgs = update.get("messages", [])
                    for msg in msgs:
                        # 优先处理工具调用：tool_calls 消息 content 可能为空
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            for tc in msg.tool_calls:
                                yield {
                                    "type": "tool_call",
                                    "name": tc.get("name", "unknown"),
                                    "args": tc.get("args", {}),
                                    "id": tc.get("id", ""),
                                    "content": msg.content or "",
                                }
                        elif hasattr(msg, "content") and msg.content:
                            yield {
                                "type": "thinking",
                                "content": msg.content or "",
                            }
                        # 同步更新内部历史，避免二次调用
                        if hasattr(msg, "type"):
                            # 找到消息在历史中的位置并更新
                            if self.messages and self.messages[-1].type != msg.type:
                                self.messages.append(msg)
                            else:
                                self.messages[-1] = msg
                elif node_name == "tools":
                    msgs = update.get("messages", [])
                    for msg in msgs:
                        if hasattr(msg, "content") and msg.content:
                            name = getattr(msg, "name", "tool") or "tool"
                            yield {
                                "type": "tool_result",
                                "name": name,
                                "content": str(msg.content)[:500],
                            }
                        # 同步更新内部历史
                        if hasattr(msg, "type"):
                            if self.messages and self.messages[-1].type != msg.type:
                                self.messages.append(msg)
                            else:
                                self.messages[-1] = msg

        # 从已更新的历史中获取最终 AI 消息
        ai_message = self.messages[-1] if self.messages else None
        if ai_message is not None:
            self.memory.log_message(ai_message)

        yield {
            "type": "final",
            "content": ai_message.content if ai_message and hasattr(ai_message, "content") else "",
        }

    def export_log(self, save_dir: str | None = None) -> str:
        """导出完整对话日志到文件。"""
        import json
        from datetime import datetime

        log_entries = []
        for msg in self.messages:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "type": getattr(msg, "type", msg.__class__.__name__),
            }
            if hasattr(msg, "content"):
                entry["content"] = msg.content
            if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
                entry["additional_kwargs"] = msg.additional_kwargs
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if hasattr(msg, "name") and msg.name:
                entry["name"] = msg.name
            log_entries.append(entry)

        # 确定保存路径
        if save_dir:
            save_path = Path(save_dir) / f"claw_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        else:
            save_path = self.base_dir / f"claw_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(
            json.dumps(log_entries, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return str(save_path)

    def clear_history(self):
        """清除对话历史。"""
        self.messages = []
        print("✅ 对话历史已清除")

    def set_work_dir(self, path: str) -> str:
        """设置工作目录，更新工具沙盒，并通知 Agent。"""
        target = Path(path)

        # 如果已是存在的绝对路径，直接使用
        if target.is_absolute() and target.exists():
            pass
        else:
            # 浏览器只传了文件夹名，在多个常见位置搜索
            name = target.name  # 纯文件夹名
            base_parent = Path(self.base_dir).parent.resolve()
            home = Path.home()
            locations = [
                base_parent / name,              # 项目同级（如 Desktop）
                Path(self.base_dir) / name,       # 项目内部
                home / name,                      # 用户主目录
                home / "Desktop" / name,          # 桌面
                home / "Documents" / name,        # 文档
                home / "Downloads" / name,        # 下载
                Path.cwd() / name,                # 当前工作目录
            ]
            found = None
            for loc in locations:
                resolved = loc.resolve()
                if resolved.exists() and resolved.is_dir():
                    found = resolved
                    break
            if found is None:
                return f"❌ 找不到目录: {path}"
            target = found

        if not target.is_dir():
            return f"❌ 不是目录: {target}"
        if not target.exists():
            return f"❌ 目录不存在: {target}"

        self.work_dir = target.resolve()
        old_base = self.base_dir

        # 更新所有工具 root_dir 到工作目录
        sandbox_attrs = ["root_dir", "base_dir"]
        for tool in self.tools:
            for attr in sandbox_attrs:
                if hasattr(tool, attr) and tool.root_dir:
                    try:
                        setattr(tool, attr, str(target))
                    except Exception:
                        pass

        # 发送系统消息告知 Agent 工作目录变更
        from langchain_core.messages import SystemMessage
        sys_msg = SystemMessage(content=(
            f"## 工作目录变更通知\n\n"
            f"用户已指定工作目录：`{target}`\n\n"
            f"**重要约束（必须遵守）：**\n"
            f"1. 所有文件读取操作**只能**访问 `{target}` 及其子目录下的文件\n"
            f"2. 所有文件写入/下载操作**必须**保存到 `{target}` 目录下\n"
            f"3. 严禁访问 `{target}` 之外的任何文件和目录\n"
            f"4. 如果用户未指定具体路径，默认使用 `{target}` 作为输出目录\n"
            f"5. 你的工作范围限定在此目录内，超出此目录的操作将被拒绝"
        ))
        self.messages.append(sys_msg)

        print(f"[WorkDir] 已设置为: {target}")
        return f"✅ 工作目录已设置为: {target}\n工具沙盒已更新，所有文件操作限制在此目录内。"

    def get_work_dir(self) -> str:
        """获取当前工作目录。"""
        return str(self.work_dir) if self.work_dir else ""


async def single_query(agent: CoreClawAgent, query: str) -> str:
    """单次查询模式。"""
    return await agent.chat(query)


def main():
    """主入口。"""
    # 检查环境变量
    main_model = os.getenv("MAIN_MODEL", "deepseek").strip().lower()

    if main_model == "qwen":
        if not os.getenv("DASHSCOPE_API_KEY"):
            print("❌ 错误: DASHSCOPE_API_KEY 未设置")
            print("请在 .env 文件中配置 DASHSCOPE_API_KEY")
            sys.exit(1)
    elif not os.getenv("DEEPSEEK_API_KEY"):
        print("❌ 错误: DEEPSEEK_API_KEY 未设置")
        print("请在 .env 文件中配置 DEEPSEEK_API_KEY")
        sys.exit(1)

    # 创建 Agent
    base_dir = Path(__file__).parent
    agent = CoreClawAgent(base_dir=base_dir)

    # 判断模式
    if len(sys.argv) > 1:
        # 单次查询模式
        query = sys.argv[1]
        result = asyncio.run(single_query(agent, query))
        print(result)
    else:
        # TUI 交互模式
        run_tui(agent)


if __name__ == "__main__":
    main()