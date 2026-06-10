# AGENTS.md

## 项目基本信息

这是 `ai_kefu` 项目，核心目标是做一个可本地运行、可联调、可观察、可评测的智能客服 Agent 系统。仓库里主要有：

- FastAPI 后端
- LangGraph / Text2Cypher / Neo4j 链路
- 普通 LLM 对话链路
- Redis 语义缓存
- MySQL 会话数据
- 本地启动脚本和服务脚本

常用工作目录：

```text
E:\workspacce\AI\ai_kefu
```

## 关键入口

- 一键启动：`start_project.ps1`
- 后端入口：`deepseek_agent\llm_backend\run.py`
- FastAPI 主入口：`deepseek_agent\llm_backend\main.py`
- 日志入口：`deepseek_agent\llm_backend\app\core\logger.py`
- 请求链路中间件：`deepseek_agent\llm_backend\app\core\middleware.py`
- 项目虚拟环境：`deepseek_agent\.venv\python.exe`

## 基本工作规则

1. 默认使用中文回复。
2. 先核对真实路径、真实入口、真实请求和真实日志，再下结论。
3. 不要轻易删除或改写已有功能；如果改动会影响现有设计，先说明风险。
4. 不要用兜底函数或冗余封装掩盖错误，保留清晰报错。
5. 本地验证优先使用 `deepseek_agent\.venv\python.exe`，不要默认用系统 Python。
6. 不要默认执行 `deepseek_agent\llm_backend\scripts\init_db.py`；它可能重建或清空 MySQL 表。
7. 用户说“解决这个问题”时，默认应尝试实际修复和验证，而不是只解释。
8. 如果问题反复没有解决，要质疑当前方向，并提出其他可能排查路径。

## 接口边界

必须先区分两个核心接口：

- `/api/chat`：普通 SSE LLM 对话路径，不会自动进入 LangGraph，也不会自动查 Neo4j。
- `/api/langgraph/query`：LangGraph/Text2Cypher/Neo4j 入口。用户期待“查数据库”“走知识图谱”“生成 Cypher”时，通常应检查这个接口。

遇到“为什么没有查数据库”“为什么没有走 LangGraph”时，先确认请求到底命中了哪个接口。

## 日志边界

当前日志改造以 file-first、单行、grep-friendly 为目标。排查时优先看文件，不要只依赖控制台输出。

优先查看：

```text
deepseek_agent\llm_backend\app\core\logger.py
deepseek_agent\llm_backend\app\core\middleware.py
```

请求链路排查时，优先用 `X-Request-ID` / `request_id` 串联 access、app、error、trace 日志。

## Skill 使用规则

项目内 skill 根目录：

```text
skills\
```

当任务命中以下场景时，先读对应 skill 的 `SKILL.md`，再执行任务。

### ai-kefu-local-runbook

路径：

```text
skills\ai-kefu-local-runbook\SKILL.md
```

使用场景：

- 用户问“怎么启动”“怎么跑起来”“本地联调”
- 用户问“接口怎么测”“健康检查怎么做”
- 用户要求检查服务是否启动
- 用户要求验证后端、API docs、`/health`、`/api/langgraph/query`
- 用户遇到本地服务启动失败、端口不通、依赖服务未启动等问题

### ai-kefu-log-observability

路径：

```text
skills\ai-kefu-log-observability\SKILL.md
```

使用场景：

- 用户贴日志并要求解释
- 用户问“怎么看 log”“日志在哪里”
- 用户问“为什么请求没进 LangGraph”“为什么没查数据库”
- 用户要求根据 `request_id` / `X-Request-ID` 追踪请求
- 用户要求分析 `/api/chat` 和 `/api/langgraph/query` 的真实命中路径

注意：这个 skill 目前只是占位草稿，不能当完整排查手册。

### ai-kefu-benchmark-eval

路径：

```text
skills\ai-kefu-benchmark-eval\SKILL.md
```

使用场景：

- 用户问“怎么 benchmark”“怎么评测 Agent 效果”
- 用户希望比较普通对话、LangGraph、Text2Cypher、GraphRAG、缓存链路
- 用户要求设计 eval case、指标、pass rate、latency、token usage
- 用户要求证明工具调用是否真的提升了最终答案

注意：这个 skill 目前只是占位草稿，不能当完整评测规范。

### skill-creator 指南

路径：

```text
skills\_guides\skill-creator\SKILL.md
```

使用场景：

- 用户要求创建新的 skill
- 用户要求修改、翻译、优化已有 skill
- 用户要求设计 skill 的触发描述、目录结构或 eval
