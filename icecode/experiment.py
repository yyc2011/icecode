"""数据集实验：把 Langfuse 数据集里的每条 Item 交给 Agent 跑一次，记为一次 run。

用法（需先安装 observability 依赖并配置 LANGFUSE_* 与模型 Key）：

    python -m icecode.experiment --run-name 2026-10-31-baseline
    python -m icecode.experiment --run-name smoke-check --limit 2

run 中每条 Item 对应一条 trace，可在 Datasets → <数据集> → Runs 里对比不同 run。
逐条运行使用非交互模式：需要确认的操作一律拒绝，不会改动工作目录。
数据集里的用例默认以本仓库为被测目录，请用 WORKDIR 指向一份干净的仓库副本。
实验 trace 的环境由 SDK 统一标为 sdk-experiment。
"""

from __future__ import annotations

import os

# 必须先于 icecode 其他模块导入：observability 在导入时读取该开关。
# 评审器需要看到输入输出正文，故实验默认记录。
os.environ.setdefault("ICECODE_LANGFUSE_RECORD_IO", "true")

import argparse  # noqa: E402
import sys  # noqa: E402
from typing import Any  # noqa: E402

from icecode import observability as obs  # noqa: E402
from icecode.headless import run_prompt  # noqa: E402

DEFAULT_DATASET = "icecode-smoke"


def item_prompt(item: Any) -> str:
    """取出 Item 的 input 作为 prompt；纯文本直接用，其他结构化输入取 input 字段或转成文本。"""
    raw = item.get("input") if isinstance(item, dict) else getattr(item, "input", None)
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("input"), str):
        return raw["input"]
    return str(raw)


def task(*, item: Any, **_kwargs: Any) -> str:
    """单条 Item 的执行体：失败时返回错误文本，不中断整个 run。"""
    try:
        return run_prompt(item_prompt(item))
    except Exception as e:  # noqa: BLE001
        return f"⚠ 运行失败: {type(e).__name__}: {e}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m icecode.experiment",
        description="用 Langfuse 数据集跑一次 Agent 实验",
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="数据集名称")
    parser.add_argument(
        "--run-name", required=True, help="本次 run 名，如 2026-10-31-baseline"
    )
    parser.add_argument("--description", default=None, help="run 说明（可选）")
    parser.add_argument(
        "--limit", type=int, default=None, help="只跑前 N 条，用于先验证流程"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if not obs.is_enabled():
        print(
            "Langfuse 未启用：请安装 langfuse 并配置 LANGFUSE_PUBLIC_KEY / "
            "LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL。",
            file=sys.stderr,
        )
        sys.exit(1)

    from langfuse import get_client

    client = get_client()
    dataset = client.get_dataset(args.dataset)
    if args.limit is not None:
        dataset.items = dataset.items[: args.limit]
    print(f"数据集 {args.dataset}：本次运行 {len(dataset.items)} 条，run 名 {args.run_name}")

    try:
        result = dataset.run_experiment(
            name=args.run_name,
            run_name=args.run_name,
            description=args.description,
            task=task,
            max_concurrency=1,  # 每条 Item 一个独立 Agent，逐条跑，避免并发混写
        )
        print(result.format())
    finally:
        obs.flush()


if __name__ == "__main__":
    main()
