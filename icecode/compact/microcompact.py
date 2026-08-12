"""Microcompact：本地清理旧 tool_result 内容（不调用大模型）。"""

from __future__ import annotations

from dataclasses import dataclass

from icecode.compact.tokens import estimate_text_tokens
from icecode.llm.base import Message, ToolResultBlock, ToolUseBlock

# 可被 microcompact 清理的工具名（仅清工具输出，不清用户/助手文本）
COMPACTABLE_TOOLS: set[str] = {
    "read_file",
    "write_file",
    "edit_file",
    "bash",
    "glob_search",
    "grep_search",
}

CLEARED_PLACEHOLDER = "[Old tool result content cleared]"


@dataclass(frozen=True)
class MicrocompactResult:
    messages: list[Message]
    cleared_count: int
    tokens_saved: int


def collect_compactable_tool_use_ids(messages: list[Message]) -> list[str]:
    """按出现顺序收集 compactable 工具的 tool_use id。"""
    ids: list[str] = []
    for message in messages:
        for block in message.content:
            if isinstance(block, ToolUseBlock) and block.name in COMPACTABLE_TOOLS:
                ids.append(block.id)
    return ids


def microcompact_messages(
    messages: list[Message],
    keep_recent: int,
) -> MicrocompactResult:
    """将旧 compactable tool_result 替换为占位串；不删消息、不改 id。

    keep_recent 至少为 1（避免清光全部工具结果）。
    不修改入参，返回新消息列表。
    """
    keep_recent = max(1, keep_recent)
    compactable_ids = collect_compactable_tool_use_ids(messages)
    if len(compactable_ids) <= keep_recent:
        return MicrocompactResult(
            messages=list(messages),
            cleared_count=0,
            tokens_saved=0,
        )

    keep_set = set(compactable_ids[-keep_recent:])
    clear_set = {tid for tid in compactable_ids if tid not in keep_set}

    cleared_count = 0
    tokens_saved = 0
    new_messages: list[Message] = []

    for message in messages:
        touched = False
        new_content = []
        for block in message.content:
            if (
                isinstance(block, ToolResultBlock)
                and block.tool_use_id in clear_set
                and block.content != CLEARED_PLACEHOLDER
            ):
                old_tokens = estimate_text_tokens(block.content)
                new_tokens = estimate_text_tokens(CLEARED_PLACEHOLDER)
                tokens_saved += max(0, old_tokens - new_tokens)
                cleared_count += 1
                touched = True
                new_content.append(
                    ToolResultBlock(
                        tool_use_id=block.tool_use_id,
                        content=CLEARED_PLACEHOLDER,
                        is_error=block.is_error,
                    )
                )
            else:
                new_content.append(block)
        if touched:
            new_messages.append(Message(role=message.role, content=new_content))
        else:
            new_messages.append(message)

    return MicrocompactResult(
        messages=new_messages,
        cleared_count=cleared_count,
        tokens_saved=tokens_saved,
    )
