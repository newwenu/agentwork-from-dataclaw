"""core/config.py 测试 — 验证配置加载、校验与模型路由。"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from core.config import ClawConfig, get_config, reload_config


@pytest.fixture(autouse=True)
def _reset_config():
    yield
    reload_config()


class TestClawConfigDefaults:
    def test_default_main_model(self):
        cfg = ClawConfig(main_model="deepseek")
        assert cfg.main_model == "deepseek"

    def test_default_memory_extraction_off(self):
        cfg = ClawConfig()
        assert cfg.memory_extraction is False

    def test_default_memory_inject_off(self):
        cfg = ClawConfig()
        assert cfg.memory_inject_long_term is False

    def test_default_memory_cooldown(self):
        cfg = ClawConfig()
        assert cfg.memory_llm_cooldown == 30

    def test_default_temperature(self):
        cfg = ClawConfig()
        assert cfg.agent_temperature == 0.2


class TestValidateApiKeys:
    def test_deepseek_valid_key(self):
        cfg = ClawConfig(llm_mode="live", main_model="deepseek", deepseek_api_key="sk-real-key-12345")
        assert cfg.validate_api_keys() == []

    def test_deepseek_empty_key(self):
        cfg = ClawConfig(llm_mode="live", main_model="deepseek", deepseek_api_key="")
        errors = cfg.validate_api_keys()
        assert len(errors) == 1
        assert "DEEPSEEK_API_KEY" in errors[0]

    def test_deepseek_placeholder_key(self):
        cfg = ClawConfig(llm_mode="live", main_model="deepseek", deepseek_api_key="sk-")
        errors = cfg.validate_api_keys()
        assert len(errors) == 1
        assert "占位符" in errors[0]

    def test_qwen_valid_key(self):
        cfg = ClawConfig(llm_mode="live", main_model="qwen", dashscope_api_key="sk-real-key-12345")
        assert cfg.validate_api_keys() == []

    def test_qwen_empty_key(self):
        cfg = ClawConfig(llm_mode="live", main_model="qwen", dashscope_api_key="")
        errors = cfg.validate_api_keys()
        assert len(errors) == 1
        assert "DASHSCOPE_API_KEY" in errors[0]

    def test_qwen_placeholder_key(self):
        cfg = ClawConfig(llm_mode="live", main_model="qwen", dashscope_api_key="sk-")
        errors = cfg.validate_api_keys()
        assert len(errors) == 1
        assert "占位符" in errors[0]

    def test_mock_mode_skips_validation(self):
        cfg = ClawConfig(llm_mode="mock", main_model="deepseek", deepseek_api_key="")
        assert cfg.validate_api_keys() == []

    def test_proxy_mode_skips_validation(self):
        cfg = ClawConfig(llm_mode="proxy", main_model="qwen", dashscope_api_key="")
        assert cfg.validate_api_keys() == []


class TestMainModelCaseInsensitive:
    """核心测试: main_model 的匹配必须大小写不敏感。

    这个测试覆盖了之前导致程序无法启动的 Bug:
    .env 中写 MAIN_MODEL=Qwen (大写 Q)，但 Claw.py 中
    config.main_model == "qwen" 是大小写敏感比较，
    导致 Qwen 用户被错误路由到 DeepSeek 分支。
    """

    @pytest.mark.parametrize("model_value", ["qwen", "Qwen", "QWEN", "QwEn"])
    def test_validate_accepts_any_case(self, model_value):
        cfg = ClawConfig(main_model=model_value, dashscope_api_key="sk-real-key")
        assert cfg.validate_api_keys() == []

    @pytest.mark.parametrize("model_value", ["qwen", "Qwen", "QWEN"])
    def test_lowercase_matches_qwen(self, model_value):
        cfg = ClawConfig(main_model=model_value)
        assert cfg.main_model.strip().lower() == "qwen"

    @pytest.mark.parametrize("model_value", ["deepseek", "DeepSeek", "DEEPSEEK"])
    def test_lowercase_matches_deepseek(self, model_value):
        cfg = ClawConfig(main_model=model_value)
        assert cfg.main_model.strip().lower() == "deepseek"


class TestGetConfigSingleton:
    def test_returns_same_instance(self):
        a = get_config()
        b = get_config()
        assert a is b

    def test_reload_creates_new_instance(self):
        a = get_config()
        b = reload_config()
        assert a is not b

    def test_reload_returns_fresh_config(self):
        a = get_config()
        b = reload_config()
        assert b is not a


class TestMemoryConfig:
    def test_extraction_enabled(self):
        cfg = ClawConfig(memory_extraction=True)
        assert cfg.memory_extraction is True

    def test_inject_enabled(self):
        cfg = ClawConfig(memory_inject_long_term=True)
        assert cfg.memory_inject_long_term is True

    def test_custom_cooldown(self):
        cfg = ClawConfig(memory_llm_cooldown=60)
        assert cfg.memory_llm_cooldown == 60
