"""命令行入口：REPL。"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from icecode.agent import Agent
from icecode.config import load_config
from icecode.llm.factory import create_provider
from icecode.session import (
    latest_session,
    list_sessions,
    load_transcript,
    new_session_id,
    transcript_path,
)
from icecode.tools.registry import build_default_registry, build_empty_registry

# macOS 上脚本内 input() 默认不加载 readline，中文退格会按字节删、删不干净。
# 交互式解释器会自动 import readline；这里显式启用并打开 UTF-8/meta。
try:
    import readline

    readline.parse_and_bind("set bind-tty-special-chars off")
    readline.parse_and_bind("set input-meta on")
    readline.parse_and_bind("set output-meta on")
    readline.parse_and_bind("set convert-meta off")
    readline.parse_and_bind("set enable-meta-keybindings on")
except ImportError:
    pass

console = Console()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="icecode", description="IceCode CLI agent")
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-c",
        "--continue",
        dest="continue_session",
        action="store_true",
        help="恢复当前工作目录下最近一次会话",
    )
    group.add_argument(
        "-r",
        "--resume",
        dest="resume_session",
        action="store_true",
        help="列出历史会话并选择恢复",
    )
    return parser.parse_args(argv)


def _pick_resume_session(workdir: str) -> tuple[str, Path, int] | None:
    sessions = list_sessions(workdir)
    if not sessions:
        console.print("[yellow]没有可恢复的会话，将开启新会话。[/yellow]")
        return None

    console.print("[bold]历史会话：[/bold]")
    for i, s in enumerate(sessions, start=1):
        when = datetime.fromtimestamp(s.mtime).strftime("%Y-%m-%d %H:%M")
        preview = s.preview or "(空)"
        console.print(f"  [{i}] {s.session_id[:8]}  {when}  {preview}")

    try:
        raw = input("选择编号（回车取消）: ").strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None

    if not raw:
        return None
    try:
        idx = int(raw)
    except ValueError:
        console.print("[red]无效编号[/red]")
        return None
    if idx < 1 or idx > len(sessions):
        console.print("[red]编号超出范围[/red]")
        return None

    chosen = sessions[idx - 1]
    loaded = load_transcript(chosen.path)
    return chosen.session_id, chosen.path, len(loaded)


def _resolve_session(
    workdir: str, *, continue_session: bool, resume_session: bool
) -> tuple[str, Path, list]:
    """返回 (session_id, path, loaded_messages)。"""
    if continue_session:
        latest = latest_session(workdir)
        if latest is None:
            console.print("[yellow]没有可继续的会话，将开启新会话。[/yellow]")
        else:
            messages = load_transcript(latest.path)
            return latest.session_id, latest.path, messages

    if resume_session:
        picked = _pick_resume_session(workdir)
        if picked is not None:
            session_id, path, _n = picked
            return session_id, path, load_transcript(path)

    session_id = new_session_id()
    path = transcript_path(workdir, session_id)
    return session_id, path, []


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    cfg = load_config()

    session_id, session_path, loaded_messages = _resolve_session(
        cfg.workdir,
        continue_session=args.continue_session,
        resume_session=args.resume_session,
    )

    tools_label = "on" if cfg.enable_tools else "off (chat-only)"
    stream_label = "on" if cfg.enable_streaming else "off"
    if loaded_messages:
        session_label = f"{session_id[:8]} (已恢复 {len(loaded_messages)} 条消息)"
    else:
        session_label = f"{session_id[:8]} (new)"

    console.print(
        Panel.fit(
            f"[bold cyan]IceCode[/bold cyan]\n"
            f"provider: [green]{cfg.provider}[/green]  "
            f"workdir: {cfg.workdir}\n"
            f"tools: {tools_label}  stream: {stream_label}  "
            f"permission: {cfg.permission_mode}\n"
            f"session: {session_label}",
            border_style="cyan",
        )
    )

    try:
        provider = create_provider(cfg)
    except RuntimeError as e:
        console.print(f"[red]配置错误: {e}[/red]")
        console.print("[dim]请复制 .env.example 为 .env 并填写 API Key。[/dim]")
        sys.exit(1)

    registry = (
        build_default_registry(cfg.workdir)
        if cfg.enable_tools
        else build_empty_registry()
    )
    agent = Agent(
        provider=provider,
        registry=registry,
        cfg=cfg,
        console=console,
        session_path=session_path,
    )
    if loaded_messages:
        agent.messages = loaded_messages

    console.print("[dim]输入你的需求，输入 exit / quit 退出。[/dim]\n")

    while True:
        try:
            # 无颜色 prompt，避免 ANSI 宽度被 readline 算错
            user_input = input("icecode> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见[/dim]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        try:
            # 流式开启时最终回答已在 Agent 内 Live 渲染；此处不再重复 Panel
            agent.run_turn(user_input)
        except Exception as e:
            console.print(f"[red]发生错误: {type(e).__name__}: {e}[/red]")
            continue


if __name__ == "__main__":
    main()
