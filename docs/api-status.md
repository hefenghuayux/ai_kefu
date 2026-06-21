# API Status

本文档记录当前 `ai_kefu` 后端接口的整理状态，避免后续继续在旧链路上扩展功能。

## Active

| 接口 | 状态 | 说明 |
| --- | --- | --- |
| `GET /health` | active | 健康检查。 |
| `POST /api/langgraph/query` | active | 主聊天入口，负责 LangGraph / Text2Cypher / GraphRAG / 实时业务工具链路。 |
| `POST /api/langgraph/resume` | active | LangGraph interrupt 恢复入口。 |
| `/api/conversations*` | active | MySQL 会话与消息管理接口。 |
| `/api/auth*` | active | 由 `app.api` 挂载的认证相关接口。 |

## Compatibility

| 接口 | 状态 | 说明 |
| --- | --- | --- |
| `POST /api/chat` | deprecated-compatible | 普通 SSE LLM 对话路径，代码已标记 `deprecated=True`；保留用于旧前端或旧调用方兼容，不作为主业务入口。 |
| `POST /api/reason` | legacy-compatible | 旧推理接口，仍通过 `LLMFactory` 调用 DeepSeek/Ollama 服务。 |
| `POST /api/search` | legacy-compatible | 旧 SerpAPI 搜索接口，独立于当前 LangGraph 工具体系。 |
| `POST /api/upload/image` | compatibility | 独立图片上传接口；主入口 `/api/langgraph/query` 已支持 multipart 图片上传。 |

## Candidate Remove

| 接口/模块 | 状态 | 处理建议 |
| --- | --- | --- |
| `POST /chat-rag` | candidate-remove | 旧文档问答入口，依赖 `RAGChatService`；删除前需要确认是否仍有前端或脚本调用。 |
| `app/lg_agent/kg_sub_graph/multi_tools.py` | removed | 早期单文件版 multi-tool workflow；当前主链路使用 `agentic_rag_agents/workflows/multi_agent/multi_tool.py`。 |
| `app/lg_agent/kg_sub_graph/kg_builder.py` | removed | 空文件，没有业务实现。 |
| `app/models/chat.py` | removed | 仅定义未使用的 `ChatRequest`；`main.py` 内已有 `ChatMessage`。 |
| `app/services/embedding_service.py` | legacy-review | FAISS/PDF 旧向量索引服务，当前 `/api/upload` 使用的是 `IndexingService`；删除前确认是否有离线脚本依赖。 |
| `app/services/search_service.py`、`app/tools/search.py`、`app/tools/definitions.py`、`app/services/function_tools.py` | legacy-review | 旧 `/api/search` 工具体系；若保留 `/api/search`，这些文件也需保留。 |

## Cleanup Rules

1. 主业务默认只扩展 `/api/langgraph/query`。
2. compatibility 接口只做兼容和必要 bugfix，不新增复杂能力。
3. candidate-remove 文件删除前必须通过静态导入检查和 smoke eval。
4. 运行产物、数据库文件、日志、报告和 `node_modules` 不应进入 Git 跟踪。
