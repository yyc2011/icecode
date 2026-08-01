"""
tool_use / tool_result 配对修复。

发送 API 前兜底：缺 tool_result 时插入合成错误结果，避免 OpenAI 兼容接口 400。
"""

from __future__ import annotations

from icecode.llm.base import Message, TextBlock, ToolResultBlock, ToolUseBlock

# 合成占位文案（仅满足配对；内容为假结果）
SYNTHETIC_TOOL_RESULT_PLACEHOLDER = "[Tool result missing due to internal error]"


def ensure_tool_result_pairing(messages: list[Message]) -> list[Message]:
    """保证每条 assistant 的 tool_use 都有紧随的 tool_result。

    正向：缺结果 → 插入合成 is_error tool_result（必要时与下一条 user 文本合并）。
    反向：无对应 tool_use 的 tool_result → 剥离。
    跨消息重复 tool_use id → 去掉后出现的重复块。
    """
    result: list[Message] = []
    all_seen_tool_use_ids: set[str] = set()
    i = 0

    while i < len(messages):
        msg = messages[i]

        if msg.role != "assistant":
            # 无前序 assistant 时，剥掉孤立 tool_result（resume 截断常见）
            prev_is_assistant = bool(result) and result[-1].role == "assistant"
            has_tool_result = any(isinstance(b, ToolResultBlock) for b in msg.content)

            if prev_is_assistant or not has_tool_result:
                result.append(msg)
                i += 1
                continue

            stripped = [b for b in msg.content if not isinstance(b, ToolResultBlock)]
            if stripped:
                result.append(Message(role="user", content=stripped))
            elif not result:
                result.append(
                    Message.user_text(
                        "[Orphaned tool result removed due to conversation resume]"
                    )
                )
            i += 1
            continue

        # --- assistant ---
        seen_in_msg: set[str] = set()
        final_content: list = []
        for block in msg.content:
            if isinstance(block, ToolUseBlock):
                if block.id in all_seen_tool_use_ids:
                    continue
                all_seen_tool_use_ids.add(block.id)
                seen_in_msg.add(block.id)
            final_content.append(block)

        if not final_content:
            final_content = [TextBlock(text="[Tool use interrupted]")]

        if final_content != list(msg.content):
            assistant_msg = Message(role="assistant", content=final_content)
        else:
            assistant_msg = msg

        result.append(assistant_msg)

        tool_use_ids = list(seen_in_msg)
        if not tool_use_ids:
            i += 1
            continue

        next_msg = messages[i + 1] if i + 1 < len(messages) else None
        existing_result_ids: set[str] = set()
        next_has_tool_results = False

        if next_msg is not None and next_msg.role == "user":
            for b in next_msg.content:
                if isinstance(b, ToolResultBlock):
                    next_has_tool_results = True
                    existing_result_ids.add(b.tool_use_id)

        missing_ids = [tid for tid in tool_use_ids if tid not in existing_result_ids]
        orphaned_ids = existing_result_ids - set(tool_use_ids)

        if not missing_ids and not orphaned_ids:
            i += 1
            continue

        synthetics = [
            ToolResultBlock(
                tool_use_id=tid,
                content=SYNTHETIC_TOOL_RESULT_PLACEHOLDER,
                is_error=True,
            )
            for tid in missing_ids
        ]

        if next_has_tool_results and next_msg is not None:
            kept: list = list(synthetics)
            seen_tr: set[str] = set(missing_ids)
            text_parts: list = []
            for b in next_msg.content:
                if isinstance(b, ToolResultBlock):
                    if b.tool_use_id in orphaned_ids or b.tool_use_id in seen_tr:
                        continue
                    seen_tr.add(b.tool_use_id)
                    kept.append(b)
                else:
                    text_parts.append(b)
            if kept:
                result.append(Message(role="user", content=kept + text_parts))
            elif text_parts:
                result.append(Message(role="user", content=text_parts))
            i += 2
            continue

        if synthetics:
            if (
                next_msg is not None
                and next_msg.role == "user"
                and not next_has_tool_results
            ):
                # 与下一条 user 文本合并：Anthropic 需角色交替；DeepSeek wire 会拆开
                result.append(
                    Message(role="user", content=list(synthetics) + list(next_msg.content))
                )
                i += 2
                continue
            result.append(Message.tool_results(synthetics))

        i += 1

    return result
