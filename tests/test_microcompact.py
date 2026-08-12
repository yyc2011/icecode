"""Microcompact 纯函数单测。"""

from __future__ import annotations

from icecode.compact.microcompact import (
    CLEARED_PLACEHOLDER,
    MicrocompactResult,
    collect_compactable_tool_use_ids,
    microcompact_messages,
)
from icecode.compact.tokens import estimate_text_tokens
from icecode.llm.base import Message, TextBlock, ToolResultBlock, ToolUseBlock
from icecode.llm.pairing import ensure_tool_result_pairing


def _tool_pair(
    tool_id: str,
    name: str,
    result_content: str,
) -> list[Message]:
    return [
        Message.assistant(
            [ToolUseBlock(id=tool_id, name=name, input={"path": f"{tool_id}.txt"})]
        ),
        Message.tool_results(
            [ToolResultBlock(tool_use_id=tool_id, content=result_content)]
        ),
    ]


def _build_n_read_file(n: int, content_len: int = 40) -> list[Message]:
    messages: list[Message] = [Message.user_text("read many files")]
    for i in range(n):
        messages.extend(_tool_pair(f"id_{i}", "read_file", "x" * content_len))
    return messages


def test_collect_compactable_tool_use_ids_order() -> None:
    messages = [
        Message.user_text("go"),
        *_tool_pair("a", "read_file", "1"),
        *_tool_pair("b", "bash", "2"),
        *_tool_pair("c", "unknown_tool", "3"),
    ]
    assert collect_compactable_tool_use_ids(messages) == ["a", "b"]


def test_microcompact_clears_old_keeps_recent() -> None:
    messages = _build_n_read_file(5, content_len=40)
    result = microcompact_messages(messages, keep_recent=3)
    assert isinstance(result, MicrocompactResult)
    assert result.cleared_count == 2
    assert len(result.messages) == len(messages)

    # id_0, id_1 cleared; id_2..id_4 kept
    cleared_ids = {"id_0", "id_1"}
    kept_ids = {"id_2", "id_3", "id_4"}
    for msg in result.messages:
        for block in msg.content:
            if isinstance(block, ToolResultBlock):
                if block.tool_use_id in cleared_ids:
                    assert block.content == CLEARED_PLACEHOLDER
                elif block.tool_use_id in kept_ids:
                    assert block.content == "x" * 40

    expected_saved = 2 * (
        estimate_text_tokens("x" * 40) - estimate_text_tokens(CLEARED_PLACEHOLDER)
    )
    assert result.tokens_saved == max(0, expected_saved)


def test_non_compactable_tool_not_cleared() -> None:
    messages = [Message.user_text("go")]
    for i in range(5):
        messages.extend(_tool_pair(f"u_{i}", "unknown_tool", "payload" * 10))
    # also add enough compactable to trigger
    for i in range(5):
        messages.extend(_tool_pair(f"r_{i}", "read_file", "data" * 10))

    result = microcompact_messages(messages, keep_recent=3)
    for msg in result.messages:
        for block in msg.content:
            if isinstance(block, ToolResultBlock) and block.tool_use_id.startswith("u_"):
                assert block.content == "payload" * 10


def test_below_keep_recent_no_clear() -> None:
    messages = _build_n_read_file(2)
    result = microcompact_messages(messages, keep_recent=3)
    assert result.cleared_count == 0
    assert result.tokens_saved == 0
    # contents unchanged
    for orig, new in zip(messages, result.messages):
        for ob, nb in zip(orig.content, new.content):
            if isinstance(ob, ToolResultBlock):
                assert isinstance(nb, ToolResultBlock)
                assert nb.content == ob.content


def test_message_structure_invariant() -> None:
    messages = _build_n_read_file(4)
    result = microcompact_messages(messages, keep_recent=2)
    assert len(result.messages) == len(messages)
    for orig, new in zip(messages, result.messages):
        assert orig.role == new.role
        assert len(orig.content) == len(new.content)
        for ob, nb in zip(orig.content, new.content):
            assert type(ob) is type(nb)
            if isinstance(ob, ToolUseBlock):
                assert isinstance(nb, ToolUseBlock)
                assert ob.id == nb.id
                assert ob.name == nb.name
            if isinstance(ob, ToolResultBlock):
                assert isinstance(nb, ToolResultBlock)
                assert ob.tool_use_id == nb.tool_use_id


def test_compatible_with_ensure_tool_result_pairing() -> None:
    messages = _build_n_read_file(6)
    before = ensure_tool_result_pairing(messages)
    result = microcompact_messages(messages, keep_recent=3)
    after = ensure_tool_result_pairing(result.messages)

    def _ids(msgs: list[Message]) -> tuple[set[str], set[str]]:
        uses: set[str] = set()
        results: set[str] = set()
        for m in msgs:
            for b in m.content:
                if isinstance(b, ToolUseBlock):
                    uses.add(b.id)
                elif isinstance(b, ToolResultBlock):
                    results.add(b.tool_use_id)
        return uses, results

    before_uses, before_results = _ids(before)
    after_uses, after_results = _ids(after)
    assert before_uses == after_uses
    assert before_results == after_results
    assert before_uses == before_results
    # pairing 不应插入合成结果（结构已完整）
    assert len(after) == len(result.messages)


def test_does_not_mutate_input() -> None:
    messages = _build_n_read_file(4)
    original_contents = [
        b.content
        for m in messages
        for b in m.content
        if isinstance(b, ToolResultBlock)
    ]
    microcompact_messages(messages, keep_recent=2)
    after_contents = [
        b.content
        for m in messages
        for b in m.content
        if isinstance(b, ToolResultBlock)
    ]
    assert original_contents == after_contents


def test_assistant_text_never_cleared() -> None:
    messages = [
        Message.user_text("go"),
        Message.assistant(
            [
                TextBlock(text="I will read files"),
                ToolUseBlock(id="id_0", name="read_file", input={}),
            ]
        ),
        Message.tool_results([ToolResultBlock(tool_use_id="id_0", content="big" * 20)]),
    ]
    for i in range(1, 5):
        messages.extend(_tool_pair(f"id_{i}", "read_file", "big" * 20))

    result = microcompact_messages(messages, keep_recent=2)
    # first assistant text intact
    text_blocks = [
        b
        for m in result.messages
        for b in m.content
        if isinstance(b, TextBlock)
    ]
    assert any(b.text == "I will read files" for b in text_blocks)
