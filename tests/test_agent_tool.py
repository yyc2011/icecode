"""子 Agent（agent 工具）：工具子集、隔离、权限继承、递归防护、usage 口径。"""

from __future__ import annotations

import io
from typing import Any

import pytest
from rich.console import Console

from icecode import observability as obs
from icecode.agent import Agent
from icecode.agents.builtin import ALL_AGENT_DISALLOWED_TOOLS, get_agent_definition
from icecode.config import Config
from icecode.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)
from icecode.tools.agent_tool import MAX_AGENT_RESULT_CHARS, AgentTool
from icecode.tools.base import Tool, ToolError
from icecode.tools.registry import ToolRegistry, build_default_registry


class ScriptedProvider(LLMProvider):
    """按调用顺序返回预设响应，并记录每次请求。"""

    name = "scripted"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.model = "fake-model"
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def create_message(
        self, messages, system, tools, max_tokens=4096, temperature=0.3
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": [Message(m.role, list(m.content)) for m in messages],
                "system": system,
                "tool_names": [t.name for t in tools],
            }
        )
        return self.responses.pop(0)


def _text(text: str, i: int = 5, o: int = 2) -> LLMResponse:
    return LLMResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        usage=Usage(input_tokens=i, output_tokens=o),
    )


def _tool_call(tool_id: str, name: str, tool_input: dict, i: int = 5, o: int = 2) -> LLMResponse:
    return LLMResponse(
        content=[ToolUseBlock(id=tool_id, name=name, input=tool_input)],
        stop_reason="tool_use",
        usage=Usage(input_tokens=i, output_tokens=o),
    )


class _ConfirmTool(Tool):
    """需确认的假工具，用来观察权限继承。"""

    name = "bash"
    description = "fake"
    input_schema = {"type": "object", "properties": {}}
    requires_confirmation = True

    def __init__(self) -> None:
        self.ran = 0

    def execute(self, tool_input: dict[str, Any]) -> str:
        self.ran += 1
        return "ran"


def _make_agent(provider: ScriptedProvider, registry: ToolRegistry, **cfg_kw) -> Agent:
    cfg = Config(
        enable_tools=True,
        enable_streaming=False,
        enable_microcompact=False,
        enable_autocompact=False,
        **cfg_kw,
    )
    return Agent(
        provider=provider,
        registry=registry,
        cfg=cfg,
        console=Console(file=io.StringIO()),
    )


def _full_registry(tmp_path) -> ToolRegistry:
    return build_default_registry(str(tmp_path))


# ---------- registry.subset ----------


def test_subset_wildcard_and_deny(tmp_path) -> None:
    reg = _full_registry(tmp_path)
    sub = reg.subset(None, {"bash"})
    names = {s.name for s in sub.schemas()}
    assert "bash" not in names
    assert {"read_file", "write_file", "edit_file"} <= names


def test_subset_allow_list_and_deny_wins(tmp_path) -> None:
    reg = _full_registry(tmp_path)
    sub = reg.subset(["read_file", "bash"], {"bash"})
    assert [s.name for s in sub.schemas()] == ["read_file"]


def test_explore_subset_has_no_write_or_agent(tmp_path) -> None:
    provider = ScriptedProvider([])
    agent = _make_agent(provider, _full_registry(tmp_path))
    assert agent.registry.get("agent") is not None
    explore = get_agent_definition("Explore")
    assert explore is not None
    sub = agent.registry.subset(
        explore.tools, ALL_AGENT_DISALLOWED_TOOLS | explore.disallowed_tools
    )
    names = {s.name for s in sub.schemas()}
    assert names.isdisjoint({"agent", "write_file", "edit_file"})
    assert {"read_file", "glob_search", "grep_search", "bash"} <= names


# ---------- AgentTool 入参 ----------


def test_validate_input() -> None:
    tool = AgentTool(runner=lambda d, p, t: "x")
    with pytest.raises(ToolError):
        tool.validate_input({"description": "d"})
    with pytest.raises(ToolError):
        tool.validate_input({"description": "d", "prompt": "  "})
    with pytest.raises(ToolError):
        tool.validate_input({"description": "d", "prompt": "p", "subagent_type": "nope"})
    tool.validate_input({"description": "d", "prompt": "p"})
    tool.validate_input({"description": "d", "prompt": "p", "subagent_type": "Explore"})


def test_format_result_truncates() -> None:
    tool = AgentTool(runner=lambda d, p, t: "x")
    short = "a" * 10
    assert tool.format_result(short) == short
    long = tool.format_result("a" * (MAX_AGENT_RESULT_CHARS + 50))
    assert len(long) > MAX_AGENT_RESULT_CHARS
    assert "截断" in long


def test_agent_tool_not_registered_when_tools_disabled() -> None:
    provider = ScriptedProvider([])
    reg = ToolRegistry()
    cfg = Config(enable_tools=False, enable_streaming=False)
    Agent(provider=provider, registry=reg, cfg=cfg, console=Console(file=io.StringIO()))
    assert reg.get("agent") is None


# ---------- 端到端：隔离 / 回传 / usage ----------


def test_subagent_isolation_result_and_usage(tmp_path) -> None:
    provider = ScriptedProvider(
        [
            # 父：派生子 Agent
            _tool_call("t1", "agent", {"description": "找东西", "prompt": "找出 foo"}, 10, 1),
            # 子：直接给报告
            _text("子报告：foo 在 a.py", 7, 3),
            # 父：收到结果后收尾
            _text("好的，foo 在 a.py", 20, 4),
        ]
    )
    agent = _make_agent(provider, _full_registry(tmp_path))
    agent.messages = [Message.user_text("历史消息")]
    agent.last_call_usage = Usage(1, 1)
    agent.last_call_message_index = 1

    out = agent.run_turn("请找 foo")
    assert out == "好的，foo 在 a.py"

    parent_call, child_call, parent_call2 = provider.calls

    # 子 Agent 只看到自己的任务，没有父历史；工具集不含 agent
    assert [m.text() for m in child_call["messages"]] == ["找出 foo"]
    assert "agent" not in child_call["tool_names"]
    assert "agent" in parent_call["tool_names"]
    assert "agent" not in child_call["system"].replace("子 Agent", "")

    # 父只多出一对 tool_use / tool_result，内容为子最终文本
    last = parent_call2["messages"][-1]
    assert isinstance(last.content[0], ToolResultBlock)
    assert last.content[0].content == "子报告：foo 在 a.py"
    assert not last.content[0].is_error

    # 累计计费：父 10+20 + 子 7；output 1+4+3
    assert agent.total_usage.input_tokens == 10 + 20 + 7
    assert agent.total_usage.output_tokens == 1 + 4 + 3
    # 窗口占用快照只来自父的最后一次调用，不含子
    assert agent.last_call_usage == Usage(20, 4)


def test_subagent_cannot_spawn_agent(tmp_path) -> None:
    provider = ScriptedProvider(
        [
            _tool_call("t1", "agent", {"description": "d", "prompt": "p"}),
            # 子 Agent 幻觉再调 agent
            _tool_call("c1", "agent", {"description": "d", "prompt": "nested"}),
            _text("子收尾"),
            _text("父收尾"),
        ]
    )
    agent = _make_agent(provider, _full_registry(tmp_path))
    agent.run_turn("go")

    # 子第二次请求里能看到对 agent 的调用得到「未知工具」错误，且没有孙 Agent 请求
    assert len(provider.calls) == 4
    child_second = provider.calls[2]
    result = child_second["messages"][-1].content[0]
    assert isinstance(result, ToolResultBlock)
    assert result.is_error
    assert "未知工具" in result.content


def test_subagent_inherits_permission_manager(tmp_path) -> None:
    confirm = _ConfirmTool()
    reg = ToolRegistry()
    reg.register(confirm)
    provider = ScriptedProvider(
        [
            _tool_call("t1", "agent", {"description": "d", "prompt": "p"}),
            _tool_call("c1", "bash", {}),
            _text("子收尾"),
            _text("父收尾"),
        ]
    )
    agent = _make_agent(provider, reg)
    agent.permission_manager.mode = "dont_ask"  # 父的 mode 应被子继承

    agent.run_turn("go")

    assert confirm.ran == 0
    child_second = provider.calls[2]
    result = child_second["messages"][-1].content[0]
    assert result.is_error
    assert "dont_ask" in result.content


def test_subagent_shares_always_allowed(tmp_path) -> None:
    confirm = _ConfirmTool()
    reg = ToolRegistry()
    reg.register(confirm)
    provider = ScriptedProvider(
        [
            _tool_call("t1", "agent", {"description": "d", "prompt": "p"}),
            _tool_call("c1", "bash", {}),
            _text("子收尾"),
            _text("父收尾"),
        ]
    )
    agent = _make_agent(provider, reg)
    agent.permission_manager._always_allowed.add("bash")  # 父已选「总是允许」

    agent.run_turn("go")
    assert confirm.ran == 1


def test_subagent_exception_still_counts_usage_and_pairs_result(tmp_path) -> None:
    class Boom(ScriptedProvider):
        def create_message(self, *a, **kw):
            if len(self.calls) == 1:  # 第二次（子 Agent）调用时炸
                self.calls.append({"messages": [], "system": "", "tool_names": []})
                raise RuntimeError("boom")
            return super().create_message(*a, **kw)

    provider = Boom([_tool_call("t1", "agent", {"description": "d", "prompt": "p"}, 10, 1), _text("父收尾", 3, 1)])
    agent = _make_agent(provider, _full_registry(tmp_path))
    out = agent.run_turn("go")
    assert out == "父收尾"
    # 父的第二次请求里，agent 的 tool_result 为错误，配对完整
    result = provider.calls[-1]["messages"][-1].content[0]
    assert isinstance(result, ToolResultBlock)
    assert result.is_error
    assert "boom" in result.content


def test_parent_prompt_contains_delegation_guide(tmp_path) -> None:
    agent = _make_agent(ScriptedProvider([]), _full_registry(tmp_path))
    assert "委派子 Agent" in agent.system_prompt
    assert "专用工具优先" in agent.system_prompt


def test_subagent_prompts_do_not_expose_agent_tool() -> None:
    for name in ("general-purpose", "Explore"):
        definition = get_agent_definition(name)
        assert definition is not None
        prompt = definition.build_system_prompt("/w", "")
        assert "agent 工具" not in prompt
    explore = get_agent_definition("Explore")
    assert explore.omit_project_context
    assert "只读" in explore.build_system_prompt("/w", "")


# ---------- 可观测 ----------


def test_subagent_scope_noop_when_disabled() -> None:
    if obs.is_enabled():
        pytest.skip("Langfuse 已启用")
    with obs.subagent_scope("Explore"):
        pass


def test_start_generation_passes_name(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(obs, "update_generation", lambda **kw: captured.update(kw))
    obs.start_generation(
        "m", max_tokens=1, temperature=0.0, system="s", messages=[], tools=[],
        name="subagent_call_model",
    )
    assert captured["name"] == "subagent_call_model"
    captured.clear()
    obs.start_generation(
        "m", max_tokens=1, temperature=0.0, system="s", messages=[], tools=[],
    )
    assert "name" not in captured
