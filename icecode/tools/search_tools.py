"""glob / grep 搜索工具：共用 .icecodeignore 判定 + 明确结果上限。"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from icecode.tools.base import Tool, ToolError
from icecode.tools.file_limits import (
    DEFAULT_GLOB_RESULT_LIMIT,
    DEFAULT_GREP_RESULT_LIMIT,
)
from icecode.tools.ignore_utils import (
    is_ignored,
    load_ignore_spec,
    path_or_ancestors_ignored,
)

_GLOB_TRUNCATED_HINT = (
    f"（结果已截断，最多显示 {DEFAULT_GLOB_RESULT_LIMIT} 个文件。"
    "请用更具体的路径或模式缩小范围。）"
)
_GREP_TRUNCATED_HINT = (
    "（结果已截断。请用更具体的 pattern 或 file_glob 缩小范围。）"
)


def _walk_files(root: Path, spec):
    """用 os.walk 剪枝：忽略目录不下钻。"""
    root = root.resolve()
    for dirpath, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(dirpath)
        try:
            rel_dir = current.relative_to(root)
            rel_dir_str = "" if str(rel_dir) == "." else str(rel_dir).replace("\\", "/")
        except ValueError:
            dirnames[:] = []
            continue

        # 剪枝：原地修改 dirnames
        kept: list[str] = []
        for name in dirnames:
            child_rel = f"{rel_dir_str}/{name}" if rel_dir_str else name
            if is_ignored(child_rel, is_dir=True, spec=spec):
                continue
            kept.append(name)
        dirnames[:] = kept

        for name in filenames:
            child_rel = f"{rel_dir_str}/{name}" if rel_dir_str else name
            if is_ignored(child_rel, is_dir=False, spec=spec):
                continue
            yield current / name


class GlobTool(Tool):
    name = "glob_search"
    description = (
        "按文件名通配符模式（如 '**/*.py'）查找项目中的文件，返回匹配的文件路径列表。"
        f"最多返回 {DEFAULT_GLOB_RESULT_LIMIT} 个结果；受 .icecodeignore 与内置噪音规则过滤。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "glob 模式，例如 '**/*.py' 或 'src/**/*.ts'",
            },
        },
        "required": ["pattern"],
    }
    is_read_only = True
    is_concurrency_safe = True

    def __init__(self, workdir: str):
        self.workdir = Path(workdir)

    def execute(self, tool_input: dict) -> str:
        pattern = tool_input["pattern"]
        spec = load_ignore_spec(self.workdir)
        matches: list[str] = []
        for p in sorted(self.workdir.glob(pattern)):
            if not p.is_file():
                continue
            try:
                rel = str(p.relative_to(self.workdir)).replace("\\", "/")
            except ValueError:
                continue
            if path_or_ancestors_ignored(rel, spec):
                continue
            matches.append(rel)

        if not matches:
            return "未找到匹配的文件"

        truncated = len(matches) > DEFAULT_GLOB_RESULT_LIMIT
        shown = matches[:DEFAULT_GLOB_RESULT_LIMIT]
        body = "\n".join(shown)
        if truncated:
            return f"{body}\n{_GLOB_TRUNCATED_HINT}"
        return body


class GrepTool(Tool):
    name = "grep_search"
    description = (
        "在项目文件中按正则表达式搜索内容，返回匹配的文件名、行号和该行内容。"
        f"默认最多返回 {DEFAULT_GREP_RESULT_LIMIT} 条；可用 head_limit 调整（0=不限）。"
        "受 .icecodeignore 与内置噪音规则过滤。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "file_glob": {
                "type": "string",
                "description": "可选，限定搜索的文件范围，如 '*.py'，默认搜索所有文本文件",
                "default": "*",
            },
            "head_limit": {
                "type": "integer",
                "description": (
                    f"最多返回多少条匹配；默认 {DEFAULT_GREP_RESULT_LIMIT}；"
                    "传 0 表示不限制（慎用）"
                ),
            },
        },
        "required": ["pattern"],
    }
    is_read_only = True
    is_concurrency_safe = True

    def __init__(self, workdir: str):
        self.workdir = Path(workdir)

    def execute(self, tool_input: dict) -> str:
        try:
            regex = re.compile(tool_input["pattern"])
        except re.error as e:
            raise ToolError(f"无效的正则表达式: {e}") from e

        file_glob = tool_input.get("file_glob", "*")
        head_raw = tool_input.get("head_limit")
        if head_raw is None:
            limit: int | None = DEFAULT_GREP_RESULT_LIMIT
        else:
            limit = int(head_raw)
            if limit < 0:
                raise ToolError("head_limit 不能为负数")
            if limit == 0:
                limit = None  # 不限

        spec = load_ignore_spec(self.workdir)
        results: list[str] = []
        truncated = False
        for path in _walk_files(self.workdir, spec):
            if not fnmatch.fnmatch(path.name, file_glob):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            try:
                rel = str(path.relative_to(self.workdir)).replace("\\", "/")
            except ValueError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    results.append(f"{rel}:{i}: {line.strip()}")
                    if limit is not None and len(results) >= limit:
                        truncated = True
                        break
            if truncated:
                break

        if not results:
            return "未找到匹配内容"
        body = "\n".join(results)
        if truncated:
            return f"{body}\n{_GREP_TRUNCATED_HINT}"
        return body
