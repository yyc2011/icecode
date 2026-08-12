"""上下文计量与压缩（microcompact 等）。"""

from icecode.compact.microcompact import (
    CLEARED_PLACEHOLDER,
    COMPACTABLE_TOOLS,
    MicrocompactResult,
    collect_compactable_tool_use_ids,
    microcompact_messages,
)
from icecode.compact.tokens import (
    estimate_context_tokens,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_text_tokens,
)
from icecode.compact.windows import (
    DEFAULT_CONTEXT_WINDOW,
    MODEL_CONTEXT_WINDOWS,
    get_context_window,
    get_effective_context_window,
    get_microcompact_threshold,
    is_above_threshold,
)

__all__ = [
    "CLEARED_PLACEHOLDER",
    "COMPACTABLE_TOOLS",
    "DEFAULT_CONTEXT_WINDOW",
    "MODEL_CONTEXT_WINDOWS",
    "MicrocompactResult",
    "collect_compactable_tool_use_ids",
    "estimate_context_tokens",
    "estimate_message_tokens",
    "estimate_messages_tokens",
    "estimate_text_tokens",
    "get_context_window",
    "get_effective_context_window",
    "get_microcompact_threshold",
    "is_above_threshold",
    "microcompact_messages",
]
