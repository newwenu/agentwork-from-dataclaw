# Mock 模式使用文档

> 零 token 消耗的本地调试模式。

---

## 1. 启用

`.env` 中设置：

```env
LLM_MODE=mock
```

然后正常运行 `python Claw.py`。Mock 模式下不校验 API Key，不调用真实大模型，所有回复由本地 `MockChatModel` 生成。

---

## 2. 默认行为

- 未配置场景时，对任意输入返回固定文本：`收到。`
- 完全兼容 `create_react_agent`，支持工具绑定
- 记忆提取自动禁用（Mock 模型无法返回有效 JSON）

---

## 3. 场景文件 `.mock/mock_scenarios.yaml`

场景文件定义不同用户输入触发的回复序列。该目录已加入 `.gitignore`。

### 基本格式

步骤有两种类型：

```yaml
scenario_name:
  - text: "纯文本回复"          # AI 直接说话
  - tool: 工具名                # AI 调用工具，Agent 会真正执行
    args:
      参数名: 参数值
  - text: "工具调用后的回复"
```

### 触发规则

用户输入中**包含场景名（不区分大小写）**即触发。回复按顺序返回，用完后恢复默认。

### 示例

```yaml
# 简单对话
greeting:
  - text: "你好！我是 DataClaw。"
  - text: "有什么可以帮你的吗？"

# 测试终端工具
terminal_test:
  - tool: terminal
    args:
      command: "echo mock test"
  - text: "终端命令执行完成。"

# 多工具连续调用
read_test:
  - tool: get_file_info
    args:
      file_path: "README.md"
  - tool: read_file
    args:
      file_path: "README.md"
      offset: 0
      limit: 20
  - text: "文件读取完成。"
```

---

## 4. 调试 Prompt：`dump_prompt`

输入中包含 `dump_prompt` 关键字，Mock LLM 会返回当前完整对话历史（含 system prompt、工具调用等），用于检查 Prompt 组装是否正确。

---

## 5. 代码中直接指定 Responses

测试代码中可直接构造 `MockChatModel`：

```python
from core.llm_factory import MockChatModel

mock_llm = MockChatModel(responses=[
    {"tool": "terminal", "args": {"command": "echo hello"}},
    "命令执行成功",
])
```

适用：单元测试精确控制 LLM 输出、验证工具调用链路。

---

## 6. 注意事项

| 项目 | 说明 |
|------|------|
| 不消耗 token | 完全本地运行 |
| 不校验 API Key | Key 为空也能启动 |
| 记忆提取自动关闭 | 防止 Mock 模型返回非法 JSON |
| 不支持真实推理 | 仅按预定义序列或默认文本回复 |
| 场景名匹配是子串匹配 | 输入中任意位置包含场景名即可触发 |
| 工具调用参数需合法 | Mock 只替代大模型，工具仍真实执行，受沙盒约束 |

切换回 live 模式：将 `.env` 改回 `LLM_MODE=live` 并配置正确的 API Key。