"""
统一配置入口。所有配置来自环境变量（可放在 .env）。

切换模型：LLM_PROVIDER=deepseek 或 anthropic
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

load_dotenv()

PermissionModeName = Literal["default", "accept_edits", "dont_ask"]


@dataclass
class Config:
    provider: str = os.getenv("LLM_PROVIDER", "deepseek")

    deepseek_api_key: str = os.getenv("DEEPSEEK_API_KEY", "")
    deepseek_model: str = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
    deepseek_base_url: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    max_tokens: int = int(os.getenv("MAX_TOKENS", "4096"))
    temperature: float = float(os.getenv("TEMPERATURE", "0.3"))
    max_turns: int = int(os.getenv("MAX_TURNS", "30"))

    workdir: str = os.getenv("WORKDIR", os.getcwd())
    auto_approve: bool = os.getenv("AUTO_APPROVE", "false").lower() == "true"
    # 设 ICECODE_ENABLE_TOOLS=false 可关工具跑纯对话
    enable_tools: bool = os.getenv("ICECODE_ENABLE_TOOLS", "true").lower() != "false"
    # 设 ICECODE_STREAM=false 关闭真流式，回退到 create_message
    enable_streaming: bool = os.getenv("ICECODE_STREAM", "true").lower() != "false"
    # default | accept_edits | dont_ask
    permission_mode: PermissionModeName = "default"  # type: ignore[assignment]

    # microcompact：清旧 tool_result（不调大模型）
    enable_microcompact: bool = (
        os.getenv("ICECODE_ENABLE_MICROCOMPACT", "true").lower() != "false"
    )
    microcompact_keep_recent: int = int(
        os.getenv("ICECODE_MICROCOMPACT_KEEP_RECENT", "3")
    )
    microcompact_buffer_tokens: int = int(
        os.getenv("ICECODE_MICROCOMPACT_BUFFER_TOKENS", "8000")
    )
    # 非空正整数时覆盖模型查表窗口；None 表示不覆盖
    context_window_override: int | None = None

    # auto compact：超阈值时摘要重建（与 microcompact 使用独立 buffer / 预留输出）
    enable_autocompact: bool = (
        os.getenv("ICECODE_ENABLE_AUTOCOMPACT", "true").lower() != "false"
    )
    autocompact_buffer_tokens: int = int(
        os.getenv("ICECODE_AUTOCOMPACT_BUFFER_TOKENS", "13000")
    )
    # 摘要调用自身的 max_tokens，不与普通回复的 MAX_TOKENS 混用
    compact_reserved_output_tokens: int = int(
        os.getenv("ICECODE_COMPACT_RESERVED_OUTPUT_TOKENS", "8000")
    )

    def __post_init__(self) -> None:
        mode = os.getenv("PERMISSION_MODE", "default").lower()
        if mode not in ("default", "accept_edits", "dont_ask"):
            mode = "default"
        object.__setattr__(self, "permission_mode", mode)
        object.__setattr__(self, "workdir", str(Path(self.workdir).resolve()))

        raw_override = os.getenv("ICECODE_CONTEXT_WINDOW_OVERRIDE", "").strip()
        if raw_override:
            try:
                parsed = int(raw_override)
            except ValueError:
                parsed = None
            object.__setattr__(
                self, "context_window_override", parsed if parsed and parsed > 0 else None
            )


def load_config() -> Config:
    return Config()
