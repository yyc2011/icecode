"""文件工具限制常量。"""

from __future__ import annotations

MAX_OUTPUT_SIZE = int(0.25 * 1024 * 1024)  # 256 KiB

DEFAULT_MAX_OUTPUT_TOKENS = 25_000

MAX_LINES_TO_READ = 2000

# 小于此尺寸走整读快路径
FAST_PATH_MAX_SIZE = 10 * 1024 * 1024  # 10 MiB

# 防 OOM：整文件读入内存做 str replace 前的硬门禁
MAX_EDIT_FILE_SIZE = 1024 * 1024 * 1024  # 1 GiB (stat bytes)


def format_file_size(n: int) -> str:
    """格式化字节数为 B / KB / MB / GB。"""
    if n < 1024:
        return f"{n} B"
    kb = n / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.2f} MB"
    return f"{mb / 1024:.1f} GB"


def rough_token_count(text: str) -> int:
    """无 tokenizer API 时的粗估（约 4 字符/token），用于门禁。"""
    return max(1, len(text) // 4) if text else 0
