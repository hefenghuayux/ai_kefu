# AI Kefu Eval Preflight

- backend_health: FAIL (required)
  - url: http://127.0.0.1:8000/health
  - latency_ms: 10038
  - reason: ReadTimeout
- neo4j_oracle: FAIL (required)
  - url: bolt://127.0.0.1:7687
  - database: neo4j
  - latency_ms: 6741
  - reason: Couldn't connect to 127.0.0.1:7687 (resolved to ('127.0.0.1:7687',)):
Failed to establish connection to ResolvedIPv4Address(('127.0.0.1', 7687)) (reason [WinError 10061] 由于目标计算机积极拒绝，无法连接。)
