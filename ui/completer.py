"""/ 命令自动补全组件。"""

from textual.widgets import Input, Label, ListItem, ListView


class CommandCompleter:
    """为输入框提供 / 命令自动补全下拉框。"""

    def __init__(
        self,
        app,
        commands: dict[str, tuple[str, str]],
        container_id: str = "#completions",
        list_id: str = "#completion-list",
        input_id: str = "#input",
    ) -> None:
        self.app = app
        self.commands = commands
        self._container_id = container_id
        self._list_id = list_id
        self._input_id = input_id
        self._applying = False

    # ── 公共 API ──

    def on_input_changed(self, value: str) -> None:
        """输入变化时更新补全框。"""
        if self._applying:
            return
        if value.startswith("/") and " " not in value:
            self._show(value)
        else:
            self.hide()

    def apply(self, item: ListItem) -> None:
        """将选中的命令填充到输入框。"""
        self._applying = True
        try:
            cmd = item.name or ""
            input_w = self._input
            self.hide()
            input_w.value = cmd + " "
            input_w.cursor_position = len(input_w.value)
            input_w.focus()
        finally:
            self._applying = False

    def hide(self) -> None:
        """隐藏补全框。"""
        self._container.styles.display = "none"

    @property
    def visible(self) -> bool:
        return self._container.styles.display != "none"

    @property
    def highlighted(self) -> ListItem | None:
        return self._list_view.highlighted_child

    def move_cursor(self, direction: str) -> None:
        """上下移动高亮项。"""
        if direction == "down":
            self._list_view.action_cursor_down()
        elif direction == "up":
            self._list_view.action_cursor_up()

    # ── 内部辅助 ──

    def _show(self, prefix: str) -> None:
        matches = [
            (cmd, desc) for cmd, (_, desc, _) in self.commands.items() if cmd.startswith(prefix)
        ]
        if not matches:
            self.hide()
            return

        list_view = self._list_view
        list_view.clear()
        for cmd, desc in matches:
            list_view.append(ListItem(Label(f"{cmd:<12} {desc}"), name=cmd))

        self._container.styles.display = "block"

    @property
    def _container(self):
        return self.app.query_one(self._container_id)

    @property
    def _list_view(self) -> ListView:
        return self.app.query_one(self._list_id, ListView)

    @property
    def _input(self) -> Input:
        return self.app.query_one(self._input_id, Input)