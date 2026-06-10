# AI Kefu Eval Preflight

- backend_health: PASS (required)
  - url: http://127.0.0.1:8000/health
  - status_code: 200
  - latency_ms: 19
- neo4j_oracle: PASS (required)
  - url: bolt://127.0.0.1:7687
  - database: neo4j
  - latency_ms: 3414
- debug_trace_env: PASS (optional)
  - reason: local eval process has AI_KEFU_DEBUG_TRACE enabled; backend must also be started with it
