"""EditFileTool：确认前 diff、唯一匹配与 replace_all。"""

from __future__ import annotations

from pathlib import Path

import pytest

from icecode.tools.base import ToolError
from icecode.tools.file_tools import EditFileTool


def _tool(workdir: Path) -> EditFileTool:
    return EditFileTool(str(workdir))


def test_unique_match_diff_and_execute(tmp_path: Path) -> None:
    path = tmp_path / "sample.py"
    path.write_text("def foo():\n    return 1\n", encoding="utf-8")
    tool = _tool(tmp_path)
    tool_input = {
        "path": "sample.py",
        "old_str": "    return 1",
        "new_str": "    return 2",
    }

    diff = tool.confirmation_diff(tool_input)
    assert diff is not None
    assert "-    return 1" in diff
    assert "+    return 2" in diff

    result = tool.execute(tool_input)
    assert "替换 1 处" in result
    assert path.read_text(encoding="utf-8") == "def foo():\n    return 2\n"


def test_old_str_not_found(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("hello\n", encoding="utf-8")
    tool = _tool(tmp_path)
    with pytest.raises(ToolError, match="未找到"):
        tool.confirmation_diff(
            {"path": "a.txt", "old_str": "missing", "new_str": "x"}
        )
    assert path.read_text(encoding="utf-8") == "hello\n"


def test_multiple_matches_without_replace_all(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("x\nx\n", encoding="utf-8")
    tool = _tool(tmp_path)
    with pytest.raises(ToolError, match="不唯一"):
        tool.confirmation_diff(
            {"path": "a.txt", "old_str": "x", "new_str": "y", "replace_all": False}
        )
    assert path.read_text(encoding="utf-8") == "x\nx\n"


def test_replace_all_succeeds(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("x\nx\n", encoding="utf-8")
    tool = _tool(tmp_path)
    tool_input = {
        "path": "a.txt",
        "old_str": "x",
        "new_str": "y",
        "replace_all": True,
    }
    result = tool.execute(tool_input)
    assert "替换 2 处" in result
    assert path.read_text(encoding="utf-8") == "y\ny\n"


def test_old_equals_new_raises(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_text("same\n", encoding="utf-8")
    tool = _tool(tmp_path)
    with pytest.raises(ToolError, match="exactly the same"):
        tool._plan(
            {"path": "a.txt", "old_str": "same\n", "new_str": "same\n"}
        )


def test_missing_file_raises_and_does_not_create(tmp_path: Path) -> None:
    tool = _tool(tmp_path)
    missing = tmp_path / "nope.txt"
    with pytest.raises(ToolError, match="不存在"):
        tool.confirmation_diff(
            {"path": "nope.txt", "old_str": "a", "new_str": "b"}
        )
    assert not missing.exists()
