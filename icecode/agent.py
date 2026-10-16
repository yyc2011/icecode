"""
Agent Loop：LLM 决策 → 工具执行 → 多轮直到完成。

只认 icecode.llm.base 的 canonical 协议。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

from icecode.compact.autocompact import (
    MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES,
    get_autocompact_threshold,
    should_autocompact,
)
from icecode.compact.full_compact import CompactError, run_full_compact
from icecode.compact.microcompact import microcompact_messages
from icecode.compact.prompt import build_compact_user_message
from icecode.compact.tokens import estimate_context_tokens
from icecode.compact.windows import (
    get_effective_context_window,
    get_microcompact_threshold,
    is_above_threshold,
)
from icecode import observability as obs
from icecode.config import Config
from icecode.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    StreamDone,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    Usage,
    accumulate_usage,
)
from icecode.permissions import PermissionDenied, PermissionManager
from icecode.project_context import build_project_context_block
from icecode.session import append_compact_boundary, append_message, append_usage_snapshot
from icecode.tools.base import ToolError
from icecode.tools.registry import ToolRegistry

SYSTEM_PROMPT_TEMPLATE = """\
你是 IceCode，一个运行在命令行里的编程助手，工作目录是: {workdir}

你可以使用提供的工具来读取/搜索/编辑文件，以及执行 shell 命令来完成用户的任务。

工作原则：
1. 在动手修改代码前，先用 glob_search / grep_search / read_file 了解相关代码，不要凭空猜测。
2. 修改已有文件时优先使用 edit_file 做精确替换，只有新建文件才用 write_file。
3. 每次只做用户明确要求或任务明显需要的改动，不要顺便重构无关代码。
4. 完成任务后用简洁的中文总结做了什么改动。

# 使用工具（专用工具优先）
- 读文件用 read_file，不要用 bash 的 cat/head/tail/sed。
- 改文件用 edit_file，不要用 bash 的 sed/awk。
- 新建文件用 write_file，不要用 bash 的 cat heredoc / echo 重定向。
- 找文件用 glob_search，不要用 find/ls；搜内容用 grep_search，不要用 grep/rg。
- bash 只用于需要 shell 执行的系统命令与终端操作（跑测试、git、安装依赖等）。
  若存在对应专用工具，默认用专用工具；仅当专用工具失败或不可用（例如 edit_file 因文件过大被拒）时，
  才回退到 bash，并用流式方式处理（如 sed -i、awk、python 按行读写），避免把整文件读进内存。
{project_context}
"""

SYSTEM_PROMPT_CHAT_ONLY = """\
你是 IceCode，一个运行在命令行里的编程助手，工作目录是: {workdir}

当前为纯对话模式（未启用工具）。用简洁的中文回答用户问题。
{project_context}
"""


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        cfg: Config,
        console: Console,
        session_path: Path | None = None,
    ):
        self.provider = provider
        self.registry = registry
        self.cfg = cfg
        self.console = console
        self.session_path = session_path
        self.permission_manager = PermissionManager(
            console,
            auto_approve=cfg.auto_approve,
            mode=cfg.permission_mode,
        )
        self.messages: list[Message] = []
        self.total_usage = Usage()
        # 最近一次 API 调用的 usage 与「该助手消息之后」的消息下标（窗口占用估算用）
        self.last_call_usage = Usage()
        self.last_call_message_index = 0
        self._autocompact_consecutive_failures = 0
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        project_context = build_project_context_block(self.cfg.workdir)

        template = (
            SYSTEM_PROMPT_TEMPLATE if self.cfg.enable_tools else SYSTEM_PROMPT_CHAT_ONLY
        )
        return template.format(workdir=self.cfg.workdir, project_context=project_context)

    def _record_message(self, message: Message) -> None:
        self.messages.append(message)
        if self.session_path is not None:
            append_message(self.session_path, message)

    def _print_usage(self, response: LLMResponse) -> None:
        self.total_usage = accumulate_usage(self.total_usage, response.usage)
        self.console.print(
            f"[dim]usage: 本次 input={response.usage.input_tokens} "
            f"output={response.usage.output_tokens} · "
            f"会话累计 input={self.total_usage.input_tokens} "
            f"output={self.total_usage.output_tokens}[/dim]"
        )

    def _persist_usage_snapshot(self) -> None:
        if self.session_path is not None:
            append_usage_snapshot(
                self.session_path, self.last_call_usage, self.last_call_message_index
            )

    def _apply_full_compact(self, trigger: Literal["auto", "manual"]) -> None:
        """摘要重建 messages，并作废压缩前的占用快照。"""
        pre_tokens = estimate_context_tokens(
            self.messages, self.last_call_usage, self.last_call_message_index
        )
        result = run_full_compact(
            self.messages,
            self.provider,
            reserved_output_tokens=self.cfg.compact_reserved_output_tokens,
        )
        self.total_usage = accumulate_usage(self.total_usage, result.usage)
        transcript = str(self.session_path) if self.session_path is not None else None
        summary_message = Message.user_text(
            build_compact_user_message(result.summary_text, transcript)
        )
        self.messages = [summary_message]
        self.last_call_usage = Usage()
        self.last_call_message_index = 0
        if self.session_path is not None:
            append_compact_boundary(self.session_path, trigger, pre_tokens)
            append_message(self.session_path, summary_message)

    def _maybe_autocompact(self) -> None:
        """若当前窗口占用超过 auto 阈值，尝试摘要重建。

        非法配置 fail-closed：本轮跳过。摘要失败不阻塞本轮，连续失败达上限后熔断。
        """
        if not self.cfg.enable_autocompact:
            return
        if self._autocompact_consecutive_failures >= MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES:
            return

        try:
            threshold = get_autocompact_threshold(
                self.provider.model,
                self.cfg.compact_reserved_output_tokens,
                self.cfg.autocompact_buffer_tokens,
                override=self.cfg.context_window_override,
            )
        except ValueError as e:
            self.console.print(f"[dim]autocompact: 配置非法（{e}），本轮跳过[/dim]")
            return

        current_tokens = estimate_context_tokens(
            self.messages, self.last_call_usage, self.last_call_message_index
        )
        if not should_autocompact(current_tokens, threshold):
            return

        try:
            self._apply_full_compact("auto")
            self._autocompact_consecutive_failures = 0
            self.console.print(
                f"[dim]auto compact: 已摘要重建"
                f"（占用≈{current_tokens} / 阈值 {threshold}）[/dim]"
            )
        except CompactError as e:
            self._autocompact_consecutive_failures += 1
            self.console.print(
                f"[dim]auto compact 失败（{e}），本轮继续携带原上下文[/dim]"
            )

    def _maybe_microcompact(self) -> None:
        """若当前窗口占用超过阈值，清理旧 compactable tool_result。

        非法配置 fail-closed：本轮跳过，不清理。一轮最多执行一次。
        只改内存中的 self.messages，不回写已落盘 JSONL。
        """
        if not self.cfg.enable_microcompact:
            return
        if self.cfg.microcompact_keep_recent < 1:
            self.console.print(
                "[dim]microcompact: keep_recent < 1，本轮跳过[/dim]"
            )
            return

        try:
            effective = get_effective_context_window(
                self.provider.model,
                self.cfg.max_tokens,
                override=self.cfg.context_window_override,
            )
            threshold = get_microcompact_threshold(
                effective, self.cfg.microcompact_buffer_tokens
            )
        except ValueError as e:
            self.console.print(f"[dim]microcompact: 配置非法（{e}），本轮跳过[/dim]")
            return

        current_tokens = estimate_context_tokens(
            self.messages, self.last_call_usage, self.last_call_message_index
        )
        if not is_above_threshold(current_tokens, threshold):
            return

        result = microcompact_messages(
            self.messages, self.cfg.microcompact_keep_recent
        )
        if result.cleared_count == 0:
            return

        self.messages = result.messages
        self.console.print(
            f"[dim]microcompact: 清理 {result.cleared_count} 条旧 tool_result，"
            f"约省 {result.tokens_saved} tokens "
            f"（占用≈{current_tokens} / 阈值 {threshold}）[/dim]"
        )

    # 薄包装：as_type="generation" 显式声明为模型调用，补充 model / usage / output
    @obs.observe(
        as_type="generation", name="call_model", capture_input=False, capture_output=False
    )
    def _traced_call_model(self, tools: list) -> LLMResponse:
        response = self._call_model(tools)
        obs.update_generation(
            model=self.provider.model,
            usage_details={
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            },
            output=obs.maybe_text(response.text()),
        )
        return response

    # 薄包装：as_type="span" 显式声明为普通子操作；span 名改为真实工具名
    @obs.observe(as_type="span", capture_input=False, capture_output=False)
    def _traced_execute_tool(self, name: str, tool_input: dict) -> tuple[str, bool]:
        obs.update_span(name=name, input=obs.maybe_args(name, tool_input))
        result_text, is_error = self._execute_tool(name, tool_input)
        obs.update_span(
            output=obs.maybe_text(result_text),
            level="ERROR" if is_error else "DEFAULT",
        )
        return result_text, is_error

    def _call_model(self, tools: list) -> LLMResponse:
        if not self.cfg.enable_streaming:
            response = self.provider.create_message(
                messages=self.messages,
                system=self.system_prompt,
                tools=tools,
                max_tokens=self.cfg.max_tokens,
                temperature=self.cfg.temperature,
            )
            return response

        accumulated = ""
        live: Live | None = None
        response: LLMResponse | None = None

        try:
            for event in self.provider.stream_message(
                messages=self.messages,
                system=self.system_prompt,
                tools=tools,
                max_tokens=self.cfg.max_tokens,
                temperature=self.cfg.temperature,
            ):
                if isinstance(event, TextDelta):
                    accumulated += event.text
                    if live is None:
                        live = Live(
                            Panel(
                                Markdown(accumulated),
                                title="assistant",
                                border_style="green",
                            ),
                            console=self.console,
                            refresh_per_second=12,
                        )
                        live.start()
                    else:
                        live.update(
                            Panel(
                                Markdown(accumulated),
                                title="assistant",
                                border_style="green",
                            )
                        )
                elif isinstance(event, StreamDone):
                    response = event.response
        finally:
            if live is not None:
                live.stop()

        if response is None:
            raise RuntimeError("模型流式响应未返回 StreamDone")
        return response

    # 最外层调用：自动成为一次 Trace 的根（没有 as_type="trace" 选项）；
    # observe_turn 内部同时把会话 id 记为 session_id
    @obs.observe_turn
    def run_turn(self, user_input: str) -> str:
        self._record_message(Message.user_text(user_input))
        tools = self.registry.schemas() if self.cfg.enable_tools else []

        for _turn in range(self.cfg.max_turns):
            self._maybe_microcompact()
            self._maybe_autocompact()
            response = self._traced_call_model(tools)
            self._print_usage(response)

            # stop_reason=tool_use 并不可靠；以 content 是否含 tool_use 为准
            tool_uses = response.tool_uses()
            content = list(response.content)
            if tool_uses and not self.cfg.enable_tools:
                content = [b for b in content if not isinstance(b, ToolUseBlock)]
                if not content:
                    content = [
                        TextBlock(text="（模型尝试调用工具，但当前未启用工具）")
                    ]
                tool_uses = []

            self._record_message(Message.assistant(content))
            # usage 覆盖到本条助手消息为止；之后的消息计入增量估算
            self.last_call_usage = response.usage
            self.last_call_message_index = len(self.messages)
            self._persist_usage_snapshot()

            if not tool_uses:
                text = response.text() or "（模型未返回文本）"
                # 非流式：Agent 负责最终 Panel；流式：Live 已渲染
                if not self.cfg.enable_streaming:
                    self.console.print(
                        Panel(Markdown(text), title="assistant", border_style="green")
                    )
                return text

            # 中间轮（还有 tool_use）：非流式补打文本说明
            if response.text() and not self.cfg.enable_streaming:
                self.console.print(response.text())

            tool_results = []
            try:
                for tool_use in tool_uses:
                    result_text, is_error = self._traced_execute_tool(
                        tool_use.name, tool_use.input
                    )
                    tool_results.append(
                        ToolResultBlock(
                            tool_use_id=tool_use.id,
                            content=result_text,
                            is_error=is_error,
                        )
                    )
            except BaseException:
                # 中断/未捕获异常时仍补齐配对，避免下次请求 400
                done_ids = {r.tool_use_id for r in tool_results}
                for tool_use in tool_uses:
                    if tool_use.id not in done_ids:
                        tool_results.append(
                            ToolResultBlock(
                                tool_use_id=tool_use.id,
                                content="[Tool result missing due to internal error]",
                                is_error=True,
                            )
                        )
                if tool_results:
                    self._record_message(Message.tool_results(tool_results))
                raise

            self._record_message(Message.tool_results(tool_results))

        return "⚠ 已达到单次任务最大轮数限制，任务可能未完全完成。"

    def _execute_tool(self, name: str, tool_input: dict) -> tuple[str, bool]:
        self.console.print(f"[dim]→ 调用工具 {name}({tool_input})[/dim]")
        try:
            result = self.registry.execute(name, tool_input, self.permission_manager)
            return result, False
        except PermissionDenied as e:
            return str(e), True
        except ToolError as e:
            return f"工具执行出错: {e}", True
        except Exception as e:
            return f"工具执行发生未预期异常: {type(e).__name__}: {e}", True
