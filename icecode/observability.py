"""
可观测性薄封装：基于 Langfuse Python SDK（v3+，OpenTelemetry 版）的 @observe 装饰器。

- Trace：一次用户命令的容器（名字由 trace_name 决定，不是 observation 的 type）
- Agent：这次命令的根节点。SDK 的 observation 类型没有 trace，根节点用 agent
- Span：一次工具调用
- Generation：一次模型调用

未安装 langfuse 包、或未配置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 时，
`observe` 退化为透明 no-op，所有 update_* / flush 直接返回，不侵入主流程、不抛异常。
"""

from __future__ import annotations

import functools
import os
from datetime import datetime
from typing import Any

# 必须先于下方读取 LANGFUSE_* 执行：config 导入时会加载 .env
import icecode.config  # noqa: F401
from icecode.llm.base import (
    LLMResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolSchema,
    ToolUseBlock,
    Usage,
)

_ENABLED = False
_RECORD_IO = os.getenv("ICECODE_LANGFUSE_RECORD_IO", "false").lower() == "true"
_get_client: Any = None
_propagate_attributes: Any = None


def _noop(*dargs: Any, **dkwargs: Any):
    """与 @observe 用法兼容的空装饰器（支持 @observe 与 @observe(...) 两种写法）。"""
    if dargs and callable(dargs[0]) and not dkwargs:
        return dargs[0]

    def deco(fn):
        return fn

    return deco


observe = _noop

if os.getenv("ICECODE_ENABLE_LANGFUSE", "auto").lower() != "false":
    try:
        from langfuse import get_client as _gc
        from langfuse import observe as _observe
        from langfuse import propagate_attributes as _pa

        if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
            observe, _get_client, _propagate_attributes, _ENABLED = _observe, _gc, _pa, True
    except Exception:
        # 未安装 / 版本过旧（缺少 propagate_attributes）：静默降级
        pass


def is_enabled() -> bool:
    return _ENABLED


def _safe_update(method: str, **kwargs: Any) -> None:
    """调用 client 的 update_current_* 方法；未启用或 SDK 出错都静默跳过。"""
    if not _ENABLED:
        return
    try:
        getattr(_get_client(), method)(**kwargs)
    except Exception:
        pass


def update_span(**kwargs: Any) -> None:
    """更新当前 Span（name / input / output / level / metadata ...）。"""
    _safe_update("update_current_span", **kwargs)


def update_generation(**kwargs: Any) -> None:
    """更新当前 Generation（model / usage_details / output / level ...）。"""
    _safe_update("update_current_generation", **kwargs)


def usage_details(usage: Usage) -> dict[str, int]:
    return {"input": usage.input_tokens, "output": usage.output_tokens}


def start_generation(
    model: str,
    *,
    max_tokens: int,
    temperature: float,
    system: str,
    messages: list[Message],
    tools: list[ToolSchema],
) -> None:
    """模型调用开始：写 model、参数与发给模型的 input。"""
    update_generation(
        model=model,
        model_parameters={"max_tokens": max_tokens, "temperature": temperature},
        input=llm_request_input(system, messages, tools),
    )


def finish_generation(
    usage: Usage, output: Any, *, first_token_at: datetime | None = None
) -> None:
    """模型调用结束：写 usage、output；流式有首 token 时刻时一并上报。"""
    details: dict[str, Any] = {"usage_details": usage_details(usage), "output": output}
    if first_token_at is not None:
        details["completion_start_time"] = first_token_at
    update_generation(**details)


def observe_turn(fn):
    """给「一次用户 turn」入口方法用：创建这条 trace，根节点类型为 agent，并把会话 id 记到 session_id。

    v3+ 里 session_id 通过 propagate_attributes 上下文传播给本 turn 内所有子 observation，
    因此在装饰器内部包一层，被装饰方法本身无需改动。
    约定：被装饰方法为 `(self, user_input)`，self 可选带 `session_path`。
    """
    if not _ENABLED:
        return fn

    def inner(self, user_input: str):
        path = getattr(self, "session_path", None)
        session_id = path.stem if path is not None else None
        update_span(input=maybe_text(user_input))
        try:
            ctx = _propagate_attributes(session_id=session_id, trace_name=agent_trace_name())
        except Exception:
            return fn(self, user_input)
        with ctx:
            result = fn(self, user_input)
        update_span(output=maybe_text(result) if isinstance(result, str) else None)
        return result

    functools.update_wrapper(inner, fn)
    # capture_input/output=False：关闭 SDK 对入参/返回值的自动上报，统一走 maybe_text 的脱敏口径。
    # observation 类型没有 trace（写了会被 SDK 退回 span）。一次用户命令本身是 trace 容器，
    # 根节点用 agent，表示这一次 agent 运行。
    return observe(
        name="agent_turn",
        as_type="agent",
        capture_input=False,
        capture_output=False,
    )(inner)


def agent_trace_name(now: datetime | None = None) -> str:
    """一次 turn 的 trace 名：agent- 加本地时间，两位年 + 月日时分秒。"""
    stamp = (now or datetime.now()).strftime("%y%m%d%H%M%S")
    return f"agent-{stamp}"


def _block_to_plain(block: Any) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    if isinstance(block, ToolResultBlock):
        return {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            "content": block.content,
            "is_error": block.is_error,
        }
    return {"type": getattr(block, "type", type(block).__name__)}


def _block_chars(block: Any) -> int:
    if isinstance(block, TextBlock):
        return len(block.text)
    if isinstance(block, ToolResultBlock):
        return len(block.content)
    if isinstance(block, ToolUseBlock):
        return len(str(block.input))
    return 0


def llm_request_input(
    system: str, messages: list[Message], tools: list[ToolSchema]
) -> Any:
    """一次模型调用的 input：system、历史消息、工具定义。

    默认只留规模；ICECODE_LANGFUSE_RECORD_IO=true 时上报发给模型的正文。
    未启用 Langfuse 时返回 None，避免白白遍历整段历史。
    """
    if not _ENABLED:
        return None
    if _RECORD_IO:
        return {
            "system": system,
            "messages": [
                {
                    "role": message.role,
                    "content": [_block_to_plain(block) for block in message.content],
                }
                for message in messages
            ],
            "tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "input_schema": tool.input_schema,
                }
                for tool in tools
            ],
        }
    return {
        "system_chars": len(system),
        "messages": [
            {
                "role": message.role,
                "chars": sum(_block_chars(block) for block in message.content),
                "block_types": [
                    getattr(block, "type", type(block).__name__)
                    for block in message.content
                ],
            }
            for message in messages
        ],
        "tool_names": [tool.name for tool in tools],
    }


def llm_response_output(response: LLMResponse) -> Any:
    """模型回复。只有文本时上报文本；含工具调用时用 content 数组上报 tool_use 块。

    工具调用放在 content 数组里（type=tool_use + name），Langfuse 才会统计 Tool Calls 列。
    默认脱敏：只带工具名，input 置空；RECORD_IO=true 才带完整入参。未启用时返回 None。
    """
    if not _ENABLED:
        return None
    text = response.text()
    tool_uses = response.tool_uses()
    if not _RECORD_IO:
        redacted: dict[str, Any] = {"chars": len(text), "stop_reason": response.stop_reason}
        if tool_uses:
            redacted["content"] = [
                {"type": "tool_use", "id": block.id, "name": block.name, "input": {}}
                for block in tool_uses
            ]
        return redacted
    if not tool_uses:
        return text
    content: list[dict[str, Any]] = []
    if text:
        content.append({"type": "text", "text": text})
    content.extend(
        {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
        for block in tool_uses
    )
    return {"stop_reason": response.stop_reason, "content": content}


def maybe_text(text: str) -> Any:
    """默认只上报字符数；ICECODE_LANGFUSE_RECORD_IO=true 才上报正文。"""
    return text if _RECORD_IO else {"chars": len(text)}


def maybe_args(tool_name: str, tool_input: dict) -> dict[str, Any]:
    """工具入参：默认只上报参数名；开启 record_io 才上报完整入参。"""
    if _RECORD_IO:
        return {"tool": tool_name, "args": tool_input}
    return {"tool": tool_name, "arg_keys": list(tool_input.keys())}


def flush() -> None:
    if not _ENABLED:
        return
    try:
        _get_client().flush()
    except Exception:
        pass
