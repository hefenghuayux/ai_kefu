---
name: ai-kefu-local-runbook
description: 在 ai_kefu 项目中处理构建、启动、停止、本地运行、服务检查、接口 smoke test、本地联调和后端验证时使用。用户提到“怎么启动”“怎么跑起来”“本地联调”“接口怎么测”“health check”“服务没起来”“验证一下后端”时，应优先使用这个 skill。
---

# ai_kefu 本地运行手册

这个 skill 用于 `ai_kefu` 仓库的本地启动、联调和 smoke 验证。
执行前要先核对当前 checkout 的真实路径、入口脚本和日志位置，不要套用通用 FastAPI/Vue 项目的默认经验。

## 第一轮检查

1. 确认当前目录是仓库根目录：
   ```powershell
   Get-Location
   Test-Path .\start_project.ps1
   Test-Path .\deepseek_agent\.venv\python.exe
   ```
2. 优先使用项目虚拟环境：
   ```powershell
   .\deepseek_agent\.venv\python.exe --version
   ```
3. 不要默认执行数据库初始化。`deepseek_agent\llm_backend\scripts\init_db.py` 会重建 MySQL 表，只有用户明确要求时才运行。

## 启动项目

默认使用仓库根目录的一键启动脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1
```

常用变体：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1 -SkipOllama
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1 -SkipBrowser
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1 -SkipBackend
```

只有在明确提醒用户可能重置本地 MySQL 表之后，才使用 `-InitDb`：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start_project.ps1 -InitDb
```

启动脚本会检查或启动 MySQL、Redis、Neo4j、Ollama，然后从 `deepseek_agent\llm_backend\run.py` 启动 FastAPI 后端。

## 服务检查

在判断后端故障前，先使用已有服务检查脚本：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\local_services\check_services.ps1
```

预期本地服务：

- MySQL on `127.0.0.1:3306`
- Redis on `127.0.0.1:6379`
- Neo4j Bolt on `127.0.0.1:7687`
- Ollama on `127.0.0.1:11434` unless `-SkipOllama` is used
- FastAPI on `http://127.0.0.1:8000`

如果检查失败，要报告具体失败的服务和命令输出。不要写兜底 helper 把错误吞掉。

## API Smoke 测试

后端启动后，先检查：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/health
```

需要人工确认接口时打开：

```text
http://127.0.0.1:8000/docs
```

必须区分接口职责：

- `/api/chat` 是普通 SSE LLM 对话路径。
- `/api/langgraph/query` 是 LangGraph/Text2Cypher/Neo4j 路径。
- 如果用户期待“查数据库”，先确认请求实际命中了 `/api/langgraph/query`，而不是 `/api/chat`。

最小 LangGraph JSON smoke 请求形态：

```powershell
$body = @{
  query = "测试查询"
  user_id = 1
  conversation_id = 1
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/langgraph/query `
  -ContentType 'application/json' `
  -Body $body
```

如果返回 `422`，先检查 endpoint 签名和请求体 `content-type`，不要直接判断是 LangGraph 或 Neo4j 故障。

## 日志

优先查看文件日志，不要只看控制台输出。日志行为先看：

```text
deepseek_agent\llm_backend\app\core\logger.py
deepseek_agent\llm_backend\app\core\middleware.py
```

常见日志目录可能包括：

```text
logs\
.data\logs\
```

追踪请求时，用 `X-Request-ID` / `request_id` 串联 access、app、error、trace 日志。如果 trace 日志没有启用，检查当前代码是否需要 `AI_KEFU_TRACE_LOG` 或相关 logger 配置。

## 快速静态验证

修改后端文件后，可以先用 `py_compile` 做语法级验证：

```powershell
.\deepseek_agent\.venv\python.exe -m py_compile .\deepseek_agent\llm_backend\main.py
```

本地 smoke 测试优先使用项目已有测试工具或 FastAPI `TestClient` 片段，不要额外启动无关服务。如果 smoke 测试写入临时文件或日志，只清理本次测试创建的产物。

## 停止与清理

在运行 `start_project.ps1` 的终端中用 `Ctrl+C` 停止后端。

需要停止依赖服务时，先查看 `local_services\` 下已有脚本，不要重新发明停止逻辑：

```text
local_services\stop_mysql.ps1
local_services\stop_redis.ps1
local_services\stop_neo4j.ps1
```

不要删除 `.data`、`logs`、uploads、数据库文件或用户创建的本地文件，除非用户明确要求。

## 回复用户时说明

汇报本地运行结果时，至少说明：

- 执行了什么命令
- 检查了哪个服务或接口
- 状态码或精确错误是什么
- 相关日志文件路径
- 完成的是运行时验证，还是只完成了静态检查
