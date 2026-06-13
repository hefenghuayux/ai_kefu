# AI Kefu Smoke Benchmark

这个目录提供轻量评测闭环，用来检查 LangGraph 入口、路由、工具选择、安全拒答和多轮上下文是否出现明显回归。

当前版本暂不自动判断 answer 准确性。模型回答会写入人工复核文件，标准答案或人工判定要点会写入单独文件。

## 运行前提

先启动后端服务，默认地址为：

```powershell
http://127.0.0.1:8000
```

评测会调用 `/api/langgraph/query`，请求体会自动带上 `debug_trace: true`，并从 SSE 里的 `event: trace` 解析结构化日志事件。

当前 trace 仍然只使用 `trace_events`，不新增 `trace_timeline`。后端会在关键事件中补充 `phase`、`status`、`elapsed_ms`、`input_query_len`、`selected_tool`、`result_count`、`rows`、`llm_output_len`、`llm_output_preview`、`cypher_preview`、`error_type` 和 `reason` 等字段。`llm_output_preview` 只作为人工排查摘要，不参与危险 Cypher 判定。

## 运行

默认运行测试版 10 条 case，用来快速确认评测链路、trace 解析、oracle 查询和报告输出是否跑通：

```powershell
python evals/run_eval.py --base-url http://127.0.0.1:8000
```

测试版 case 文件：

```text
evals/cases/smoke_test.jsonl
```

完整回归版 case 文件仍然保留为：

```text
evals/cases/smoke.jsonl
```

需要跑完整版时显式指定：

```powershell
python evals/run_eval.py --cases evals/cases/smoke.jsonl --base-url http://127.0.0.1:8000
```

如果需要覆盖 Neo4j 连接配置，可以使用：

```powershell
python evals/run_eval.py --neo4j-url bolt://localhost:7687 --neo4j-username neo4j --neo4j-password password --neo4j-database neo4j
```

`run_eval.py` 会优先读取命令行参数，其次读取环境变量和 `deepseek_agent/llm_backend/.env`。配置了 `oracle_cypher` 的数据库类 case 会在评测时执行只读查询，并把结果写入 `standard_answers.md`。如果只想生成问题和模型回答、不执行 oracle 查询，可以加：

```powershell
python evals/run_eval.py --skip-oracle
```

输出文件：

- `evals/reports/results.jsonl`：每条 case 的完整结构化结果
- `evals/reports/latest_summary.md`：本次汇总报告
- `evals/reports/manual_answers.md`：模型回答人工复核文件
- `evals/reports/standard_answers.md`：每条 case 的标准答案或人工判定要点

`latest_summary.md` 会额外统计 trace 覆盖情况、缺失 trace 的 case、包含 failed trace event 的 case，以及全局最慢 trace event。`manual_answers.md` 会在每条 case 下展示 route、selected tool、最大结果数量、最慢事件和失败原因，方便人工复核模型答案时同时查看执行证据。

## 本地单元测试

```powershell
python -m unittest evals.test_verify
```

## 结果口径

第一版保留轻量自动指标：

- `pass_rate`
- `route_ok`
- `tool_ok`
- `latency_ms`
- `failure_category`
- `trace_present`
- `failed_trace_event`
- `slowest_trace_event`

answer 准确性暂时不进入自动失败分类，由人工查看 `manual_answers.md` 后判断。

`route_ok` 和 `tool_ok` 默认是诊断指标，不再自动决定 `passed=false`。这样可以避免“模型换了等价工具但查出了正确答案”时被误判为失败。只有当 case 显式声明严格检查时，路由或工具不匹配才会进入失败分类：

```json
{"route_check": "required"}
{"tool_check": "required"}
```

也可以使用 `"strict"` 作为 `"required"` 的别名。建议只在验证固定编排、固定工具策略或回归某个已知路由 bug 时开启严格检查。默认情况下，`passed=true` 表示请求没有超时、运行时错误或安全违规，且答案准确性等待人工复核；`route_ok/tool_ok` 仍然保留在结果中，用于分析路径漂移和工具选择变化。

固定失败分类：

- `route_error`
- `tool_selection_error`
- `unsafe_allowed`
- `timeout`
- `runtime_error`
