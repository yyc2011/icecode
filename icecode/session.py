"""
会话持久化：按工作目录存 JSONL transcript，支持 resume / continue。

最小实现：追加写 + 按 mtime 列出；不做 parent-chain / sidechain / 远程会话。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from icecode.llm.base import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
)

ICECODE_HOME_DEFAULT = "~/.icecode"


def icecode_home() -> Path:
    return Path(os.getenv("ICECODE_HOME", ICECODE_HOME_DEFAULT)).expanduser()


def projects_dir() -> Path:
    return icecode_home() / "projects"


def sanitize_workdir(workdir: str) -> str:
    """把绝对路径变成目录名安全的 slug。"""
    resolved = str(Path(workdir).resolve())
    slug = resolved.lstrip("/").replace("/", "-").replace("\\", "-").replace(":", "-")
    return slug or "root"


def session_dir_for(workdir: str) -> Path:
    path = projects_dir() / sanitize_workdir(workdir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def new_session_id() -> str:
    return uuid.uuid4().hex


def transcript_path(workdir: str, session_id: str) -> Path:
    return session_dir_for(workdir) / f"{session_id}.jsonl"


def content_block_to_dict(block: TextBlock | ToolUseBlock | ToolResultBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
        }
    return {
        "type": "tool_result",
        "tool_use_id": block.tool_use_id,
        "content": block.content,
        "is_error": block.is_error,
    }


def content_block_from_dict(data: dict[str, Any]) -> TextBlock | ToolUseBlock | ToolResultBlock:
    btype = data.get("type")
    if btype == "text":
        return TextBlock(text=data.get("text") or "")
    if btype == "tool_use":
        return ToolUseBlock(
            id=data.get("id") or "",
            name=data.get("name") or "",
            input=data.get("input") or {},
        )
    if btype == "tool_result":
        return ToolResultBlock(
            tool_use_id=data.get("tool_use_id") or "",
            content=data.get("content") or "",
            is_error=bool(data.get("is_error", False)),
        )
    raise ValueError(f"未知 content block type: {btype!r}")


def message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "type": "message",
        "role": message.role,
        "content": [content_block_to_dict(b) for b in message.content],
    }


def message_from_dict(data: dict[str, Any]) -> Message:
    role = data.get("role")
    if role not in ("user", "assistant"):
        raise ValueError(f"未知 message role: {role!r}")
    content = [content_block_from_dict(b) for b in data.get("content") or []]
    return Message(role=role, content=content)


def _append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def append_message(path: Path, message: Message) -> None:
    _append_jsonl(path, message_to_dict(message))


def append_compact_boundary(
    path: Path,
    trigger: Literal["auto", "manual"],
    pre_tokens: int,
) -> None:
    """写入 compact 分界行（本地元数据，不发给模型）。"""
    _append_jsonl(
        path,
        {
            "type": "compact_boundary",
            "trigger": trigger,
            "pre_tokens": pre_tokens,
        },
    )


def append_usage_snapshot(path: Path, usage: Usage, after_index: int) -> None:
    """写入窗口占用估算用的 usage 快照（本地元数据，不发给模型）。"""
    _append_jsonl(
        path,
        {
            "type": "usage_snapshot",
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "after_index": after_index,
        },
    )


def _record_kind(data: dict[str, Any]) -> str:
    """判别 JSONL 行类型。无 type 但有 role 的旧格式视为 message。"""
    kind = data.get("type")
    if kind in ("message", "compact_boundary", "usage_snapshot"):
        return kind
    if data.get("role") in ("user", "assistant"):
        return "message"
    return "unknown"


def _iter_jsonl_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def load_transcript(path: Path) -> list[Message]:
    """只还原 message 行；静默跳过 boundary / usage 等旁路记录。"""
    messages: list[Message] = []
    for data in _iter_jsonl_records(path):
        if _record_kind(data) != "message":
            continue
        messages.append(message_from_dict(data))
    return messages


@dataclass
class SessionState:
    """resume 用的活跃段：messages + 占用估算指针。"""

    messages: list[Message]
    last_usage: Usage
    last_usage_message_index: int


def empty_session_state() -> SessionState:
    return SessionState(messages=[], last_usage=Usage(), last_usage_message_index=0)


def load_session_state(path: Path) -> SessionState:
    """从 JSONL 恢复活跃段。

    遇到 compact_boundary 时丢弃此前 messages 与 usage 快照（旧占用作废）。
    usage_snapshot 只在当前 boundary 段内生效。
    """
    messages: list[Message] = []
    last_usage = Usage()
    last_usage_message_index = 0

    for data in _iter_jsonl_records(path):
        kind = _record_kind(data)
        if kind == "compact_boundary":
            messages = []
            last_usage = Usage()
            last_usage_message_index = 0
            continue
        if kind == "usage_snapshot":
            last_usage = Usage(
                input_tokens=int(data.get("input_tokens") or 0),
                output_tokens=int(data.get("output_tokens") or 0),
            )
            last_usage_message_index = int(data.get("after_index") or 0)
            continue
        if kind == "message":
            messages.append(message_from_dict(data))

    return SessionState(
        messages=messages,
        last_usage=last_usage,
        last_usage_message_index=last_usage_message_index,
    )


@dataclass
class SessionInfo:
    session_id: str
    path: Path
    mtime: float
    preview: str


def _preview_from_path(path: Path) -> str:
    try:
        messages = load_transcript(path)
    except Exception:
        return ""
    for m in messages:
        if m.role == "user":
            text = m.text().strip()
            if text:
                return text[:50] + ("…" if len(text) > 50 else "")
    return ""


def list_sessions(workdir: str) -> list[SessionInfo]:
    directory = session_dir_for(workdir)
    infos: list[SessionInfo] = []
    for p in directory.glob("*.jsonl"):
        session_id = p.stem
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        infos.append(
            SessionInfo(
                session_id=session_id,
                path=p,
                mtime=mtime,
                preview=_preview_from_path(p),
            )
        )
    infos.sort(key=lambda s: s.mtime, reverse=True)
    return infos


def latest_session(workdir: str) -> SessionInfo | None:
    sessions = list_sessions(workdir)
    return sessions[0] if sessions else None
