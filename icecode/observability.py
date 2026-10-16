"""
可观测性薄封装：基于 Langfuse Python SDK（v3+，OpenTelemetry 版）的 @observe 装饰器。

- Trace：一次用户 turn（最外层被装饰的调用自动成为 Trace 根）
- Span：一次工具调用
- Generation：一次模型调用

未安装 langfuse 包、或未配置 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY 时，
`observe` 退化为透明 no-op，所有 update_* / flush 直接返回，不侵入主流程、不抛异常。
"""

from __future__ import annotations

import functools
import os
from typing import Any

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


def update_span(**kwargs: Any) -> None:
    """更新当前 Span（name / input / output / level / metadata ...）。"""
    if not _ENABLED:
        return
    try:
        _get_client().update_current_span(**kwargs)
    except Exception:
        pass


def update_generation(**kwargs: Any) -> None:
    """更新当前 Generation（model / usage_details / output / level ...）。"""
    if not _ENABLED:
        return
    try:
        _get_client().update_current_generation(**kwargs)
    except Exception:
        pass


def observe_turn(fn):
    """给「一次用户 turn」入口方法用：成为 Trace 根，并把会话 id 记到 session_id。

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
            ctx = _propagate_attributes(session_id=session_id, trace_name="agent_turn")
        except Exception:
            return fn(self, user_input)
        with ctx:
            result = fn(self, user_input)
        update_span(output=maybe_text(result) if isinstance(result, str) else None)
        return result

    functools.update_wrapper(inner, fn)
    # capture_input/output=False：关闭 SDK 对入参/返回值的自动上报，统一走 maybe_text 的脱敏口径
    return observe(name="agent_turn", capture_input=False, capture_output=False)(inner)


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
