"""diff_utils 单元测试。"""

from __future__ import annotations

from icecode.tools.diff_utils import unified_diff_text


def test_unified_diff_no_change_returns_empty() -> None:
    text = "hello\nworld\n"
    assert unified_diff_text("a.txt", text, text) == ""


def test_unified_diff_shows_hunk_header_and_changes() -> None:
    old = "line1\nline2\nline3\n"
    new = "line1\nchanged\nline3\n"
    diff = unified_diff_text("demo.py", old, new)
    assert "@@" in diff
    assert "-line2" in diff
    assert "+changed" in diff
    assert "a/demo.py" in diff
    assert "b/demo.py" in diff
