"""上下文计量与压缩（microcompact / full compact / auto compact）。"""

from icecode.compact.autocompact import (
    MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES,
    get_autocompact_threshold,
    should_autocompact,
)
from icecode.compact.full_compact import CompactError, FullCompactResult, run_full_compact
from icecode.compact.microcompact import (
    CLEARED_PLACEHOLDER,
    COMPACTABLE_TOOLS,
    MicrocompactResult,
    collect_compactable_tool_use_ids,
    microcompact_messages,
)
from icecode.compact.prompt import build_compact_system_prompt, build_compact_user_message
from icecode.compact.tokens import (
    estimate_context_tokens,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_text_tokens,
)
from icecode.compact.windows import (
    DEFAULT_CONTEXT_WINDOW,
    MODEL_CONTEXT_WINDOWS,
    get_buffer_threshold,
    get_context_window,
    get_effective_context_window,
    get_microcompact_threshold,
    is_above_threshold,
)

__all__ = [
    "CLEARED_PLACEHOLDER",
    "COMPACTABLE_TOOLS",
    "DEFAULT_CONTEXT_WINDOW",
    "MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES",
    "MODEL_CONTEXT_WINDOWS",
    "CompactError",
    "FullCompactResult",
    "MicrocompactResult",
    "build_compact_system_prompt",
    "build_compact_user_message",
    "collect_compactable_tool_use_ids",
    "estimate_context_tokens",
    "estimate_message_tokens",
    "estimate_messages_tokens",
    "estimate_text_tokens",
    "get_autocompact_threshold",
    "get_buffer_threshold",
    "get_context_window",
    "get_effective_context_window",
    "get_microcompact_threshold",
    "is_above_threshold",
    "microcompact_messages",
    "run_full_compact",
    "should_autocompact",
]
