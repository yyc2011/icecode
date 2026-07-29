"""DeepSeek Provider — OpenAI 兼容 API ↔ canonical 协议。"""

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


class DeepSeekProvider(LLMProvider):
    name = "deepseek"

    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
    ):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    def _to_wire_messages(self, messages: list[Message], system: str) -> list[dict]:
        wire: list[dict] = [{"role": "system", "content": system}]

        for m in messages:
            text_parts = [b.text for b in m.content if isinstance(b, TextBlock)]
            tool_uses = [b for b in m.content if isinstance(b, ToolUseBlock)]
            tool_results = [b for b in m.content if isinstance(b, ToolResultBlock)]

            if m.role == "assistant":
                msg: dict = {"role": "assistant", "content": "\n".join(text_parts) or None}
                if tool_uses:
                    msg["tool_calls"] = [
                        {
                            "id": tu.id,
                            "type": "function",
                            "function": {
                                "name": tu.name,
                                "arguments": json.dumps(tu.input, ensure_ascii=False),
                            },
                        }
                        for tu in tool_uses
                    ]
                wire.append(msg)
            elif tool_results:
                for tr in tool_results:
                    wire.append(
                        {
                            "role": "tool",
                            "tool_call_id": tr.tool_use_id,
                            "content": tr.content,
                        }
                    )
            else:
                wire.append({"role": "user", "content": "\n".join(text_parts)})

        return wire

    def _to_wire_tools(self, tools: list[ToolSchema]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]

    def _from_wire_response(self, resp) -> LLMResponse:
        choice = resp.choices[0]
        msg = choice.message
        blocks: list = []

        if msg.content:
            blocks.append(TextBlock(text=msg.content))

        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append(ToolUseBlock(id=tc.id, name=tc.function.name, input=args))

        finish_reason = choice.finish_reason
        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        usage = Usage()
        if resp.usage:
            usage = Usage(
                input_tokens=resp.usage.prompt_tokens,
                output_tokens=resp.usage.completion_tokens,
            )

        return LLMResponse(content=blocks, stop_reason=stop_reason, usage=usage)

    def create_message(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> LLMResponse:
        kwargs: dict = dict(
            model=self._model,
            messages=self._to_wire_messages(messages, system),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if tools:
            kwargs["tools"] = self._to_wire_tools(tools)
            kwargs["tool_choice"] = "auto"

        resp = self._client.chat.completions.create(**kwargs)
        return self._from_wire_response(resp)

    def stream_message(
        self,
        messages: list[Message],
        system: str,
        tools: list[ToolSchema],
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[StreamEvent]:
        kwargs: dict[str, Any] = dict(
            model=self._model,
            messages=self._to_wire_messages(messages, system),
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tools:
            kwargs["tools"] = self._to_wire_tools(tools)
            kwargs["tool_choice"] = "auto"

        stream = self._client.chat.completions.create(**kwargs)

        text_parts: list[str] = []
        # index -> {id, name, arguments}
        tool_acc: dict[int, dict[str, str]] = {}
        finish_reason: str | None = None
        usage = Usage()

        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = Usage(
                    input_tokens=chunk.usage.prompt_tokens or 0,
                    output_tokens=chunk.usage.completion_tokens or 0,
                )

            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            if choice.finish_reason:
                finish_reason = choice.finish_reason

            delta = choice.delta
            if delta is None:
                continue

            if delta.content:
                text_parts.append(delta.content)
                yield TextDelta(delta.content)

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index if tc.index is not None else 0
                    entry = tool_acc.setdefault(
                        idx, {"id": "", "name": "", "arguments": ""}
                    )
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            entry["name"] = tc.function.name
                        if tc.function.arguments:
                            entry["arguments"] += tc.function.arguments

        blocks: list = []
        full_text = "".join(text_parts)
        if full_text:
            blocks.append(TextBlock(text=full_text))

        for idx in sorted(tool_acc):
            entry = tool_acc[idx]
            try:
                args = json.loads(entry["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            blocks.append(
                ToolUseBlock(
                    id=entry["id"] or f"toolu_ds_{idx}",
                    name=entry["name"] or "unknown",
                    input=args,
                )
            )

        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        else:
            stop_reason = "end_turn"

        yield StreamDone(
            LLMResponse(content=blocks, stop_reason=stop_reason, usage=usage)
        )
