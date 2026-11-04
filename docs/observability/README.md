# IceCode 可观测与评测

本目录记录 IceCode 的可观测(Trace)与评测(Evaluation)落地过程:**步骤、数据集、SOP、运行记录**。
评测主要在 Langfuse 页面上配置,代码改动很少,因此以文档沉淀为主。

## 当前进度与下一步(新窗口先看这里)

| 状态 | 阶段 | 说明 |
|------|------|------|
| 已完成 | Trace 验收 | [runs/2026-10-25-trace-check.md](runs/2026-10-25-trace-check.md) |
| 已完成 | A 人工打分 | 6 条含失败样本,发现 4 项问题:[runs/2026-10-25-stage-a-manual-scoring.md](runs/2026-10-25-stage-a-manual-scoring.md) |
| 可选 | B 标注队列 | 只需学会用法,不追求数量 |
| 已完成 | D LLM-as-judge 评审器 | 两个评审器已跑通,读 `.env` 判为 false:[runs/2026-10-31-stage-d-llm-judge.md](runs/2026-10-31-stage-d-llm-judge.md) |
| 已完成 | C 数据集 | `icecode-smoke` 当前 v3,12 条(v2 补入 1 条 trace 失败用例;v3 去掉会伤宿主机的 `rm -rf /` 用例):[runs/2026-10-31-stage-c-dataset.md](runs/2026-10-31-stage-c-dataset.md) |
| 已完成 | E 实验回归 | baseline 13 条跑通并评审,Experiments 页对比走通:[runs/2026-10-31-stage-e-experiment.md](runs/2026-10-31-stage-e-experiment.md) |
| 已完成 | 评审校准 | 新建 `judge_task_success_v2` 修正误判;发现评审分数有抖动:[runs/2026-11-01-judge-calibration.md](runs/2026-11-01-judge-calibration.md) |
| 已完成 | v3 baseline 与同配置重跑 | 质量分数一致,成本 +68%、延迟 +22%,量出 Agent 抖动范围:[runs/2026-11-01-baseline-v3-rerun.md](runs/2026-11-01-baseline-v3-rerun.md) |
| 暂停 | 可观测方向 | 主链路已走通,不再继续推进。剩余学习目标与过程级评测设计见 [02-roadmap.md](02-roadmap.md)、[05](05-evaluators-and-experiments.md) |

当前目标是**学会各功能的用法**,不是优化 Agent;发现的问题先登记,不立即修。

## 完整链路

```
Agent 运行 ──埋点──▶ Trace ──筛选/抽样──▶ 人工标注 ──▶ Dataset(测试集)
                        │                                   │
                        └─▶ 在线 LLM-as-judge 打分           └─▶ Experiment(批量回归 + 对比)
```

| 环节 | Langfuse 功能 | 解决的问题 |
|------|---------------|------------|
| 观测 | Traces / Sessions | 一次任务里模型调了什么、工具用了什么、慢在哪、贵在哪 |
| 打分 | Scores + Score Configs | 把"好/坏"变成可统计的字段 |
| 人工评审 | Annotation Queue | 建立可信的"人类基准",也是造数据集的入口 |
| 测试集 | Datasets | 固定一批输入 + 期望,改动后可重复验证 |
| 自动评审 | Evaluators(LLM-as-judge) | 按规则对线上/实验 trace 自动打分 |
| 回归对比 | Experiments(同一数据集的多次 run) | 改了 prompt/模型/工具后,同一数据集分数是否变差 |

## 文档索引

| 文档 | 内容 |
|------|------|
| [01-setup.md](01-setup.md) | 前置配置与 Trace 验收(先做) |
| [02-roadmap.md](02-roadmap.md) | 分阶段路线与每阶段的完成标准 |
| [03-scoring-and-annotation.md](03-scoring-and-annotation.md) | Score Configs 定义、标注规范、标注队列 SOP |
| [04-datasets.md](04-datasets.md) | 数据集设计、字段约定、导入与维护 SOP |
| [05-evaluators-and-experiments.md](05-evaluators-and-experiments.md) | LLM-as-judge 配置与实验回归 SOP |
| [datasets/icecode-smoke-v1.csv](datasets/icecode-smoke-v1.csv) | 首批种子测试集(可直接导入 Langfuse) |
| [datasets/icecode-smoke-v2.csv](datasets/icecode-smoke-v2.csv) | v1 + 1 条 trace 来源的失败用例(bash 读取 `.env`) |
| [datasets/icecode-smoke-v3.csv](datasets/icecode-smoke-v3.csv) | v2 去掉 `rm -rf /` 用例,12 条,当前线上版本 |
| [runs/](runs/) | 每次评测/实验的运行记录(按 `runs/_TEMPLATE.md` 填写) |

## 约定

- 数据集文件放 `datasets/`,文件名 `<名称>-v<版本>.csv`,改动即升版本,不原地覆盖。
- 每次评测或实验在 `runs/` 新增一份记录,写清:改了什么、数据集版本、分数结果、结论。
- 数据集内**不得**包含密钥、个人信息、私有代码片段。
