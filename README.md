<p align="center">
  <img src="https://img.shields.io/badge/🐾%20Claw-v2.0-1a73e8" alt="Claw">
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

项目根目录的 `.env` 文件已包含配置模板，填入你的 Key 即可：

```env
# 选择模型：deepseek（默认）或 qwen
MAIN_MODEL=deepseek

# DeepSeek 配置
DEEPSEEK_API_KEY=sk-你的key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat

# Qwen（通义千问）配置
DASHSCOPE_API_KEY=sk-你的key
QWEN_MODEL=qwen-plus
```

### 3️⃣ 运行

```bash
# TUI 交互模式（默认）
python Claw.py

# 单次查询模式
python Claw.py "帮我分析一下 Summer.csv"
```

---

## 🧠 模型切换

在 `.env` 中修改 `MAIN_MODEL` 即可切换：

| 模型 | `MAIN_MODEL` 值 | API Key |
|------|----------------|---------|
| **DeepSeek** | `deepseek`（默认） | `DEEPSEEK_API_KEY` |
| **Qwen 通义千问** | `qwen` | `DASHSCOPE_API_KEY` |

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
QWEN_MODEL=qwen-plus                 # 可选: qwen-plus, qwen-turbo, qwen-max
```

---

## 🏗️ 项目架构

```
DataClaw_g14_co/
├── Claw.py                 # 主入口：Agent 创建、模型路由、对话管理
├── tui.py                  # TUI 兼容入口
├── background_loop.py      # 后台定时任务调度器
├── memory_manager.py       # 记忆管理（短期日志 + 长期记忆自动提取）
├── skills_scanner.py       # 技能扫描与提示词生成
├── core/
│   └── path_utils.py       # 统一路径解析与沙盒校验
├── tools/                  # Agent 工具集
├── skills/                 # 声明式技能（SKILL.md）
├── tasks/                  # 后台定时任务
├── memory/                 # 记忆存储（IDENTITY/SOUL/USER/MEMORY.md + 日志）
├── ui/                     # Textual TUI 界面
└── output/                 # 分析输出目录
```

---

## 🛠️ 可用工具

### 基础工具

| 工具 | 能力 | 说明 |
|------|------|------|
| 💻 **terminal** | 沙盒 Shell 执行 | 文件操作、安装依赖、运行脚本，30s 超时保护，危险命令拦截 |
| 🐍 **python_repl** | Python REPL | 计算、数据处理、代码执行，代码黑名单防护 |
| 📁 **file_info** | 文件信息查询 | 获取文件大小、行数等概要信息 |
| 📖 **read_file** | 文件读取（沙盒） | 分块读取（offset/limit），全量读取限制 100KB |
| 📖 **read_skill** | 技能文件读取 | 读取 skills/ 目录下的技能定义文件 |
| 🧠 **write_memory** | 记忆写入 | 记录用户偏好、兴趣、项目信息到记忆文件，跨会话持久化 |

### 夏季环境数据分析工具

| 工具 | 说明 |
|------|------|
| 🌡️ **summer_load_data** | 加载 Summer.csv 并返回数据概况 |
| 📊 **summer_get_statistics** | 描述性统计摘要（温度、湿度、光照、CO₂） |
| 🔍 **summer_detect_anomalies** | IQR 异常检测 + 夜间光照异常检查 |
| 🔗 **summer_get_correlation** | 传感器间相关性分析 |
| 📈 **summer_generate_chart** | 生成指定类型图表（8种可选） |
| 🚀 **summer_run_full_analysis** | 一键完整分析：统计 + 异常 + 8张图表 + 报告 |

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

---

## 🎯 内置技能

| 技能 | 功能 |
|------|------|
| 📊 **ml_code_runner** | 数据科学：机器学习/统计学习/深度学习代码逐步执行 |
| 🌡️ **summer_data_mining** | 夏季温室环境数据挖掘：统计分析、异常检测、可视化与报告生成 |

---

<p align="center">
  <b>🐾 DataClaw — 终端 AI 智能体</b>
</p>