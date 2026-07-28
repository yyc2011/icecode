"""project_context：icecode.md 加载、空白、截断。"""

from __future__ import annotations

from pathlib import Path

from icecode.project_context import (
    MAX_ICECODE_MD_CHARS,
    build_project_context_block,
    load_icecode_md,
)


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    content, truncated = load_icecode_md(tmp_path)
    assert content is None
    assert truncated is False
    assert build_project_context_block(tmp_path) == ""


def test_blank_file_treated_as_missing(tmp_path: Path) -> None:
    (tmp_path / "icecode.md").write_text("   \n\n  ", encoding="utf-8")
    content, truncated = load_icecode_md(tmp_path)
    assert content is None
    assert truncated is False
    assert build_project_context_block(tmp_path) == ""


def test_normal_content_injected_with_instruction(tmp_path: Path) -> None:
    (tmp_path / "icecode.md").write_text("# Rules\nuse pytest\n", encoding="utf-8")
    block = build_project_context_block(tmp_path)
    assert "icecode.md" in block
    assert "优先于默认行为" in block or "务必遵守" in block
    assert "use pytest" in block
    assert "截断" not in block


def test_oversize_content_truncated(tmp_path: Path) -> None:
    body = "A" * (MAX_ICECODE_MD_CHARS + 100)
    (tmp_path / "icecode.md").write_text(body, encoding="utf-8")
    content, truncated = load_icecode_md(tmp_path)
    assert truncated is True
    assert content is not None
    assert len(content) == MAX_ICECODE_MD_CHARS

    block = build_project_context_block(tmp_path)
    assert "截断" in block
    assert "A" * 50 in block
