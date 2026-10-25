"""
内置子 Agent 类型：general-purpose（全工具子集）与 Explore（只读搜索）。

子 Agent 的工具集 = 父 registry 的子集：先剔除全局禁用集（含 agent 自身，禁止再派生），
再按类型的 allow / deny 过滤。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from icecode.prompts import TOOL_USAGE_GUIDE, WORKING_PRINCIPLES

AGENT_TOOL_NAME = "agent"

# 所有子 Agent 强制剔除：禁止递归派生。
ALL_AGENT_DISALLOWED_TOOLS: frozenset[str] = frozenset({AGENT_TOOL_NAME})

DEFAULT_AGENT_TYPE = "general-purpose"


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    when_to_use: str
    # None 表示通配（全部工具，再减 disallowed）
    tools: tuple[str, ...] | None
    disallowed_tools: frozenset[str] = field(default_factory=frozenset)
    # 只读搜索类不需要项目说明，省 token
    omit_project_context: bool = False
    build_system_prompt: Callable[[str, str], str] = field(
        default=lambda workdir, project_context: ""
    )


def _general_purpose_prompt(workdir: str, project_context: str) -> str:
    return (
        f"你是 IceCode 派生出的子 Agent，工作目录是: {workdir}\n\n"
        "你会收到一个自包含的任务描述，用提供的工具把任务完整做完："
        "不要过度发挥，也不要半途而废。\n\n"
        "擅长：在大型代码库中搜索代码/配置/模式、分析多个文件理解结构、"
        "调查需要探索许多文件的复杂问题、执行多步调研。\n\n"
        f"{WORKING_PRINCIPLES}\n"
        "子 Agent 额外约束：\n"
        "- 不知道东西在哪时先广泛搜索，知道具体路径时直接 read_file；第一种搜索无果就换搜索策略。\n"
        "- 除非任务必需，不要新建文件；优先编辑已有文件。不要主动创建文档类文件。\n"
        "- 完成后用简洁的报告回复（做了什么、关键发现）。调用方会把报告转述给用户，"
        "所以只需要要点，不要重复贴大段原文。\n\n"
        f"{TOOL_USAGE_GUIDE}"
        f"{project_context}"
    )


def _explore_prompt(workdir: str, project_context: str) -> str:
    # project_context 被忽略：omit_project_context=True
    return (
        f"你是 IceCode 派生出的只读搜索子 Agent，工作目录是: {workdir}\n\n"
        "=== 重要：只读模式，禁止修改任何文件 ===\n"
        "这是一次只读探索任务，严格禁止：\n"
        "- 新建文件（包括 touch、重定向 >、>>、heredoc 写文件，含 /tmp 下的临时文件）\n"
        "- 修改、删除、移动、复制已有文件\n"
        "- 运行任何会改变系统状态的命令（git add/commit、安装依赖等）\n\n"
        "你没有文件编辑工具，尝试编辑只会失败。你的职责只是搜索和分析现有代码。\n\n"
        "做法：\n"
        "- 用 glob_search 做宽范围文件名匹配，用 grep_search 做正则内容搜索，"
        "知道具体路径时用 read_file。\n"
        "- bash 仅限只读命令（ls、git status、git log、git diff 等）。\n"
        "- 根据调用方给出的彻底程度调整搜索深度。\n"
        "- 你是一个要求快速返回的 Agent：高效使用工具，尽量在同一轮并行发起多个搜索/读取调用。\n"
        "- 最终报告直接作为普通回复给出，不要尝试写文件；只需要要点和关键文件路径。\n"
    )


GENERAL_PURPOSE_AGENT = AgentDefinition(
    name="general-purpose",
    when_to_use=(
        "通用子 Agent：调研复杂问题、在代码库里搜索、执行多步任务。"
        "当你不确定前几次搜索能否找到目标时，交给它去搜。"
        "拥有除 agent 外的全部工具。"
    ),
    tools=None,
    build_system_prompt=_general_purpose_prompt,
)

EXPLORE_AGENT = AgentDefinition(
    name="Explore",
    when_to_use=(
        "快速、只读的代码库探索：按模式找文件、按关键词搜代码、回答「这块代码怎么工作」。"
        "调用时说明期望的彻底程度：quick / medium / very thorough。"
        "不能修改文件。"
    ),
    tools=None,
    disallowed_tools=frozenset({"write_file", "edit_file"}),
    omit_project_context=True,
    build_system_prompt=_explore_prompt,
)

BUILTIN_AGENTS: dict[str, AgentDefinition] = {
    a.name: a for a in (GENERAL_PURPOSE_AGENT, EXPLORE_AGENT)
}


def get_agent_definition(subagent_type: str | None) -> AgentDefinition | None:
    """未传类型取默认；未知类型返回 None（调用方转 ToolError）。"""
    return BUILTIN_AGENTS.get(subagent_type or DEFAULT_AGENT_TYPE)
