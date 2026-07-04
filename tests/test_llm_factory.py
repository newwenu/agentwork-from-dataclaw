"""LLM Factory 测试 — 验证三种 LLM 模式的创建逻辑和场景自动匹配。"""

import os
import tempfile
import pytest

from langchain_core.messages import HumanMessage

from core.config import ClawConfig, reload_config
from core.llm_factory import create_llm, MockChatModel, _load_all_scenarios


@pytest.fixture(autouse=True)
def _reset_config():
    yield
    reload_config()


class TestMockMode:
    def test_creates_mock_chat_model(self):
        cfg = ClawConfig(llm_mode="mock")
        llm = create_llm(cfg)
        assert llm is not None
        result = llm.invoke("hello")
        assert result.content

    def test_no_api_key_required(self):
        cfg = ClawConfig(llm_mode="mock", deepseek_api_key="", dashscope_api_key="")
        llm = create_llm(cfg)
        assert llm is not None

    def test_validate_skipped(self):
        cfg = ClawConfig(llm_mode="mock", deepseek_api_key="")
        assert cfg.validate_api_keys() == []


class TestMockChatModelToolCall:
    def test_text_response(self):
        llm = MockChatModel(responses=["hello"])
        result = llm.invoke("hi")
        assert result.content == "hello"
        assert result.tool_calls == []

    def test_tool_call_response(self):
        llm = MockChatModel(responses=[
            {"tool": "terminal", "args": {"command": "echo test"}},
            "done",
        ])
        r1 = llm.invoke("run")
        assert r1.content == ""
        assert len(r1.tool_calls) == 1
        assert r1.tool_calls[0]["name"] == "terminal"
        assert r1.tool_calls[0]["args"] == {"command": "echo test"}

        r2 = llm.invoke("then")
        assert r2.content == "done"
        assert r2.tool_calls == []

    def test_bind_tools_returns_self(self):
        llm = MockChatModel()
        bound = llm.bind_tools([])
        assert bound is llm

    def test_responses_cycle(self):
        llm = MockChatModel(responses=["a", "b"])
        assert llm.invoke("1").content == "a"
        assert llm.invoke("2").content == "b"
        assert llm.invoke("3").content == "a"


class TestScenarioAutoMatch:
    def test_input_matches_scenario(self):
        llm = MockChatModel()
        llm._scenarios = {"terminal_test": [
            {"tool": "terminal", "args": {"command": "echo hi"}},
            "done",
        ]}
        r = llm.invoke("帮我跑一下terminal_test")
        assert len(r.tool_calls) == 1
        assert r.tool_calls[0]["name"] == "terminal"

    def test_exact_name_match(self):
        llm = MockChatModel()
        llm._scenarios = {"python_test": [
            {"tool": "python_repl", "args": {"query": "print(1)"}},
            "ok",
        ]}
        r = llm.invoke("python_test")
        assert r.tool_calls[0]["name"] == "python_repl"

    def test_no_match_uses_default(self):
        llm = MockChatModel()
        llm._scenarios = {"terminal_test": [{"tool": "terminal", "args": {}}]}
        r = llm.invoke("普通对话")
        assert r.tool_calls == []
        assert r.content

    def test_multi_step_scenario(self):
        llm = MockChatModel()
        llm._scenarios = {"multi_step": [
            {"tool": "terminal", "args": {"command": "dir"}},
            {"tool": "python_repl", "args": {"query": "1+1"}},
            "all done",
        ]}
        r1 = llm.invoke("multi_step")
        assert r1.tool_calls[0]["name"] == "terminal"

        r2 = llm.invoke("继续")
        assert r2.tool_calls[0]["name"] == "python_repl"

        r3 = llm.invoke("继续")
        assert r3.content == "all done"
        assert r3.tool_calls == []

    def test_case_insensitive_match(self):
        llm = MockChatModel()
        llm._scenarios = {"Terminal_Test": [{"tool": "terminal", "args": {}}]}
        r = llm.invoke("terminal_test")
        assert r.tool_calls[0]["name"] == "terminal"


class TestDumpPrompt:
    def test_dump_prompt_returns_messages(self):
        from langchain_core.messages import SystemMessage, HumanMessage as HM
        llm = MockChatModel()
        msgs = [
            SystemMessage(content="你是DataClaw助手"),
            HM(content="dump_prompt"),
        ]
        result = llm.invoke(msgs)
        assert "收到 2 条消息" in result.content
        assert "SYSTEM" in result.content
        assert "HUMAN" in result.content
        assert "DataClaw" in result.content

    def test_dump_prompt_in_user_input(self):
        llm = MockChatModel()
        r = llm.invoke("帮我dump_prompt看看")
        assert "收到" in r.content

    def test_dump_prompt_shows_tool_calls(self):
        from langchain_core.messages import SystemMessage, HumanMessage as HM, AIMessage
        llm = MockChatModel()
        msgs = [
            SystemMessage(content="system"),
            HM(content="test"),
            AIMessage(content="", tool_calls=[{"name": "terminal", "args": {"command": "ls"}, "id": "c1", "type": "tool_call"}]),
            HM(content="dump_prompt"),
        ]
        result = llm.invoke(msgs)
        assert "tool_call: terminal" in result.content

    def test_dump_prompt_shows_full_content(self):
        from langchain_core.messages import HumanMessage as HM
        llm = MockChatModel()
        long_text = "x" * 1000
        result = llm.invoke([HM(content=long_text), HM(content="dump_prompt")])
        assert "x" * 1000 in result.content


class TestLoadAllScenarios:
    def test_loads_from_yaml(self):
        scenarios = _load_all_scenarios()
        assert isinstance(scenarios, dict)
        if scenarios:
            assert "terminal_test" in scenarios
            assert scenarios["terminal_test"][0]["tool"] == "terminal"

    def test_missing_file_returns_empty(self):
        scenarios = _load_all_scenarios(path="/nonexistent/file.yaml")
        assert scenarios == {}

    def test_custom_yaml_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write("my_test:\n  - text: 'custom response'\n  - tool: terminal\n    args:\n      command: ls\n")
            f.flush()
            scenarios = _load_all_scenarios(path=f.name)
            assert "my_test" in scenarios
            assert scenarios["my_test"][0] == "custom response"
            assert scenarios["my_test"][1]["tool"] == "terminal"
        os.unlink(f.name)


class TestProxyMode:
    def test_creates_chat_openai(self):
        cfg = ClawConfig(llm_mode="proxy", llm_proxy_url="http://127.0.0.1:8000/v1")
        llm = create_llm(cfg)
        assert llm is not None

    def test_validate_skipped(self):
        cfg = ClawConfig(llm_mode="proxy", deepseek_api_key="")
        assert cfg.validate_api_keys() == []


class TestLiveMode:
    def test_deepseek_with_valid_key(self):
        cfg = ClawConfig(
            llm_mode="live",
            main_model="deepseek",
            deepseek_api_key="sk-real-test-key-12345",
        )
        llm = create_llm(cfg)
        assert llm is not None

    def test_qwen_with_valid_key(self):
        cfg = ClawConfig(
            llm_mode="live",
            main_model="qwen",
            dashscope_api_key="sk-real-test-key-12345",
        )
        llm = create_llm(cfg)
        assert llm is not None

    def test_deepseek_missing_key_raises(self):
        cfg = ClawConfig(llm_mode="live", main_model="deepseek", deepseek_api_key="")
        with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
            create_llm(cfg)

    def test_qwen_missing_key_raises(self):
        cfg = ClawConfig(llm_mode="live", main_model="qwen", dashscope_api_key="")
        with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
            create_llm(cfg)

    def test_deepseek_placeholder_key_raises(self):
        cfg = ClawConfig(llm_mode="live", main_model="deepseek", deepseek_api_key="sk-")
        with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
            create_llm(cfg)

    def test_validate_catches_missing_key(self):
        cfg = ClawConfig(llm_mode="live", main_model="deepseek", deepseek_api_key="")
        errors = cfg.validate_api_keys()
        assert len(errors) > 0


class TestInvalidMode:
    def test_unknown_mode_raises(self):
        cfg = ClawConfig(llm_mode="nonexistent")
        with pytest.raises(ValueError, match="未知的 LLM_MODE"):
            create_llm(cfg)