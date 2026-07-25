"""
工具注册表。执行管线：查找 → validate → 权限 → execute → format_result。

阶段 6 扩展点：在 build_default_registry 中 register todo / agent / mcp 工具。
"""

from __future__ import annotations

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
    # 阶段 6 预留：
    # registry.register(TodoWriteTool())
    # registry.register(AgentTool(...))
    # MCP 工具由 mcp client 动态 register
    return registry


def build_empty_registry() -> ToolRegistry:
    """阶段 0：纯对话，无工具。"""
    return ToolRegistry()
