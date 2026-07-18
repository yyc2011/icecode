"""Bash 工具：确认 + 危险命令黑名单 + 超时。"""

from __future__ import annotations

import re
import subprocess

from icecode.tools.base import Tool, ToolError

_DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+/(\s|$)",
    r"\brm\s+-rf\s+~",
    r"\brm\s+-rf\s+\*",
    r":\(\)\{.*:\|:.*\};:",
    r"\bmkfs\.",
    r"\bdd\s+.*of=/dev/",
    r">\s*/dev/sd[a-z]",
    r"\bchmod\s+-R\s+000\s+/",
    r"\bcurl\b.*\|\s*sh\b",
    r"\bwget\b.*\|\s*sh\b",
    r"\bsudo\s+rm\b",
    r"\bshutdown\b",
    r"\breboot\b",
]
_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_PATTERNS), re.IGNORECASE)


def is_dangerous_command(command: str) -> bool:
    """供权限层与工具共用的黑名单检测。"""
    return bool(_DANGEROUS_RE.search(command))


class BashTool(Tool):
    name = "bash"
    description = (
        "在项目的工作目录下执行一条 shell 命令，返回 stdout/stderr。"
        "适用于运行测试、安装依赖、查看 git 状态等。不要用它做文件的批量编辑，请优先用 edit_file。"
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），默认60",
                "default": 60,
            },
        },
        "required": ["command"],
    }
    requires_confirmation = True

    def __init__(self, workdir: str):
        self.workdir = workdir

    def confirmation_summary(self, tool_input: dict) -> str:
        return f"执行命令: {tool_input.get('command', '')}"

    def validate_input(self, tool_input: dict) -> None:
        super().validate_input(tool_input)
        command = tool_input.get("command", "")
        if not str(command).strip():
            raise ToolError("command 不能为空")
        # 黑名单在 validate 阶段拦截，不进入用户确认
        if is_dangerous_command(str(command)):
            raise ToolError(f"命令被安全策略拦截，拒绝执行: {command}")

    def execute(self, tool_input: dict) -> str:
        command = tool_input["command"]
        timeout = int(tool_input.get("timeout", 60))

        # 二次拦截（防御深度）
        if is_dangerous_command(command):
            raise ToolError(f"命令被安全策略拦截，拒绝执行: {command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise ToolError(f"命令执行超时（>{timeout}s）: {command}") from e

        output = f"exit_code={result.returncode}\n"
        if result.stdout:
            output += f"--- stdout ---\n{result.stdout[-8000:]}\n"
        if result.stderr:
            output += f"--- stderr ---\n{result.stderr[-4000:]}\n"
        return output
