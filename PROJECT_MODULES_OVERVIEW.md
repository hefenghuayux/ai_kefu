# ai_kefu 项目模块说明与后续改进指引

本文档用于让人或 AI 快速了解 `ai_kefu` 项目已经实现了什么、各模块如何协作、核心代码在哪里，以及后续改动应该优先看哪些入口。

## 1. 项目定位

`ai_kefu` 是一个本地可运行、可联调、可观察、可评测的智能客服 Agent 系统。它不是单纯的 LLM 聊天接口，而是把客服问答拆成以下能力：

- 普通 LLM 对话。
- 基于 LangGraph 的 Agent 编排。
- Text2Cypher + Neo4j 的结构化图谱查询。
- GraphRAG 查询和本地知识检索。
- Redis 语义缓存。
- MySQL 会话、消息和上下文记忆持久化。
- SSE 流式返回。
- request_id / debug_trace / eval 的可观测与评测链路。

当前主聊天入口应优先理解为：

```text
POST /api/langgraph/query
```

`/api/chat` 仍存在，但更适合作为 deprecated compatibility path，不应再作为主链路理解项目。

## 2. 顶层目录

```text
.
├── start_project.ps1                  # 一键启动脚本
├── local_services/                    # 本地 MySQL / Redis / Neo4j 启停与检查脚本
├── deepseek_agent/                    # 后端主体工程
│   ├── README.md
│   └── llm_backend/
│       ├── run.py                     # 后端启动入口
│       ├── main.py                    # FastAPI 主入口和主要 API 路由
│       ├── scripts/                   # 初始化、上下文表创建、知识同步脚本
│       └── app/
│           ├── api/                   # 认证等 API router
│           ├── core/                  # 配置、数据库、日志、中间件、安全
│           ├── models/                # SQLAlchemy 数据模型
│           ├── services/              # LLM、缓存、会话、搜索、业务 API 客户端
│           ├── lg_agent/              # LangGraph Agent 主链路
│           ├── graphrag/              # GraphRAG 相关实现和 vendored 代码
│           ├── tools/                 # 工具定义
│           └── prompts/               # Prompt 模板
├── evals/                             # 轻量评测、smoke case、报告输出
├── skills/                            # Codex/Agent 使用的项目 runbook
├── logs/                              # 运行日志目录
├── outputs/                           # GraphRAG 或运行输出
├── uploads/                           # 上传文件
└── .data/                             # 本地服务数据目录
```

## 3. 请求主链路

### 3.1 主路径

用户问题进入系统后的主流程：

```text
前端/调用方
-> FastAPI /api/langgraph/query
-> 规范化 conversation_id / thread_id
-> 可选加载上下文记忆
-> LangGraph 主图
-> 路由到普通回答、图谱查询、GraphRAG、实时业务查询等路径
-> SSE 流式返回
-> 可选保存 MySQL 会话消息
-> 可选输出 debug_trace
```

核心代码：

```text
deepseek_agent/llm_backend/main.py
```

重点位置：

- `LangGraphRequest`：`/api/langgraph/query` 请求体模型。
- `_debug_trace_requested()`：判断是否开启 debug trace。
- `_debug_trace_sse()`：把 trace events 包装成 SSE `event: trace`。
- `_handle_session_note_update()`：debug trace 时同步更新 session note，便于评测和排查。
- `langgraph_query()`：主聊天入口。
- `langgraph_resume()`：LangGraph 中断恢复入口。
- `chat_endpoint()`：旧 `/api/chat` 兼容路径，已标记 deprecated。

### 3.2 为什么主入口迁到 `/api/langgraph/query`

`/api/chat` 更偏普通 LLM 对话，无法代表 LangGraph、Text2Cypher、Neo4j、GraphRAG 的真实链路。智能客服项目的核心价值在于可路由、可查工具、可观测，因此主入口迁移到 `/api/langgraph/query` 后，前端主聊天窗口、评测和本地验证都应围绕这个接口展开。

迁移时需要保留旧链路的关键语义：MySQL 会话持久化仍应在最终 assistant 输出后执行。需要注意：

- LangGraph runtime 使用的 `thread_id` 可以是字符串。
- MySQL 会话主键只适合数值型 `conversation_id`。
- 类似 `ecommerce_...` 的前端合成线程 id 不应直接写入 MySQL conversation 主键。

## 4. FastAPI 接口层

核心代码：

```text
deepseek_agent/llm_backend/main.py
deepseek_agent/llm_backend/app/api/auth.py
deepseek_agent/llm_backend/app/api/__init__.py
```

主要接口：

| 接口 | 状态 | 作用 |
| --- | --- | --- |
| `GET /health` | 活跃 | 健康检查 |
| `POST /api/langgraph/query` | 主入口 | LangGraph Agent 查询、SSE 返回、trace、会话保存 |
| `POST /api/langgraph/resume` | 活跃 | LangGraph interrupt/resume 恢复 |
| `POST /api/chat` | deprecated | 普通 LLM 对话兼容路径 |
| `POST /api/search` | 活跃 | 搜索服务接口 |
| `POST /api/upload` | 活跃 | 文件上传 |
| `POST /api/upload/image` | 活跃 | 图片上传 |
| `POST /chat-rag` | 旧/辅助 | RAG 聊天入口 |
| `/api/conversations/*` | 活跃 | 会话创建、查询、删除、改名 |

实现特点：

- 用 FastAPI 管理 HTTP API。
- 用 SSE 逐步返回模型响应和 trace。
- 兼容旧 `messages` 结构，降低前端迁移成本。
- 请求链路通过 `request_id` 和日志上下文串联。

后续改进：

- 明确标注旧接口的使用边界，逐步减少 `/api/chat` 的业务含义。
- 把 `/api/langgraph/query` 里较长的流式处理逻辑拆成服务层函数，但不要用无意义兜底封装掩盖错误。
- 给接口请求体和响应体补更完整的 schema 文档。

## 5. LangGraph Agent 主编排

核心代码：

```text
deepseek_agent/llm_backend/app/lg_agent/lg_builder.py
deepseek_agent/llm_backend/app/lg_agent/lg_states.py
deepseek_agent/llm_backend/app/lg_agent/main.py
```

主要职责：

- 定义 Agent 输入状态和运行状态。
- 根据用户问题进行意图分析和路由。
- 决定是否走普通回答、知识图谱、文件查询、图片查询等路径。
- 编译 LangGraph 主图。
- 使用 `MemorySaver` 支持 LangGraph checkpoint。

主图关键节点：

```text
START
-> analyze_and_route_query
-> route_query 决定后续节点
-> respond_to_general_query / get_additional_info / create_research_plan / create_image_query / create_file_query
```

关键函数：

- `analyze_and_route_query()`：分析用户问题，产出路由决策。
- `route_query()`：把分析结果映射到下一个 LangGraph 节点。
- `respond_to_general_query()`：普通 LLM 回答。
- `get_additional_info()`：补充信息路径。
- `create_research_plan()`：知识图谱或 GraphRAG 子图入口之一。
- `create_image_query()`：图片查询路径。
- `create_file_query()`：文件查询路径，目前更像预留或待完善路径。
- `check_hallucinations()`：回答检查逻辑。
- `builder = StateGraph(...)` / `graph = builder.compile(...)`：主图装配。

设计原因：

普通客服问答不是单次 `prompt -> LLM -> answer`。不同问题需要不同工具和不同上下文。LangGraph 把复杂链路拆成节点和边，使每一步可以单独观察、测试和替换。

后续改进：

- 明确 `route_query` 的路由类型枚举，减少字符串分支漂移。
- 给每个主节点增加统一 trace 字段，例如 `phase`、`route_type`、`status`、`elapsed_ms`。
- 将文件查询、图片查询等未完全接线的能力标记为 experimental，避免面试或文档中过度表述。

## 6. LangChain 与 LangGraph 的分工

项目中两者都用到了，但职责不同：

```text
LangChain：组件层
LangGraph：编排层
```

LangChain 主要用于：

- `ChatPromptTemplate`：Prompt 模板。
- `BaseChatModel`：统一模型接口。
- `ChatDeepSeek` / `ChatOllama`：模型封装。
- `StrOutputParser`：输出解析。
- `Runnable`：节点内部链式组合。
- `Neo4jGraph`：Neo4j 图数据库封装。
- `Document` / message 类型：统一数据结构。

LangGraph 主要用于：

- `StateGraph`：定义状态图。
- `START` / `END`：流程入口和结束。
- `add_node()` / `add_edge()` / `add_conditional_edges()`：节点和边。
- `Command` / `Send`：动态路由和 map-reduce 风格分发。
- `MemorySaver`：checkpoint。

准确表述：

```text
LangGraph 负责“下一步走哪里、状态如何流转”。
LangChain 负责“某个节点内部怎么调用模型、Prompt、Parser 或 Neo4j”。
```

## 7. GraphRAG、Neo4j、Text2Cypher 模块

### 7.1 概念边界

不要把 Neo4j、GraphRAG、Text2Cypher 混成同一个东西。

```text
Neo4j：图数据库，存节点、关系、属性。
Text2Cypher：把自然语言问题转换成 Cypher 查询。
GraphRAG：利用图结构、实体关系、社区/文本单元上下文或图查询结果增强 LLM 回答的流程。
```

在本项目中，更准确的说法是：

```text
图结构数据主要存储在 Neo4j。
GraphRAG 是围绕图结构和检索结果组织回答的流程。
Text2Cypher 是连接自然语言和 Neo4j 查询的关键能力。
```

### 7.2 Neo4j 连接与结构化查询

核心代码：

```text
deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/kg_neo4j_conn.py
deepseek_agent/llm_backend/app/core/config.py
deepseek_agent/llm_backend/scripts/sync_commerce_knowledge.py
```

关键点：

- `get_neo4j_graph()` 返回 `langchain_neo4j.Neo4jGraph`。
- Neo4j 配置在 `Settings` 中，包括 `NEO4J_URL`、`NEO4J_USERNAME`、`NEO4J_PASSWORD`、`NEO4J_DATABASE`。
- `sync_commerce_knowledge.py` 可把电商知识 JSON/Markdown 同步到 Neo4j 和文档目录。

适合 Neo4j 的问题：

- 实体关系查询。
- 多跳关系查询。
- 商品、类目、订单、用户、规则之间的结构化关系。
- 需要 Cypher 精确过滤、聚合或路径查询的问题。

不适合 Neo4j 的问题：

- 强实时订单状态。
- 实时库存。
- 秒杀资格。
- 支付状态和物流轨迹。

这些更适合走业务 API 或业务数据库。

### 7.3 活跃 GraphRAG 工作流

活跃工作流核心代码：

```text
deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/workflows/multi_agent/multi_tool.py
deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/workflows/multi_agent/edges.py
```

注意：`deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/multi_tools.py` 是旧版单文件 workflow，当前不应优先当作活跃主链路。

活跃子图结构：

```text
START
-> guardrails
-> planner
-> tool_selection
-> cypher_query / predefined_cypher / customer_tools
-> summarize
-> final_answer
-> END
```

核心节点：

- `guardrails`：判断问题是否在允许范围内。
- `planner`：把用户问题拆成任务。
- `tool_selection`：选择 Text2Cypher、预定义 Cypher、GraphRAG 或实时业务工具。
- `cypher_query`：执行 Text2Cypher 类图查询。
- `predefined_cypher`：执行预定义 Cypher 查询。
- `customer_tools`：GraphRAG 查询或 commerce live query。
- `summarize`：汇总工具结果。
- `final_answer`：生成最终回答。

这个工作流是受约束的 DAG，不应简单表述为经典 ReAct loop。它有 tool selection，但没有“工具结果回流到 tool selection 再多轮循环”的标准 ReAct 形态。

### 7.4 GraphRAG 和 customer_tools

核心代码：

```text
deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/customer_tools/node.py
deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/kg_tools_list.py
deepseek_agent/llm_backend/app/graphrag/
```

关键能力：

- `GraphRAGAPI` 封装 GraphRAG 查询。
- 支持 `local_search`、`global_search`、`drift_search`、`basic_search` 等查询方式。
- 默认更应理解为本地 GraphRAG 查询，而不是单纯向量 top-k。
- `commerce_live_query` 通过业务 HTTP API 查询实时电商状态。

工具定义：

```text
cypher_query
predefined_cypher
microsoft_graphrag_query
commerce_live_query
real_time_network_query
```

后续改进：

- 把 GraphRAG 查询类型和配置集中暴露到 `.env` 或统一 settings。
- 为 `customer_tools` 补更明确的 trace：query_type、tool_name、result_count、elapsed_ms、error_type。
- 明确区分 GraphRAG 文档检索、Neo4j 结构查询、commerce live query 三条链路。

## 8. 实时电商业务 API 集成

核心代码：

```text
deepseek_agent/llm_backend/app/services/commerce_client.py
deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/customer_tools/node.py
deepseek_agent/llm_backend/scripts/sync_commerce_knowledge.py
```

已有能力：

- `CommerceApiClient` 通过 HTTP 调用外部电商服务。
- 支持查询订单状态、用户订单、秒杀状态、购买资格等动作。
- 使用 `X-Internal-Token` 调用内部接口。
- `commerce_live_query` 作为工具接入 `customer_tools`。

支持动作：

```text
order_status
user_orders
seckill_status
purchase_eligibility
```

设计边界：

- 实时事实应由电商服务或业务数据库提供。
- Neo4j/GraphRAG 更适合半静态知识、关系解释、规则说明。
- 这类 service composition 比把所有业务数据复制进 `ai_kefu` 更清晰。

后续改进：

- 增加 commerce API 健康检查。
- 在 trace 中记录 action、参数完整性、HTTP status、耗时。
- 为实时工具补 eval case，验证它不会错误走 GraphRAG 或 Neo4j。

## 9. 会话、上下文记忆与 MySQL 持久化

### 9.1 数据模型

核心代码：

```text
deepseek_agent/llm_backend/app/models/user.py
deepseek_agent/llm_backend/app/models/conversation.py
deepseek_agent/llm_backend/app/models/message.py
deepseek_agent/llm_backend/app/models/conversation_context.py
deepseek_agent/llm_backend/app/models/user_memory.py
deepseek_agent/llm_backend/app/core/database.py
deepseek_agent/llm_backend/scripts/create_context_tables.py
```

主要表：

| 模型 | 表 | 作用 |
| --- | --- | --- |
| `User` | `users` | 用户 |
| `Conversation` | `conversations` | 会话 |
| `Message` | `messages` | 消息 |
| `ConversationContextItem` | `conversation_context_items` | 会话级上下文、session note、tool evidence |
| `UserMemoryItem` | `user_memory_items` | 用户级长期记忆 |

### 9.2 会话服务

核心代码：

```text
deepseek_agent/llm_backend/app/services/conversation_service.py
```

主要职责：

- 创建会话。
- 查询用户会话列表。
- 查询会话消息。
- 删除会话。
- 更新会话名。
- 保存用户消息和 assistant 回答。

### 9.3 上下文管理

核心代码：

```text
deepseek_agent/llm_backend/app/lg_agent/context_manager.py
```

核心概念：

- `recent_messages`：保留最近消息，保证连续对话。
- `session_note`：把长对话压缩成当前会话摘要。
- `tool_evidence`：保存工具调用证据，便于后续引用和排查。
- `user_memories`：跨会话用户偏好或长期信息。
- `memory_trace`：debug 路径可见的记忆更新过程。
- `session_note_json`：结构化 session note。

关键函数：

- `load_context_bundle()`：加载会话上下文。
- `format_context_bundle()`：格式化上下文给 Prompt 使用。
- `summarize_tool_evidence()`：从工具响应中提取证据摘要。
- `save_tool_evidence_items()`：保存工具证据。
- `should_update_session_note()`：判断是否应更新 session note。
- `build_session_note_prompt()`：构造 session note 生成 Prompt。
- `generate_session_note_with_llm()`：调用 LLM 生成 session note。
- `validate_session_note()`：校验结构化 note。
- `save_session_note()`：保存 session note、confirmed facts、failed paths、user preferences。
- `update_session_note_for_trace()`：debug trace 路径下同步更新 note。
- `maybe_schedule_session_note_update()`：生产路径后台更新 note。

设计原因：

长对话不能无限把所有历史消息塞进模型。MySQL 负责完整历史，context manager 负责控制推理输入，把近期消息、会话摘要、工具证据和用户偏好分层组织。

后续改进：

- 为 session note 更新策略补单元测试。
- 给 `should_update_session_note()` 的阈值配置化。
- 明确哪些记忆可过期、哪些应长期保存。
- 为 failed paths 增加“避免重复失败工具路径”的运行时使用逻辑。

## 10. LLM 服务、Embedding 与 Redis 语义缓存

### 10.1 LLM 服务

核心代码：

```text
deepseek_agent/llm_backend/app/services/llm_factory.py
deepseek_agent/llm_backend/app/services/deepseek_service.py
deepseek_agent/llm_backend/app/services/ollama_service.py
deepseek_agent/llm_backend/app/core/config.py
```

主要职责：

- 根据配置选择 DeepSeek 或 Ollama。
- 支持普通聊天模型、推理模型、Agent 模型。
- 通过统一 service 层隔离具体模型供应商。

配置项：

```text
DEEPSEEK_API_KEY
DEEPSEEK_BASE_URL
DEEPSEEK_MODEL
OLLAMA_BASE_URL
OLLAMA_CHAT_MODEL
OLLAMA_REASON_MODEL
OLLAMA_EMBEDDING_MODEL
OLLAMA_AGENT_MODEL
CHAT_SERVICE
REASON_SERVICE
AGENT_SERVICE
```

### 10.2 RedisSemanticCache

核心代码：

```text
deepseek_agent/llm_backend/app/services/redis_semantic_cache.py
deepseek_agent/llm_backend/app/services/deepseek_service.py
```

实现方式：

- 从用户消息中取最后一条 user content。
- 调用 Ollama `/api/embed` 生成 embedding。
- 在 Redis 中保存 query、embedding、response、metadata。
- lookup 时计算当前向量和历史缓存向量的 cosine similarity。
- 相似度超过阈值时复用缓存回答。
- 按 user_id 做缓存 key 隔离。
- 超过最大缓存数量时按 last_access 清理旧项。

关键函数：

- `_get_ollama_embedding()`：调用 Ollama embed API。
- `_get_embedding()`：获取文本向量。
- `lookup()`：相似问题查缓存。
- `update()`：写入缓存。
- `_remove_cache_item()`：删除缓存项。

设计边界：

- 语义缓存适合稳定、高频、相似问法的问题。
- 不适合实时订单状态、库存、物流等强时效问题。
- 缓存命中要注意业务规则变化后的过期问题。

后续改进：

- 给缓存命中写入 trace，区分 cache hit / miss。
- 增加按业务域或工具类型的缓存策略。
- 对实时工具结果默认禁用语义缓存。

## 11. 日志、trace 与可观测性

核心代码：

```text
deepseek_agent/llm_backend/app/core/logger.py
deepseek_agent/llm_backend/app/core/middleware.py
deepseek_agent/llm_backend/main.py
```

已有能力：

- 使用 loguru 输出结构化日志。
- 按文件分离 access、app、error、trace 日志。
- 支持 `request_id` / `X-Request-ID`。
- 支持 `AI_KEFU_DEBUG_TRACE`、`AI_KEFU_TRACE_LOG`、`AI_KEFU_CONSOLE_LOG`、`AI_KEFU_LOG_LEVEL`。
- `start_trace()` / `get_trace()` / `clear_trace()` 管理请求内 trace_events。
- `log_event()` 用统一字段记录关键事件。
- `/api/langgraph/query?debug_trace=1` 或请求体 `debug_trace: true` 可让 SSE 返回 `event: trace`。

日志文件：

```text
logs/access_YYYY-MM-DD.log
logs/app_YYYY-MM-DD.log
logs/error_YYYY-MM-DD.log
logs/trace_YYYY-MM-DD.log
```

trace 中应重点关注：

- route_type。
- selected_tool。
- cypher_preview。
- result_count / rows。
- elapsed_ms。
- status。
- error_type。
- reason。
- memory_trace。
- session_note_json。

后续改进：

- 给所有 LangGraph 节点统一埋点规范。
- 保持 evals 与 trace schema 同步。
- 增加慢事件分析和链路火焰图式摘要。

## 12. 评测与回归验证

核心代码：

```text
evals/run_eval.py
evals/verify.py
evals/test_verify.py
evals/README.md
evals/cases/smoke_test.jsonl
evals/cases/smoke.jsonl
```

设计目标：

- 用轻量 smoke case 验证主链路是否能跑通。
- 调用 `/api/langgraph/query`，默认带 `debug_trace: true`。
- 解析 SSE 中的 `event: trace`。
- 输出结构化结果和人工复核材料。

输出文件：

```text
evals/reports/results.jsonl
evals/reports/latest_summary.md
evals/reports/manual_answers.md
evals/reports/standard_answers.md
evals/reports/preflight.md
```

重要原则：

- `route_ok` 和 `tool_ok` 默认是诊断指标。
- 只有 case 显式设置 `required` 或 `strict` 时，路由/工具不匹配才作为硬失败。
- 如果工具不是预期但最终答案正确，默认不直接判失败。
- 自动评测主要检查运行时错误、超时、安全违规、严格路由/工具错误；答案准确性仍需要人工复核。

后续改进：

- 保持 quick smoke 集优先，避免评测体系过早复杂化。
- 为每条新增工具链路配最小 case。
- 每次 trace schema 改动时同步更新 `run_eval.py`、`verify.py`、`test_verify.py` 和 `evals/README.md`。

## 13. 本地启动与服务编排

核心代码：

```text
start_project.ps1
local_services/start_all_services.py
local_services/start_mysql.ps1
local_services/start_redis.ps1
local_services/start_neo4j.ps1
local_services/check_services.ps1
local_services/stop_mysql.ps1
local_services/stop_redis.ps1
local_services/stop_neo4j.ps1
deepseek_agent/llm_backend/run.py
```

启动目标：

- 启动 MySQL。
- 启动 Redis。
- 启动 Neo4j。
- 检查 Ollama。
- 启动 FastAPI 后端。
- 可选打开浏览器访问本地页面。

常用检查点：

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/health
http://127.0.0.1:8000/docs
```

本地服务数据：

```text
.data/mysql-win/
.data/redis/
.data/neo4j-win/
.data/logs/
.data/run/
```

注意：

- 不要默认执行 `deepseek_agent/llm_backend/scripts/init_db.py`，它可能重建或清空 MySQL 表。
- 优先使用项目虚拟环境 `deepseek_agent/.venv/python.exe`。
- 本地服务问题应先查端口、health、docs 和服务监听状态，不要直接怀疑 LangGraph。

## 14. 技能文档与项目 runbook

核心目录：

```text
skills/
```

现有 skill：

```text
skills/ai-kefu-local-runbook/SKILL.md
skills/ai-kefu-log-observability/SKILL.md
skills/ai-kefu-benchmark-eval/SKILL.md
skills/_guides/skill-creator/SKILL.md
```

使用边界：

- 本地启动、健康检查、接口验证：读 `ai-kefu-local-runbook`。
- 日志、trace、request_id、接口命中路径：读 `ai-kefu-log-observability`。
- benchmark、eval、case、pass rate：读 `ai-kefu-benchmark-eval`。
- 新建或修改 skill：读 `_guides/skill-creator`。

后续改进：

- 把本文件作为项目总览，skill 作为具体操作手册。
- 每当真实启动流程、trace schema、eval 入口变化时，同时更新相关 skill。

## 15. 前端与静态资源

当前 FastAPI 会挂载前端构建产物，路径在：

```text
deepseek_agent/llm_backend/static/dist
```

注意：

- 该目录可能被 ignore，不能只靠 `git status` 判断前端 bundle 是否变化。
- 如果修改前端请求入口，应直接搜索构建产物中是否仍有 `/api/chat` 或旧路径。

后续改进：

- 分离源码前端和构建产物说明。
- 明确前端主聊天窗口调用 `/api/langgraph/query`。
- 避免把 ignored bundle 改动误认为没有发生。

## 16. 已完成能力概览

| 能力 | 当前状态 | 主要代码 |
| --- | --- | --- |
| FastAPI 后端 | 已接线 | `main.py`, `run.py` |
| 主聊天入口迁移到 LangGraph | 已完成 | `main.py` |
| `/api/chat` 兼容路径 | 已保留，deprecated | `main.py` |
| SSE 流式返回 | 已接线 | `main.py` |
| LangGraph 主图 | 已接线 | `lg_builder.py`, `lg_states.py` |
| GraphRAG 多工具子图 | 已接线 | `multi_tool.py`, `edges.py` |
| Neo4j 连接 | 已接线 | `kg_neo4j_conn.py`, `config.py` |
| Text2Cypher | 已接线 | `agentic_rag_agents/components/text2cypher/` |
| GraphRAG customer tools | 已接线 | `customer_tools/node.py` |
| commerce live query | 已接线 | `commerce_client.py`, `customer_tools/node.py` |
| MySQL 会话持久化 | 已接线 | `conversation_service.py`, `models/` |
| session note / memory trace | 已接线 | `context_manager.py` |
| Redis 语义缓存 | 已接线 | `redis_semantic_cache.py`, `deepseek_service.py` |
| request_id 日志 | 已接线 | `middleware.py`, `logger.py` |
| debug_trace SSE | 已接线 | `main.py`, `logger.py` |
| 轻量 eval | 已接线 | `evals/run_eval.py`, `evals/verify.py` |
| 本地服务脚本 | 已接线 | `start_project.ps1`, `local_services/` |
| 项目 skills | 已接线 | `skills/` |

## 17. 后续改进优先级

### P0：保持主链路稳定

- 固定 `/api/langgraph/query` 为主入口。
- 所有验证、eval、文档默认围绕 `/api/langgraph/query`。
- 修改 trace schema 时同步更新 eval。
- 修改 LangGraph 节点时同步更新日志和文档。

### P1：提高可观测性

- 给主图和子图节点统一 trace 字段。
- 为 Redis cache hit/miss、GraphRAG query_type、commerce action 增加 trace。
- 在 `manual_answers.md` 中展示更清楚的工具链路证据。

### P1：整理工具和路由边界

- 明确普通问答、Neo4j、GraphRAG、commerce live query 的触发条件。
- 为 `route_query` 和 `tool_selection` 增加更稳定的枚举或 schema。
- 避免把 GraphRAG、Neo4j、Text2Cypher 混成同一层概念。

### P2：完善测试与 eval

- 保持 `smoke_test.jsonl` 轻量可跑。
- 为每个新增工具链路补最小 case。
- 对上下文记忆策略补单元测试。
- 对 dangerous Cypher、安全拒答、实时查询误路由补回归 case。

### P2：清理 legacy 与运行产物

- 谨慎处理旧 `kg_sub_graph/multi_tools.py`，不能只因为 AST 显示未引用就删除。
- 搜索时默认排除 `.data/`、`logs/`、`tmp/`、`outputs/`、`evals/reports/`、`.venv/`。
- 对 deprecated API 和 legacy workflow 做状态映射后再清理。

### P3：业务集成增强

- 将电商服务作为事实源，`ai_kefu` 作为 Agent runtime。
- 实时订单、库存、秒杀资格走 commerce API。
- 半静态知识、规则解释、关系查询走 Neo4j/GraphRAG。
- 为 commerce API 增加健康检查和失败降级说明。

## 18. 给后续 AI 接手的建议

如果要排查“为什么没有查数据库”：

1. 先确认请求是否命中 `/api/langgraph/query`，不是 `/api/chat`。
2. 开启 `debug_trace=1` 或请求体 `debug_trace: true`。
3. 用 `X-Request-ID` 串联 access/app/error/trace 日志。
4. 看 trace 中是否出现 route、tool_selection、selected_tool、cypher_preview、result_count。
5. 如果没有进入工具节点，先查 LangGraph 路由和 tool_selection，不要直接查 Neo4j。

如果要解释 GraphRAG：

1. 先区分 Neo4j、GraphRAG、Text2Cypher。
2. Neo4j 是存储和查询图结构数据。
3. Text2Cypher 是自然语言到 Cypher 的转换。
4. GraphRAG 是检索和回答生成流程，可以使用 Neo4j 查询结果和 GraphRAG local/global search 上下文。
5. 不要把当前工作流说成经典 ReAct loop。

如果要新增工具：

1. 先定义工具 schema。
2. 接入 `tool_selection`。
3. 实现工具节点。
4. 补 trace 事件。
5. 补最小 eval case。
6. 更新本文档和相关 skill。

如果要修改上下文记忆：

1. 先看 `context_manager.py`。
2. 区分 MySQL 完整消息历史和 session note 推理摘要。
3. debug 路径要能看到 `memory_trace`。
4. 不要让后台异步更新影响 trace 可验证性。

## 19. 设计合理性与不足

这个项目的合理性在于把智能客服拆成了可控的工程链路：接口层负责协议和流式返回，LangGraph 负责状态流转，LangChain 负责组件调用，Neo4j/GraphRAG 负责知识增强，MySQL 负责会话持久化，Redis 负责语义缓存，日志和 eval 负责验证。

不足也很明显：系统栈较厚，本地联调依赖 MySQL、Redis、Neo4j、Ollama、LLM API 等多个组件；LangGraph 节点、GraphRAG 查询、Text2Cypher、业务 API 之间的边界需要持续维护；如果 trace 和 eval 没有同步更新，后续很容易出现“功能看似可用但无法证明真实链路”的问题。

后续演进应优先保持主链路可验证，再逐步增强工具能力和业务覆盖范围。
