# DataClaw 开发文档

> 面向开发者的快速参考。

---

## 1. 项目简介

DataClaw 是基于 LangGraph ReAct Agent 的终端智能体，核心能力：

- 大模型对话（DeepSeek / Qwen）
- 工具调用（终端、Python REPL、文件读写、数据分析等）
- 声明式技能系统（`skills/*/SKILL.md`）
- 会话历史 + 长期记忆管理
- 后台定时任务
- Textual TUI 交互界面

---

## 2. 目录结构

```
DataClaw_g14_co/
├── Claw.py                  # 主入口：组装 Agent、启动 TUI/单次查询
├── tui.py                   # TUI 兼容入口（转发到 ui/ 包）
├── background_loop.py       # 后台定时任务调度器
├── memory_manager.py        # 聊天记录日志 + 长期记忆监听/提取
├── skills_scanner.py        # 扫描 skills/ 并生成 system prompt
├── core/
│   ├── config.py            # pydantic-settings 配置中心
│   ├── conversation_history.py  # 会话历史 + token 统计
│   ├── llm_factory.py       # live / mock / proxy 三种 LLM 模式
│   ├── path_utils.py        # 沙盒路径解析
│   └── prompt_builder.py    # system prompt 组装
├── tools/
│   ├── __init__.py          # get_all_tools() 工厂
│   ├── terminal_tool.py     # 沙盒 shell
│   ├── python_repl_tool.py  # Python REPL
│   ├── read_file_tool.py    # 文件读取 / 文件信息 / 技能文件读取
│   ├── delete_file_tool.py  # 安全删除（移入 .trash/）
│   ├── write_memory_tool.py # 写入记忆
│   └── summer_analysis_tool.py  # 夏季环境数据分析
├── skills/                  # 声明式技能（每个子目录含 SKILL.md）
├── tasks/
│   ├── __init__.py          # scan_tasks() 任务扫描器
│   ├── check_temperature_warning.py
│   └── say_hello_task.py
├── memory/                  # 记忆存储（IDENTITY/SOUL/USER/MEMORY.md）
├── ui/                      # Textual TUI（app/chat/commands/completer/capture/styles.tcss）
├── tests/                   # 单元测试
├── requirements.txt
└── .env.example
```

---

## 3. 协作流程（Fork → Clone → PR）

### 3.1 Fork 仓库

1. 在 GitHub 上打开原仓库页面
2. 点击右上角 **Fork** 按钮
3. 选择你的账号作为 Fork 目标，确认创建

Fork 后你会在自己的 GitHub 账号下得到一份副本，例如：
`https://github.com/你的用户名/agentwork-from-dataclaw.git`

### 3.2 克隆到本地

```bash
git clone https://github.com/你的用户名/agentwork-from-dataclaw.git
cd agentwork-from-dataclaw/DataClaw_g14_co
```

添加上游仓库，方便后续同步原仓库的更新：

```bash
git remote add upstream https://github.com/newwenu/agentwork-from-dataclaw.git
```

验证远程仓库配置：

```bash
git remote -v
# origin    https://github.com/你的用户名/agentwork-from-dataclaw.git (fetch)
# origin    https://github.com/你的用户名/agentwork-from-dataclaw.git (push)
# upstream  https://github.com/newwenu/agentwork-from-dataclaw.git (fetch)
# upstream  https://github.com/newwenu/agentwork-from-dataclaw.git (push)
```

### 3.3 开发与提交

每次开发新功能或修复 Bug 前，先从 upstream 拉取最新代码：

```bash
git checkout main
git fetch upstream
git merge upstream/main
```

在独立分支上开发：

```bash
git checkout -b feature/你的功能名
# 或 git checkout -b fix/你的修复名
```

开发完成后提交：

```bash
git add .
git commit -m "简要描述本次改动"
```

### 3.4 提交 Pull Request

1. 将分支推送到你的 Fork：

```bash
git push origin feature/你的功能名
```

2. 在 GitHub 上打开你的 Fork 页面，会看到 **Compare & pull request** 提示
3. 点击它，填写 PR 标题和描述：
   - **标题**：简明概括改动内容（如 `feat: 添加 XXX 工具` 或 `fix: 修复 XXX 去重问题`）
   - **描述**：说明改了什么、为什么改、如何测试
4. 确认目标分支是原仓库的 `main`，提交 PR

### 3.5 同步上游更新

当原仓库有新提交时，同步到本地：

```bash
git checkout main
git fetch upstream
git merge upstream/main
git push origin main
```

---

## 4. 快速运行

```bash
pip install -r requirements.txt
cp .env.example .env          # 填入真实 API Key
python Claw.py                # TUI 模式
python Claw.py "帮我分析 Summer.csv"  # 单次查询
```

`.env` 最小配置：

```env
MAIN_MODEL=deepseek
DEEPSEEK_API_KEY=sk-你的key
```

或使用 Qwen：

```env
MAIN_MODEL=qwen
DASHSCOPE_API_KEY=sk-你的key
```

无 API Key 时设 `LLM_MODE=mock` 即可本地调试（见 [mock_mode.md](./mock_mode.md)）。

---

## 5. 核心模块

### 5.1 Agent 组装流程（Claw.py）

1. `get_config()` 加载配置
2. `validate_api_keys()` 校验 API Key（mock/proxy 模式跳过）
3. `create_llm(config)` 根据 `LLM_MODE` 创建 LLM
4. `MemoryManager` 初始化并启动日志监听
5. `build_system_prompt()` 拼接 IDENTITY/SOUL/Skills/USER/MEMORY
6. `create_react_agent()` 创建 LangGraph Agent
7. 进入 TUI 或执行单次查询

### 5.2 配置项（core/config.py）

| 环境变量 | 说明 | 默认值 |
|----------|------|--------|
| `MAIN_MODEL` | 主模型：`deepseek` / `qwen` | `deepseek` |
| `LLM_MODE` | 运行模式：`live` / `mock` / `proxy` | `live` |
| `LLM_PROXY_URL` | proxy 模式转发地址 | `http://127.0.0.1:8000/v1` |
| `DEEPSEEK_API_KEY` / `BASE_URL` / `MODEL` | DeepSeek 配置 | - |
| `DASHSCOPE_API_KEY` / `BASE_URL` / `QWEN_MODEL` | Qwen 配置 | - |
| `MEMORY_EXTRACTION` | 是否启用 LLM 自动提取记忆 | `false` |
| `MEMORY_INJECT_LONG_TERM` | 是否将 MEMORY.md 注入 system prompt | `false` |
| `MEMORY_LLM_COOLDOWN` | 记忆提取最小间隔（秒） | `30` |
| `AGENT_TEMPERATURE` | LLM temperature | `0.2` |
| `TUI_LOG_MIN_WIDTH` | 日志面板最小宽度阈值 | `80` |

### 5.3 LLM 模式（core/llm_factory.py）

- **live**：真实 API，消耗 token
- **mock**：本地 MockChatModel，支持工具绑定，按 YAML 场景响应
- **proxy**：通过 OpenAI 兼容接口转发到本地 model_server

### 5.4 路径沙盒（core/path_utils.py）

所有文件工具必须调用 `resolve_under(root, file_path)`，规则：

- 禁止 `..`、null 字节、符号链接
- 禁止访问 `root/.trash/`
- 返回严格位于 `root` 下的绝对路径

---

## 6. 如何添加工具

1. 在 `tools/` 下新建 `.py`，定义 `BaseTool` 子类（`name`、`description`、`args_schema`、`_run()`）
2. 在 `tools/__init__.py` 的 `get_all_tools()` 中注册

```python
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

class MyToolInput(BaseModel):
    arg: str = Field(description="参数说明")

class MyTool(BaseTool):
    name: str = "my_tool"
    description: str = "工具描述"
    args_schema: type[BaseModel] = MyToolInput

    def _run(self, arg: str) -> str:
        return f"result: {arg}"
```

安全提示：文件系统操作用 `resolve_under`；代码执行加黑名单/超时；不信任 LLM 参数。

---

## 7. 如何添加技能

1. 在 `skills/` 下新建目录，创建 `SKILL.md`
2. 文件顶部写入元数据：

```markdown
name: my_skill
description: 技能简短描述

# 技能标题

## 角色定位
...

## 执行步骤
1. ...
```

3. 重启 Agent 后自动扫描加载；Agent 匹配到技能时会调用 `read_skill_file` 读取该文件

---

## 8. 如何添加后台任务

1. 在 `tasks/` 下新建 `.py` 文件，定义 `name`、`interval`、`run()`：

```python
name = "我的任务"
interval = 60  # 秒，范围 [1, 86400]
description = "任务描述"

async def run():
    print("[任务:我的任务] 执行中...")
```

2. 重启 Agent，`tasks/__init__.py` 的 `scan_tasks()` 会自动扫描，`BackgroundLoop` 注册并启动
3. TUI 中输入 `/task` 查看状态

注意：`BackgroundLoop` 还内置了 `check_skills` 和 `auto_save_memory` 两个任务。

---

## 9. TUI 命令

| 命令 | 功能 |
|------|------|
| `/help` | 命令列表 |
| `/clear` | 清除对话历史 |
| `/cancel` | 取消当前工具/对话流 |
| `/tools` | 查看可用工具 |
| `/skills` | 查看已加载技能 |
| `/memory` | 查看记忆文件 |
| `/task` | 查看后台任务 |
| `/workdir <路径>` | 设置工作目录 |
| `/export` | 导出对话日志 |
| `/log` | 切换日志面板显隐 |
| `/quit` | 退出 |

快捷键：`↑/↓` 历史导航、`Tab` 补全、`Esc`/`Ctrl+C` 取消、`Ctrl+D` 退出。

---

## 10. 测试

```bash
pytest tests/
```

覆盖：config、conversation_history、llm_factory、path_utils、prompt_builder、delete_file_tool、python_repl_safety、terminal_safety、skills_scanner。

---

## 11. 安全约束速查

| 模块 | 关键约束 |
|------|----------|
| 终端工具 | 白名单命令、禁止管道/元字符、禁止删除命令、路径沙盒、30s 超时 |
| Python REPL | 黑名单（os/subprocess/sys/socket/urllib/eval/exec/open）、代码长度 ≤8000、30s 超时 |
| 文件读取 | 必须位于工作目录内、默认分块、全量 ≤100KB、禁止 `.trash/` |
| 文件删除 | 仅移入 `.trash/`、单文件、路径沙盒 |
| 数据分析 | 输入/输出目录均受沙盒限制 |
| 路径工具 | 禁止 `..`、null 字节、符号链接 |

---

## 12. 开发建议

1. 修改代码前确认相关测试存在或补充测试
2. 新增工具/技能/任务后用 `/tools`、`/skills`、`/task` 验证
3. 复杂改动先用 `LLM_MODE=mock` 调试
4. 不要提交 `.env`、`output/`、`.trash/`、`memory/logs/`、`Summer.csv`、`.mock/`
