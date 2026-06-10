---
name: ai-kefu-log-observability
description: Use this skill in the ai_kefu project when the user asks where logs are, how to inspect logs, how to trace a request with X-Request-ID/request_id, why a request did not enter LangGraph/Text2Cypher/Neo4j, how to enable debug trace, how to validate traceback logs, or how to explain the project's logging/observability design.
---

# ai_kefu Log Observability Runbook

Use this skill for `ai_kefu` logging, request tracing, LangGraph route diagnosis, Text2Cypher/Neo4j observability, and debug trace validation.

## Core Principles

- Answer in Chinese unless the user explicitly asks otherwise.
- Start from real request evidence: endpoint, status code, `X-Request-ID`, and log lines.
- Prefer file logs over console output. The project is designed to keep console low-noise.
- Do not assume `/api/chat` enters LangGraph. `/api/chat` is the normal SSE chat path; `/api/langgraph/query` is the LangGraph/Text2Cypher/Neo4j entry.
- Use `request_id` to connect `access`, `app`, `error`, and `trace` logs.
- Do not claim the Neo4j/Text2Cypher chain succeeded unless logs show events such as `route_type=graphrag-query`, `event=neo4j_query_started`, `event=cypher_generated`, or `tool=multi_tool_workflow`.
- Do not expose full prompt/history/model response in answers unless the user explicitly asks and it is safe. Prefer counts and lengths: `message_count`, `query_len`, `content_len`, `result_count`.

## Important Files

Logging implementation:

```text
deepseek_agent/llm_backend/app/core/logger.py
deepseek_agent/llm_backend/app/core/middleware.py
deepseek_agent/llm_backend/main.py
deepseek_agent/llm_backend/app/lg_agent/lg_builder.py
deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/cypher_tools/node.py
```

Daily log files are written under the project root by default:

```text
logs/access_YYYY-MM-DD.log
logs/app_YYYY-MM-DD.log
logs/error_YYYY-MM-DD.log
logs/trace_YYYY-MM-DD.log
```

Default retention:

```text
access/app: 14 days
error: 30 days
trace: 7 days
```

## Environment Variables

Set these before starting the backend process. Running services do not pick up new environment variables until restarted.

```powershell
$env:AI_KEFU_DEBUG_TRACE_CONSOLE="1"
$env:AI_KEFU_CONSOLE_LOG="1"
$env:AI_KEFU_LOG_LEVEL="INFO"
$env:AI_KEFU_TRACE_LOG="1"
$env:AI_KEFU_DEBUG_TRACE="1"
$env:AI_KEFU_LOG_DIR="logs"
```

Meaning:

- `AI_KEFU_CONSOLE_LOG`: current code reads this. `1` enables minimal console logs; `0` disables normal console output. Access logs still go to files.
- `AI_KEFU_LOG_LEVEL`: current code reads this. Controls app file log level, for example `INFO`, `DEBUG`, `WARNING`, or `ERROR`.
- `AI_KEFU_TRACE_LOG`: current code reads this. `1` enables `trace_YYYY-MM-DD.log` with full traceback for exception logs; `0` disables traceback file output.
- `AI_KEFU_DEBUG_TRACE`: current code reads this. `1` allows `/api/langgraph/query` and `/api/langgraph/resume` to return structured debug trace in SSE when the request also asks for it; `0` disables response trace even if the request sends `debug_trace=1`.
- `AI_KEFU_LOG_DIR`: current code reads this. Overrides log directory. Relative paths are resolved under the project root.
- `AI_KEFU_DEBUG_TRACE_CONSOLE`: intended switch for printing debug trace summaries to the backend terminal. As of the current code, this variable is not wired yet. Do not rely on it until the logger/main implementation is updated to read it.

Example: low-noise file-first mode with response trace disabled:

```powershell
$env:AI_KEFU_DEBUG_TRACE_CONSOLE="1"
$env:AI_KEFU_LOG_LEVEL="INFO"
$env:AI_KEFU_CONSOLE_LOG="1"
$env:AI_KEFU_TRACE_LOG="0"
$env:AI_KEFU_DEBUG_TRACE="0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1
```

Interpretation:

- Console remains enabled, but only minimal console-eligible logs are shown.
- App file logs are written at `INFO+`.
- Full traceback file logging is disabled because `AI_KEFU_TRACE_LOG=0`.
- `/api/langgraph/query?debug_trace=1` will not return `event: trace` because `AI_KEFU_DEBUG_TRACE=0`.
- `AI_KEFU_DEBUG_TRACE_CONSOLE=1` currently has no effect unless code support is added.

Example: debug mode for Postman trace validation:

```powershell
$env:AI_KEFU_LOG_LEVEL="INFO"
$env:AI_KEFU_CONSOLE_LOG="1"
$env:AI_KEFU_TRACE_LOG="1"
$env:AI_KEFU_DEBUG_TRACE="1"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1
```

In this mode, send `?debug_trace=1`, `X-Debug-Trace: 1`, or `"debug_trace": true` to receive structured SSE trace.

## Request ID Flow

`LoggingMiddleware` reads or generates `X-Request-ID`.

Expected behavior:

- If the client sends `X-Request-ID`, the backend reuses it.
- If the client does not send it, the backend generates a UUID.
- The backend writes it to `request.state.request_id`.
- The backend returns it in response header `X-Request-ID`.
- Logs include `request_id=...`.

Use a stable request id when testing:

```text
X-Request-ID: postman-trace-test-1
```

## Common Grep Commands

PowerShell:

```powershell
$today = Get-Date -Format 'yyyy-MM-dd'
$requestId = "postman-trace-test-1"

Select-String ".\logs\access_$today.log" -Pattern $requestId
Select-String ".\logs\app_$today.log" -Pattern $requestId
Select-String ".\logs\error_$today.log" -Pattern $requestId
Select-String ".\logs\trace_$today.log" -Pattern $requestId
```

Check LangGraph route decisions:

```powershell
Select-String ".\logs\app_$today.log" -Pattern "event=node_finished.*node=analyze_and_route_query"
```

Check whether GraphRAG/Text2Cypher/Neo4j was triggered:

```powershell
Select-String ".\logs\app_$today.log" -Pattern "route_type=graphrag-query|event=neo4j_query_started|event=cypher_generated|tool=multi_tool_workflow"
```

Check errors:

```powershell
Select-String ".\logs\error_$today.log" -Pattern "level=ERROR"
```

Check traceback logs:

```powershell
Select-String ".\logs\trace_$today.log" -Pattern "Traceback|request_id="
```

## Postman Debug Trace

Backend must be started with:

```powershell
$env:AI_KEFU_DEBUG_TRACE="1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1
```

Postman request:

```text
POST http://127.0.0.1:8000/api/langgraph/query?debug_trace=1
```

Headers:

```text
Content-Type: application/json
X-Debug-Trace: 1
X-Request-ID: postman-trace-test-1
```

Body:

```json
{
  "query": "请查询智能灯泡的库存和价格",
  "user_id": 1,
  "conversation_id": "postman-trace-thread-1",
  "debug_trace": true
}
```

Expected response is SSE, not plain JSON:

```text
data: "..."

event: trace
data: {"request_id":"postman-trace-test-1","conversation_id":"postman-trace-thread-1","thread_id":"postman-trace-thread-1","events":[...]}
```

Important: if the response does not include `event: trace`, check that:

- The backend was restarted after setting `AI_KEFU_DEBUG_TRACE=1`.
- The URL includes `?debug_trace=1`, or the header includes `X-Debug-Trace: 1`, or the JSON body includes `"debug_trace": true`.
- The request is going to `/api/langgraph/query`, not `/api/chat`.

## How Debug Trace Works

The implementation uses two switches:

- Global switch: `AI_KEFU_DEBUG_TRACE=1`
- Per-request switch: `debug_trace=1`, `X-Debug-Trace: 1`, or `"debug_trace": true`

Only when both are true does the backend call `start_trace()`.

`log_event()` remains the single event source. Each event still writes file logs, and when trace context is active, the same event is appended to the per-request trace list. At the end of the SSE stream, `main.py` emits:

```text
event: trace
data: {...}
```

This means file logs and response trace are derived from the same structured event stream.

## Traceback Logs

To enable full traceback file logs:

```powershell
$env:AI_KEFU_TRACE_LOG="1"
```

Then restart the backend. On exception, expected behavior:

- `error_YYYY-MM-DD.log`: single-line error summary.
- `trace_YYYY-MM-DD.log`: full traceback.
- Both should include the same `request_id`.

Do not expect normal successful requests to create `trace_YYYY-MM-DD.log`. Traceback file logs are for exception paths.

## Interpreting LangGraph Logs

Minimum signs that a request entered LangGraph:

```text
event=langgraph_started
event=stream_started
event=node_started node=analyze_and_route_query
event=node_finished node=analyze_and_route_query route_type=...
event=stream_finished
```

If `route_type=general-query`, the request did not enter GraphRAG/Text2Cypher/Neo4j. This is a router decision, not necessarily a logging failure.

Signs that the GraphRAG/Neo4j chain was triggered:

```text
route_type=graphrag-query
node=create_research_plan
event=tool_called tool=multi_tool_workflow
event=neo4j_query_started
event=cypher_generated
event=neo4j_query_finished
```

If the user asks "why did it not query the database?", first verify:

1. Did the request hit `/api/langgraph/query`?
2. Does the same `request_id` appear in `access` and `app` logs?
3. What is `route_type` for `node=analyze_and_route_query`?
4. Are there any `neo4j_query_*` or `cypher_generated` events?

## Validation Commands

Static validation:

```powershell
.\deepseek_agent\.venv\python.exe -m py_compile .\deepseek_agent\llm_backend\app\core\logger.py
.\deepseek_agent\.venv\python.exe -m py_compile .\deepseek_agent\llm_backend\app\core\middleware.py
.\deepseek_agent\.venv\python.exe -m py_compile .\deepseek_agent\llm_backend\main.py
.\deepseek_agent\.venv\python.exe -m py_compile .\deepseek_agent\llm_backend\app\lg_agent\lg_builder.py
```

Send a request with Python when PowerShell JSON quoting is unreliable:

```powershell
$env:PYTHONPATH='E:\workspacce\AI\ai_kefu\deepseek_agent\llm_backend'
@'
import httpx

request_id = "codex-log-smoke-1"
payload = {
    "query": "日志验证：请简短回答",
    "user_id": 1,
    "conversation_id": "codex-log-smoke-thread",
    "debug_trace": True,
}

with httpx.Client(timeout=90.0) as client:
    response = client.post(
        "http://127.0.0.1:8000/api/langgraph/query?debug_trace=1",
        headers={"X-Request-ID": request_id, "X-Debug-Trace": "1"},
        json=payload,
    )
    print(response.status_code)
    print(response.headers.get("x-request-id"))
    print(response.text[:1200])
'@ | .\deepseek_agent\.venv\python.exe -
```

## Interview Explanation Template

If the user asks for an interview-style explanation, emphasize this:

> The logging system is designed for Agent observability, not just text output. FastAPI middleware creates or propagates `X-Request-ID`; loguru is configured with separate file sinks for access, app, error, and trace logs; business code emits stable structured events through `log_event()`; LangGraph nodes log route, node, model, tool, and Neo4j events; and debug mode can return the same per-request event stream as structured SSE trace. This makes it possible to prove whether a request actually entered LangGraph, which route was selected, which tool was called, and where an error happened.

Explain why:

- File-first logs reduce console noise.
- Single-line logfmt makes grep and script parsing reliable.
- `request_id` enables request-level correlation.
- Error summary and full traceback are separated because they serve different debugging needs.
- Debug trace is behind both environment and request-level switches to avoid leaking internal implementation details by default.

## Common Failure Patterns

- No `event: trace` in Postman: backend was not restarted with `AI_KEFU_DEBUG_TRACE=1`, or request did not include `debug_trace=1` / `X-Debug-Trace: 1` / `"debug_trace": true`.
- `debug_trace=1` still returns no trace: check whether startup used `AI_KEFU_DEBUG_TRACE=0`. This global switch overrides the per-request debug flag.
- `AI_KEFU_DEBUG_TRACE_CONSOLE=1` does not print trace in the backend terminal: current code does not read this variable yet. It must be implemented before it can work.
- No Neo4j logs: route probably stayed `general-query`. Check `node=analyze_and_route_query route_type=...`.
- 422 before app logs: request failed FastAPI validation before business logic. Check endpoint signature and body content type.
- `/api/chat` logs exist but no LangGraph logs: this is expected; `/api/chat` is the normal chat path.
- `trace_YYYY-MM-DD.log` missing: `AI_KEFU_TRACE_LOG` was not enabled before backend start, or no exception path was triggered.

## Limitations

- This is file-based observability, not distributed tracing.
- The trace contains only events that code emits through `log_event()`.
- SSE debug trace is readable in Postman, but automated evaluation must parse SSE.
- If future architecture adds background workers or multiple services, move toward explicit trace propagation or OpenTelemetry.
