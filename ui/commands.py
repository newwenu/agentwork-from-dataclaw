"""TUI 斜杠命令注册表与处理器。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widgets import RichLog

if TYPE_CHECKING:
    from textual.app import App
    from Claw import CoreClawAgent


# key: 命令前缀
# value: (处理函数名, 简短说明)
COMMANDS: dict[str, tuple[str, str]] = {
    "/quit": ("cmd_quit", "退出"),
    "/clear": ("cmd_clear", "清除对话历史"),
    "/help": ("cmd_help", "查看命令"),
    "/cancel": ("cmd_cancel", "中止当前命令或对话流"),
    "/tools": ("cmd_tools", "查看可用工具"),
    "/skills": ("cmd_skills", "查看技能列表"),
    "/memory": ("cmd_memory", "查看记忆文件"),
    "/task": ("cmd_task", "查看后台任务"),
    "/workdir": ("cmd_workdir", "设置工作目录 <路径>"),
    "/export": ("cmd_export", "导出对话日志"),
}


class CommandHandler:
    """处理 / 命令分发与执行。"""

    def __init__(self, app: App, agent: CoreClawAgent) -> None:
        self.app = app
        self.agent = agent

    def dispatch(self, chat: RichLog, text: str) -> bool:
        """根据命令注册表分发到对应处理函数。"""
        parts = text.split(" ", 1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        entry = COMMANDS.get(cmd)
        if not entry:
            chat.write(f"[red]❌ 未知命令: {cmd}[/]")
            return True

        handler_name, _ = entry
        handler = getattr(self, handler_name)
        handler(chat, text, arg)
        return True

    def cmd_quit(self, chat: RichLog, text: str, arg: str) -> None:
        self.app.exit()

    def cmd_clear(self, chat: RichLog, text: str, arg: str) -> None:
        chat.clear()
        self.agent.clear_history()
        chat.write("[dim]✅ 对话历史已清除[/]")

    def cmd_help(self, chat: RichLog, text: str, arg: str) -> None:
        lines = ["[bold]命令列表:[/]"]
        for cmd, (_, desc) in COMMANDS.items():
            lines.append(f"  [cyan]{cmd:<12}[/] {desc}")
        chat.write("\n".join(lines))

    def cmd_cancel(self, chat: RichLog, text: str, arg: str) -> None:
        """中止当前正在执行的命令或对话流。"""
        messages = self.app._cancel_current()
        if messages:
            chat.write("[yellow]" + "\n".join(messages) + "[/]")
        else:
            chat.write("[dim]⚠️ 没有正在执行的操作[/]")

    def cmd_tools(self, chat: RichLog, text: str, arg: str) -> None:
        chat.write("[bold]🔧 可用工具:[/]")
        for tool in self.agent.tools:
            desc = tool.description or "(no description)"
            chat.write(f"  [yellow]• {tool.name}[/]: {desc}")

    def cmd_skills(self, chat: RichLog, text: str, arg: str) -> None:
        from skills_scanner import scan_skills
        skills = scan_skills(self.agent.base_dir / "skills")
        if skills:
            chat.write(f"[bold]🎯 已加载 {len(skills)} 个技能:[/]")
            for skill in skills:
                chat.write(f"  [green]• {skill['name']}[/]: {skill['description']}")
        else:
            chat.write("[dim]📭 暂无技能[/]")

    def cmd_memory(self, chat: RichLog, text: str, arg: str) -> None:
        chat.write("[bold]🧠 记忆文件:[/]")
        for name, path in self.agent.memory.get_memory_files().items():
            exists = "✅" if path.exists() else "❌"
            chat.write(f"  {exists} {name}: {path}")

    def cmd_task(self, chat: RichLog, text: str, arg: str) -> None:
        tasks = self.agent.bg_loop.list_tasks()
        if tasks:
            chat.write(f"[bold]⏰ 运行中的任务 ({len(tasks)} 个):[/]")
            for task in tasks:
                status = "🟢" if task["running"] else "🔴"
                interval_m = task["interval"] / 60
                interval_str = f"{int(interval_m)}分钟" if interval_m >= 1 else f"{int(task['interval'])}秒"
                chat.write(f"  {status} {task['name']}: 每{interval_str}")
        else:
            chat.write("[dim]📭 暂无运行中的任务[/]")

    def cmd_workdir(self, chat: RichLog, text: str, arg: str) -> None:
        path = arg.strip()
        if not path:
            chat.write("[red]❌ 用法: /workdir <路径>[/]")
            return
        result = self.agent.set_work_dir(path)
        chat.write(f"[dim]{result}[/]")

    def cmd_export(self, chat: RichLog, text: str, arg: str) -> None:
        path = self.agent.export_log()
        chat.write(f"[dim]✅ 日志已导出到: {path}[/]")
