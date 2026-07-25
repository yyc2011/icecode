"""Unified diff 生成与终端着色渲染。"""

from __future__ import annotations

import difflib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

# 与常见 unified diff 展示一致：变更前后各保留若干上下文行
CONTEXT_LINES = 3


def unified_diff_text(
    path: str,
    old_content: str,
    new_content: str,
    *,
    context: int = CONTEXT_LINES,
) -> str:
    """生成 unified diff 文本；内容无变化时返回空字符串。"""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)
    # splitlines(keepends=True) 对末尾无换行的最后一行会原样保留；
    # 若两侧都无末尾换行，difflib 仍能正确对比。
    diff_iter = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=context,
    )
    return "".join(diff_iter)


def render_diff(console: Console, diff_text: str) -> None:
    """按行前缀着色打印 diff；用 Text 避免文件内容触发 Rich markup。"""
    from rich.text import Text

    if not diff_text:
        return

    for raw in diff_text.splitlines():
        if raw.startswith("+++") or raw.startswith("---"):
            style = "bold"
        elif raw.startswith("@@"):
            style = "cyan"
        elif raw.startswith("+"):
            style = "green"
        elif raw.startswith("-"):
            style = "red"
        else:
            style = "dim"
        console.print(Text(raw, style=style))
