"""agent 工具：派生同步阻塞的子 Agent，只回传其最后一条文本。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from icecode.agents.builtin import (
    AGENT_TOOL_NAME,
    BUILTIN_AGENTS,
    DEFAULT_AGENT_TYPE,
)
from icecode.tools.base import Tool, ToolError

# 子 Agent 报告回灌父上下文的字符上限，防止长报告撑大父窗口。
MAX_AGENT_RESULT_CHARS = 20_000
_TRUNCATED_HINT = "\n（子 Agent 报告已截断。如需更多细节，请缩小问题范围后重新派生。）"

# runner(description, prompt, subagent_type) -> 子 Agent 最终文本
AgentRunner = Callable[[str, str, str], str]


def _build_description() -> str:
    types = "\n".join(
        f"- {a.name}: {a.when_to_use}" for a in BUILTIN_AGENTS.values()
    )
    return (
        "派生一个子 Agent 独立完成任务，并返回它的最终报告。"
        "子 Agent 有全新的上下文、看不到当前对话，因此 prompt 必须自包含"
        "（目标、已知线索、期望返回的内容）。子 Agent 不能再派生子 Agent。\n"
        "可用类型（subagent_type，缺省为 general-purpose）：\n"
        f"{types}"
    )


class AgentTool(Tool):
    name = AGENT_TOOL_NAME
    description = _build_description()
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "任务的简短描述（3-5 个词）",
            },
            "prompt": {
                "type": "string",
                "description": "交给子 Agent 的完整任务描述（自包含）",
            },
            "subagent_type": {
                "type": "string",
                "enum": list(BUILTIN_AGENTS.keys()),
                "description": f"子 Agent 类型，缺省 {DEFAULT_AGENT_TYPE}",
            },
        },
        "required": ["description", "prompt"],
    }
    # 自身不弹确认：子循环里每个有副作用的工具各自走权限确认。
    requires_confirmation = False
    is_read_only = False
    is_concurrency_safe = False

    def __init__(self, runner: AgentRunner) -> None:
        self._runner = runner

    def validate_input(self, tool_input: dict[str, Any]) -> None:
        super().validate_input(tool_input)
        if not str(tool_input.get("prompt", "")).strip():
            raise ToolError("prompt 不能为空")
        subagent_type = tool_input.get("subagent_type") or DEFAULT_AGENT_TYPE
        if subagent_type not in BUILTIN_AGENTS:
            raise ToolError(
                f"未知 subagent_type: {subagent_type}。可用: {', '.join(BUILTIN_AGENTS)}"
            )

    def execute(self, tool_input: dict[str, Any]) -> str:
        subagent_type = tool_input.get("subagent_type") or DEFAULT_AGENT_TYPE
        return self._runner(
            str(tool_input.get("description", "")),
            str(tool_input["prompt"]),
            subagent_type,
        )

    def format_result(self, result: str) -> str:
        if len(result) <= MAX_AGENT_RESULT_CHARS:
            return result
        return result[:MAX_AGENT_RESULT_CHARS] + _TRUNCATED_HINT

    def confirmation_summary(self, tool_input: dict[str, Any]) -> str:
        return f"agent({tool_input.get('subagent_type') or DEFAULT_AGENT_TYPE})"
