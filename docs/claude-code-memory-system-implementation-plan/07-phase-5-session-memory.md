# 7. Phase 5: SessionMemory 会话记忆

本文是实施计划第 7 个文件，对应 Phase 5。目标是实现文件型 SessionMemory，用 `summary.md` 保留当前会话的工作状态、工具证据、失败路径和下一步动作。

## 7.1 阶段目标

Phase 5 要完成：

```text
1. 新增 session_memory.py
2. 新增 prompts/session_memory.md
3. 读取 sessions/{conversation_id}/summary.md
4. 判断是否需要更新 session memory
5. 生成或更新 summary.md
6. 与现有 DB 型 session_note 并行
7. debug trace 可观察更新状态
8. 编写单元测试
```

本阶段可以先不使用完整 ForkedAgent。MVP 可先由服务端调用 LLM 生成结构化 Markdown，但必须保留后续替换为 `run_forked_agent()` 的接口。

## 7.2 为什么先做

SessionMemory 只影响当前 conversation，风险低于长期 memory 抽取。它可以先与现有 `conversation_context_items.session_note` 并行，不破坏旧逻辑。

先做它的价值：

```text
验证 summary.md 文件读写
验证后台任务不污染主 transcript
验证 debug trace 观测链路
为 ExtractMemories 提供更稳定的会话摘要
```

## 7.3 文件变更

新增：

```text
deepseek_agent/llm_backend/app/memory_system/session_memory.py
deepseek_agent/llm_backend/app/memory_system/prompts/session_memory.md
deepseek_agent/llm_backend/app/test/test_session_memory.py
```

可能修改：

```text
memory_system/schemas.py
memory_system/config.py
```

Phase 9 再修改：

```text
main.py
context_manager.py
```

## 7.4 核心数据结构

### SessionMemoryConfig

```python
@dataclass(frozen=True)
class SessionMemoryConfig:
    minimum_message_tokens_to_init: int = 10000
    minimum_tokens_between_update: int = 5000
    tool_calls_between_updates: int = 3
```

如果 `ai_kefu` 会话普遍短，可以通过环境变量调小：

```text
AI_KEFU_SESSION_MEMORY_MIN_INIT_TOKENS
AI_KEFU_SESSION_MEMORY_MIN_UPDATE_TOKENS
AI_KEFU_SESSION_MEMORY_TOOL_CALLS
```

### SessionMemoryState

```python
@dataclass(frozen=True)
class SessionMemoryState:
    summary_path: Path
    exists: bool
    content: str | None
    last_updated_at: str | None
```

### SessionMemoryUpdateDecision

```python
@dataclass(frozen=True)
class SessionMemoryUpdateDecision:
    should_update: bool
    reason: str
    token_estimate: int
    tool_call_count: int
```

### SessionMemoryUpdateResult

```python
@dataclass(frozen=True)
class SessionMemoryUpdateResult:
    status: str
    reason: str | None
    summary_path: str | None
    updated: bool
    error_type: str | None = None
```

## 7.5 summary.md 模板

文件：

```text
prompts/session_memory.md
```

模板 section 必须固定：

```md
# Session Title
_A short and distinctive title for the session._

# Current State
_What is actively being worked on right now? Pending tasks and immediate next steps._

# Customer Need
_The user's current business need, constraints, and unresolved questions._

# Confirmed Facts
_Facts explicitly confirmed by user or tools. Include source when useful._

# Tool Evidence
_Important tool calls and results. Preserve request_id or raw reference._

# Failed Paths
_Failed queries, wrong assumptions, or approaches that should not be repeated._

# User Preferences
_Preferences expressed in this session. Only promote to long-term memory when durable._

# Next Action
_The most useful next move if the conversation continues._

# Worklog
_Terse step-by-step record of what has been attempted or completed._
```

Prompt 约束：

```text
保留所有 header
保留 italic 说明
只编辑说明下面的正文
不要新增 section
不要写“我正在更新记忆”
不要把实时订单/库存/价格写成长期事实
```

## 7.6 关键函数设计

### load_session_memory()

```python
async def load_session_memory(summary_path: Path) -> SessionMemoryState:
    """读取当前 conversation 的 summary.md。不存在则返回 exists=False。"""
```

### should_update_session_memory()

```python
def should_update_session_memory(
    *,
    current_summary: str | None,
    recent_messages: list[dict[str, Any]],
    tool_evidence: list[dict[str, Any]],
    token_estimate: int,
    config: SessionMemoryConfig,
) -> SessionMemoryUpdateDecision:
    ...
```

MVP 判断：

```text
summary 不存在且 token_estimate >= minimum_message_tokens_to_init -> init
summary 存在且 token 增量 >= minimum_tokens_between_update -> update
tool_evidence 数量 >= tool_calls_between_updates -> update
否则 skipped
```

### build_session_memory_prompt()

```python
def build_session_memory_prompt(
    *,
    current_summary: str | None,
    recent_messages: list[dict[str, Any]],
    user_query: str,
    final_answer: str,
    tool_evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    ...
```

### update_session_memory()

```python
async def update_session_memory(
    *,
    summary_path: Path,
    context_bundle: dict[str, Any],
    user_query: str,
    final_answer: str,
    tool_evidence: list[dict[str, Any]],
    config: MemorySystemConfig,
) -> SessionMemoryUpdateResult:
    ...
```

MVP 可直接调用现有 LLM 客户端。Phase 7 替换为：

```python
await run_forked_agent(..., query_source="session_memory", skip_transcript=True)
```

### validate_session_summary()

```python
def validate_session_summary(markdown: str) -> None:
    """校验所有固定 section 存在。缺失则抛 ValueError。"""
```

## 7.7 与现有 ai_kefu 接入点

Phase 9 中：

```text
context_manager.py:
  load_context_bundle() 读取 summary.md，把摘要加入 prompt_context。

main.py:
  final_answer 后调度 update_session_memory()。
```

与旧 session_note 并行：

```text
旧 session_note:
  继续由 context_manager.py 写入 conversation_context_items。

新 summary.md:
  文件型 session memory。
```

Prompt 优先级建议：

```text
当前用户 query
当前工具证据
文件型 session memory
旧 DB session_note
长期 selected memories
```

需要在 Phase 9 具体实现时再确认 prompt 顺序。

## 7.8 验证方式

单元测试：

```text
test_load_session_memory_missing
test_validate_session_summary_requires_all_sections
test_should_init_after_token_threshold
test_should_update_after_tool_threshold
test_should_skip_below_threshold
test_update_session_memory_writes_summary
test_update_session_memory_rejects_missing_sections
```

手动验证：

```text
构造 recent_messages 和 tool_evidence
调用 update_session_memory()
确认 sessions/{conversation_id}/summary.md 生成
确认包含 Current State、Tool Evidence、Next Action
确认 transcript JSONL 没有写入 session_memory prompt
```

完成标准：

```text
session_memory.py 存在
prompts/session_memory.md 存在
summary.md 可生成和更新
所有固定 section 存在
debug result 能返回 status/reason
后台过程不写主 transcript
单测通过
```

## 7.9 风险和暂缓项

风险：

```text
summary.md 可能把实时事实写得像长期事实。
阈值太高会导致不更新，太低会导致频繁写。
与旧 session_note 共存会导致 prompt 重复。
```

暂缓：

```text
完整 Claude-Code prompt cache
自动 compact 集成
session summary 版本历史
人工编辑冲突检测
```

