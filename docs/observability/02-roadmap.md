# 02 评测路线

按"先人工、后自动;先小集、后批量"推进。每阶段有明确完成标准,做完勾选。

## 前置:Trace 验收

- [x] [01-setup.md](01-setup.md) 清单全部通过(2026-10-25,见 [runs/2026-10-25-trace-check.md](runs/2026-10-25-trace-check.md))

## 阶段 A:手动打分(半天)

目标:理解 Scores 的数据模型。

- [x] 创建 3 个 Score Config(见 [03](03-scoring-and-annotation.md))
- [x] 在 Traces 里手动给 `agent_turn` 打分(实际 6 条,含失败样本)
- [x] 能用 Score 过滤出"失败的 trace",并说出共同原因(见 [runs/2026-10-25-stage-a-manual-scoring.md](runs/2026-10-25-stage-a-manual-scoring.md))

## 阶段 B:人工标注队列(半天)

目标:产出可信的人类基准。

- [ ] 创建 Annotation Queue `icecode-review`,绑定上述 Score Config
- [ ] 从 Traces 表勾选 trace,点 **Add to Annotation Queue**
- [ ] 标注 20 条(含成功、失败、边界各类),按 [03](03-scoring-and-annotation.md) 的规范

## 阶段 C:数据集(1 天)

目标:固定一批可重复跑的输入。

- [x] 导入种子集 [`datasets/icecode-smoke-v1.csv`](datasets/icecode-smoke-v1.csv)
- [x] 挑选高价值 trace,通过 **Add to Dataset** 补入(失败用例优先):补入阶段 A 的 bash 读取 `.env` 用例,升为 [v2](datasets/icecode-smoke-v2.csv)(2026-10-31,见 [runs/2026-10-31-stage-c-dataset.md](runs/2026-10-31-stage-c-dataset.md))
- [ ] 数据集达到 30 条,覆盖 [04](04-datasets.md) 里的各类别(当前以学会用法为主,暂不追求)

## 阶段 D:自动评审 Evaluator(1 天)

目标:用 LLM 复刻人工评分,省人力。

- [x] 配置 LLM Connection(评审模型 `deepseek-flash`)
- [x] 创建 `judge_task_success`(`agent_turn`)和 `judge_bash_safety`(`bash`),不挂实时规则
- [x] 与阶段 A 人工分对比:已配对取值一致;读取 `.env` 的命令被 `judge_bash_safety` 判为 false(2026-10-31,见 [runs/2026-10-31-stage-d-llm-judge.md](runs/2026-10-31-stage-d-llm-judge.md))

## 阶段 E:实验回归(1–2 天,需少量代码)

目标:改 prompt/模型/工具后,一键验证是否变差。

- [x] 写一个非交互入口:输入一条 prompt → 返回最终回答(`icecode -p`,权限自动拒绝)
- [x] 用 Langfuse SDK 的 Dataset experiment 把数据集逐条跑一遍,run 名带日期(`python -m icecode.experiment`,baseline 13 条)
- [x] 在 Experiments 页对比两个 run 的分数、成本、延迟(baseline 对 smoke-check;同配置重跑见 [runs/2026-11-01-baseline-v3-rerun.md](runs/2026-11-01-baseline-v3-rerun.md))
- [x] 在 `runs/` 记录结论(见 [runs/2026-10-31-stage-e-experiment.md](runs/2026-10-31-stage-e-experiment.md))

## 阶段 F(可选):告警与看板

- [ ] Dashboard:按天的 task_success 均值、平均成本、P95 延迟
- [ ] 阈值告警(自建 Langfuse 视版本支持情况)

## 剩余学习目标(2026-11-01 起暂停推进)

评测主链路(打分、数据集、评审、回归、噪声)已走通,可观测方向暂不继续。以下目标记录在案,需要时再选。

| 目标 | 学到什么 | 成本 / 工作量 | 状态 |
|------|----------|---------------|------|
| B 人工标注队列 | 建队列、批量送 trace、逐条标注,产出人工基准,之后能算评审器与人的一致率 | 纯 UI,不花钱;只学用法不追求数量 | 暂缓 |
| F1 Dashboard | 按天的任务成功率、平均成本、P95 延迟 | 纯 UI,不花钱,日常观测价值最直接 | 暂缓 |
| F2 阈值告警 | 成本或失败率越界时通知 | 取决于自建 Langfuse 版本是否支持 | 暂缓 |
| C 数据集扩到 30 条 | 补齐各类别,`safety` 类现在只剩 2 条 | 路线图已注明暂不追求 | 暂缓 |
| 实时评审规则 | 评审规则从 Skip 改为 Execute,新 trace 自动评审 | 配置简单,每条新 trace 有评审成本 | 暂缓 |
| 改 Agent 后做回归对比 | 用已知噪声范围,改一处后看对比结果 | 需改代码,属于功能开发 | 暂缓 |
| 实验接入 CI | 每次提交自动跑数据集并与 baseline 比 | 每次约 $0.2 ~ $0.35,需先定通过策略 | 暂缓 |
| Prompt 管理 | 提示词放进 Langfuse 做版本化,实验按版本对比 | 需改代码接入,范围较大 | 暂缓 |
| 评审器负样本验证 | 造已知有问题的回答,看评审器能否判 false | 已取消 | 取消 |
| 过程级评测(工具与调用次数) | 评审整个 `agent_turn` 的过程,见 [05](05-evaluators-and-experiments.md)「过程级评测」 | 需要少量代码 | 仅有设计,未实现 |

## 推进原则

1. 没有人工基准前,不信任自动评审。
2. 数据集改动升版本号;实验必须记录数据集版本。
3. 每个阶段结束写一份 `runs/` 记录,沉淀 SOP 的修订意见。
