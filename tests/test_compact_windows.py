"""上下文窗口与 microcompact 阈值单测。"""

from __future__ import annotations

import pytest

from icecode.compact.windows import (
    DEFAULT_CONTEXT_WINDOW,
    get_context_window,
    get_effective_context_window,
    get_microcompact_threshold,
    is_above_threshold,
)


def test_get_context_window_known_and_default() -> None:
    assert get_context_window("deepseek-chat") == 1_000_000
    assert get_context_window("claude-sonnet-4-6") == 200_000
    assert get_context_window("unknown-model-xyz") == DEFAULT_CONTEXT_WINDOW


def test_get_context_window_override() -> None:
    assert get_context_window("deepseek-chat", override=50_000) == 50_000


def test_get_context_window_invalid_override() -> None:
    with pytest.raises(ValueError):
        get_context_window("deepseek-chat", override=0)
    with pytest.raises(ValueError):
        get_context_window("deepseek-chat", override=-1)


def test_get_effective_context_window() -> None:
    # deepseek 1_000_000 - 4096
    assert get_effective_context_window("deepseek-chat", 4096) == 1_000_000 - 4096


def test_get_effective_context_window_invalid() -> None:
    with pytest.raises(ValueError):
        get_effective_context_window("deepseek-chat", -1)
    with pytest.raises(ValueError):
        get_effective_context_window("deepseek-chat", 2_000_000)


def test_get_microcompact_threshold() -> None:
    assert get_microcompact_threshold(100_000, 8_000) == 92_000


def test_get_microcompact_threshold_invalid() -> None:
    with pytest.raises(ValueError):
        get_microcompact_threshold(0, 100)
    with pytest.raises(ValueError):
        get_microcompact_threshold(10_000, -1)
    with pytest.raises(ValueError):
        get_microcompact_threshold(5_000, 8_000)  # threshold <= 0


def test_is_above_threshold_inclusive() -> None:
    assert is_above_threshold(100, 100) is True
    assert is_above_threshold(101, 100) is True
    assert is_above_threshold(99, 100) is False
