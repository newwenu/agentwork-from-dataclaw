from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from langgraph.prebuilt import create_react_agent
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from background_loop import BackgroundLoop
from core.config import get_config
from core.conversation_history import ConversationHistory
from core.llm_factory import create_llm
from core.prompt_builder import build_system_prompt
from memory_manager import MemoryManager
from tools import get_all_tools
from tui import run_tui


class CoreClawAgent:
    """CoreClaw Agent with tool support and memory management."""

    def __init__(self, base_dir: Path | None = None, model: str | None = None):
        self.base_dir = base_dir or Path.cwd()
        self.tools = get_all_tools(self.base_dir)
        self.work_dir: Path | None = None

        config = get_config()

        self.llm = create_llm(config)

        # mock 模式下禁用记忆提取：MockChatModel 无法返回有效 JSON
        effective_extraction = config.memory_extraction
        if config.llm_mode == "mock":
            effective_extraction = False

        self.memory = MemoryManager(
            self.base_dir,
            llm_client=self.llm,
            enable_extraction=effective_extraction,
            enable_long_term_inject=config.memory_inject_long_term,
            llm_cooldown=config.memory_llm_cooldown,
        )
        self.memory.start_watching()

        # 初始化后台定时任务（延迟启动，等事件循环准备好）
        self.bg_loop = BackgroundLoop(self.base_dir)
        self._bg_started = False

        # 构建 system prompt（身份 + 性格 + 技能 + 用户档案 + 长期记忆）
        full_system_prompt = build_system_prompt(
            memory_dir=self.memory.memory_dir,
            skills_dir=self.base_dir / "skills",
            inject_long_term_memory=self.memory.enable_long_term_inject,
        )

        # 创建 Agent
        self.agent = create_react_agent(
            model=self.llm,
            tools=self.tools,
            prompt=full_system_prompt,
        )

        # 会话历史（消息管理 + token 统计 + 截断策略）
        self.history = ConversationHistory()

    def close(self) -> None:
        """清理资源。"""
        if hasattr(self, "memory") and self.memory:
            self.memory.close()
        if hasattr(self, "bg_loop") and self.bg_loop and self._bg_started:
            self.bg_loop.stop()
            self._bg_started = False

    # ── 聊天公共管道 ──────────────────────────────────────

    def _ensure_bg_started(self) -> None:
        """延迟启动后台任务（第一次聊天时触发）。"""
        if not self._bg_started:
            self.bg_loop.start()
            self._bg_started = True

    def _prepare_chat(self, user_input: str) -> None:
        """聊天前置：启动后台任务 + 追加用户消息 + 记录日志。"""
        self._ensure_bg_started()
        user_msg = HumanMessage(content=user_input)
        self.history.append(user_msg)
        self.memory.log_message(user_msg)

    def _finalize_chat(self, ai_message: BaseMessage | None) -> None:
        """聊天后置：记录 AI 回复到日志。"""
        if ai_message is not None:
            self.memory.log_message(ai_message)

    # ── 聊天方法 ──────────────────────────────────────────

    async def chat(self, user_input: str) -> str:
        """发送消息给 Agent 并返回回复。"""
        self._prepare_chat(user_input)

        response = await self.agent.ainvoke(
            {"messages": self.history.get_messages()},
            config={"recursion_limit": 200},
        )

        self.history.replace_all(response["messages"])
        ai_message = self.history.last()
        self._finalize_chat(ai_message)

        return ai_message.content if ai_message and hasattr(ai_message, "content") else ""

    async def stream_chat_with_events(self, user_input: str):
        """流式输出 Agent 的回复及中间事件（工具调用等）。

        使用 stream_mode=["updates", "messages"]：
        - "messages" 提供 LLM token 级流式输出（content / reasoning_content）
        - "updates" 提供节点级事件（tool_call / tool_result）
        流式结束后从历史中取出最终 AI 消息，避免双重 LLM 调用。
        """
        self._prepare_chat(user_input)

        # 同时使用 "messages"（token 级流式）和 "updates"（节点状态/工具结果）
        # 当 stream_mode 为列表时，每个 chunk 是 (mode, data) 元组
        current_reasoning = ""
        current_content = ""
        async for chunk in self.agent.astream(
            {"messages": self.history.get_messages()},
            config={"recursion_limit": 200},
            stream_mode=["updates", "messages"],
        ):
            mode, data = chunk
            if mode == "messages":
                # messages 模式返回 (msg, metadata)，msg 是 LLM 的 token 增量
                msg, _metadata = data

                # 只处理 AI 消息，避免工具/人类消息混入流式输出
                if getattr(msg, "type", None) != "ai":
                    continue

                # 提取思维链（DeepSeek / Qwen 等模型放在 additional_kwargs）
                reasoning_raw = ""
                if hasattr(msg, "additional_kwargs"):
                    reasoning_raw = msg.additional_kwargs.get("reasoning_content") or ""
                if reasoning_raw:
                    if reasoning_raw.startswith(current_reasoning):
                        delta = reasoning_raw[len(current_reasoning):]
                    else:
                        delta = reasoning_raw
                        current_reasoning = ""
                    if delta:
                        current_reasoning += delta
                        yield {
                            "type": "reasoning",
                            "content": current_reasoning,
                            "delta": delta,
                        }

                # 提取正式回复内容并做增量累积
                content_raw = getattr(msg, "content", "") or ""
                if content_raw:
                    if content_raw.startswith(current_content):
                        delta = content_raw[len(current_content):]
                    else:
                        delta = content_raw
                        current_content = ""
                    if delta:
                        current_content += delta
                        yield {
                            "type": "thinking",
                            "content": current_content,
                            "delta": delta,
                        }

            elif mode == "updates":
                for node_name, update in data.items():
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
                            # 从 AI 消息中提取 token 用量
                            elif hasattr(msg, "response_metadata") and msg.response_metadata:
                                token_usage = msg.response_metadata.get("token_usage") or {}
                                if token_usage:
                                    self.history.token_stats.record(
                                        token_usage.get("input_tokens", 0),
                                        token_usage.get("output_tokens", 0),
                                        (token_usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
                                    )
                            # 同步更新内部历史，避免二次调用
                            if hasattr(msg, "type"):
                                self.history.sync_append(msg)
                    elif node_name == "tools":
                        msgs = update.get("messages", [])
                        for msg in msgs:
                            if hasattr(msg, "content") and msg.content:
                                name = getattr(msg, "name", "tool") or "tool"
                                tool_call_id = getattr(msg, "tool_call_id", "") or ""
                                yield {
                                    "type": "tool_result",
                                    "name": name,
                                    "content": str(msg.content),
                                    "tool_call_id": tool_call_id,
                                }
                            # 同步更新内部历史
                            if hasattr(msg, "type"):
                                self.history.sync_append(msg)

        # 从已更新的历史中获取最终 AI 消息
        ai_message = self.history.last()
        self._finalize_chat(ai_message)

        yield {
            "type": "final",
            "content": ai_message.content if ai_message and hasattr(ai_message, "content") else "",
            "token_usage": self.history.token_stats.as_dict(),
        }

    # ── 工具方法 ──────────────────────────────────────────

    def export_log(self, save_dir: str | None = None) -> str:
        """导出完整对话日志到文件。"""
        target_dir = Path(save_dir) if save_dir else self.base_dir
        return self.history.export_log(target_dir)

    def clear_history(self):
        """清除对话历史。"""
        self.history.clear()
        print("✅ 对话历史已清除")

    def set_work_dir(self, path: str) -> str:
        """设置工作目录，更新工具沙盒，并通知 Agent。"""
        target = Path(path).expanduser()

        # 如果已是存在的绝对路径，直接使用
        if target.is_absolute() and target.exists() and target.is_dir():
            pass
        else:
            # Path(".").name 为空字符串，Path(any) / "" == Path(any)
            # 会导致搜索意外匹配到父目录，需提前 resolve
            target = target.resolve()
            if target.is_absolute() and target.exists() and target.is_dir():
                pass
            else:
                # 只传了文件夹名，在多个常见位置搜索
                name = target.name
                if not name:
                    return f"❌ 无效的目录路径: {path}"
                base_parent = Path(self.base_dir).parent.resolve()
                home = Path.home()
                locations = [
                    base_parent / name,
                    Path(self.base_dir) / name,
                    home / name,
                    home / "Desktop" / name,
                    home / "Documents" / name,
                    home / "Downloads" / name,
                    Path.cwd() / name,
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

        self.work_dir = target.resolve()

        # 更新需要跟随工作目录的工具 root_dir
        # 跳过 read_skill_file（root_dir 指向 skills/，不应随工作目录变化）
        # 跳过 write_memory（memory_dir 指向 memory/，不应随工作目录变化）
        for tool in self.tools:
            if tool.name == "read_skill_file":
                continue
            if tool.name == "write_memory":
                continue
            current_val = getattr(tool, "root_dir", None)
            if current_val is not None:
                try:
                    setattr(tool, "root_dir", str(target.resolve()))
                except (AttributeError, TypeError):
                    pass

        # 发送系统消息告知 Agent 工作目录变更
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
        self.history.append(sys_msg)

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
    config = get_config()
    errors = config.validate_api_keys()
    if errors:
        for err in errors:
            print(f"❌ 错误: {err}")
        print("请在 .env 文件中配置正确的 API Key")
        sys.exit(1)

    base_dir = Path(__file__).parent.resolve()
    agent = CoreClawAgent(base_dir=base_dir)

    if len(sys.argv) > 1:
        query = sys.argv[1]
        result = asyncio.run(single_query(agent, query))
        print(result)
    else:
        run_tui(agent)


if __name__ == "__main__":
    main()