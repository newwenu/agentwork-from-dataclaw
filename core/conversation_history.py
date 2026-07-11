"""ConversationHistory — 会话历史的生命周期管理。

职责:
1. 消息列表的追加、替换、清除
2. Token 用量统计（input / output / cached）
3. 对话日志导出

截断策略预留为 _apply_strategy()，当前暂不截断，
后续可在此处注入 sliding_window / summary_prefix 等策略。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage


class TokenStats:
    """会话级 token 用量累计。"""

    def __init__(self) -> None:
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cached_tokens: int = 0

    def record(self, input_t: int, output_t: int, cached_t: int) -> None:
        self.input_tokens += input_t
        self.output_tokens += output_t
        self.cached_tokens += cached_t

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "input": self.input_tokens,
            "output": self.output_tokens,
            "cached": self.cached_tokens,
            "total": self.total,
        }


class ConversationHistory:
    """会话历史管理器。

    所有对消息列表的变更都通过此类进行，确保截断策略、
    token 统计等横切关注点有统一入口。
    """

    def __init__(self) -> None:
        self._messages: list[BaseMessage] = []
        self.token_stats = TokenStats()

    def append(self, msg: BaseMessage) -> None:
        if not msg.additional_kwargs.get("_timestamp"):
            msg.additional_kwargs["_timestamp"] = datetime.now().isoformat()
        self._messages.append(msg)
        self._apply_strategy()

    def replace_all(self, messages: list[BaseMessage]) -> None:
        """用 Agent 返回的完整消息列表替换当前历史，并重新执行策略。"""
        for msg in messages:
            if not msg.additional_kwargs.get("_timestamp"):
                msg.additional_kwargs["_timestamp"] = datetime.now().isoformat()
        self._messages = list(messages)
        self.cleanup_orphaned_tool_calls()
        self._apply_strategy()

    def _msg_identity(self, msg: BaseMessage) -> str | None:
        """提取消息唯一标识，用于判断是否为同一条消息的增量更新。

        - ToolMessage 用 tool_call_id 标识
        - AIMessage 用 id 标识
        - 其他类型返回 None（无法判断，不做合并）
        """
        tc_id = getattr(msg, "tool_call_id", None)
        if tc_id:
            return f"tool:{tc_id}"
        msg_id = getattr(msg, "id", None)
        if msg_id:
            return f"ai:{msg_id}"
        return None

    def sync_append(self, msg: BaseMessage) -> None:
        """流式场景下同步追加单条消息（不触发完整策略，避免频繁截断）。

        去重规则：在历史末尾 20 条消息中查找相同唯一标识的消息，
        找到则替换（增量更新），否则追加。

        向后搜索（而非仅检查最后一条）的原因是：在 LangGraph
        updates 模式下，agent 节点可能将已有消息随新消息一同
        返回，若中间夹杂了 HumanMessage 等无标识消息，仅检查
        最后一条会导致去重失效，产生带有 tool_calls 但没有对应
        ToolMessage 的孤儿 AIMessage。
        """
        if not msg.additional_kwargs.get("_timestamp"):
            msg.additional_kwargs["_timestamp"] = datetime.now().isoformat()
        new_id = self._msg_identity(msg)
        if new_id is not None and self._messages:
            # 从后往前搜索最近 20 条消息，找到即替换
            search_start = max(0, len(self._messages) - 20)
            for i in range(len(self._messages) - 1, search_start - 1, -1):
                if self._msg_identity(self._messages[i]) == new_id:
                    self._messages[i] = msg
                    return
        self._messages.append(msg)

    def get_messages(self) -> list[BaseMessage]:
        return self._messages

    def last(self) -> BaseMessage | None:
        return self._messages[-1] if self._messages else None

    def __len__(self) -> int:
        return len(self._messages)

    def clear(self) -> None:
        self._messages.clear()

    def cleanup_orphaned_tool_calls(self) -> int:
        """清理存在孤立 tool_calls 的 AIMessage。

        某些 LLM 提供商（如 DeepSeek）严格要求每条带有 tool_calls
        的 AIMessage 之后必须有对应的 ToolMessage。若因流式同步异常
        导致历史中出现"孤儿"工具调用，后续请求将被拒绝。

        策略：收集所有 ToolMessage 的 tool_call_id，然后移除那些
        tool_calls 中包含未匹配 ID 的 AIMessage（若某 AIMessage
        的所有 tool_calls 均无对应 ToolMessage，则整条移除）。

        Returns:
            移除的消息数量。
        """
        if not self._messages:
            return 0

        # 收集所有已存在的 tool_call_id（来自 ToolMessage）
        responded_ids: set[str] = set()
        for msg in self._messages:
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id:
                responded_ids.add(tc_id)

        cleaned: list[BaseMessage] = []
        removed = 0
        for msg in self._messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                # 检查是否有任何一个 tool_call 没有收到 ToolMessage 响应
                orphaned = any(
                    tc.get("id", "") not in responded_ids
                    for tc in msg.tool_calls
                )
                if orphaned:
                    removed += 1
                    continue  # 丢弃整条消息
            cleaned.append(msg)

        if removed:
            self._messages = cleaned
        return removed

    def _apply_strategy(self) -> None:
        """截断策略入口，当前暂不截断。

        后续可在此实现:
        - sliding_window: 保留最近 N 条
        - summary_prefix: 将老消息压缩为摘要前缀
        - token_budget: 按 token 预算动态裁剪
        """
        pass

    def export_log(self, save_dir: Path) -> str:
        """导出完整对话日志到 JSON 文件。"""
        log_entries = []
        for msg in self._messages:
            entry: dict[str, Any] = {
                "timestamp": msg.additional_kwargs.get("_timestamp", datetime.now().isoformat()),
                "type": getattr(msg, "type", msg.__class__.__name__),
            }
            if hasattr(msg, "content"):
                entry["content"] = msg.content
            if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
                entry["additional_kwargs"] = {
                    k: v for k, v in msg.additional_kwargs.items() if not k.startswith("_")
                }
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                entry["tool_calls"] = msg.tool_calls
            if hasattr(msg, "name") and msg.name:
                entry["name"] = msg.name
            log_entries.append(entry)

        save_path = save_dir / f"claw_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(
            json.dumps(log_entries, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return str(save_path)