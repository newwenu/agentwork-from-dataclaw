"""对话区组件：用独立消息 Widget 替代 RichLog。"""

from __future__ import annotations

from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Collapsible, Static


class ChatMessage(Horizontal):
    """单条对话消息，左侧固定宽度头像，右侧弹性气泡容器包裹内容。

    所有样式统一在 styles.tcss 中定义，此处不再重复 DEFAULT_CSS，
    避免两处样式不一致导致特异性冲突或属性遗漏。
    """

    def __init__(
        self,
        sender: str,
        icon: str,
        content: str = "",
        classes: str | None = None,
        extra_widgets: list[Widget] | None = None,
        extra_widgets_after: list[Widget] | None = None,
        *,
        body_markup: bool = False,
    ) -> None:
        self.sender = sender
        self.icon = icon
        self._content = content

        # 左侧固定宽度头像
        avatar = Static(self.icon, classes="message-avatar", shrink=False)

        # 右侧气泡容器：宽度由父容器决定（1fr）
        sender_static = Static(self.sender, classes="message-sender", shrink=False)
        header = Horizontal(sender_static, classes="message-header")

        # 消息体：expand/shrink 都开启，让宽度完全由气泡容器决定，
        # 避免 emoji 等宽字符通过"最优宽度"撑开布局。
        # markup=False 避免用户输入中的 { } [ ] 被 Rich 误解析为 markup 标签。
        self._body = Static(
            content, classes="message-body", expand=True, shrink=True, markup=body_markup
        )
        if not content:
            self._body.display = False

        bubble_children: list[Widget] = [header]
        if extra_widgets:
            bubble_children.extend(extra_widgets)
        bubble_children.append(self._body)
        if extra_widgets_after:
            bubble_children.extend(extra_widgets_after)
        bubble = Vertical(*bubble_children, classes="message-bubble")

        super().__init__(avatar, bubble, classes=classes)

    def set_content(self, text: str) -> None:
        self._content = text
        self._body.update(self._content)
        self._body.display = bool(text)

    def append_content(self, text: str) -> None:
        self.set_content(self._content + text)

    @property
    def content(self) -> str:
        return self._content


class UserMessage(ChatMessage):
    """用户消息。"""

    def __init__(self, content: str = "") -> None:
        super().__init__("You", "👤", content, classes="user-message")


class AIMessage(ChatMessage):
    """AI 回复消息，支持可折叠思维链。

    思维链样式统一在 styles.tcss 中定义。
    """

    def __init__(self, content: str = "") -> None:
        self._reasoning_content = ""
        self._reasoning_body = Static("", classes="reasoning-body", markup=False)
        self._reasoning = Collapsible(
            self._reasoning_body,
            title="🧠 思维链",
            collapsed=False,
            classes="reasoning-section",
        )
        # 初始没有思维链时隐藏折叠面板
        self._reasoning.display = False
        super().__init__(
            "DataClaw",
            "🤖",
            content,
            classes="ai-message",
            extra_widgets=[self._reasoning],
        )

    def set_reasoning(self, text: str) -> None:
        """设置思维链完整内容（流式更新时使用）。"""
        self._reasoning_content = text
        self._reasoning_body.update(self._reasoning_content)
        if self._reasoning_content:
            self._reasoning.display = True
            self._update_reasoning_title()

    def append_reasoning(self, text: str) -> None:
        """追加思维链内容。"""
        self.set_reasoning(self._reasoning_content + text)

    def collapse_reasoning(self) -> None:
        """收起思维链。"""
        self._reasoning.collapsed = True

    def expand_reasoning(self) -> None:
        """展开思维链。"""
        self._reasoning.collapsed = False

    @property
    def has_reasoning(self) -> bool:
        return bool(self._reasoning_content)

    def _update_reasoning_title(self) -> None:
        lines = self._reasoning_content.strip().split("\n")
        preview = lines[0][:24] if lines[0] else "🧠 思维链"
        if len(lines[0]) > 24:
            preview += "..."
        self._reasoning.title = f"🧠 思维链 · {preview}"

    def set_token_usage(self, usage: dict) -> None:
        """在消息头部显示 token 消耗信息。"""
        total = usage.get("total", 0)
        cached = usage.get("cached", 0)
        output = usage.get("output", 0)
        if total == 0:
            return
        parts = [f"📊 {total:,} tokens"]
        if cached > 0:
            parts.append(f"{cached:,}")
        parts.append(f"输出 {output:,}")
        sender_widget = self.query_one(".message-sender", Static)
        sender_widget.update(f"DataClaw  [dim]{' · '.join(parts)}[/]")


class ToolMessage(ChatMessage):
    """工具调用消息，调用结果可折叠，避免长输出占用过多空间。

    工具结果样式统一在 styles.tcss 中定义。
    """

    def __init__(self, name: str = "", args: object = None, tool_call_id: str = "") -> None:
        self._tool_name = name
        self._tool_args = args
        self._tool_call_id = tool_call_id
        self._result = ""
        self._args_collapsible = False

        self._args_preview = Static("", classes="tool-args-preview", markup=False)
        self._args_preview.display = False
        self._args_body = Static("", classes="tool-args-body", markup=False)

        self._result_body = Static("", classes="tool-result-body", markup=False)
        self._result_scroll = VerticalScroll(
            self._result_body,
            classes="tool-result-scroll",
        )
        self._collapse_link = Static("↑ 收起", classes="tool-result-collapse")
        self._result_container = Vertical(
            self._result_scroll,
            self._collapse_link,
            classes="tool-result-container",
        )
        self._result_section = Collapsible(
            self._result_container,
            title="📄 结果",
            collapsed=True,
            classes="tool-result-section",
        )
        self._result_section.display = False
        super().__init__(
            name or "Tool",
            "🔧",
            "",
            classes="tool-message",
            extra_widgets=[self._args_preview, self._args_body],
            extra_widgets_after=[self._result_section],
        )
        self._update_args()

    def _format_args(self) -> str:
        import json

        if self._tool_name == "python_repl" and isinstance(self._tool_args, dict):
            code = self._tool_args.get("code") or self._tool_args.get("query")
            if code:
                return str(code)

        try:
            raw = json.dumps(self._tool_args, ensure_ascii=False, indent=2)
        except Exception:
            return str(self._tool_args)

        if isinstance(self._tool_args, dict) and raw.startswith("{\n") and raw.endswith("\n}"):
            lines = raw.splitlines()
            return "\n".join(lines[1:-1])
        return raw

    def _make_args_preview(self, max_lines: int = 3) -> str:
        text = self._format_args().strip()
        lines = [l for l in text.splitlines() if l.strip()]
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] += " …"
        return "\n".join(lines)

    def _update_args(self) -> None:
        args_text = self._format_args()
        if not args_text.strip():
            self._args_preview.display = False
            self._args_body.display = False
            return

        lines = args_text.strip().splitlines()
        self._args_collapsible = len(lines) > 3

        if self._args_collapsible:
            self._args_preview.display = True
            self._args_preview.update(self._make_args_preview())
            self._args_body.display = False
            self._args_body.update(args_text)
        else:
            self._args_preview.display = False
            self._args_body.display = True
            self._args_body.update(args_text)

    def _toggle_args(self) -> None:
        if not self._args_collapsible:
            return
        expanded = self._args_body.display
        if expanded:
            self._args_body.display = False
            self._args_preview.update(self._make_args_preview())
        else:
            self._args_body.display = True
            self._args_preview.update("[dim]── ▲ 收起 ──[/]")

    def _make_preview(self, content: str, max_lines: int = 2, max_chars: int = 80) -> str:
        """从结果内容生成简短预览文本（单行，用于嵌入标题）。"""
        text = content.strip().replace("\n", " ")
        truncated = False
        if len(text) > max_chars:
            text = text[:max_chars]
            truncated = True
        if truncated:
            text += " …"
        return text

    def _update_result_title(self) -> None:
        """根据折叠状态更新标题：收起时显示预览，展开时只显示标题。"""
        if not self._result:
            self._result_section.title = "📄 结果"
            return
        if self._result_section.collapsed:
            preview = self._make_preview(self._result)
            self._result_section.title = f"📄 结果  [dim italic]{preview}[/]"
        else:
            self._result_section.title = "📄 结果"

    def set_result(self, content: str) -> None:
        self._result = content
        self._result_body.update(self._result)
        if self._result:
            self._result_section.display = True
            self._update_result_title()

    def append_result(self, content: str) -> None:
        self.set_result(self._result + content)

    def on_click(self, event) -> None:
        clicked = getattr(event, "control", None) or getattr(event, "widget", None)
        if clicked is self._collapse_link:
            self._result_section.collapsed = True
            self._update_result_title()
        elif clicked is self._args_preview:
            self._toggle_args()

    def on_collapsible_expanded(self, event: Collapsible.Expanded) -> None:
        if event.collapsible is self._result_section:
            self._result_section.title = "📄 结果"

    def on_collapsible_collapsed(self, event: Collapsible.Collapsed) -> None:
        if event.collapsible is self._result_section:
            self._update_result_title()


class SystemMessage(ChatMessage):
    """系统提示消息，保留 Rich markup 支持着色（如 [red]错误[/]）。"""

    def __init__(self, content: str = "") -> None:
        super().__init__("System", "·", content, classes="system-message", body_markup=True)


class ChatView(VerticalScroll):
    """对话区容器，管理消息列表并自动滚动到底部。

    样式统一在 styles.tcss 中定义。
    """

    def __init__(self, welcome: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._welcome = welcome
        self._current_ai: AIMessage | None = None
        self._current_tool: ToolMessage | None = None
        self._tools_by_id: dict[str, ToolMessage] = {}

    def on_mount(self) -> None:
        if self._welcome:
            self.add_system(self._welcome)

    def _scroll_to_end(self) -> None:
        self.scroll_end(animate=False)

    def add_user(self, text: str) -> None:
        self.mount(UserMessage(text))
        self._scroll_to_end()

    def add_ai(self, text: str = "") -> AIMessage:
        msg = AIMessage(text)
        self.mount(msg)
        self._current_ai = msg
        self._scroll_to_end()
        return msg

    def append_ai(self, text: str) -> None:
        if self._current_ai is None:
            self.add_ai(text)
        else:
            self._current_ai.append_content(text)
            self._scroll_to_end()

    def set_ai_content(self, text: str) -> None:
        if self._current_ai is None:
            self.add_ai(text)
        else:
            self._current_ai.set_content(text)
            self._scroll_to_end()

    def set_ai_reasoning(self, text: str) -> None:
        if self._current_ai is None:
            self.add_ai()
        if isinstance(self._current_ai, AIMessage):
            self._current_ai.set_reasoning(text)
            self._scroll_to_end()

    def collapse_ai_reasoning(self) -> None:
        if isinstance(self._current_ai, AIMessage):
            self._current_ai.collapse_reasoning()
            self._scroll_to_end()

    def set_ai_token_usage(self, usage: dict) -> None:
        if isinstance(self._current_ai, AIMessage):
            self._current_ai.set_token_usage(usage)

    def add_tool_call(self, name: str, args: object, tool_call_id: str = "") -> None:
        # 工具调用后，当前 AI 消息结束，后续回复应创建新消息
        self._current_ai = None
        # 将调用和结果包裹到同一条 Tool 消息中
        self._current_tool = ToolMessage(name, args, tool_call_id)
        if tool_call_id:
            self._tools_by_id[tool_call_id] = self._current_tool
        self.mount(self._current_tool)
        self._scroll_to_end()

    def add_tool_result(self, content: str, tool_call_id: str = "") -> None:
        self._current_ai = None
        # 优先通过 tool_call_id 找到对应的 ToolMessage，支持并行/多工具调用
        tool = self._tools_by_id.pop(tool_call_id, None) if tool_call_id else self._current_tool
        if tool is not None:
            tool.set_result(content)
        else:
            self._current_tool = ToolMessage()
            self._current_tool.set_result(content)
            self.mount(self._current_tool)
        self._scroll_to_end()

    def add_system(self, text: str) -> None:
        self.mount(SystemMessage(text))
        self._scroll_to_end()

    def clear_messages(self) -> None:
        self._current_ai = None
        self._current_tool = None
        self._tools_by_id.clear()
        for child in list(self.children):
            child.remove()