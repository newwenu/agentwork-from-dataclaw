<p align="center">
  <img src="https://img.shields.io/badge/🐾%20Claw-v3.0-1a73e8" alt="Claw">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue">
  <img src="https://img.shields.io/badge/LLM-DeepSeek%20%7C%20Qwen-brightgreen">
</p>

<h1 align="center">🐾 DataClaw — 易扩展的终端智能体</h1>

---

## 🚀 快速使用

### 1️⃣ 安装依赖

```bash
pip install -r requirements.txt
```

### 2️⃣ 配置 API Key

项目根目录的 `.env` 文件已包含配置模板（参考 `.env_default`改名为 `.env` ），填入你的 Key 即可：

```env
# 选择模型：deepseek（默认）或 qwen
MAIN_MODEL=deepseek

# DeepSeek 配置
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# Qwen（通义千问）配置
DASHSCOPE_API_KEY=sk-你的key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus

# 记忆系统配置
MEMORY_EXTRACTION=false          # LLM 记忆提取（消耗 API 调用，默认关闭）
MEMORY_INJECT_LONG_TERM=false    # 长期记忆注入 system prompt
MEMORY_LLM_COOLDOWN=30           # 记忆提取最小间隔（秒）

# Agent 配置
AGENT_TEMPERATURE=0.2            # LLM 温度（0.0 确定性 ~ 1.0 创造性）
```

### 3️⃣ 运行

```bash
# TUI 交互模式（默认）
python Claw.py

# 单次查询模式
python Claw.py "帮我分析一下 Summer.csv"
```

> ⚠️ **集成终端 Emoji 渲染提示**：在 VS Code 等IDE的集成终端中运行时，部分 Emoji 字符可能出现显示异常造成界面出现错位的情况。如遇此问题，建议使用系统原生终端（如 Windows Terminal、macOS Terminal）运行。

---

## 🧠 模型切换

在 `.env` 中修改 `MAIN_MODEL` 即可切换：

| 模型 | `MAIN_MODEL` 值 | API Key |
|------|----------------|---------|
| **DeepSeek** | `deepseek`（默认） | `DEEPSEEK_API_KEY` |
| **Qwen 通义千问** | `qwen` | `DASHSCOPE_API_KEY` |

### LLM 运行模式

通过 `LLM_MODE` 环境变量切换运行模式（默认 `live`）：

| 模式 | `LLM_MODE` 值 | 说明 |
|------|--------------|------|
| **live** | `live`（默认） | 真实 API 调用，消耗 token |
| **mock** | `mock` | 本地模拟，零 token，支持工具绑定与场景驱动，适合开发调试 |
| **proxy** | `proxy` | 通过 OpenAI 兼容接口转发到 model_server |

---

## 🔑 API Key 获取

### DeepSeek

| 项目 | 说明 |
|------|------|
| **申请地址** | [https://platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys) |
| **步骤** | 注册/登录 → 控制台 → API Keys → 创建 → 复制 `sk-...` |
| **费用** | 新用户有免费额度，后续按量计费 |

```env
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat        # 可选: deepseek-chat, deepseek-reasoner
```

### Qwen（通义千问）

| 项目 | 说明 |
|------|------|
| **申请地址** | [https://bailian.console.aliyun.com/](https://bailian.console.aliyun.com/) |
| **步骤** | 登录阿里云 → 百炼控制台 → API-KEY 管理 → 创建 → 复制 `sk-...` |
| **费用** | 新用户有免费额度，按量计费 |

```env
DASHSCOPE_API_KEY=sk-你的key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus                 # 可选: qwen-plus, qwen-turbo, qwen-max
```

---

## 🏗️ 项目架构

```
DataClaw_g14_co/
├── Claw.py                 # 主入口：Agent 创建、模型路由、对话管理
├── tui.py                  # TUI 兼容入口（转发到 ui/ 包）
├── background_loop.py      # 后台定时任务调度器
├── memory_manager.py       # 记忆管理（短期日志 + 长期记忆自动提取）
├── skills_scanner.py       # 技能扫描与提示词生成
├── core/
│   ├── config.py           # pydantic-settings 配置中心
│   ├── conversation_history.py  # 会话历史管理 + token 统计
│   ├── llm_factory.py      # LLM 工厂（live/mock/proxy 三模式）
│   ├── path_utils.py       # 统一路径解析与沙盒校验
│   └── prompt_builder.py   # System Prompt 组装（身份+性格+技能+记忆）
├── tools/                  # Agent 工具集
│   ├── terminal_tool.py    # 沙盒 Shell 执行（白名单+黑名单+路径校验）
│   ├── python_repl_tool.py # Python REPL（代码黑名单防护）
│   ├── read_file_tool.py   # 文件读取与信息查询
│   ├── write_memory_tool.py # 记忆写入
│   └── summer_analysis_tool.py  # 夏季环境数据分析工具集
├── skills/                 # 声明式技能（SKILL.md）
├── tasks/                  # 后台定时任务
├── memory/                 # 记忆存储（IDENTITY/SOUL/USER/MEMORY.md + 日志）
├── ui/                     # Textual TUI 界面
│   ├── app.py              # 主应用 + 流式对话
│   ├── chat.py             # 聊天视图
│   ├── commands.py         # 斜杠命令注册表与处理
│   ├── completer.py        # 命令自动补全
│   └── styles.tcss         # TUI 样式
└── output/                 # 分析输出目录
```

---

## 🛠️ 可用工具

### 基础工具

| 工具 | 能力 | 说明 |
|------|------|------|
| 💻 **terminal** | 沙盒 Shell 执行 | 文件操作、安装依赖、运行脚本，30s 超时保护，危险命令拦截 |
| 🐍 **python_repl** | Python REPL | 计算、数据处理、代码执行，代码黑名单防护 |
| 📁 **get_file_info** | 文件信息查询 | 获取文件大小、行数等概要信息 |
| 📖 **read_file** | 文件读取（沙盒） | 分块读取（offset/limit），全量读取限制 100KB |
| 📖 **read_skill_file** | 技能文件读取 | 读取 skills/ 目录下的技能定义文件 |
| 🗑️ **delete_file** | 文件删除（安全） | 将文件移入 .trash/ 目录（非永久删除），支持恢复 |
| 🧠 **write_memory** | 记忆写入 | 记录用户偏好、兴趣、项目信息到记忆文件，跨会话持久化 |

### 夏季环境数据分析工具

通过 `summer_analysis` 工具的 `action` 参数调用不同功能：

| action | 说明 |
|--------|------|
| 🌡️ **load** | 加载 Summer.csv 并返回数据概况 |
| 📊 **statistics** | 描述性统计摘要（温度、湿度、光照、CO₂） |
| 🔍 **anomaly** | IQR 异常检测 + 夜间光照异常检查 |
| 🔗 **correlation** | 传感器间相关性分析 |
| 📈 **chart** | 生成指定类型图表（8种可选） |
| 🚀 **full** | 一键完整分析：统计 + 异常 + 8张图表 + 报告 |

---

## 💬 TUI 命令

在 TUI 交互模式中，输入 `/` 触发命令自动补全：

| 命令 | 功能 |
|------|------|
| `/help` | 查看命令列表 |
| `/quit` | 退出 |
| `/clear` | 清除对话历史 |
| `/cancel` | 中止当前工具调用或对话流 |
| `/tools` | 查看可用工具列表 |
| `/skills` | 查看已加载的技能 |
| `/memory` | 查看记忆文件状态 |
| `/task` | 查看运行中的定时任务 |
| `/workdir` | 设置工作目录 |
| `/export` | 导出对话日志 |
| `/log` | 切换日志面板显隐 |

---

## 🎯 内置技能

| 技能 | 功能 |
|------|------|
| 📊 **Data_Analysis** | 数据科学：机器学习/统计学习/深度学习代码逐步执行 |
| 🌡️ **summer_data_mining** | 夏季温室环境数据挖掘：统计分析、异常检测、可视化与报告生成 |

---

<p align="center">
  <b>🐾 DataClaw — 终端 AI 智能体</b>
</p>