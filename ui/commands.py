"""TUI 斜杠命令注册表与处理器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App
    from Claw import CoreClawAgent
    from ui.chat import ChatView


# key: 命令前缀
# value: (处理函数名, 简短说明, 是否需要参数)
COMMANDS: dict[str, tuple[str, str, bool]] = {
    "/quit": ("cmd_quit", "退出", False),
    "/clear": ("cmd_clear", "清除对话历史", False),
    "/help": ("cmd_help", "查看命令", False),
    "/cancel": ("cmd_cancel", "中止当前命令或对话流", False),
    "/tools": ("cmd_tools", "查看可用工具", False),
    "/skills": ("cmd_skills", "查看技能列表", False),
    "/memory": ("cmd_memory", "查看记忆文件", False),
    "/task": ("cmd_task", "查看后台任务", False),
    "/workdir": ("cmd_workdir", "设置工作目录 <路径>", True),
    "/export": ("cmd_export", "导出对话日志", False),
    "/log": ("cmd_log", "切换日志面板显隐", False),
}


class CommandHandler:
    """处理 / 命令分发与执行。"""

    def __init__(self, app: App, agent: CoreClawAgent) -> None:
        self.app = app
        self.agent = agent

    def dispatch(self, chat: ChatView, text: str) -> bool:
        """根据命令注册表分发到对应处理函数。"""
        parts = text.split(" ", 1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        entry = COMMANDS.get(cmd)
        if not entry:
            chat.add_system(f"[red]❌ 未知命令: {cmd}[/]")
            return True

        handler_name = entry[0]
        handler = getattr(self, handler_name)
        handler(chat, text, arg)
        return True

    def cmd_quit(self, chat: ChatView, text: str, arg: str) -> None:
        self.app.exit()

    def cmd_clear(self, chat: ChatView, text: str, arg: str) -> None:
        chat.clear_messages()
        self.agent.clear_history()
        chat.add_system("[dim]✅ 对话历史已清除[/]")

    def cmd_help(self, chat: ChatView, text: str, arg: str) -> None:
        lines = ["[bold]命令列表:[/]"]
        for cmd, (_, desc, _) in COMMANDS.items():
            lines.append(f"  [cyan]{cmd:<12}[/] {desc}")
        chat.add_system("\n".join(lines))

    def cmd_cancel(self, chat: ChatView, text: str, arg: str) -> None:
        """中止当前正在执行的命令或对话流。"""
        messages = self.app._cancel_current()
        if messages:
            chat.add_system("[yellow]" + "\n".join(messages) + "[/]")
        else:
            chat.add_system("[dim]⚠️ 没有正在执行的操作[/]")

    def cmd_tools(self, chat: ChatView, text: str, arg: str) -> None:
        lines = ["[bold]🔧 可用工具:[/]"]
        for tool in self.agent.tools:
            desc = tool.description or "(no description)"
            lines.append(f"  [yellow]• {tool.name}[/]: {desc}")
        chat.add_system("\n".join(lines))

    def cmd_skills(self, chat: ChatView, text: str, arg: str) -> None:
        from skills_scanner import scan_skills
        skills = scan_skills(self.agent.base_dir / "skills")
        if skills:
            lines = [f"[bold]🎯 已加载 {len(skills)} 个技能:[/]"]
            for skill in skills:
                lines.append(f"  [green]• {skill['name']}[/]: {skill['description']}")
            chat.add_system("\n".join(lines))
        else:
            chat.add_system("[dim]📭 暂无技能[/]")

    def cmd_memory(self, chat: ChatView, text: str, arg: str) -> None:
        lines = ["[bold]🧠 记忆文件:[/]"]
        for name, path in self.agent.memory.get_memory_files().items():
            exists = "✅" if path.exists() else "❌"
            lines.append(f"  {exists} {name}: {path}")
        chat.add_system("\n".join(lines))

    def cmd_task(self, chat: ChatView, text: str, arg: str) -> None:
        tasks = self.agent.bg_loop.list_tasks()
        if tasks:
            lines = [f"[bold]⏰ 运行中的任务 ({len(tasks)} 个):[/]"]
            for task in tasks:
                status = "🟢" if task["running"] else "🔴"
                interval_m = task["interval"] / 60
                interval_str = f"{int(interval_m)}分钟" if interval_m >= 1 else f"{int(task['interval'])}秒"
                lines.append(f"  {status} {task['name']}: 每{interval_str}")
            chat.add_system("\n".join(lines))
        else:
            chat.add_system("[dim]📭 暂无运行中的任务[/]")

    def cmd_workdir(self, chat: ChatView, text: str, arg: str) -> None:
        path = arg.strip()
        if not path:
            chat.add_system("[red]❌ 用法: /workdir <路径>[/]")
            return
        result = self.agent.set_work_dir(path)
        chat.add_system(f"[dim]{result}[/]")

    def cmd_export(self, chat: ChatView, text: str, arg: str) -> None:
        path = self.agent.export_log()
        chat.add_system(f"[dim]✅ 日志已导出到: {path}[/]")

    def cmd_log(self, chat: ChatView, text: str, arg: str) -> None:
        log_panel = self.app.query_one("#log-panel")
        self.app._log_user_pref = not log_panel.display
        just_visible = self.app._apply_log_visibility()
        if just_visible:
            self.app._schedule_rewrite()
        state = "显示" if log_panel.display else "隐藏"
        chat.add_system(f"[dim]📋 日志面板已{state}[/]")