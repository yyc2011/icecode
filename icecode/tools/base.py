"""工具抽象基类。fail-closed：is_read_only / is_concurrency_safe 默认 False。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from icecode.llm.base import ToolSchema


class ToolError(Exception):
    """工具执行失败，Agent 转为 is_error tool_result。"""


class Tool(ABC):
    name: str
    description: str
    input_schema: dict[str, Any]
    requires_confirmation: bool = False
    # 默认：非只读、非并发安全（fail-closed）
    is_read_only: bool = False
    is_concurrency_safe: bool = False

    def schema(self) -> ToolSchema:
        return ToolSchema(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
        )

    def validate_input(self, tool_input: dict[str, Any]) -> None:
        """入参校验；失败抛 ToolError（回传模型，不弹权限 UI）。"""
        required = self.input_schema.get("required") or []
        for key in required:
            if key not in tool_input:
                raise ToolError(f"缺少必填参数: {key}")

    @abstractmethod
    def execute(self, tool_input: dict[str, Any]) -> str:
        raise NotImplementedError

    def format_result(self, result: str) -> str:
        """结果格式化钩子；默认原样返回，子类可截断/美化。"""
        return result

    def confirmation_summary(self, tool_input: dict[str, Any]) -> str:
        return f"{self.name}({tool_input})"

    def confirmation_diff(self, tool_input: dict[str, Any]) -> str | None:
        """确认前可选的 unified diff 预览；默认无。子类可覆写。"""
        return None
