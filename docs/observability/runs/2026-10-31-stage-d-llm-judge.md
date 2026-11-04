# 2026-10-31 阶段 D:LLM-as-judge

## 目的

学会在 Langfuse 里配置评审模型、建立 observation 级评审器，并对历史 trace 批量打分。当前目标是学会用法，不据此改 Agent。

## 配置

- 环境:本地自建 Langfuse。批量评审失败时为 v4.59；web 与 worker 更新到同一版本后为 v4.72。
- LLM Connection:适配器 OpenAI，连接名 `deepseek`，Base URL `https://api.deepseek.com`，自定义模型 `deepseek-flash`。关闭 Enable default models，否则连通性测试会用 `gpt-4.1`。
- `judge_task_success`:Boolean，变量 `input` / `output` 映射 observation 的 Input / Output。只对已人工打分的 `agent_turn` 批量评审。保存后 Skip execution，不挂实时规则。
- `judge_bash_safety`:Boolean，只映射 `input`(即命令)。试跑筛选 Name = `bash`。保存后 Skip execution。

## 步骤

1. 配好 LLM Connection，新建 `judge_task_success`，在页面上试跑一条 `agent_turn`。
2. Tracing 勾选已有人工 `task_success` 的 `agent_turn`，点 Evaluate。第一次 worker 报错，分数没写上；web / worker 镜像更新到同一版本后重跑成功。
3. 在 Scores 里按同一条 trace 对照人工分(ANNOTATION)与 `judge_task_success`(EVAL)。完整理由要点进 trace，表格里的 Comment 会被截断。
4. 新建 `judge_bash_safety`，对读取 `.env` 的 `bash` span 试跑并批量评审。

## 结果

| 评审器 | 目标 | 结果 |
|--------|------|------|
| `judge_task_success` | 已打人工分的 `agent_turn` | 已配对的取值都是 True，与人工 `task_success` 一致。当时列表里人工分 10 条、LLM 分 9 条，有一条没有 LLM 分 |
| `judge_bash_safety` | Name = `bash` | 读取 `.env` 的命令判为 false，符合预期 |

取值不一致项:没有。已看到的配对都是人工 True、LLM True。理由措辞不同，结论相同。例如「把那个 bug 修一下」:人工注明先排查、列出候选、请求澄清；LLM 注明请求缺少具体指向、助手做了检查。两边都判 true。

`judge_task_success` 看不到子节点里的工具调用，因此抓不到 bash 读取 `.env`。该问题由 `judge_bash_safety` 判 false。这是评审挂在哪个节点上的差别，不是 prompt 校准问题。

## 结论与后续

- 两个评审器的用法已走通，暂不改评审 prompt。
- 不挂实时规则；需要对历史数据打分时，在 Tracing 勾选对应节点再 Evaluate。`judge_bash_safety` 必须勾选 `bash` span，勾 `agent_turn` 时输入是用户请求，看不到命令。
- 下一步是阶段 C:导入种子数据集，学会 Dataset 的用法。

## SOP 修订意见

- DeepSeek 一类兼容接口要关闭默认模型，并填写服务商真实的模型名。
- `langfuse` 与 `langfuse-worker` 镜像要同一次拉取。版本不一致时，worker 查 LLM 连接会因缺少 `llm_api_keys.organization_id` 失败；Batch Actions 仍显示 Completed，但不会产生评审 trace 和分数。页面上的单条试跑走 web，所以仍能成功。
- 保存评审器后的规则弹窗:学习阶段点 Skip execution。Execute 会让以后新来的匹配节点自动评审。
- Scores 表一行一个分数，同一条 trace 只能上下看。左右并排用 Tracing 的分数列；完整 Comment 要点进 trace。
