# AI Kefu Smoke Benchmark

这个目录提供轻量评测闭环，用来检查 LangGraph 入口、路由、工具选择、安全拒答和多轮上下文是否出现明显回归。

当前版本暂不自动判断 answer 准确性。模型回答会写入人工复核文件，标准答案或人工判定要点会写入单独文件。

## 运行前提

先启动后端服务，默认地址为：

```powershell
http://127.0.0.1:8000
```

评测会调用 `/api/langgraph/query`，请求体会自动带上 `debug_trace: true`，并从 SSE 里的 `event: trace` 解析结构化日志事件。

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

answer 准确性暂时不进入自动失败分类，由人工查看 `manual_answers.md` 后判断。

固定失败分类：

- `route_error`
- `tool_selection_error`
- `unsafe_allowed`
- `timeout`
- `runtime_error`
