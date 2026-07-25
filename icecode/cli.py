"""命令行入口：REPL。"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from icecode.agent import Agent
from icecode.config import load_config
from icecode.llm.factory import create_provider
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


def main() -> None:
    cfg = load_config()

    tools_label = "on" if cfg.enable_tools else "off (chat-only)"
    console.print(
        Panel.fit(
            f"[bold cyan]IceCode[/bold cyan]\n"
            f"provider: [green]{cfg.provider}[/green]  "
            f"workdir: {cfg.workdir}\n"
            f"tools: {tools_label}  permission: {cfg.permission_mode}",
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
    agent = Agent(provider=provider, registry=registry, cfg=cfg, console=console)

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
            reply = agent.run_turn(user_input)
        except Exception as e:
            console.print(f"[red]发生错误: {type(e).__name__}: {e}[/red]")
            continue

        console.print(Panel(Markdown(reply), title="assistant", border_style="green"))


if __name__ == "__main__":
    main()
