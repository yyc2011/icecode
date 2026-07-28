"""Agent 搜索忽略规则：.icecodeignore + 内置兜底；默认不读 .gitignore。"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from pathspec import PathSpec

ICECODEIGNORE_FILENAME = ".icecodeignore"

# VCS 元数据目录：始终排除，不可被 ! 覆盖
VCS_DIRS = frozenset({".git", ".svn", ".hg", ".bzr", ".jj", ".sl"})

# 常见依赖/构建噪音：始终排除，不可被 ! 覆盖
FALLBACK_NOISE_DIRS = frozenset(
    {
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".eggs",
    }
)

# 密钥类文件：始终排除（文件名匹配）
ALWAYS_IGNORE_FILE_PATTERNS = (".env", ".env.*")

# .icecodeignore 内 opt-in 合并 .gitignore 的标记行
USE_GITIGNORE_MARKER = re.compile(
    r"^\s*#\s*icecode:\s*use-gitignore\s*$",
    re.IGNORECASE,
)


def _read_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    return text.splitlines()


def _pattern_lines_from_icecodeignore(lines: list[str]) -> tuple[list[str], bool]:
    """返回 (模式行, 是否 opt-in 合并 .gitignore)。标记行本身不作为模式。"""
    patterns: list[str] = []
    use_gitignore = False
    for line in lines:
        if USE_GITIGNORE_MARKER.match(line):
            use_gitignore = True
            continue
        patterns.append(line)
    return patterns, use_gitignore


def load_ignore_spec(workdir: Path | str) -> PathSpec | None:
    """
    加载 Agent 搜索用的 PathSpec。

    - 无 .icecodeignore → None（仅靠内置兜底）
    - 有 .icecodeignore → 编译其中模式；若含 `# icecode: use-gitignore`，
      则先合并根目录 .gitignore 行，再追加 .icecodeignore 行（后者优先）。
    """
    root = Path(workdir)
    ice_path = root / ICECODEIGNORE_FILENAME
    if not ice_path.is_file():
        return None

    ice_lines = _read_lines(ice_path)
    ice_patterns, use_gitignore = _pattern_lines_from_icecodeignore(ice_lines)

    merged: list[str] = []
    if use_gitignore:
        merged.extend(_read_lines(root / ".gitignore"))
    merged.extend(ice_patterns)

    # 去掉空内容后若无有效行，仍返回空 PathSpec（表示「用户文件存在但无模式」）
    return PathSpec.from_lines("gitignore", merged)


def _path_parts(rel_path: str) -> list[str]:
    # 统一为正斜杠，去掉尾部 /
    normalized = rel_path.replace("\\", "/").rstrip("/")
    if not normalized or normalized == ".":
        return []
    return [p for p in normalized.split("/") if p and p != "."]


def _is_always_ignored_filename(name: str) -> bool:
    for pattern in ALWAYS_IGNORE_FILE_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
    # *.egg-info 目录名
    if name.endswith(".egg-info"):
        return True
    return False


def is_ignored(rel_path: str, is_dir: bool, spec: PathSpec | None) -> bool:
    """
    判定相对 workdir 的路径是否应被搜索忽略。

    内置硬编码（VCS / 噪音目录 / .env）优先且不可被 ! 覆盖；
    其余再查 PathSpec（若有）。
    """
    parts = _path_parts(rel_path)
    if not parts:
        return False

    for part in parts:
        if part in VCS_DIRS or part in FALLBACK_NOISE_DIRS:
            return True
        if part.endswith(".egg-info"):
            return True

    # 文件名级密钥规则：对路径最后一段判定
    if _is_always_ignored_filename(parts[-1]):
        return True

    if spec is None:
        return False

    posix = "/".join(parts)
    if spec.match_file(posix):
        return True
    if is_dir and spec.match_file(posix + "/"):
        return True
    return False


def path_or_ancestors_ignored(rel_path: str, spec: PathSpec | None) -> bool:
    """文件或其任一祖先目录被忽略时返回 True（用于 glob 结果过滤）。"""
    parts = _path_parts(rel_path)
    # 逐级检查祖先目录
    for i in range(1, len(parts)):
        ancestor = "/".join(parts[:i])
        if is_ignored(ancestor, is_dir=True, spec=spec):
            return True
    # 文件自身
    return is_ignored(rel_path, is_dir=False, spec=spec)
