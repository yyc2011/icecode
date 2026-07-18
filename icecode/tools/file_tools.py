"""文件读写工具。"""

from __future__ import annotations

from pathlib import Path

from icecode.tools.base import Tool, ToolError


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
        "读取指定文件的内容。可选地指定起始行和结束行来只读取文件的一部分（大文件建议这样做）。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径（相对或绝对）"},
            "start_line": {"type": "integer", "description": "起始行号（从1开始），可选"},
            "end_line": {"type": "integer", "description": "结束行号（含），可选"},
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

        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = tool_input.get("start_line", 1)
        end = tool_input.get("end_line", len(lines))
        start = max(1, int(start))
        end = min(len(lines), int(end))

        numbered = [f"{i:>5}\t{lines[i - 1]}" for i in range(start, end + 1)]
        return f"文件: {path} (共{len(lines)}行，显示第{start}-{end}行)\n" + "\n".join(numbered)


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
        "对已有文件做精确的查找替换。old_str 必须在文件中唯一匹配（否则会报错要求你提供更多上下文）。"
        "这是修改已有文件的首选方式，比 write_file 更安全、更省 token。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "old_str": {"type": "string", "description": "要被替换的原文本，必须在文件中唯一出现"},
            "new_str": {"type": "string", "description": "替换后的新文本"},
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

        content = path.read_text(encoding="utf-8")
        old_str = tool_input["old_str"]
        new_str = tool_input["new_str"]

        count = content.count(old_str)
        if count == 0:
            raise ToolError("old_str 在文件中未找到，请检查是否完全匹配（包括空格/缩进）")
        if count > 1:
            raise ToolError(
                f"old_str 在文件中出现了 {count} 次，不唯一。请提供更多上下文使其唯一匹配。"
            )

        new_content = content.replace(old_str, new_str, 1)
        path.write_text(new_content, encoding="utf-8")
        return f"编辑成功: {path}\n--- 替换前 ---\n{old_str}\n--- 替换后 ---\n{new_str}"
