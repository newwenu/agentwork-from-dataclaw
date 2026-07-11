"""ConversationHistory 测试 — 验证会话历史管理、token 统计与日志导出。"""

import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from core.conversation_history import ConversationHistory, TokenStats


# ── TokenStats ──────────────────────────────────────────────


class TestTokenStatsDefaults:
    def test_initial_values(self):
        stats = TokenStats()
        assert stats.input_tokens == 0
        assert stats.output_tokens == 0
        assert stats.cached_tokens == 0
        assert stats.total == 0

    def test_as_dict_structure(self):
        stats = TokenStats()
        d = stats.as_dict()
        assert set(d.keys()) == {"input", "output", "cached", "total"}
        assert all(v == 0 for v in d.values())


class TestTokenStatsRecord:
    def test_single_record(self):
        stats = TokenStats()
        stats.record(100, 50, 30)
        assert stats.input_tokens == 100
        assert stats.output_tokens == 50
        assert stats.cached_tokens == 30
        assert stats.total == 150

    def test_cumulative_record(self):
        stats = TokenStats()
        stats.record(100, 50, 30)
        stats.record(200, 80, 60)
        assert stats.input_tokens == 300
        assert stats.output_tokens == 130
        assert stats.cached_tokens == 90
        assert stats.total == 430

    def test_as_dict_after_record(self):
        stats = TokenStats()
        stats.record(100, 50, 30)
        d = stats.as_dict()
        assert d == {"input": 100, "output": 50, "cached": 30, "total": 150}

    def test_zero_record(self):
        stats = TokenStats()
        stats.record(0, 0, 0)
        assert stats.total == 0


# ── ConversationHistory 基础操作 ────────────────────────────


class TestConversationHistoryInit:
    def test_empty_on_init(self):
        h = ConversationHistory()
        assert len(h) == 0
        assert h.get_messages() == []
        assert h.last() is None


class TestConversationHistoryAppend:
    def test_append_human_message(self):
        h = ConversationHistory()
        msg = HumanMessage(content="hello")
        h.append(msg)
        assert len(h) == 1
        assert h.last() is msg

    def test_append_multiple_types(self):
        h = ConversationHistory()
        h.append(HumanMessage(content="hi"))
        h.append(AIMessage(content="hey"))
        h.append(SystemMessage(content="system"))
        assert len(h) == 3
        assert h.last().type == "system"

    def test_append_returns_none(self):
        h = ConversationHistory()
        result = h.append(HumanMessage(content="x"))
        assert result is None


class TestConversationHistoryReplaceAll:
    def test_replace_with_new_messages(self):
        h = ConversationHistory()
        h.append(HumanMessage(content="old"))
        new_msgs = [HumanMessage(content="a"), AIMessage(content="b")]
        h.replace_all(new_msgs)
        assert len(h) == 2
        assert h.get_messages()[0].content == "a"
        assert h.get_messages()[1].content == "b"

    def test_replace_makes_copy(self):
        h = ConversationHistory()
        original = [HumanMessage(content="x")]
        h.replace_all(original)
        original.append(AIMessage(content="y"))
        assert len(h) == 1

    def test_replace_with_empty(self):
        h = ConversationHistory()
        h.append(HumanMessage(content="x"))
        h.replace_all([])
        assert len(h) == 0
        assert h.last() is None


class TestConversationHistorySyncAppend:
    def test_append_different_type(self):
        h = ConversationHistory()
        h.append(HumanMessage(content="hi"))
        ai_msg = AIMessage(content="hey")
        h.sync_append(ai_msg)
        assert len(h) == 2
        assert h.last() is ai_msg

    def test_replace_same_id_ai_message(self):
        h = ConversationHistory()
        h.append(AIMessage(content="partial", id="msg1"))
        h.sync_append(AIMessage(content="updated", id="msg1"))
        assert len(h) == 1
        assert h.last().content == "updated"

    def test_no_replace_different_id_ai_messages(self):
        h = ConversationHistory()
        h.append(AIMessage(content="first", id="msg1"))
        h.sync_append(AIMessage(content="second", id="msg2"))
        assert len(h) == 2
        assert h.get_messages()[0].content == "first"
        assert h.get_messages()[1].content == "second"

    def test_replace_same_tool_call_id(self):
        h = ConversationHistory()
        h.append(ToolMessage(content="partial", tool_call_id="c1"))
        h.sync_append(ToolMessage(content="updated", tool_call_id="c1"))
        assert len(h) == 1
        assert h.last().content == "updated"

    def test_no_replace_different_tool_call_ids(self):
        h = ConversationHistory()
        h.append(ToolMessage(content="result1", tool_call_id="c1"))
        h.sync_append(ToolMessage(content="result2", tool_call_id="c2"))
        assert len(h) == 2
        assert h.get_messages()[0].content == "result1"
        assert h.get_messages()[1].content == "result2"

    def test_sync_on_empty_history(self):
        h = ConversationHistory()
        h.sync_append(HumanMessage(content="first"))
        assert len(h) == 1

    def test_tool_message_after_ai_replaced(self):
        h = ConversationHistory()
        h.append(AIMessage(content=""))
        tool_msg = ToolMessage(content="result", tool_call_id="c1")
        h.sync_append(tool_msg)
        assert len(h) == 2
        assert h.last().type == "tool"

    def test_no_id_messages_always_append(self):
        h = ConversationHistory()
        h.sync_append(HumanMessage(content="a"))
        h.sync_append(HumanMessage(content="b"))
        assert len(h) == 2
        assert h.get_messages()[0].content == "a"
        assert h.get_messages()[1].content == "b"

    def test_consecutive_ai_with_tool_calls_preserved(self):
        h = ConversationHistory()
        h.sync_append(AIMessage(content="", id="tc_msg", tool_calls=[
            {"name": "terminal", "args": {"command": "ls"}, "id": "c1", "type": "tool_call"},
        ]))
        h.sync_append(AIMessage(content="", id="meta_msg", response_metadata={"token_usage": {}}))
        assert len(h) == 2


class TestConversationHistoryClear:
    def test_clear_resets_messages(self):
        h = ConversationHistory()
        h.append(HumanMessage(content="a"))
        h.append(AIMessage(content="b"))
        h.clear()
        assert len(h) == 0
        assert h.last() is None

    def test_clear_preserves_token_stats(self):
        h = ConversationHistory()
        h.token_stats.record(100, 50, 30)
        h.clear()
        assert h.token_stats.total == 150


class TestConversationHistoryLast:
    def test_last_returns_none_when_empty(self):
        h = ConversationHistory()
        assert h.last() is None

    def test_last_returns_latest(self):
        h = ConversationHistory()
        h.append(HumanMessage(content="first"))
        h.append(AIMessage(content="second"))
        assert h.last().content == "second"


class TestConversationHistoryGetMessages:
    def test_returns_internal_list_reference(self):
        h = ConversationHistory()
        h.append(HumanMessage(content="x"))
        msgs = h.get_messages()
        assert msgs is h._messages

    def test_reflects_changes(self):
        h = ConversationHistory()
        h.append(HumanMessage(content="a"))
        assert len(h.get_messages()) == 1
        h.append(AIMessage(content="b"))
        assert len(h.get_messages()) == 2


# ── ConversationHistory + TokenStats 集成 ──────────────────


class TestConversationHistoryTokenStats:
    def test_token_stats_accessible(self):
        h = ConversationHistory()
        assert isinstance(h.token_stats, TokenStats)

    def test_record_via_history(self):
        h = ConversationHistory()
        h.token_stats.record(500, 200, 100)
        assert h.token_stats.as_dict() == {
            "input": 500, "output": 200, "cached": 100, "total": 700,
        }


# ── export_log ──────────────────────────────────────────────


class TestConversationHistoryExportLog:
    def test_export_creates_file(self, tmp_path):
        h = ConversationHistory()
        h.append(HumanMessage(content="hello"))
        h.append(AIMessage(content="world"))
        path = h.export_log(tmp_path)
        assert Path(path).exists()
        assert Path(path).suffix == ".json"

    def test_export_json_structure(self, tmp_path):
        h = ConversationHistory()
        h.append(HumanMessage(content="hi"))
        path = h.export_log(tmp_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["type"] == "human"
        assert data[0]["content"] == "hi"
        assert "timestamp" in data[0]

    def test_export_timestamp_from_append_time(self, tmp_path):
        h = ConversationHistory()
        h.append(HumanMessage(content="first"))
        h.append(AIMessage(content="second"))
        path = h.export_log(tmp_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        ts1 = data[0]["timestamp"]
        ts2 = data[1]["timestamp"]
        assert ts1 != ""
        assert ts2 != ""
        assert "T" in ts1

    def test_export_multiple_messages(self, tmp_path):
        h = ConversationHistory()
        h.append(HumanMessage(content="q"))
        h.append(AIMessage(content="a"))
        path = h.export_log(tmp_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 2
        assert data[0]["type"] == "human"
        assert data[1]["type"] == "ai"

    def test_export_preserves_tool_calls(self, tmp_path):
        h = ConversationHistory()
        h.append(AIMessage(
            content="",
            tool_calls=[{"name": "terminal", "args": {"command": "ls"}, "id": "c1", "type": "tool_call"}],
        ))
        path = h.export_log(tmp_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data[0]["tool_calls"]) == 1
        assert data[0]["tool_calls"][0]["name"] == "terminal"

    def test_export_preserves_additional_kwargs(self, tmp_path):
        h = ConversationHistory()
        h.append(AIMessage(content="thinking", additional_kwargs={"reasoning_content": "step 1"}))
        path = h.export_log(tmp_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["additional_kwargs"]["reasoning_content"] == "step 1"

    def test_export_preserves_name(self, tmp_path):
        h = ConversationHistory()
        h.append(ToolMessage(content="result", name="terminal", tool_call_id="c1"))
        path = h.export_log(tmp_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["name"] == "terminal"

    def test_export_empty_history(self, tmp_path):
        h = ConversationHistory()
        path = h.export_log(tmp_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data == []

    def test_export_ensures_parent_dir(self, tmp_path):
        h = ConversationHistory()
        h.append(HumanMessage(content="x"))
        nested = tmp_path / "a" / "b"
        path = h.export_log(nested)
        assert Path(path).exists()

    def test_export_utf8_content(self, tmp_path):
        h = ConversationHistory()
        h.append(HumanMessage(content="你好世界 🌍"))
        path = h.export_log(tmp_path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data[0]["content"] == "你好世界 🌍"


# ── _apply_strategy 预留 ────────────────────────────────────


class TestApplyStrategyNoop:
    def test_no_truncation_on_append(self):
        h = ConversationHistory()
        for i in range(100):
            h.append(HumanMessage(content=str(i)))
        assert len(h) == 100

    def test_no_truncation_on_replace_all(self):
        h = ConversationHistory()
        msgs = [HumanMessage(content=str(i)) for i in range(100)]
        h.replace_all(msgs)
        assert len(h) == 100