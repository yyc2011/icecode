"""
权限：副作用工具执行前确认；deny 优先 fail-closed。

PermissionMode：
  - default: 需确认的工具询问 y/n/a
  - accept_edits: 写文件类自动允许，bash 仍询问
  - dont_ask: 需要确认时直接 deny（ask→deny）
"""

from __future__ import annotations

from typing import Literal

from rich.console import Console
from rich.prompt import Prompt

PermissionMode = Literal["default", "accept_edits", "dont_ask"]

# accept_edits 模式下可自动放行的工具
_EDIT_TOOLS = frozenset({"write_file", "edit_file"})


class PermissionDenied(Exception):
    pass


class PermissionManager:
    def __init__(
        self,
        console: Console,
        auto_approve: bool = False,
        mode: PermissionMode = "default",
    ):
        self.console = console
        self.auto_approve = auto_approve
        self.mode: PermissionMode = mode
        self._always_allowed: set[str] = set()
        self._denied_tools: set[str] = set()  # 会话级 deny（显式拒绝后可选扩展）

    def deny_tool(self, tool_name: str) -> None:
        """会话级工具 deny，优先于 allow。"""
        self._denied_tools.add(tool_name)

    def check(self, tool_name: str, summary: str, *, is_edit_tool: bool = False) -> None:
        if tool_name in self._denied_tools:
            raise PermissionDenied(f"工具已被拒绝: {tool_name}")

        if self.auto_approve or tool_name in self._always_allowed:
            return

        if self.mode == "accept_edits" and (is_edit_tool or tool_name in _EDIT_TOOLS):
            return

        if self.mode == "dont_ask":
            raise PermissionDenied(f"dont_ask 模式拒绝需确认的操作: {summary}")

        self.console.print(f"\n[yellow]⚠ 即将执行:[/yellow] {summary}")
        choice = (
            Prompt.ask(
                "允许吗？",
                choices=["y", "n", "a"],
                default="y",
                show_choices=True,
            )
            .strip()
            .lower()
        )

        if choice == "n":
            raise PermissionDenied(f"用户拒绝执行: {summary}")
        if choice == "a":
            self._always_allowed.add(tool_name)
