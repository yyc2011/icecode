"""DeepSeek Provider — OpenAI 兼容 API ↔ canonical 协议。"""

from __future__ import annotations

import json

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
