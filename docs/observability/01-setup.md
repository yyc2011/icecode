# 01 前置配置与 Trace 验收

评测建立在"trace 里有可判断的内容"之上。先把这一步做对,否则后面都是空转。

## 1. 开启正文上报(评测环境必需)

默认只上报字符数/参数名(脱敏),LLM 评审与"加入数据集"都拿不到真实内容。

`.env`(仅本地/评测环境,不要用于含敏感数据的场景):

```
LANGFUSE_PUBLIC_KEY=pk-...
LANGFUSE_SECRET_KEY=sk-...
LANGFUSE_HOST=http://localhost:3000     # 自建地址
ICECODE_LANGFUSE_RECORD_IO=true         # 评测期开启:上报 input/output 正文
LANGFUSE_TRACING_ENVIRONMENT=dev        # 区分环境,见下
```

建议用环境区分流量,评测/回归跑批时设为 `eval`,日常手玩为 `dev`,在页面 Environment 筛选器里隔离,避免污染统计。

## 2. Trace 验收清单

跑 3 种任务各一次(纯问答 / 读文件+搜索 / 派生子 Agent),在 Langfuse 里确认:

- [ ] Trace 名为 `agent-<时间戳>`,根节点 `agent_turn`(type=agent)
- [ ] 下挂 `call_model`(generation)与真实工具名的 span
- [ ] 同一次 REPL 会话的多个 turn 在 Sessions 里归为一个 session
- [ ] 子 Agent:`agent` 工具 span 下有 `subagent_call_model`,metadata 含 `subagent_type`
- [ ] `agent_turn` 的 Input/Output 是正文(而不是 `{"chars": N}`)
- [ ] generation 有 model、usage、TTFT(流式)
- [ ] Tool Calls 列非 0(模型发起过工具调用的 generation)

任何一项不通过,先修埋点,再进入评测。

## 3. 打分挂在哪一层

Langfuse 可以给 trace 或 observation 打分。本项目约定:

| 评测对象 | 挂载位置 | 过滤条件 |
|----------|----------|----------|
| 整个任务是否完成 | 根 observation `agent_turn` | Name = `agent_turn` |
| 单次模型调用质量 | `call_model` generation | Name = `call_model` |
| 子 Agent 结论质量 | `subagent_call_model` / `agent` span | Name = `agent` |

首批评测只做第一行:**一个任务一个分**。
