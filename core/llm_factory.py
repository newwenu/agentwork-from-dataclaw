"""LLM Factory — 根据配置创建对应的 LLM 实例。

支持三种模式：
- live:  真实 API 调用（DeepSeek / Qwen），消耗 token
- mock:  本地 Mock LLM，零 token，支持工具绑定，适合开发调试
- proxy: 通过 OpenAI 兼容接口转发到 model_server，零真实 token

使用方式：
    from core.llm_factory import create_llm
    llm = create_llm(config)
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolCall
from langchain_core.outputs import ChatGeneration, ChatResult

from core.config import ClawConfig

_SCENARIOS_DIR = Path(__file__).resolve().parent.parent / ".mock" / "mock_scenarios.yaml"


def _load_all_scenarios(path: Path | str | None = None) -> dict[str, list[str | dict]]:
    """从 YAML 文件加载全部场景，返回 {场景名: 回复序列} 映射。"""
    import yaml

    file_path = Path(path) if path else _SCENARIOS_DIR
    if not file_path.exists():
        return {}

    with open(file_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        return {}

    result: dict[str, list[str | dict]] = {}
    for name, steps in raw.items():
        responses: list[str | dict] = []
        for step in steps:
            if "tool" in step:
                responses.append({"tool": step["tool"], "args": step.get("args", {})})
            else:
                responses.append(step.get("text", ""))
        result[name] = responses

    return result


class MockChatModel(BaseChatModel):
    """支持工具绑定的 Mock LLM — 零 token 消耗，兼容 create_react_agent。

    自动加载 .mock/mock_scenarios.yaml 中的场景，用户输入匹配场景名时
    自动切换到对应回复序列（含工具调用），否则返回默认文本。

    触发规则：用户输入中包含场景名即触发，如输入 "terminal_test" 或
    "帮我跑一下terminal_test" 都会匹配 terminal_test 场景。

    也可在代码中直接指定 responses：
        MockChatModel(responses=[
            {"tool": "terminal", "args": {"command": "echo hello"}},
            "命令执行成功",
        ])
    """

    responses: list[str | dict] = []
    _bound_tools: list[Any] | None = None
    _scenarios: dict[str, list[str | dict]] = {}
    _active_responses: list[str | dict] | None = None
    _active_count: int = 0

    def model_post_init(self, __context: Any) -> None:
        self._scenarios = _load_all_scenarios()

    def _match_scenario(self, user_input: str) -> list[str | dict] | None:
        if not self._scenarios or not user_input:
            return None
        text = user_input.lower().strip()
        for name, responses in self._scenarios.items():
            if name.lower() in text:
                return responses
        return None

    @property
    def _llm_type(self) -> str:
        return "mock-chat-model"

    def _make_tool_call(self, spec: dict) -> AIMessage:
        name = spec["tool"]
        args = spec.get("args", {})
        call_id = spec.get("id", f"call_{uuid.uuid4().hex[:8]}")
        return AIMessage(
            content="",
            tool_calls=[ToolCall(name=name, args=args, id=call_id, type="tool_call")],
        )

    _DUMP_KEYWORD = "dump_prompt"

    def _format_messages(self, messages: list[BaseMessage]) -> str:
        """将消息列表格式化为可读文本，用于 dump_prompt 场景。"""
        lines: list[str] = []
        for i, msg in enumerate(messages):
            role = msg.type.upper()
            content = msg.content or ""
            tc = getattr(msg, "tool_calls", [])
            if tc:
                for tc_item in tc:
                    lines.append(f"[{i}] {role} → tool_call: {tc_item['name']}({tc_item['args']})")
            elif content:
                lines.append(f"[{i}] {role} ({len(content)}字):\n{content}")
        total_chars = sum(len(m.content or "") for m in messages)
        header = f"=== 收到 {len(messages)} 条消息，共 {total_chars:,} 字 ==="
        return f"{header}\n" + "\n".join(lines)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_human = ""
        for msg in reversed(messages):
            if msg.type == "human":
                last_human = msg.content
                break

        if self._DUMP_KEYWORD in last_human.lower():
            message = AIMessage(content=self._format_messages(messages))
            return ChatResult(generations=[ChatGeneration(message=message)])

        matched = self._match_scenario(last_human)
        if matched is not None and self._active_responses is not matched:
            self._active_responses = matched
            self._active_count = 0

        if self._active_responses is not None:
            idx = self._active_count % len(self._active_responses)
            self._active_count += 1
            response = self._active_responses[idx]
            if self._active_count >= len(self._active_responses):
                self._active_responses = None
        elif self.responses:
            idx = self._active_count % len(self.responses)
            self._active_count += 1
            response = self.responses[idx]
        else:
            response = "收到。"

        if isinstance(response, dict):
            message = self._make_tool_call(response)
        else:
            message = AIMessage(content=response)

        generation = ChatGeneration(message=message)
        return ChatResult(generations=[generation])

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
        self._bound_tools = tools
        return self


def _create_mock_llm(config: ClawConfig) -> BaseChatModel:
    """创建 Mock LLM — 零 token 消耗，支持工具绑定。

    使用内置默认回复。如需自定义场景，在测试代码中用 load_scenario() 加载。
    """
    return MockChatModel()


def _create_proxy_llm(config: ClawConfig) -> BaseChatModel:
    """创建 Proxy LLM — 通过 OpenAI 兼容接口转发到 model_server。"""
    from langchain_openai import ChatOpenAI

    model_name = config.deepseek_model
    if config.main_model == "qwen":
        model_name = config.qwen_model

    return ChatOpenAI(
        model=model_name,
        base_url=config.llm_proxy_url,
        api_key="mock-key",
        temperature=config.agent_temperature,
    )


def _create_live_llm(config: ClawConfig) -> BaseChatModel:
    """创建 Live LLM — 真实 API 调用，消耗 token。"""
    if config.main_model == "qwen":
        from langchain_community.chat_models import ChatTongyi

        if not config.dashscope_api_key or config.dashscope_api_key.strip() in ("sk-", ""):
            raise ValueError("DASHSCOPE_API_KEY 未正确配置（不能为空或占位符 'sk-'）")
        return ChatTongyi(
            model=config.qwen_model,
            dashscope_api_key=config.dashscope_api_key,
            temperature=config.agent_temperature,
        )
    else:
        from langchain_deepseek import ChatDeepSeek

        if not config.deepseek_api_key or config.deepseek_api_key.strip() in ("sk-", ""):
            raise ValueError("DEEPSEEK_API_KEY 未正确配置（不能为空或占位符 'sk-'）")
        return ChatDeepSeek(
            model=config.deepseek_model,
            api_key=config.deepseek_api_key,
            base_url=config.deepseek_base_url,
            temperature=config.agent_temperature,
        )


def create_llm(config: ClawConfig) -> BaseChatModel:
    """根据配置创建 LLM 实例。"""
    mode = config.llm_mode.strip().lower()

    if mode == "mock":
        return _create_mock_llm(config)
    elif mode == "proxy":
        return _create_proxy_llm(config)
    elif mode == "live":
        return _create_live_llm(config)
    else:
        raise ValueError(
            f"未知的 LLM_MODE: {config.llm_mode!r}，可选值: live / mock / proxy"
        )
