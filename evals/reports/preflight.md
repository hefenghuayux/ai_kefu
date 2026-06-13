# AI Kefu Eval Preflight

- backend_health: PASS (required)
  - url: http://127.0.0.1:8000/health
  - status_code: 200
  - latency_ms: 15
- neo4j_oracle: PASS (required)
  - url: bolt://127.0.0.1:7687
  - database: neo4j
  - latency_ms: 930
- debug_trace_env: FAIL (optional)
  - reason: local eval process does not set AI_KEFU_DEBUG_TRACE; start backend with AI_KEFU_DEBUG_TRACE=1 to receive trace events
