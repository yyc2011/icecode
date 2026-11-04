"""
工具注册表。执行管线：查找 → validate → 权限 → execute → format_result。

子 Agent 工具由 Agent 构造时注入（需要父 Agent 的运行时上下文）；
后续可在 build_default_registry 中 register 任务清单 / MCP 等工具。
"""

from __future__ import annotations

from collections.abc import Iterable

from icecode.llm.base import ToolSchema
from icecode.permissions import PermissionManager
from icecode.tools.base import Tool, ToolError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def schemas(self) -> list[ToolSchema]:
        return [t.schema() for t in self._tools.values()]

    def get(self, name: str):
        return self._tools.get(name)

    def subset(
        self, allow: Iterable[str] | None, deny: Iterable[str] = ()
    ) -> ToolRegistry:
        """返回新 registry（共享 Tool 实例）。allow=None 表示通配；deny 优先于 allow。"""
        denied = set(deny)
        allowed = None if allow is None else set(allow)
        child = ToolRegistry()
        for name, tool in self._tools.items():
            if name in denied:
                continue
            if allowed is not None and name not in allowed:
                continue
            child.register(tool)
        return child

    def execute(
        self, name: str, tool_input: dict, permission_manager: PermissionManager
    ) -> str:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"未知工具: {name}")

        # 1. 校验
        tool.validate_input(tool_input)

        # 2. 权限（fail-closed：需确认则走 PermissionManager）
        # confirmation_diff 先跑校验（失败抛 ToolError，不进确认 UI、不写盘）
        if tool.requires_confirmation:
            diff = tool.confirmation_diff(tool_input)
            permission_manager.check(
                name,
                tool.confirmation_summary(tool_input),
                is_edit_tool=name in ("write_file", "edit_file"),
                diff=diff,
            )

        # 3. 执行 + 4. 格式化
        raw = tool.execute(tool_input)
        return tool.format_result(raw)


def build_default_registry(workdir: str) -> ToolRegistry:
    from icecode.tools.bash_tool import BashTool
    from icecode.tools.file_tools import EditFileTool, ReadFileTool, WriteFileTool
    from icecode.tools.search_tools import GlobTool, GrepTool

    registry = ToolRegistry()
    registry.register(ReadFileTool(workdir))
    registry.register(WriteFileTool(workdir))
    registry.register(EditFileTool(workdir))
    registry.register(BashTool(workdir))
    registry.register(GlobTool(workdir))
    registry.register(GrepTool(workdir))
    # 预留扩展：任务清单、子代理、MCP 动态注册等
    return registry


def build_empty_registry() -> ToolRegistry:
    """无工具注册表（纯对话模式）。"""
    return ToolRegistry()
