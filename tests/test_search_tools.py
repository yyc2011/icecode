"""搜索工具：.icecodeignore、默认不读 .gitignore、Glob/Grep 一致、上限截断。"""

from __future__ import annotations

from pathlib import Path

from icecode.tools.file_limits import (
    DEFAULT_GLOB_RESULT_LIMIT,
    DEFAULT_GREP_RESULT_LIMIT,
)
from icecode.tools.ignore_utils import is_ignored, load_ignore_spec
from icecode.tools.search_tools import GlobTool, GrepTool


def _write(path: Path, text: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_default_does_not_respect_gitignore(tmp_path: Path) -> None:
    """有 .gitignore 忽略 doc/，无 .icecodeignore 时仍能搜到 doc/。"""
    _write(tmp_path / "doc" / "ref.py", "hello_ref\n")
    _write(tmp_path / "src" / "app.py", "hello_app\n")
    (tmp_path / ".gitignore").write_text("doc/\n", encoding="utf-8")

    glob_out = GlobTool(str(tmp_path)).execute({"pattern": "**/*.py"})
    assert "doc/ref.py" in glob_out
    assert "src/app.py" in glob_out

    grep_out = GrepTool(str(tmp_path)).execute({"pattern": "hello_"})
    assert "doc/ref.py" in grep_out
    assert "src/app.py" in grep_out


def test_icecodeignore_hides_from_both_tools(tmp_path: Path) -> None:
    _write(tmp_path / "keep" / "a.py", "needle_keep\n")
    _write(tmp_path / "secret" / "b.py", "needle_secret\n")
    (tmp_path / ".icecodeignore").write_text("secret/\n", encoding="utf-8")

    glob_out = GlobTool(str(tmp_path)).execute({"pattern": "**/*.py"})
    assert "keep/a.py" in glob_out
    assert "secret/b.py" not in glob_out

    grep_out = GrepTool(str(tmp_path)).execute({"pattern": "needle_"})
    assert "keep/a.py" in grep_out
    assert "secret/b.py" not in grep_out


def test_negation_in_icecodeignore(tmp_path: Path) -> None:
    # gitignore 语义：父目录用 vendor/ 排除后无法 ! 再包含内部文件；
    # 用 vendor/* 排除内容后，!vendor/keep.py 才生效。
    _write(tmp_path / "vendor" / "lib.py", "vendor_lib\n")
    _write(tmp_path / "vendor" / "keep.py", "vendor_keep\n")
    (tmp_path / ".icecodeignore").write_text(
        "vendor/*\n!vendor/keep.py\n", encoding="utf-8"
    )

    glob_out = GlobTool(str(tmp_path)).execute({"pattern": "vendor/**/*.py"})
    assert "vendor/keep.py" in glob_out
    assert "vendor/lib.py" not in glob_out


def test_opt_in_use_gitignore(tmp_path: Path) -> None:
    _write(tmp_path / "doc" / "ref.py", "doc_only\n")
    _write(tmp_path / "src" / "app.py", "src_only\n")
    (tmp_path / ".gitignore").write_text("doc/\n", encoding="utf-8")
    (tmp_path / ".icecodeignore").write_text(
        "# icecode: use-gitignore\n", encoding="utf-8"
    )

    glob_out = GlobTool(str(tmp_path)).execute({"pattern": "**/*.py"})
    assert "doc/ref.py" not in glob_out
    assert "src/app.py" in glob_out

    grep_out = GrepTool(str(tmp_path)).execute({"pattern": "_only"})
    assert "doc/ref.py" not in grep_out
    assert "src/app.py" in grep_out


def test_builtin_vcs_and_env_always_ignored(tmp_path: Path) -> None:
    # 用 .svn 代替 .git，避免沙箱禁止写 .git/
    _write(tmp_path / ".svn" / "entries", "svnstuff\n")
    _write(tmp_path / ".env", "SECRET=1\n")
    _write(tmp_path / "ok.py", "SECRET=ok\n")

    assert is_ignored(".git", is_dir=True, spec=None)
    assert is_ignored(".svn", is_dir=True, spec=None)
    assert is_ignored(".env", is_dir=False, spec=None)

    glob_out = GlobTool(str(tmp_path)).execute({"pattern": "**/*"})
    lines = [ln for ln in glob_out.splitlines() if not ln.startswith("（")]
    assert ".env" not in lines
    assert "ok.py" in lines
    assert not any(".svn" in ln for ln in lines)

    grep_out = GrepTool(str(tmp_path)).execute({"pattern": "SECRET"})
    assert ".env" not in grep_out
    assert "ok.py" in grep_out


def test_glob_and_grep_visibility_consistent(tmp_path: Path) -> None:
    """同一路径：Glob 看不到 ⟺ Grep 也看不到。"""
    _write(tmp_path / "visible" / "a.py", "marker_visible\n")
    _write(tmp_path / "hidden" / "b.py", "marker_hidden\n")
    (tmp_path / ".icecodeignore").write_text("hidden/\n", encoding="utf-8")
    spec = load_ignore_spec(tmp_path)

    assert not is_ignored("visible/a.py", is_dir=False, spec=spec)
    assert is_ignored("hidden", is_dir=True, spec=spec) or is_ignored(
        "hidden/b.py", is_dir=False, spec=spec
    )

    glob_out = GlobTool(str(tmp_path)).execute({"pattern": "**/*.py"})
    grep_out = GrepTool(str(tmp_path)).execute({"pattern": "marker_"})

    for path in ("visible/a.py", "hidden/b.py"):
        in_glob = path in glob_out
        in_grep = path in grep_out
        assert in_glob == in_grep, f"{path}: glob={in_glob} grep={in_grep}"


def test_glob_result_limit_truncation(tmp_path: Path) -> None:
    for i in range(DEFAULT_GLOB_RESULT_LIMIT + 5):
        _write(tmp_path / "files" / f"f{i:03d}.txt", "x\n")

    out = GlobTool(str(tmp_path)).execute({"pattern": "files/*.txt"})
    lines = [ln for ln in out.splitlines() if not ln.startswith("（")]
    assert len(lines) == DEFAULT_GLOB_RESULT_LIMIT
    assert "结果已截断" in out


def test_grep_head_limit_default_and_zero(tmp_path: Path) -> None:
    # 每文件一行匹配，超过默认上限
    for i in range(DEFAULT_GREP_RESULT_LIMIT + 3):
        _write(tmp_path / "g" / f"f{i:03d}.txt", f"hit_line_{i}\n")

    default_out = GrepTool(str(tmp_path)).execute({"pattern": "hit_line_"})
    default_hits = [ln for ln in default_out.splitlines() if "hit_line_" in ln]
    assert len(default_hits) == DEFAULT_GREP_RESULT_LIMIT
    assert "结果已截断" in default_out

    unlimited = GrepTool(str(tmp_path)).execute(
        {"pattern": "hit_line_", "head_limit": 0}
    )
    unlimited_hits = [ln for ln in unlimited.splitlines() if "hit_line_" in ln]
    assert len(unlimited_hits) == DEFAULT_GREP_RESULT_LIMIT + 3
    assert "结果已截断" not in unlimited
