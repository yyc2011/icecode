"""模型上下文窗口与 microcompact 阈值计算。"""

from __future__ import annotations

# 未知模型兜底：偏保守，更早触发压缩判定
DEFAULT_CONTEXT_WINDOW = 200_000

# 模型名 → 上下文窗口（token）。可被 ICECODE_CONTEXT_WINDOW_OVERRIDE 覆盖。
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # DeepSeek（官方 Models & Pricing：1M）
    "deepseek-chat": 1_000_000,
    "deepseek-reasoner": 1_000_000,
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
    # Anthropic 常用默认
    "claude-sonnet-4-6": 200_000,
    "claude-opus-4": 200_000,
    "claude-haiku-4": 200_000,
}


def get_context_window(model: str, override: int | None = None) -> int:
    """查表得到模型上下文窗口；override > 0 时直接覆盖。

    非法 override（≤0）抛 ValueError（由调用方 fail-closed 跳过压缩）。
    """
    if override is not None:
        if override <= 0:
            raise ValueError(f"context window override must be > 0, got {override}")
        return override
    return MODEL_CONTEXT_WINDOWS.get(model, DEFAULT_CONTEXT_WINDOW)


def get_effective_context_window(model: str, reserved_output_tokens: int, *, override: int | None = None) -> int:
    """有效窗口 = 上下文窗口 − 预留输出配额。

    reserved_output_tokens < 0 或结果 ≤ 0 时抛 ValueError。
    """
    if reserved_output_tokens < 0:
        raise ValueError(
            f"reserved_output_tokens must be >= 0, got {reserved_output_tokens}"
        )
    window = get_context_window(model, override=override)
    if window <= 0:
        raise ValueError(f"context window must be > 0, got {window}")
    effective = window - reserved_output_tokens
    if effective <= 0:
        raise ValueError(
            f"effective context window must be > 0 "
            f"(window={window}, reserved={reserved_output_tokens})"
        )
    return effective


def get_microcompact_threshold(effective_window: int, buffer_tokens: int) -> int:
    """microcompact 触发阈值 = 有效窗口 − buffer。

    effective_window ≤ 0、buffer < 0、或阈值 ≤ 0 时抛 ValueError。
    """
    if effective_window <= 0:
        raise ValueError(f"effective_window must be > 0, got {effective_window}")
    if buffer_tokens < 0:
        raise ValueError(f"buffer_tokens must be >= 0, got {buffer_tokens}")
    threshold = effective_window - buffer_tokens
    if threshold <= 0:
        raise ValueError(
            f"microcompact threshold must be > 0 "
            f"(effective={effective_window}, buffer={buffer_tokens})"
        )
    return threshold


def is_above_threshold(current_tokens: int, threshold: int) -> bool:
    """当前占用是否达到/超过阈值（含等于）。"""
    return current_tokens >= threshold
