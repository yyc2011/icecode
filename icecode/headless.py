"""非交互运行：传入一条 prompt，跑完 Agent Loop，返回最终回答。

与交互 REPL 的差别：
  - 不读 stdin，也不渲染界面（Console quiet）
  - 需要确认的操作一律拒绝（dont_ask），且忽略 AUTO_APPROVE
  - 不写会话文件，每次调用都是全新上下文
  - 关闭流式输出，避免 Live 渲染
"""

from __future__ import annotations

import copy

from rich.console import Console

from icecode.agent import Agent
from icecode.config import Config, load_config
from icecode.llm.base import LLMProvider
from icecode.llm.factory import create_provider
from icecode.tools.registry import build_default_registry, build_empty_registry


def build_headless_config(base: Config | None = None) -> Config:
    """复制配置并收紧为无人值守设置。

    用 copy 而不是 dataclasses.replace：后者会重跑 __post_init__，从环境变量覆盖 permission_mode。
    """
    cfg = copy.copy(base or load_config())
    cfg.permission_mode = "dont_ask"
    cfg.auto_approve = False
    cfg.enable_streaming = False
    return cfg


def run_prompt(
    prompt: str,
    *,
    cfg: Config | None = None,
    provider: LLMProvider | None = None,
) -> str:
    """跑一条 prompt，返回最终回答文本。

    provider 可注入（测试用）；缺省时按配置创建，缺少 API Key 会抛 RuntimeError。
    """
    cfg = build_headless_config(cfg)
    provider = provider or create_provider(cfg)
    registry = (
        build_default_registry(cfg.workdir)
        if cfg.enable_tools
        else build_empty_registry()
    )
    agent = Agent(
        provider=provider,
        registry=registry,
        cfg=cfg,
        console=Console(quiet=True),
        session_path=None,
    )
    return agent.run_turn(prompt)
