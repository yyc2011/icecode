"""observability：未配置时 no-op；启用路径验证 v3+ SDK 调用与嵌套不抛异常。"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest

from icecode import observability as obs


@pytest.fixture
def disabled(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setenv("ICECODE_LANGFUSE_RECORD_IO", "false")
    yield importlib.reload(obs)
    importlib.reload(obs)


def test_disabled_when_no_keys(disabled):
    assert disabled.is_enabled() is False


def test_noop_observe_bare_and_with_args(disabled):
    @disabled.observe
    def f(x):
        return x + 1

    @disabled.observe(as_type="span", name="n", capture_input=False)
    def g(x):
        return x * 2

    assert f(1) == 2
    assert g(3) == 6


def test_noop_observe_turn_returns_original(disabled):
    def run(self, text):
        return text.upper()

    assert disabled.observe_turn(run) is run


def test_update_and_flush_noop_do_not_raise(disabled):
    disabled.update_span(name="n", level="ERROR")
    disabled.update_generation(model="m")
    disabled.flush()


def test_explicit_off_switch(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("ICECODE_ENABLE_LANGFUSE", "false")
    mod = importlib.reload(obs)
    assert mod.is_enabled() is False
    monkeypatch.delenv("ICECODE_ENABLE_LANGFUSE")
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY")
    importlib.reload(obs)


def test_agent_trace_name_is_local_timestamp():
    from datetime import datetime

    assert obs.agent_trace_name(datetime(2026, 10, 24, 21, 2, 3)) == "agent-261024210203"


def test_payload_builders_skip_work_when_disabled(disabled):
    from icecode.llm.base import (
        LLMResponse,
        Message,
        TextBlock,
        ToolSchema,
        Usage,
    )

    message = Message(role="user", content=[TextBlock(text="hello")])
    tool = ToolSchema(name="bash", description="run", input_schema={"type": "object"})
    assert disabled.llm_request_input("sys", [message], [tool]) is None
    response = LLMResponse(
        content=[TextBlock(text="ok")], stop_reason="end_turn", usage=Usage()
    )
    assert disabled.llm_response_output(response) is None


def test_generation_helpers_report_usage_and_first_token(disabled, monkeypatch):
    from datetime import datetime, timezone

    from icecode.llm.base import Message, TextBlock, Usage

    calls: list[dict] = []
    monkeypatch.setattr(disabled, "update_generation", lambda **kw: calls.append(kw))
    monkeypatch.setattr(disabled, "_ENABLED", True)

    disabled.start_generation(
        "m",
        max_tokens=10,
        temperature=0.5,
        system="sys",
        messages=[Message(role="user", content=[TextBlock(text="hi")])],
        tools=[],
    )
    assert calls[0]["model"] == "m"
    assert calls[0]["model_parameters"] == {"max_tokens": 10, "temperature": 0.5}
    assert calls[0]["input"]["system_chars"] == 3

    stamp = datetime(2026, 10, 25, tzinfo=timezone.utc)
    disabled.finish_generation(Usage(input_tokens=4, output_tokens=2), "out", first_token_at=stamp)
    disabled.finish_generation(Usage(input_tokens=1, output_tokens=1), "out")
    assert calls[1] == {
        "usage_details": {"input": 4, "output": 2},
        "output": "out",
        "completion_start_time": stamp,
    }
    assert calls[2] == {"usage_details": {"input": 1, "output": 1}, "output": "out"}


def test_llm_request_input_redacts_body(disabled, monkeypatch):
    monkeypatch.setattr(disabled, "_ENABLED", True)
    from icecode.llm.base import (
        LLMResponse,
        Message,
        TextBlock,
        ToolSchema,
        ToolUseBlock,
        Usage,
    )

    message = Message(role="user", content=[TextBlock(text="hello")])
    tool = ToolSchema(name="bash", description="run", input_schema={"type": "object"})
    assert disabled.llm_request_input("sys", [message], [tool]) == {
        "system_chars": 3,
        "messages": [{"role": "user", "chars": 5, "block_types": ["text"]}],
        "tool_names": ["bash"],
    }
    response = LLMResponse(
        content=[
            TextBlock(text="ok"),
            ToolUseBlock(id="toolu_1", name="bash", input={"command": "ls"}),
        ],
        stop_reason="tool_use",
        usage=Usage(input_tokens=1, output_tokens=2),
    )
    assert disabled.llm_response_output(response) == {
        "chars": 2,
        "stop_reason": "tool_use",
        "content": [{"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {}}],
    }


def test_llm_request_input_includes_prompt_when_record_io(disabled, monkeypatch):
    from icecode.llm.base import LLMResponse, Message, TextBlock, ToolSchema, Usage

    monkeypatch.setenv("ICECODE_LANGFUSE_RECORD_IO", "true")
    mod = importlib.reload(disabled)
    monkeypatch.setattr(mod, "_ENABLED", True)
    message = Message(role="user", content=[TextBlock(text="hello")])
    tool = ToolSchema(name="bash", description="run", input_schema={"type": "object"})
    assert mod.llm_request_input("sys", [message], [tool]) == {
        "system": "sys",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        "tools": [
            {"name": "bash", "description": "run", "input_schema": {"type": "object"}}
        ],
    }
    assert (
        mod.llm_response_output(
            LLMResponse(content=[TextBlock(text="ok")], stop_reason="end_turn", usage=Usage())
        )
        == "ok"
    )


def test_llm_response_output_tool_use_in_content_when_record_io(disabled, monkeypatch):
    from icecode.llm.base import LLMResponse, TextBlock, ToolUseBlock, Usage

    monkeypatch.setenv("ICECODE_LANGFUSE_RECORD_IO", "true")
    mod = importlib.reload(disabled)
    monkeypatch.setattr(mod, "_ENABLED", True)
    response = LLMResponse(
        content=[
            TextBlock(text="先看目录"),
            ToolUseBlock(id="toolu_1", name="bash", input={"command": "ls"}),
        ],
        stop_reason="tool_use",
        usage=Usage(),
    )
    out = mod.llm_response_output(response)
    # Langfuse 只从 content 数组里的 tool_use 块统计 Tool Calls；不得再用自定义键
    assert "tool_uses" not in out
    assert out["content"] == [
        {"type": "text", "text": "先看目录"},
        {"type": "tool_use", "id": "toolu_1", "name": "bash", "input": {"command": "ls"}},
    ]
    only_tool = LLMResponse(
        content=[ToolUseBlock(id="toolu_2", name="read_file", input={"path": "a"})],
        stop_reason="tool_use",
        usage=Usage(),
    )
    assert mod.llm_response_output(only_tool)["content"] == [
        {"type": "tool_use", "id": "toolu_2", "name": "read_file", "input": {"path": "a"}}
    ]


def test_maybe_text_default_only_length(disabled):
    assert disabled.maybe_text("hello") == {"chars": 5}
    assert disabled.maybe_args("bash", {"command": "ls"}) == {
        "tool": "bash",
        "arg_keys": ["command"],
    }


def test_maybe_text_records_body_when_record_io(disabled, monkeypatch):
    monkeypatch.setenv("ICECODE_LANGFUSE_RECORD_IO", "true")
    mod = importlib.reload(disabled)
    assert mod.maybe_text("hello") == "hello"
    assert mod.maybe_args("bash", {"command": "ls"}) == {
        "tool": "bash",
        "args": {"command": "ls"},
    }


def test_call_model_reports_completion_start_time(monkeypatch):
    import io
    from datetime import datetime, timezone

    from rich.console import Console

    import icecode.agent as agent_mod
    from icecode.agent import Agent
    from icecode.config import Config
    from icecode.llm.base import (
        LLMProvider,
        LLMResponse,
        StreamDone,
        TextBlock,
        TextDelta,
        Usage,
    )
    from icecode.tools.registry import build_empty_registry

    stamp = datetime(2026, 10, 25, 1, 2, 3, tzinfo=timezone.utc)
    updates: list[dict] = []
    monkeypatch.setattr(agent_mod.obs, "update_generation", lambda **kw: updates.append(kw))

    class StreamProvider(LLMProvider):
        name = "fake"

        def __init__(self) -> None:
            self.model = "fake-model"

        def create_message(self, messages, system, tools, max_tokens=4096, temperature=0.3):
            raise AssertionError("流式调用不应回退到整包请求")

        def stream_message(self, messages, system, tools, max_tokens=4096, temperature=0.3):
            yield TextDelta("hi")
            yield StreamDone(
                LLMResponse(
                    content=[TextBlock(text="hi")],
                    stop_reason="end_turn",
                    usage=Usage(input_tokens=3, output_tokens=1),
                    first_token_at=stamp,
                )
            )

    agent = Agent(
        provider=StreamProvider(),
        registry=build_empty_registry(),
        cfg=Config(
            enable_tools=False,
            enable_streaming=True,
            enable_microcompact=False,
            enable_autocompact=False,
        ),
        console=Console(file=io.StringIO()),
    )
    response = agent._traced_call_model([])
    assert response.first_token_at == stamp
    assert updates[-1]["completion_start_time"] == stamp
    assert updates[-1]["usage_details"] == {"input": 3, "output": 1}


def test_call_model_omits_completion_start_when_not_streaming(monkeypatch):
    import io

    from rich.console import Console

    import icecode.agent as agent_mod
    from icecode.agent import Agent
    from icecode.config import Config
    from icecode.llm.base import LLMProvider, LLMResponse, TextBlock, Usage
    from icecode.tools.registry import build_empty_registry

    updates: list[dict] = []
    monkeypatch.setattr(agent_mod.obs, "update_generation", lambda **kw: updates.append(kw))

    class OnceProvider(LLMProvider):
        name = "fake"

        def __init__(self) -> None:
            self.model = "fake-model"

        def create_message(self, messages, system, tools, max_tokens=4096, temperature=0.3):
            return LLMResponse(
                content=[TextBlock(text="ok")],
                stop_reason="end_turn",
                usage=Usage(input_tokens=2, output_tokens=1),
            )

    agent = Agent(
        provider=OnceProvider(),
        registry=build_empty_registry(),
        cfg=Config(
            enable_tools=False,
            enable_streaming=False,
            enable_microcompact=False,
            enable_autocompact=False,
        ),
        console=Console(file=io.StringIO()),
    )
    response = agent._traced_call_model([])
    assert response.first_token_at is None
    assert "completion_start_time" not in updates[-1]
    assert updates[-1]["usage_details"] == {"input": 2, "output": 1}


def test_enabled_path_calls_client_and_swallows_errors(disabled, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(disabled, "_ENABLED", True)
    monkeypatch.setattr(disabled, "_get_client", lambda: client)

    disabled.update_span(name="read_file")
    disabled.update_generation(model="m", usage_details={"input": 1, "output": 2})
    disabled.flush()
    client.update_current_span.assert_called_once_with(name="read_file")
    client.update_current_generation.assert_called_once_with(
        model="m", usage_details={"input": 1, "output": 2}
    )
    client.flush.assert_called_once()

    client.update_current_span.side_effect = RuntimeError("boom")
    disabled.update_span(name="x")  # 不抛异常


def test_real_sdk_nesting_with_unreachable_server(monkeypatch):
    """装了 langfuse 时：用假 key + 不可达地址，三层装饰器嵌套调用不得影响返回值。"""
    pytest.importorskip("langfuse")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.delenv("ICECODE_ENABLE_LANGFUSE", raising=False)
    mod = importlib.reload(obs)
    try:
        assert mod.is_enabled() is True

        class FakeAgent:
            session_path = None

            @mod.observe(as_type="generation", name="call_model", capture_input=False)
            def gen(self):
                mod.update_generation(model="m", usage_details={"input": 1, "output": 1})
                return "resp"

            @mod.observe(as_type="span", capture_input=False)
            def tool(self, name):
                mod.update_span(name=name, input=mod.maybe_args(name, {"a": 1}))
                mod.update_span(output=mod.maybe_text("out"), level="DEFAULT")
                return "out", False

            @mod.observe_turn
            def run_turn(self, text):
                return (self.gen(), self.tool("read_file"), text)

        assert FakeAgent().run_turn("hi") == ("resp", ("out", False), "hi")
        mod.flush()
    finally:
        monkeypatch.undo()
        importlib.reload(obs)
