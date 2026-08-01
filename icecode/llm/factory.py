"""根据配置创建 Provider。新模型：实现 LLMProvider + 在此注册。"""

from __future__ import annotations

from icecode.config import Config
from icecode.llm.anthropic_provider import AnthropicProvider
from icecode.llm.base import LLMProvider
from icecode.llm.deepseek_provider import DeepSeekProvider


def create_provider(cfg: Config) -> LLMProvider:
    provider_name = cfg.provider.lower()

    if provider_name == "deepseek":
        if not cfg.deepseek_api_key:
            raise RuntimeError("未设置 DEEPSEEK_API_KEY，无法使用 deepseek provider")
        return DeepSeekProvider(
            api_key=cfg.deepseek_api_key,
            model=cfg.deepseek_model,
            base_url=cfg.deepseek_base_url,
        )

    if provider_name == "anthropic":
        if not cfg.anthropic_api_key:
            raise RuntimeError("未设置 ANTHROPIC_API_KEY，无法使用 anthropic provider")
        return AnthropicProvider(
            api_key=cfg.anthropic_api_key,
            model=cfg.anthropic_model,
        )

    # 可在此扩展注册其他 OpenAI 兼容 Provider（如 glm）
    raise ValueError(f"未知的 provider: {provider_name!r}，目前支持 deepseek / anthropic")
