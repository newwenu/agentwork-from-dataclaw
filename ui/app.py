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
from ui.commands import COMMANDS, CommandHandler
from ui.completer import CommandCompleter

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
        self._ignore_completion_count: int = 0  # 忽略来自历史导航的输入变更事件
        self._last_prefix: str = ""  # 上一条日志的前缀，用于缩写

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="chat-panel"):
                yield RichLog(id="chat", highlight=True, markup=True, max_lines=1000, wrap=True)
            with Vertical(id="log-panel"):
                yield RichLog(id="task-list", markup=True, max_lines=100, wrap=True)
                yield RichLog(id="task-log", highlight=True, markup=True, max_lines=500, wrap=True)
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
        self.set_interval(1, self._refresh_task_log)
        self.set_interval(1, self._update_status)
        self.set_interval(5, self._update_task_list)

        model = getattr(self.agent.llm, 'model_name', None) or getattr(self.agent.llm, 'model', 'Unknown')
        self.query_one("#chat", RichLog).write(
            f"[bold green]🐾 DataClaw 已启动[/]\n"
            f"[dim]模型:[/] [cyan]{model}[/]  [dim]工具:[/] [cyan]{len(self.agent.tools)}[/] 个\n"
            f"[dim]输入 /help 查看命令，输入 / 触发自动补全[/]\n"
        )

    def _update_status(self) -> None:
        model = getattr(self.agent.llm, 'model_name', None) or getattr(self.agent.llm, 'model', 'Unknown')
        now = datetime.now().strftime("%H:%M:%S")
        self.query_one("#status-left", Static).update(f"🤖 {model}")
        self.query_one("#status-center", Static).update("")
        self.query_one("#status-right", Static).update(f"⏰ {now}")

    def _refresh_task_log(self) -> None:
        log = self.query_one("#task-log", RichLog)
        lines = self.capture.drain()
        if not lines:
            return

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

            max_width = 32
            if len(display_line) > max_width:
                words = display_line.split(' ')
                current_line = ""
                for word in words:
                    if len(current_line) + len(word) + 1 > max_width:
                        log.write(f"[dim]{current_line}[/]")
                        current_line = word
                    else:
                        current_line += " " + word if current_line else word
                if current_line:
                    log.write(f"[dim]{current_line}[/]")
            else:
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

    def _chat_write(self, text: str) -> None:
        self.call_from_thread(self.query_one("#chat", RichLog).write, text)

    # ── 事件路由 ──

    def on_input_changed(self, event: Input.Changed) -> None:
        # 历史导航导致的 value 变更不触发补全框
        if self._ignore_completion_count > 0:
            self._ignore_completion_count -= 1
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
        input_w.clear()

        if not text:
            return

        # 补全框可见时，优先处理高亮项。
        # 若用户只输入了部分前缀，先补全但不写入对话栏；
        # 若已输入完整命令，则隐藏补全框并继续执行。
        if self._completer.visible:
            highlighted = self._completer.highlighted
            if highlighted is not None:
                cmd = highlighted.name or ""
                if text != cmd and not text.startswith(cmd + " "):
                    self._completer.apply(highlighted)
                    return
            self._completer.hide()

        # 确定不是补全操作后，才写入对话栏
        self._add_to_history(text)
        chat = self.query_one("#chat", RichLog)
        chat.write(f"\n[bold cyan]👤 You:[/] {text}")

        # 命令分发
        if text.startswith("/"):
            if self._handler.dispatch(chat, text):
                return

        self._stream_response(text)

    @work(exclusive=True, exit_on_error=False)
    async def _stream_response(self, text: str) -> None:
        chat = self.query_one("#chat", RichLog)
        chat.write("[bold green]🤖 CoreClaw:[/]")

        try:
            current_response = ""
            async for event in self.agent.stream_chat_with_events(text):
                if event["type"] == "tool_call":
                    chat.write(f"  [yellow]🔧 {event['name']}({event['args']})[/]")
                elif event["type"] == "tool_result":
                    content = str(event.get("content", ""))[:300]
                    if content:
                        chat.write(f"  [dim]→ {content}[/]")
                elif event["type"] == "thinking":
                    new_content = event["content"]
                    if new_content.startswith(current_response):
                        delta = new_content[len(current_response):]
                        if delta:
                            chat.write(delta)
                        current_response = new_content
                    else:
                        chat.clear()
                        chat.write("[bold green]🤖 CoreClaw:[/]\n")
                        chat.write(new_content)
                        current_response = new_content
                elif event["type"] == "final":
                    if event["content"] != current_response:
                        chat.write(event["content"][len(current_response):])
                    chat.write("\n")
        except Exception as e:
            chat.write(f"[red]❌ 错误: {e}[/]")

    def on_unmount(self) -> None:
        self.agent.close()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.ERROR:
            chat = self.query_one("#chat", RichLog)
            chat.write(f"[red]❌ 工作线程错误: {event.error}[/]")

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
                chat = self.query_one("#chat", RichLog)
                if messages:
                    chat.write("[yellow]" + "\n".join(messages) + "[/]")
                else:
                    chat.write("[dim]⚠️ 没有正在执行的操作[/]")
                event.stop()
                return

        # Ctrl+C: 有运行中进程时等效 /cancel，否则保持默认行为
        if event.key == "ctrl+c":
            messages = self._cancel_current()
            if messages:
                chat = self.query_one("#chat", RichLog)
                chat.write("[yellow]" + "\n".join(messages) + "[/]")
                event.stop()
            return

        # 历史记录导航（加载历史项时忽略随之而来的输入变更事件，避免补全框弹出）
        if event.key == "up":
            if self._history and self._history_index > 0:
                self._ignore_completion_count += 1
                self._completer.hide()
                self._history_index -= 1
                input_w.value = self._history[self._history_index]
                input_w.cursor_position = len(input_w.value)
            event.stop()
        elif event.key == "down":
            self._ignore_completion_count += 1
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
