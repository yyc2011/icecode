# 2026-10-25 Trace 验收

## 目的

评测开始前确认埋点完整,trace 内容可用于标注与评审。

## 配置

- 环境:dev
- `ICECODE_LANGFUSE_RECORD_IO=true`
- Langfuse:本地自建

## 步骤

按 [01-setup.md](../01-setup.md) 的 Trace 验收清单,跑纯问答、读文件+搜索、派生子 Agent 三类任务,并在页面上核对。

## 结果

清单全部通过:trace 名与根节点、generation/工具 span、session 归组、子 Agent metadata、正文上报、usage/TTFT、Tool Calls 列。

## 结论与后续

可以进入阶段 A:创建 Score Config,手动给 10 条 `agent_turn` 打分。
