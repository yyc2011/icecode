"""Auto compact：超阈值触发 full compact；连续失败熔断。"""

from __future__ import annotations

from icecode.compact.windows import (
    get_buffer_threshold,
    get_effective_context_window,
    is_above_threshold,
)

# 连续摘要失败达到该次数后，本会话内不再自动压缩
MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3


def get_autocompact_threshold(
    model: str,
    reserved_output_tokens: int,
    buffer_tokens: int,
    *,
    override: int | None = None,
) -> int:
    """auto compact 触发阈值 = (窗口 − 摘要预留输出) − buffer。"""
    effective = get_effective_context_window(
        model, reserved_output_tokens, override=override
    )
    return get_buffer_threshold(effective, buffer_tokens)


def should_autocompact(current_tokens: int, threshold: int) -> bool:
    """当前占用是否达到/超过 auto compact 阈值（含等于）。"""
    return is_above_threshold(current_tokens, threshold)
