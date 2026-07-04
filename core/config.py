"""Claw 配置中心 — 统一管理所有运行时配置。

使用 pydantic-settings 从 .env 文件和环境变量加载配置，
提供类型安全、启动时校验、IDE 自动补全。

配置优先级: 环境变量 > .env 文件 > 默认值

原则: 只收录真正被代码消费的配置项，不预设"将来可能用到"的项。
"""

from __future__ import annotations

from pydantic import model_validator
from pydantic_settings import BaseSettings


class ClawConfig(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    # ── 模型配置 ──────────────────────────────────────────
    main_model: str = "deepseek"

    # LLM 运行模式: "live"(真实API) / "mock"(零token本地模拟) / "proxy"(转发到model_server)
    llm_mode: str = "live"

    # proxy 模式目标地址（配合 model_server 使用）
    llm_proxy_url: str = "http://127.0.0.1:8000/v1"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Qwen / DashScope
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    # ── 记忆系统配置 ──────────────────────────────────────
    memory_extraction: bool = False
    memory_inject_long_term: bool = False
    memory_llm_cooldown: int = 30

    # ── Agent 配置 ────────────────────────────────────────
    agent_temperature: float = 0.2

    # ── TUI 配置 ──────────────────────────────────────────
    # 日志面板自动隐藏的终端最小宽度（列数），低于此值时自动隐藏
    tui_log_min_width: int = 80

    @model_validator(mode="after")
    def _normalize_main_model(self) -> ClawConfig:
        self.main_model = self.main_model.strip().lower()
        return self

    def validate_api_keys(self) -> list[str]:
        """校验 API Key 配置，返回错误信息列表（空列表表示全部通过）。

        mock / proxy 模式下不需要真实 API Key，跳过校验。
        """
        if self.llm_mode in ("mock", "proxy"):
            return []

        errors = []

        if self.main_model == "qwen":
            if not self.dashscope_api_key or self.dashscope_api_key.strip() in ("sk-", ""):
                errors.append("DASHSCOPE_API_KEY 未正确配置（不能为空或占位符 'sk-'）")
        else:
            if not self.deepseek_api_key or self.deepseek_api_key.strip() in ("sk-", ""):
                errors.append("DEEPSEEK_API_KEY 未正确配置（不能为空或占位符 'sk-'）")

        return errors


_config: ClawConfig | None = None


def get_config() -> ClawConfig:
    """获取全局配置单例。"""
    global _config
    if _config is None:
        _config = ClawConfig()
    return _config


def reload_config() -> ClawConfig:
    """强制重新加载配置（主要用于测试）。"""
    global _config
    _config = ClawConfig()
    return _config
