"""
llm/base.py — canonical 协议（Anthropic 风格 content-block）。
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Literal, Union


@dataclass
class TextBlock:
    text: str
    type: Literal["text"] = "text"


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: Literal["tool_use"] = "tool_use"


@dataclass
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False
    type: Literal["tool_result"] = "tool_result"


ContentBlock = Union[TextBlock, ToolUseBlock, ToolResultBlock]


def new_tool_use_id() -> str:
    return f"toolu_{uuid.uuid4().hex[:20]}"


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: list[ContentBlock] = field(default_factory=list)

    @staticmethod
    def user_text(text: str) -> Message:
        return Message(role="user", content=[TextBlock(text=text)])

    @staticmethod
    def assistant(content: list[ContentBlock]) -> Message:
        return Message(role="assistant", content=content)

    @staticmethod
    def tool_results(results: list[ToolResultBlock]) -> Message:
        return Message(role="user", content=list(results))

    def text(self) -> str:
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))


@dataclass
class ToolSchema:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


def accumulate_usage(total: Usage, new: Usage) -> Usage:
    """累加两次 API 调用的 usage（会话级合计）。"""
    return Usage(
        input_tokens=total.input_tokens + new.input_tokens,
        output_tokens=total.output_tokens + new.output_tokens,
    )


@dataclass
class LLMResponse:
    content: list[ContentBlock]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens", "error"]
    usage: Usage = field(default_factory=Usage)

    def tool_uses(self) -> list[ToolUseBlock]:
        return [b for b in self.content if isinstance(b, ToolUseBlock)]

    def text(self) -> str:
        return "\n".join(b.text for b in self.content if isinstance(b, TextBlock))


@dataclass
class TextDelta:
    """流式增量文本（仅 text；工具入参在 StreamDone 中一次性给出）。"""

    text: str


@dataclass
class StreamDone:
    """流结束：完整 LLMResponse（含 usage / tool_use / stop_reason）。"""

    response: LLMResponse


StreamEvent = Union[TextDelta, StreamDone]


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def create_message(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        raise NotImplementedError

    def stream_message(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[StreamEvent]:
        """默认回退：单次 create_message，再产出 TextDelta（若有）+ StreamDone。"""
        resp = self.create_message(messages, system, tools, max_tokens, temperature)
        if resp.text():
            yield TextDelta(resp.text())
        yield StreamDone(resp)
