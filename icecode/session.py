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
from typing import Any

from icecode.llm.base import (
    Message,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
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
        "role": message.role,
        "content": [content_block_to_dict(b) for b in message.content],
    }


def message_from_dict(data: dict[str, Any]) -> Message:
    role = data.get("role")
    if role not in ("user", "assistant"):
        raise ValueError(f"未知 message role: {role!r}")
    content = [content_block_from_dict(b) for b in data.get("content") or []]
    return Message(role=role, content=content)


def append_message(path: Path, message: Message) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(message_to_dict(message), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()


def load_transcript(path: Path) -> list[Message]:
    if not path.is_file():
        return []
    messages: list[Message] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            messages.append(message_from_dict(json.loads(line)))
    return messages


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
