"""Full compact：一次摘要调用，把过长对话重建为摘要。"""

from __future__ import annotations

from dataclasses import dataclass

from icecode.compact.prompt import build_compact_system_prompt
from icecode.compact.tokens import estimate_messages_tokens
from icecode.llm.base import LLMProvider, Message, Usage


class CompactError(RuntimeError):
    """摘要重建失败（空对话、空回复、调用异常）。"""


@dataclass(frozen=True)
class FullCompactResult:
    summary_text: str
    pre_compact_tokens: int
    usage: Usage


def run_full_compact(
    messages: list[Message],
    provider: LLMProvider,
    *,
    reserved_output_tokens: int,
) -> FullCompactResult:
    """对 messages 做一次无工具摘要调用。

    messages 为空、调用异常、或回复无文本时抛 CompactError。
    """
    if not messages:
        raise CompactError("没有足够的消息可压缩")
    if reserved_output_tokens <= 0:
        raise CompactError(
            f"reserved_output_tokens 必须 > 0，得到 {reserved_output_tokens}"
        )

    pre_compact_tokens = estimate_messages_tokens(messages)
    try:
        response = provider.create_message(
            messages=messages,
            system=build_compact_system_prompt(),
            tools=[],
            max_tokens=reserved_output_tokens,
            temperature=0.0,
        )
    except CompactError:
        raise
    except Exception as e:
        raise CompactError(f"摘要调用失败: {type(e).__name__}: {e}") from e

    summary = (response.text() or "").strip()
    if not summary:
        raise CompactError("摘要调用未返回文本")

    return FullCompactResult(
        summary_text=summary,
        pre_compact_tokens=pre_compact_tokens,
        usage=response.usage,
    )
