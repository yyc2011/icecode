"""工作区项目说明 icecode.md 的加载与 system prompt 注入块。"""

from __future__ import annotations

from pathlib import Path

ICECODE_MD_FILENAME = "icecode.md"
# icecode.md 注入 system prompt 的字符上限；超出则硬截断
MAX_ICECODE_MD_CHARS = 40_000

_MEMORY_INSTRUCTION = (
    "以下是本项目的约定与指令（来自工作区根目录 icecode.md）。"
    "请务必遵守；这些说明优先于默认行为，必须按其执行。"
)


def load_icecode_md(workdir: Path | str) -> tuple[str | None, bool]:
    """
    读取 icecode.md。

    返回 (content_or_none, truncated)：
    - 不存在 / 空白 → (None, False)
    - 超限 → (截断后内容, True)
    - 正常 → (全文, False)
    """
    path = Path(workdir) / ICECODE_MD_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, False
    except OSError:
        return None, False

    content = raw.strip()
    if not content:
        return None, False

    if len(content) > MAX_ICECODE_MD_CHARS:
        return content[:MAX_ICECODE_MD_CHARS], True
    return content, False


def build_project_context_block(workdir: Path | str) -> str:
    """拼进 system prompt 的项目说明块；无有效文件时返回空串。"""
    content, truncated = load_icecode_md(workdir)
    if content is None:
        return ""

    parts = [
        "",
        _MEMORY_INSTRUCTION,
        "",
        content,
    ]
    if truncated:
        parts.append("")
        parts.append(
            f"（说明：icecode.md 超过 {MAX_ICECODE_MD_CHARS} 字符，"
            "以上为截断后的内容。）"
        )
    parts.append("")
    return "\n".join(parts)
