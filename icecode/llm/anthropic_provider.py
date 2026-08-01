"""Anthropic Provider — canonical ≈ 官方 content-block。"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from icecode.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    StreamDone,
    StreamEvent,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolSchema,
    ToolUseBlock,
    Usage,
)
from icecode.llm.pairing import ensure_tool_result_pairing


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def _to_wire_messages(self, messages: list[Message]) -> list[dict]:
        wire = []
        for m in ensure_tool_result_pairing(messages):
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

    def _normalize_stop_reason(self, stop_reason: str | None) -> str:
        if stop_reason == "tool_use":
            return "tool_use"
        if stop_reason == "max_tokens":
            return "max_tokens"
        return "end_turn"

    def _from_wire_response(self, resp) -> LLMResponse:
        blocks = []
        for b in resp.content:
            if b.type == "text":
                blocks.append(TextBlock(text=b.text))
            elif b.type == "tool_use":
                blocks.append(ToolUseBlock(id=b.id, name=b.name, input=b.input))

        return LLMResponse(
            content=blocks,
            stop_reason=self._normalize_stop_reason(resp.stop_reason),  # type: ignore[arg-type]
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

    def stream_message(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[StreamEvent]:
        stream = self._client.messages.create(
            model=self._model,
            system=system,
            messages=self._to_wire_messages(messages),
            tools=self._to_wire_tools(tools) if tools else [],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        # index -> block state
        blocks_by_index: dict[int, dict[str, Any]] = {}
        usage = Usage()
        stop_reason: str | None = None

        for event in stream:
            etype = getattr(event, "type", None)

            if etype == "message_start":
                msg = getattr(event, "message", None)
                if msg is not None and getattr(msg, "usage", None) is not None:
                    usage = Usage(
                        input_tokens=msg.usage.input_tokens or 0,
                        output_tokens=getattr(msg.usage, "output_tokens", 0) or 0,
                    )

            elif etype == "content_block_start":
                idx = getattr(event, "index", 0)
                block = getattr(event, "content_block", None)
                if block is None:
                    continue
                btype = getattr(block, "type", None)
                if btype == "text":
                    blocks_by_index[idx] = {"kind": "text", "text": ""}
                elif btype == "tool_use":
                    blocks_by_index[idx] = {
                        "kind": "tool_use",
                        "id": getattr(block, "id", "") or "",
                        "name": getattr(block, "name", "") or "",
                        "partial_json": "",
                    }

            elif etype == "content_block_delta":
                idx = getattr(event, "index", 0)
                delta = getattr(event, "delta", None)
                if delta is None:
                    continue
                dtype = getattr(delta, "type", None)
                state = blocks_by_index.get(idx)
                if state is None:
                    continue
                if dtype == "text_delta":
                    piece = getattr(delta, "text", "") or ""
                    state["text"] = state.get("text", "") + piece
                    if piece:
                        yield TextDelta(piece)
                elif dtype == "input_json_delta":
                    state["partial_json"] = state.get("partial_json", "") + (
                        getattr(delta, "partial_json", "") or ""
                    )

            elif etype == "message_delta":
                delta = getattr(event, "delta", None)
                if delta is not None and getattr(delta, "stop_reason", None):
                    stop_reason = delta.stop_reason
                part_usage = getattr(event, "usage", None)
                if part_usage is not None:
                    out = getattr(part_usage, "output_tokens", None)
                    if out is not None:
                        usage = Usage(
                            input_tokens=usage.input_tokens,
                            output_tokens=out,
                        )

            elif etype == "message_stop":
                pass

        content: list = []
        for idx in sorted(blocks_by_index):
            state = blocks_by_index[idx]
            if state["kind"] == "text":
                text = state.get("text", "")
                if text:
                    content.append(TextBlock(text=text))
            elif state["kind"] == "tool_use":
                try:
                    args = json.loads(state.get("partial_json") or "{}")
                except json.JSONDecodeError:
                    args = {}
                content.append(
                    ToolUseBlock(
                        id=state.get("id") or f"toolu_anth_{idx}",
                        name=state.get("name") or "unknown",
                        input=args,
                    )
                )

        yield StreamDone(
            LLMResponse(
                content=content,
                stop_reason=self._normalize_stop_reason(stop_reason),  # type: ignore[arg-type]
                usage=usage,
            )
        )
