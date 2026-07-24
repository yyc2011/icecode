"""文件读写工具：read / write / edit，含 workdir 围栏与唯一 str_replace。"""

from __future__ import annotations

from pathlib import Path

from icecode.tools.base import Tool, ToolError
from icecode.tools.file_limits import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    MAX_EDIT_FILE_SIZE,
    MAX_LINES_TO_READ,
    MAX_OUTPUT_SIZE,
    format_file_size,
    rough_token_count,
)
from icecode.tools.read_file_in_range import FileTooLargeError, read_file_in_range


def _resolve(path: str, workdir: str) -> Path:
    p = Path(path)
    full = p if p.is_absolute() else Path(workdir) / p
    full = full.resolve()
    workdir_resolved = Path(workdir).resolve()
    if workdir_resolved not in full.parents and full != workdir_resolved:
        raise ToolError(f"拒绝访问 workdir 之外的路径: {path}")
    return full


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "读取本地文件内容（cat -n 行号格式）。"
        f"默认从文件开头最多读取 {MAX_LINES_TO_READ} 行；"
        f"未指定 limit 且整文件超过 {format_file_size(MAX_OUTPUT_SIZE)} 会报错。"
        "大文件请用 offset（起始行，从 1 起）与 limit（行数）分段读取，"
        "或改用 grep_search / glob_search。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对或绝对）"},
            "offset": {
                "type": "integer",
                "description": "起始行号（从 1 开始）。仅当文件太大无法一次读完时提供",
            },
            "limit": {
                "type": "integer",
                "description": "读取行数。仅当文件太大无法一次读完时提供",
            },
        },
        "required": ["path"],
    }
    is_read_only = True
    is_concurrency_safe = True

    def __init__(self, workdir: str):
        self.workdir = workdir

    def execute(self, tool_input: dict) -> str:
        path = _resolve(tool_input["path"], self.workdir)
        if not path.exists():
            raise ToolError(f"文件不存在: {path}")
        if not path.is_file():
            raise ToolError(f"不是一个文件: {path}")

        # offset 默认 1；limit 默认未指定
        offset = int(tool_input.get("offset", 1))
        if offset < 0:
            raise ToolError("offset 不能为负数")
        start_line = 1 if offset == 0 else offset

        limit_raw = tool_input.get("limit")
        if limit_raw is None:
            # 提示词承诺默认最多 MAX_LINES_TO_READ 行；同时未传 limit 时做整文件字节门禁
            limit: int | None = MAX_LINES_TO_READ
            max_bytes: int | None = MAX_OUTPUT_SIZE
        else:
            limit = int(limit_raw)
            if limit <= 0:
                raise ToolError("limit 必须为正整数")
            # 显式分段：允许读大文件的一段（跳过整文件 256KB 门禁）
            max_bytes = None

        line_offset = 0 if offset == 0 else start_line - 1
        try:
            result = read_file_in_range(path, line_offset, limit, max_bytes)
        except FileTooLargeError as e:
            raise ToolError(str(e)) from e
        except IsADirectoryError as e:
            raise ToolError(str(e)) from e

        tokens = rough_token_count(result.content)
        if tokens > DEFAULT_MAX_OUTPUT_TOKENS:
            raise ToolError(
                f"File content ({tokens} tokens) exceeds maximum allowed tokens "
                f"({DEFAULT_MAX_OUTPUT_TOKENS}). Use offset and limit parameters to read "
                f"specific portions of the file, or search for specific content instead of "
                f"reading the whole file."
            )

        if result.line_count == 0 and result.total_lines < start_line:
            return (
                f"<system-reminder>Warning: the file exists but is shorter than the "
                f"provided offset ({start_line}). The file has {result.total_lines} lines."
                f"</system-reminder>"
            )

        if result.line_count == 0:
            numbered: list[str] = []
        else:
            numbered = [
                f"{i:>6}\t{line}"
                for i, line in enumerate(result.content.split("\n"), start=start_line)
            ]

        end_shown = start_line + result.line_count - 1 if result.line_count else 0
        header = f"文件: {path} (共 {result.total_lines} 行，显示第 {start_line}-{end_shown} 行)"
        body = "\n".join(numbered)
        return f"{header}\n{body}" if body else header


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "创建新文件或完全覆盖已有文件的内容。用于新建文件；"
        "如果只是想修改已有文件的一部分，请优先使用 edit_file。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的完整文件内容"},
        },
        "required": ["path", "content"],
    }
    requires_confirmation = True

    def __init__(self, workdir: str):
        self.workdir = workdir

    def confirmation_summary(self, tool_input: dict) -> str:
        path = tool_input.get("path", "?")
        n = len(tool_input.get("content", ""))
        return f"写入文件 {path}（{n} 字符）"

    def execute(self, tool_input: dict) -> str:
        path = _resolve(tool_input["path"], self.workdir)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(tool_input["content"], encoding="utf-8")
        return f"{'覆盖' if existed else '创建'}文件成功: {path}"


class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "对已有文件做精确的查找替换。old_str 必须在文件中唯一匹配"
        "（除非 replace_all=true）。这是修改已有文件的首选方式，比 write_file 更安全、更省 token。"
        f"文件超过 {format_file_size(MAX_EDIT_FILE_SIZE)} 会被拒绝（防 OOM）；"
        "若因此失败，改用 bash 流式编辑（sed -i / awk / python），不要用 write_file 整文件重写。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_str": {
                "type": "string",
                "description": "要被替换的原文本；默认必须在文件中唯一出现",
            },
            "new_str": {"type": "string", "description": "替换后的新文本"},
            "replace_all": {
                "type": "boolean",
                "description": "为 true 时替换所有匹配",
                "default": False,
            },
        },
        "required": ["path", "old_str", "new_str"],
    }
    requires_confirmation = True

    def __init__(self, workdir: str):
        self.workdir = workdir

    def confirmation_summary(self, tool_input: dict) -> str:
        # 阶段 3：此处可改为展示 unified diff 后再确认
        return f"编辑文件 {tool_input.get('path', '?')}"

    def execute(self, tool_input: dict) -> str:
        path = _resolve(tool_input["path"], self.workdir)
        if not path.exists():
            raise ToolError(f"文件不存在: {path}")
        if not path.is_file():
            raise ToolError(f"不是一个文件: {path}")

        # 整文件读入前防 OOM
        size = path.stat().st_size
        if size > MAX_EDIT_FILE_SIZE:
            raise ToolError(
                f"File is too large to edit ({format_file_size(size)}). "
                f"Maximum editable file size is {format_file_size(MAX_EDIT_FILE_SIZE)}. "
                "Fall back to bash with streaming edits "
                "(e.g. sed -i, awk, or python line-by-line); do not load the whole file."
            )

        content = path.read_text(encoding="utf-8")
        old_str = tool_input["old_str"]
        new_str = tool_input["new_str"]
        replace_all = bool(tool_input.get("replace_all", False))

        if old_str == new_str:
            raise ToolError(
                "No changes to make: old_str and new_str are exactly the same."
            )

        count = content.count(old_str)
        if count == 0:
            raise ToolError("old_str 在文件中未找到，请检查是否完全匹配（包括空格/缩进）")
        if count > 1 and not replace_all:
            raise ToolError(
                f"old_str 在文件中出现了 {count} 次，不唯一。"
                f"请提供更多上下文使其唯一匹配，或设置 replace_all=true。"
            )

        if replace_all:
            new_content = content.replace(old_str, new_str)
            n = count
        else:
            new_content = content.replace(old_str, new_str, 1)
            n = 1
        path.write_text(new_content, encoding="utf-8")
        return (
            f"编辑成功: {path}（替换 {n} 处）\n"
            f"--- 替换前 ---\n{old_str}\n--- 替换后 ---\n{new_str}"
        )
