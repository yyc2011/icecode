"""按行范围读文件：小文件快路径 + 大文件流式。

- 常规文件 < 10MB：整文件读入再切行（快路径）
- 更大文件 / 特殊文件：流式扫描，只累积目标行范围内的内容
- max_bytes + truncate_on_byte_limit=False：超限抛 FileTooLargeError（默认）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from icecode.tools.file_limits import (
    FAST_PATH_MAX_SIZE,
    format_file_size,
)


class FileTooLargeError(Exception):
    def __init__(self, size_in_bytes: int, max_size_bytes: int):
        self.size_in_bytes = size_in_bytes
        self.max_size_bytes = max_size_bytes
        super().__init__(
            f"File content ({format_file_size(size_in_bytes)}) exceeds maximum allowed size "
            f"({format_file_size(max_size_bytes)}). Use offset and limit parameters to read "
            f"specific portions of the file, or search for specific content instead of "
            f"reading the whole file."
        )


@dataclass
class ReadFileRangeResult:
    content: str
    line_count: int
    total_lines: int
    total_bytes: int
    read_bytes: int
    truncated_by_bytes: bool = False


def read_file_in_range(
    file_path: Path,
    offset: int = 0,
    max_lines: int | None = None,
    max_bytes: int | None = None,
    *,
    truncate_on_byte_limit: bool = False,
) -> ReadFileRangeResult:
    """返回行区间 [offset, offset + max_lines)（0-based offset）。"""
    path = Path(file_path)
    if path.is_dir():
        raise IsADirectoryError(f"EISDIR: illegal operation on a directory, read '{path}'")

    stats = path.stat()
    if path.is_file() and stats.st_size < FAST_PATH_MAX_SIZE:
        if (
            not truncate_on_byte_limit
            and max_bytes is not None
            and stats.st_size > max_bytes
        ):
            raise FileTooLargeError(stats.st_size, max_bytes)
        text = path.read_text(encoding="utf-8", errors="replace")
        return _read_file_in_range_fast(
            text,
            offset,
            max_lines,
            max_bytes if truncate_on_byte_limit else None,
        )

    return _read_file_in_range_streaming(
        path,
        offset,
        max_lines,
        max_bytes,
        truncate_on_byte_limit,
    )


def _strip_bom(text: str) -> str:
    if text.startswith("\ufeff"):
        return text[1:]
    return text


def _read_file_in_range_fast(
    raw: str,
    offset: int,
    max_lines: int | None,
    truncate_at_bytes: int | None,
) -> ReadFileRangeResult:
    text = _strip_bom(raw)
    end_line = offset + max_lines if max_lines is not None else float("inf")
    selected: list[str] = []
    selected_bytes = 0
    truncated = False
    line_index = 0
    start_pos = 0

    def try_push(line: str) -> bool:
        nonlocal selected_bytes, truncated
        if truncate_at_bytes is not None:
            sep = 1 if selected else 0
            next_bytes = selected_bytes + sep + len(line.encode("utf-8"))
            if next_bytes > truncate_at_bytes:
                truncated = True
                return False
            selected_bytes = next_bytes
        selected.append(line)
        return True

    while True:
        newline_pos = text.find("\n", start_pos)
        if newline_pos == -1:
            break
        if line_index >= offset and line_index < end_line and not truncated:
            line = text[start_pos:newline_pos]
            if line.endswith("\r"):
                line = line[:-1]
            try_push(line)
        line_index += 1
        start_pos = newline_pos + 1

    if line_index >= offset and line_index < end_line and not truncated:
        line = text[start_pos:]
        if line.endswith("\r"):
            line = line[:-1]
        try_push(line)
    line_index += 1

    content = "\n".join(selected)
    return ReadFileRangeResult(
        content=content,
        line_count=len(selected),
        total_lines=line_index,
        total_bytes=len(text.encode("utf-8")),
        read_bytes=len(content.encode("utf-8")),
        truncated_by_bytes=truncated,
    )


def _read_file_in_range_streaming(
    path: Path,
    offset: int,
    max_lines: int | None,
    max_bytes: int | None,
    truncate_on_byte_limit: bool,
) -> ReadFileRangeResult:
    end_line = offset + max_lines if max_lines is not None else float("inf")
    selected: list[str] = []
    selected_bytes = 0
    truncated = False
    current_line = 0
    total_bytes = 0
    partial = ""
    is_first = True

    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        while True:
            chunk = f.read(512 * 1024)
            if not chunk:
                break
            if is_first:
                is_first = False
                chunk = _strip_bom(chunk)

            total_bytes += len(chunk.encode("utf-8"))
            if (
                not truncate_on_byte_limit
                and max_bytes is not None
                and total_bytes > max_bytes
            ):
                raise FileTooLargeError(total_bytes, max_bytes)

            data = partial + chunk if partial else chunk
            partial = ""
            start_pos = 0
            while True:
                newline_pos = data.find("\n", start_pos)
                if newline_pos == -1:
                    break
                if current_line >= offset and current_line < end_line:
                    line = data[start_pos:newline_pos]
                    if line.endswith("\r"):
                        line = line[:-1]
                    if truncate_on_byte_limit and max_bytes is not None:
                        sep = 1 if selected else 0
                        next_bytes = selected_bytes + sep + len(line.encode("utf-8"))
                        if next_bytes > max_bytes:
                            truncated = True
                            end_line = current_line
                        else:
                            selected_bytes = next_bytes
                            selected.append(line)
                    else:
                        selected.append(line)
                current_line += 1
                start_pos = newline_pos + 1

            if start_pos < len(data):
                if current_line >= offset and current_line < end_line:
                    fragment = data[start_pos:]
                    if truncate_on_byte_limit and max_bytes is not None:
                        sep = 1 if selected else 0
                        frag_bytes = selected_bytes + sep + len(fragment.encode("utf-8"))
                        if frag_bytes > max_bytes:
                            truncated = True
                            end_line = current_line
                            continue
                    partial = fragment

    if current_line >= offset and current_line < end_line:
        line = partial
        if line.endswith("\r"):
            line = line[:-1]
        if truncate_on_byte_limit and max_bytes is not None:
            sep = 1 if selected else 0
            next_bytes = selected_bytes + sep + len(line.encode("utf-8"))
            if next_bytes > max_bytes:
                truncated = True
            else:
                selected.append(line)
        else:
            selected.append(line)
    current_line += 1

    content = "\n".join(selected)
    return ReadFileRangeResult(
        content=content,
        line_count=len(selected),
        total_lines=current_line,
        total_bytes=total_bytes,
        read_bytes=len(content.encode("utf-8")),
        truncated_by_bytes=truncated,
    )
