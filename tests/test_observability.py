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


def test_maybe_text_default_only_length(disabled):
    assert disabled.maybe_text("hello") == {"chars": 5}
    assert disabled.maybe_args("bash", {"command": "ls"}) == {
        "tool": "bash",
        "arg_keys": ["command"],
    }


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
