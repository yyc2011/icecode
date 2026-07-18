"""Anthropic Provider — canonical ≈ 官方 content-block。"""

from __future__ import annotations

from icecode.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolSchema,
    ToolUseBlock,
    Usage,
)


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _to_wire_messages(self, messages: list[Message]) -> list[dict]:
        wire = []
        for m in messages:
            content = []
            for b in m.content:
                if isinstance(b, TextBlock):
                    content.append({"type": "text", "text": b.text})
                elif isinstance(b, ToolUseBlock):
                    content.append(
                        {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                    )
                elif isinstance(b, ToolResultBlock):
                    content.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": b.tool_use_id,
                            "content": b.content,
                            "is_error": b.is_error,
                        }
                    )
            wire.append({"role": m.role, "content": content})
        return wire

    def _to_wire_tools(self, tools: list[ToolSchema]) -> list[dict]:
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]

    def _from_wire_response(self, resp) -> LLMResponse:
        blocks = []
        for b in resp.content:
            if b.type == "text":
                blocks.append(TextBlock(text=b.text))
            elif b.type == "tool_use":
                blocks.append(ToolUseBlock(id=b.id, name=b.name, input=b.input))

        stop_reason = "tool_use" if resp.stop_reason == "tool_use" else "end_turn"
        if resp.stop_reason == "max_tokens":
            stop_reason = "max_tokens"

        return LLMResponse(
            content=blocks,
            stop_reason=stop_reason,
            usage=Usage(
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
            ),
        )

    def create_message(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        resp = self._client.messages.create(
            model=self._model,
            system=system,
            messages=self._to_wire_messages(messages),
            tools=self._to_wire_tools(tools) if tools else [],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return self._from_wire_response(resp)
