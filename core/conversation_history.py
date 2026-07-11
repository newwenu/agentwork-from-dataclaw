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

        去重规则：如果新消息与历史最后一条具有相同唯一标识
        （tool_call_id 或 id），则视为同一条消息的增量更新，替换之；
        否则直接追加，避免连续同类型但不同消息被错误覆盖。
        """
        if not msg.additional_kwargs.get("_timestamp"):
            msg.additional_kwargs["_timestamp"] = datetime.now().isoformat()
        new_id = self._msg_identity(msg)
        if new_id is not None and self._messages:
            last_id = self._msg_identity(self._messages[-1])
            if last_id == new_id:
                self._messages[-1] = msg
                return
        self._messages.append(msg)

    def get_messages(self) -> list[BaseMessage]:
        self._repair_orphaned_tool_calls()
        return self._messages

    def _repair_orphaned_tool_calls(self) -> None:
        """修复孤立的 tool_calls：直接抛弃不完整的工具调用链。

        场景：用户取消（Esc/Ctrl+C）或异常中断流式对话时，
        AIMessage(tool_calls) 已追加但 ToolMessage 尚未到达，
        导致下次调用时 LangGraph 报 INVALID_CHAT_HISTORY 错误。

        修复策略（抛弃式）：
        1. 收集所有已应答的 tool_call_id
        2. 找出 AIMessage 中未应答的 tool_call，从列表中剥离
        3. 若剥离后 AIMessage 无 tool_calls 也无 content，则整条删除
        4. 若删除 AIMessage 导致其已应答的 ToolMessage 失去父级，一并删除
        """
        if not self._messages:
            return

        answered_ids: set[str] = set()
        for msg in self._messages:
            tc_id = getattr(msg, "tool_call_id", None)
            if tc_id:
                answered_ids.add(tc_id)

        ai_orphans: dict[int, list[str]] = {}
        for idx, msg in enumerate(self._messages):
            tool_calls = getattr(msg, "tool_calls", None)
            if not tool_calls:
                continue
            orphan_ids = []
            for tc in tool_calls:
                tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                if tc_id and tc_id not in answered_ids:
                    orphan_ids.append(tc_id)
            if orphan_ids:
                ai_orphans[idx] = orphan_ids

        if not ai_orphans:
            return

        remove_indices: set[int] = set()

        for idx, orphan_ids in ai_orphans.items():
            msg = self._messages[idx]
            tool_calls = list(getattr(msg, "tool_calls", []))
            kept = [tc for tc in tool_calls if (tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")) not in orphan_ids]

            if not kept and not (getattr(msg, "content", None) or "").strip():
                remove_indices.add(idx)
            elif len(kept) < len(tool_calls):
                msg.tool_calls = kept
                invalid_kwargs = getattr(msg, "invalid_tool_calls", None)
                if invalid_kwargs:
                    msg.invalid_tool_calls = [
                        itc for itc in invalid_kwargs
                        if (itc.get("id", "") if isinstance(itc, dict) else getattr(itc, "id", "")) not in orphan_ids
                    ]

        if remove_indices:
            orphaned_tool_ids: set[str] = set()
            for idx in remove_indices:
                msg = self._messages[idx]
                for tc in getattr(msg, "tool_calls", []):
                    tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
                    if tc_id:
                        orphaned_tool_ids.add(tc_id)

            for idx, msg in enumerate(self._messages):
                tc_id = getattr(msg, "tool_call_id", None)
                if tc_id and tc_id in orphaned_tool_ids:
                    remove_indices.add(idx)

            self._messages = [m for i, m in enumerate(self._messages) if i not in remove_indices]

    def last(self) -> BaseMessage | None:
        return self._messages[-1] if self._messages else None

    def __len__(self) -> int:
        return len(self._messages)

    def clear(self) -> None:
        self._messages.clear()

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