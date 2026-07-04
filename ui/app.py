"""DataClaw Textual TUI 主应用。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, ListView, RichLog, Static
from textual.worker import Worker, WorkerState

from ui.capture import BackgroundCapture
from ui.chat import ChatView
from ui.commands import COMMANDS, CommandHandler
from ui.completer import CommandCompleter
from core.config import get_config

if TYPE_CHECKING:
    from Claw import CoreClawAgent


class DataClawApp(App):
    """DataClaw 主 TUI 应用。"""

    TITLE = "DataClaw"
    CSS_PATH = Path(__file__).parent / "styles.tcss"

    def __init__(self, agent: CoreClawAgent, capture: BackgroundCapture) -> None:
        super().__init__()
        self.agent = agent
        self.capture = capture
        self._handler = CommandHandler(self, agent)
        self._completer = CommandCompleter(self, COMMANDS)
        self._history: list[str] = []
        self._history_index: int = -1
        self._suppress_completion: bool = False
        self._last_prefix: str = ""
        self._log_user_pref: bool | None = None
        self._raw_log_lines: list[str] = []
        self._raw_log_max = 500
        self._rewrite_timer = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="chat-panel"):
                model = getattr(self.agent.llm, 'model_name', None) or getattr(self.agent.llm, 'model', 'Unknown')
                welcome = (
                    f"[bold green]🐾 DataClaw 已启动[/]\n"
                    f"[dim]模型:[/] [cyan]{model}[/]  [dim]工具:[/] [cyan]{len(self.agent.tools)}[/] 个\n"
                    f"[dim]输入 /help 查看命令，/log 切换日志面板，输入 / 触发自动补全[/]"
                )
                yield ChatView(id="chat", welcome=welcome)
            with Vertical(id="log-panel"):
                yield RichLog(id="task-list", markup=True, max_lines=100, wrap=True, min_width=1)
                yield RichLog(id="task-log", highlight=True, markup=True, max_lines=500, wrap=True, min_width=1)
        with Vertical(id="input-area"):
            with Vertical(id="completions"):
                completion_list = ListView(id="completion-list")
                completion_list.can_focus = False
                yield completion_list
            with Horizontal(id="input-container"):
                yield Static("❯", id="input-label")
                yield Input(id="input", placeholder="输入消息...（/help 查看命令）")
            with Horizontal(id="status-bar"):
                yield Static(id="status-left")
                yield Static(id="status-center")
                yield Static(id="status-right")

    async def on_mount(self) -> None:
        # Textual 会在 app.run() 内部覆盖 sys.stdout，需要在启动后再次替换
        sys.stdout = self.capture

        # 启动后台任务（延迟到事件循环就绪后）
        if not self.agent._bg_started:
            self.agent.bg_loop.start()
            self.agent._bg_started = True

        self.query_one("#input", Input).focus()
        self._update_status()
        self._update_task_list()
        self._apply_log_visibility()
        if not self.query_one("#log-panel").display and self._log_user_pref is None:
            chat = self.query_one("#chat", ChatView)
            chat.add_system("[dim]⚠️ 终端较窄，日志面板已自动隐藏。输入 /log 可手动开启[/]")
        self.set_interval(1, self._refresh_task_log)
        self.set_interval(1, self._update_status)
        self.set_interval(5, self._update_task_list)

    def _apply_log_visibility(self) -> bool:
        """根据终端宽度和用户偏好决定日志面板显隐。

        返回面板是否刚刚变为可见（用于触发重写）。

        逻辑：
        - 用户手动 /log 切换后，记住偏好（True=开/False=关），始终尊重
        - 自动模式下（_log_user_pref is None）：
          - 终端宽度 < tui_log_min_width 时自动隐藏
          - 终端宽度 >= tui_log_min_width 时自动显示
        """
        try:
            term_width = self.console.size.width
        except Exception:
            term_width = 120
        log_panel = self.query_one("#log-panel")
        min_width = get_config().tui_log_min_width
        was_visible = log_panel.display

        if self._log_user_pref is not None:
            log_panel.display = self._log_user_pref
        elif term_width < min_width:
            log_panel.display = False
        else:
            log_panel.display = True

        return log_panel.display and not was_visible

    def _rewrite_all_logs(self) -> None:
        """清空 RichLog 并从 _raw_log_lines 重写所有日志行（用于宽度变化时重排）。"""
        log = self.query_one("#task-log", RichLog)
        log.clear()
        for display_line in self._raw_log_lines:
            log.write(f"[dim]{display_line}[/]")

    def _schedule_rewrite(self) -> None:
        """防抖式安排日志重写：取消上一次定时器后再安排新的。"""
        if self._rewrite_timer is not None:
            self._rewrite_timer.stop()
        self._rewrite_timer = self.set_timer(0.05, self._rewrite_all_logs)

    def on_resize(self, event) -> None:
        just_visible = self._apply_log_visibility()
        if just_visible or self.query_one("#log-panel").display:
            self._schedule_rewrite()

    def _update_status(self) -> None:
        model = getattr(self.agent.llm, 'model_name', None) or getattr(self.agent.llm, 'model', 'Unknown')
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#status-left", Static).update(f"🤖 {model}")
        stats = self.agent.history.token_stats
        if stats.total > 0:
            self.query_one("#status-center", Static).update(f"📊 {stats.total:,} tokens (缓存 {stats.cached_tokens:,})")
        else:
            self.query_one("#status-center", Static).update("")
        self.query_one("#status-right", Static).update(f"⏰ {now}")

    def _refresh_task_log(self) -> None:
        lines = self.capture.drain()
        if not lines:
            return

        formatted: list[str] = []
        for line in lines:
            prefix = ""
            content = line
            if line.startswith("[") and "]" in line:
                end = line.index("]") + 1
                prefix = line[:end]
                content = line[end:].strip()

            display_prefix = "↳" if prefix and prefix == self._last_prefix else prefix
            self._last_prefix = prefix
            display_line = f"{display_prefix} {content}" if display_prefix else content
            formatted.append(display_line)

        self._raw_log_lines.extend(formatted)
        if len(self._raw_log_lines) > self._raw_log_max:
            self._raw_log_lines = self._raw_log_lines[-self._raw_log_max:]

        log_panel = self.query_one("#log-panel")
        if log_panel.display:
            log = self.query_one("#task-log", RichLog)
            for display_line in formatted:
                log.write(f"[dim]{display_line}[/]")

    def _update_task_list(self) -> None:
        task_list = self.query_one("#task-list", RichLog)
        task_list.clear()
        tasks = self.agent.bg_loop.list_tasks()
        if tasks:
            task_list.write("[bold]⏰ 定时任务[/]")
            for task in tasks:
                status = "🟢" if task["running"] else "🔴"
                interval_m = task["interval"] / 60
                interval_str = f"{int(interval_m)}分钟" if interval_m >= 1 else f"{int(task['interval'])}秒"
                task_list.write(f"{status} [cyan]{task['name']}[/] 每{interval_str}")
        else:
            task_list.write("[dim]暂无任务[/]")

    def _cancel_current(self) -> list[str]:
        """取消当前正在执行的工具和对话流，返回用于展示的消息列表。"""
        messages: list[str] = []

        # 1. 取消工具层正在执行的命令（terminal / python_repl 等）
        for tool in self.agent.tools:
            if hasattr(tool, "cancel"):
                result = tool.cancel()
                if result:
                    messages.append(result)

        # 2. 取消 Textual 工作线程中的对话流
        cancelled_worker = False
        for worker in self.workers:
            if worker.state in (WorkerState.RUNNING, WorkerState.PENDING):
                worker.cancel()
                cancelled_worker = True
        if cancelled_worker:
            messages.append("✅ 已取消当前对话流")

        return messages

    # ── 事件路由 ──

    def on_input_changed(self, event: Input.Changed) -> None:
        # 历史导航导致的 value 变更不触发补全框
        if self._suppress_completion:
            self._suppress_completion = False
            self._completer.hide()
            return
        self._completer.on_input_changed(event.value)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._completer.apply(event.item)

    def _add_to_history(self, text: str) -> None:
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
        self._history_index = len(self._history)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        input_w = self.query_one("#input", Input)

        if not text:
            input_w.clear()
            return

        # 补全框可见且用户按回车时：根据命令是否需要参数决定行为
        # - 无参数命令：补全后直接发送
        # - 需参数命令（如 /workdir）：只填充到输入框，不发送，等用户输入参数
        if self._completer.visible:
            highlighted = self._completer.highlighted
            if highlighted is not None:
                cmd = highlighted.name or ""
                if text != cmd and not text.startswith(cmd + " "):
                    entry = COMMANDS.get(cmd)
                    needs_arg = entry[2] if entry else False
                    if needs_arg:
                        self._completer.apply(highlighted)
                        return
                    text = cmd
            self._completer.hide()

        input_w.clear()

        # 写入对话栏并发送
        self._add_to_history(text)
        chat = self.query_one("#chat", ChatView)
        chat.add_user(text)

        # 命令分发
        if text.startswith("/"):
            if self._handler.dispatch(chat, text):
                return

        self._stream_response(text)

    @work(exclusive=True, exit_on_error=False)
    async def _stream_response(self, text: str) -> None:
        chat = self.query_one("#chat", ChatView)
        chat.add_ai()

        try:
            current_response = ""
            async for event in self.agent.stream_chat_with_events(text):
                if event["type"] == "tool_call":
                    chat.add_tool_call(event["name"], event["args"], event.get("id", ""))
                elif event["type"] == "tool_result":
                    content = str(event.get("content", ""))
                    if not content:
                        content = "(无输出)"
                    chat.add_tool_result(content, event.get("tool_call_id", ""))
                elif event["type"] == "reasoning":
                    chat.set_ai_reasoning(event["content"])
                    chat._scroll_to_end()
                elif event["type"] == "thinking":
                    new_content = event["content"]
                    if new_content.startswith(current_response):
                        delta = new_content[len(current_response):]
                        if delta:
                            chat.append_ai(delta)
                            chat._scroll_to_end()
                        current_response = new_content
                    else:
                        chat.set_ai_content(new_content)
                        chat._scroll_to_end()
                        current_response = new_content
                elif event["type"] == "final":
                    final_content = event["content"]
                    if final_content != current_response:
                        chat.set_ai_content(final_content)
                        chat._scroll_to_end()
                    current_response = final_content
                    # 回复完成后收起思维链，避免历史消息占用空间
                    chat.collapse_ai_reasoning()
                    # 显示本次 token 消耗
                    token_usage = event.get("token_usage", {})
                    if token_usage and token_usage.get("total", 0) > 0:
                        chat.set_ai_token_usage(token_usage)
                        self._update_status()
        except Exception as e:
            chat.add_system(f"[red]❌ 错误: {e}[/]")

    def on_unmount(self) -> None:
        self.agent.close()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.ERROR:
            chat = self.query_one("#chat", ChatView)
            chat.add_system(f"[red]❌ 工作线程错误: {event.error}[/]")

    def on_key(self, event) -> None:
        if event.key == "ctrl+d":
            self.exit()
            return

        input_w = self.query_one("#input", Input)

        # 补全框可见时，方向键/Tab/Esc 优先给补全框
        if self._completer.visible:
            if event.key == "down":
                self._completer.move_cursor("down")
                event.stop()
                return
            elif event.key == "up":
                self._completer.move_cursor("up")
                event.stop()
                return
            elif event.key == "tab":
                highlighted = self._completer.highlighted
                if highlighted is not None:
                    self._completer.apply(highlighted)
                event.stop()
                return
            elif event.key == "escape":
                # Esc 优先级：补全框可见时先隐藏补全；否则执行取消
                if self._completer.visible:
                    self._completer.hide()
                    event.stop()
                    return
                messages = self._cancel_current()
                chat = self.query_one("#chat", ChatView)
                if messages:
                    chat.add_system("[yellow]" + "\n".join(messages) + "[/]")
                else:
                    chat.add_system("[dim]⚠️ 没有正在执行的操作[/]")
                event.stop()
                return

        # Ctrl+C: 有运行中进程时等效 /cancel，否则保持默认行为
        if event.key == "ctrl+c":
            messages = self._cancel_current()
            if messages:
                chat = self.query_one("#chat", ChatView)
                chat.add_system("[yellow]" + "\n".join(messages) + "[/]")
                event.stop()
            return

        # 历史记录导航（加载历史项时抑制补全框弹出）
        if event.key == "up":
            if self._history and self._history_index > 0:
                self._suppress_completion = True
                self._completer.hide()
                self._history_index -= 1
                input_w.value = self._history[self._history_index]
                input_w.cursor_position = len(input_w.value)
            event.stop()
        elif event.key == "down":
            self._suppress_completion = True
            self._completer.hide()
            if self._history and self._history_index < len(self._history) - 1:
                self._history_index += 1
                input_w.value = self._history[self._history_index]
                input_w.cursor_position = len(input_w.value)
            else:
                self._history_index = len(self._history)
                input_w.value = ""
            event.stop()


def run_tui(agent: CoreClawAgent) -> None:
    """启动 Textual TUI（替换原有 interactive_mode）。"""
    capture = BackgroundCapture(echo=False)
    sys.stdout = capture

    app = DataClawApp(agent, capture)
    try:
        app.run()
    except Exception as e:
        sys.stdout = capture._real_stdout
        print(f"❌ TUI 错误: {e}")
        raise
    finally:
        sys.stdout = capture._real_stdout
        agent.close()