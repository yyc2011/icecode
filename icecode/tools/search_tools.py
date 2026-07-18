"""glob / grep 搜索工具。"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from icecode.tools.base import Tool, ToolError

_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def _walk_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and not any(part in _IGNORE_DIRS for part in p.parts):
            yield p


class GlobTool(Tool):
    name = "glob_search"
    description = "按文件名通配符模式（如 '**/*.py'）查找项目中的文件，返回匹配的文件路径列表。"
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
        matches = sorted(str(p.relative_to(self.workdir)) for p in self.workdir.glob(pattern))
        matches = [m for m in matches if not any(seg in _IGNORE_DIRS for seg in Path(m).parts)]
        if not matches:
            return "未找到匹配的文件"
        return "\n".join(matches[:200])


class GrepTool(Tool):
    name = "grep_search"
    description = "在项目文件中按正则表达式搜索内容，返回匹配的文件名、行号和该行内容。"
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式"},
            "file_glob": {
                "type": "string",
                "description": "可选，限定搜索的文件范围，如 '*.py'，默认搜索所有文本文件",
                "default": "*",
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
        results = []
        for path in _walk_files(self.workdir):
            if not fnmatch.fnmatch(path.name, file_glob):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if regex.search(line):
                    rel = path.relative_to(self.workdir)
                    results.append(f"{rel}:{i}: {line.strip()}")
                    if len(results) >= 200:
                        break
            if len(results) >= 200:
                break

        return "\n".join(results) if results else "未找到匹配内容"
