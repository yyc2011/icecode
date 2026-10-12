"""compact boundary / usage 快照 JSONL 写读与 resume 恢复。"""

from __future__ import annotations

import json
from pathlib import Path

from icecode.llm.base import Message, TextBlock, Usage
from icecode.session import (
    append_compact_boundary,
    append_message,
    append_usage_snapshot,
    load_session_state,
    load_transcript,
    message_to_dict,
)


def test_append_boundary_and_usage_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    append_message(path, Message.user_text("hello"))
    append_usage_snapshot(path, Usage(input_tokens=10, output_tokens=4), after_index=1)
    append_compact_boundary(path, "auto", pre_tokens=99)
    summary = Message.user_text("summary of hello")
    append_message(path, summary)
    append_usage_snapshot(path, Usage(input_tokens=3, output_tokens=2), after_index=1)

    state = load_session_state(path)
    assert len(state.messages) == 1
    assert state.messages[0].text() == "summary of hello"
    assert state.last_usage.input_tokens == 3
    assert state.last_usage.output_tokens == 2
    assert state.last_usage_message_index == 1


def test_load_session_state_without_boundary_keeps_all(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    append_message(path, Message.user_text("a"))
    append_message(path, Message.assistant([TextBlock(text="b")]))
    append_usage_snapshot(path, Usage(input_tokens=20, output_tokens=5), after_index=2)

    state = load_session_state(path)
    transcript = load_transcript(path)
    assert [m.text() for m in state.messages] == [m.text() for m in transcript]
    assert len(state.messages) == 2
    assert state.last_usage.input_tokens == 20
    assert state.last_usage_message_index == 2


def test_compact_boundary_invalidates_stale_usage(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    append_message(path, Message.user_text("old"))
    append_usage_snapshot(path, Usage(input_tokens=190_000, output_tokens=50), after_index=1)
    append_compact_boundary(path, "auto", pre_tokens=190_050)
    append_message(path, Message.user_text("compacted summary"))

    state = load_session_state(path)
    assert len(state.messages) == 1
    assert state.messages[0].text() == "compacted summary"
    # boundary 之后若尚无新快照，旧占用必须作废
    assert state.last_usage.input_tokens == 0
    assert state.last_usage.output_tokens == 0
    assert state.last_usage_message_index == 0


def test_legacy_jsonl_without_type_still_loads(tmp_path: Path) -> None:
    path = tmp_path / "legacy.jsonl"
    legacy = {"role": "user", "content": [{"type": "text", "text": "旧格式"}]}
    path.write_text(json.dumps(legacy, ensure_ascii=False) + "\n", encoding="utf-8")

    loaded = load_transcript(path)
    assert len(loaded) == 1
    assert loaded[0].text() == "旧格式"

    state = load_session_state(path)
    assert len(state.messages) == 1
    assert state.messages[0].text() == "旧格式"
    assert state.last_usage.input_tokens == 0


def test_load_transcript_skips_sidecar_rows(tmp_path: Path) -> None:
    path = tmp_path / "s.jsonl"
    append_message(path, Message.user_text("keep"))
    append_compact_boundary(path, "manual", pre_tokens=1)
    append_usage_snapshot(path, Usage(1, 1), after_index=0)
    append_message(path, Message.user_text("after"))

    loaded = load_transcript(path)
    assert [m.text() for m in loaded] == ["keep", "after"]


def test_message_to_dict_has_type_not_usage() -> None:
    data = message_to_dict(Message.user_text("hi"))
    assert data["type"] == "message"
    assert "usage" not in data
    assert set(data.keys()) == {"type", "role", "content"}


def test_missing_file_is_empty(tmp_path: Path) -> None:
    path = tmp_path / "missing.jsonl"
    assert load_transcript(path) == []
    state = load_session_state(path)
    assert state.messages == []
    assert state.last_usage.input_tokens == 0
    assert state.last_usage_message_index == 0
