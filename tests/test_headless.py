"""非交互运行（-p）与数据集实验脚本的单测。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from icecode import headless
from icecode.cli import main
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


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, responses: list[LLMResponse]) -> None:
        self.model = "fake-model"
        self.responses = list(responses)
        self.calls: list[list[Message]] = []

    def create_message(
        self, messages, system, tools, max_tokens=4096, temperature=0.3
    ) -> LLMResponse:
        self.calls.append([Message(m.role, list(m.content)) for m in messages])
        return self.responses.pop(0)


def _text(text: str) -> LLMResponse:
    return LLMResponse(
        content=[TextBlock(text=text)],
        stop_reason="end_turn",
        usage=Usage(input_tokens=5, output_tokens=2),
    )


def _tool_call(tool_id: str, name: str, tool_input: dict[str, Any]) -> LLMResponse:
    return LLMResponse(
        content=[ToolUseBlock(id=tool_id, name=name, input=tool_input)],
        stop_reason="tool_use",
        usage=Usage(input_tokens=5, output_tokens=2),
    )


def test_headless_config_is_locked_down() -> None:
    base = Config(auto_approve=True, enable_streaming=True)
    base.permission_mode = "accept_edits"

    cfg = headless.build_headless_config(base)

    assert cfg.permission_mode == "dont_ask"
    assert cfg.auto_approve is False
    assert cfg.enable_streaming is False
    # 不改动传入的原配置
    assert base.permission_mode == "accept_edits"
    assert base.auto_approve is True


def test_run_prompt_returns_final_text() -> None:
    provider = ScriptedProvider([_text("你好")])
    cfg = Config(enable_tools=False)

    assert headless.run_prompt("hi", cfg=cfg, provider=provider) == "你好"


def test_run_prompt_denies_writes_without_prompting(tmp_path) -> None:
    target = tmp_path / "out.txt"
    provider = ScriptedProvider(
        [
            _tool_call(
                "t1", "write_file", {"file_path": str(target), "content": "hello"}
            ),
            _text("没能写入"),
        ]
    )
    cfg = Config(workdir=str(tmp_path), enable_tools=True, auto_approve=True)

    answer = headless.run_prompt("写个文件", cfg=cfg, provider=provider)

    assert answer == "没能写入"
    assert not target.exists()
    results = [
        b
        for b in provider.calls[1][-1].content
        if isinstance(b, ToolResultBlock)
    ]
    assert len(results) == 1 and results[0].is_error


def test_cli_print_writes_answer_to_stdout(monkeypatch, capsys) -> None:
    monkeypatch.setattr(headless, "run_prompt", lambda prompt: f"回答:{prompt}")

    main(["-p", "你好"])

    out = capsys.readouterr()
    assert out.out.strip() == "回答:你好"


def test_cli_print_failure_exits_nonzero(monkeypatch, capsys) -> None:
    def boom(prompt: str) -> str:
        raise RuntimeError("缺少 API Key")

    monkeypatch.setattr(headless, "run_prompt", boom)

    with pytest.raises(SystemExit) as exc:
        main(["-p", "你好"])

    assert exc.value.code == 1
    assert "缺少 API Key" in capsys.readouterr().err


def test_cli_print_conflicts_with_continue() -> None:
    with pytest.raises(SystemExit):
        main(["-p", "你好", "-c"])


@pytest.fixture
def experiment(monkeypatch):
    # 该模块在导入时会 setdefault 记录正文开关；先 setenv 让 monkeypatch 负责还原
    monkeypatch.setenv("ICECODE_LANGFUSE_RECORD_IO", "false")
    from icecode import experiment as module

    return module


def test_item_prompt_handles_common_shapes(experiment) -> None:
    assert experiment.item_prompt({"input": "文本"}) == "文本"
    assert experiment.item_prompt(SimpleNamespace(input="文本")) == "文本"
    assert experiment.item_prompt(SimpleNamespace(input={"input": "嵌套"})) == "嵌套"


def test_task_returns_error_text_instead_of_raising(experiment, monkeypatch) -> None:
    def boom(prompt: str) -> str:
        raise ValueError("模型超时")

    monkeypatch.setattr(experiment, "run_prompt", boom)

    out = experiment.task(item={"input": "hi"})

    assert out.startswith("⚠ 运行失败") and "模型超时" in out
