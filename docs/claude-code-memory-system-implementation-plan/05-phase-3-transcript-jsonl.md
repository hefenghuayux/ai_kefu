# 5. Phase 3: Transcript JSONL

本文是实施计划第 5 个文件，对应 Phase 3。目标是实现 Claude-Code 风格 transcript JSONL，作为 SessionMemory、ExtractMemories、AutoDream 的原始事实来源。

## 5.1 阶段目标

Phase 3 要完成：

```text
1. 新增 transcripts.py
2. 定义 transcript event 数据结构
3. 每轮主请求完成后可追加 user/assistant/tool evidence 事件
4. 支持按 cursor 增量读取 transcript
5. 支持 extract_cursor.json 读写
6. 明确后台 memory agent 不写主 transcript
7. 编写单元测试
```

本阶段可以先不接入 `/api/langgraph/query`，但函数签名必须为 Phase 9 接入准备好。

## 5.2 为什么先做

长期记忆抽取不能直接依赖 `main.py` 的临时变量。没有 transcript，会出现：

```text
ExtractMemories 无法增量处理
AutoDream 无法跨 session 回看
错误 memory 无法追溯原始请求
debug trace 只能看到结果，看不到原材料
```

`ai_kefu` 虽然已有 MySQL messages、LangGraph state 和日志，但它们不是 Claude-Code 风格 transcript：

```text
MySQL messages:
  保存对话历史，但不一定包含完整 tool evidence、request_id、memory trace 关联。

LangGraph state:
  服务当前线程恢复，不适合作为长期抽取 cursor。

日志:
  用于观测，不应作为业务数据源。
```

因此 Phase 3 单独实现 JSONL transcript。

## 5.3 文件变更

新增：

```text
deepseek_agent/llm_backend/app/memory_system/transcripts.py
deepseek_agent/llm_backend/app/test/test_memory_transcripts.py
```

依赖：

```text
memory_system/config.py
memory_system/paths.py
memory_system/schemas.py
```

本阶段不修改：

```text
deepseek_agent/llm_backend/main.py
deepseek_agent/llm_backend/app/lg_agent/context_manager.py
```

Phase 9 再接入主请求链路。

## 5.4 核心数据结构

### TranscriptRole

```python
class TranscriptRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"
```

`SYSTEM` 只用于显式记录主链路系统事件，不用于记录后台 memory agent prompt。

### TranscriptToolEvidence

```python
@dataclass(frozen=True)
class TranscriptToolEvidence:
    tool_name: str
    request_id: str
    raw_ref: str | None
    result_digest: str
    result_count: int | None = None
    elapsed_ms: int | None = None
```

要求：

```text
result_digest 是摘要，不保存大段原始工具输出。
raw_ref 可以保存 request_id、tool_call_id、业务系统查询 ID。
不要保存完整手机号、完整地址、支付信息。
```

### TranscriptEvent

```python
@dataclass(frozen=True)
class TranscriptEvent:
    event_id: str
    timestamp: str
    request_id: str
    conversation_id: str
    user_id: int
    tenant_id: str
    role: TranscriptRole
    content: str
    content_digest: str
    tool_calls: tuple[str, ...] = ()
    tool_evidence: tuple[TranscriptToolEvidence, ...] = ()
    source: str = "main_agent"
```

字段边界：

```text
source="main_agent":
  允许写入主 transcript。

source="session_memory" / "extract_memories" / "auto_dream":
  默认不允许写入主 transcript。
```

### ExtractCursor

```python
@dataclass(frozen=True)
class ExtractCursor:
    conversation_id: str
    last_event_id: str | None
    last_line_index: int
    updated_at: str
```

存储文件：

```text
deepseek_agent/runtime/memory/state/extract_cursor.json
```

推荐结构：

```json
{
  "conversations": {
    "123": {
      "last_event_id": "evt_...",
      "last_line_index": 8,
      "updated_at": "2026-06-21T10:00:00+08:00"
    }
  }
}
```

## 5.5 关键函数设计

### append_transcript_event()

```python
async def append_transcript_event(
    path: Path,
    event: TranscriptEvent,
    *,
    allow_background_source: bool = False,
) -> None:
    """向 conversation JSONL 追加单个事件。"""
```

规则：

```text
显式 UTF-8 写入
一行一个 JSON
ensure_ascii=False
写入前校验 source
source != main_agent 且 allow_background_source=False 时抛 ValueError
```

原因：

```text
后台记忆过程不能污染主对话 transcript。
```

### append_turn_transcript()

```python
async def append_turn_transcript(
    *,
    transcript_path: Path,
    request_id: str,
    conversation_id: str,
    user_id: int,
    tenant_id: str,
    user_query: str,
    final_answer: str,
    tool_evidence: list[dict[str, Any]],
) -> list[TranscriptEvent]:
    """一次主请求完成后，追加 user 和 assistant 事件。"""
```

输出：

```text
返回实际写入的 events，供 debug trace 使用。
```

事件顺序：

```text
user event
assistant event
```

工具证据放入 assistant event。

### read_transcript_events()

```python
async def read_transcript_events(
    path: Path,
    *,
    start_line: int = 0,
    max_events: int | None = None,
) -> list[TranscriptEvent]:
    """从 JSONL 读取事件。"""
```

规则：

```text
空文件返回 []
坏 JSON 行抛 TranscriptFormatError，不静默跳过
如果是测试需要容忍坏行，另写显式测试辅助，不放生产逻辑
```

### read_transcript_since_cursor()

```python
async def read_transcript_since_cursor(
    *,
    transcript_path: Path,
    cursor_path: Path,
    conversation_id: str,
    max_events: int,
) -> tuple[list[TranscriptEvent], ExtractCursor]:
    """读取 cursor 之后的新事件。"""
```

### update_extract_cursor()

```python
async def update_extract_cursor(
    *,
    cursor_path: Path,
    conversation_id: str,
    last_event: TranscriptEvent,
    last_line_index: int,
) -> None:
    """ExtractMemories 成功后推进 cursor。"""
```

只有 ExtractMemories 成功完成后才能推进 cursor。失败时不能推进，否则会漏抽记忆。

## 5.6 与现有 ai_kefu 的接入点

Phase 9 中在 `main.py` 请求完成后接入：

```python
events = await append_turn_transcript(
    transcript_path=paths.transcript_path,
    request_id=request_id,
    conversation_id=str(conversation_id or thread_id),
    user_id=user_id,
    tenant_id=identity.tenant_id,
    user_query=query,
    final_answer=final_message,
    tool_evidence=tool_evidence,
)
```

接入位置应在：

```text
final_answer 已生成
ConversationService.save_message 已完成或已明确跳过
save_tool_evidence_items 已完成或已明确跳过
_handle_session_note_update 之前或之后均可
```

推荐顺序：

```text
1. 保存 MySQL message
2. 保存 tool_evidence
3. append transcript
4. schedule session memory update
5. schedule extract memories
```

## 5.7 验证方式

单元测试：

```text
test_append_transcript_event_writes_one_json_line
test_append_turn_transcript_writes_user_then_assistant
test_append_rejects_background_source_by_default
test_read_transcript_events_reads_utf8_chinese
test_read_transcript_since_cursor_returns_only_new_events
test_update_extract_cursor_advances_after_success
test_bad_json_line_raises_format_error
```

手动验证：

```text
构造一个 tmp transcript_path
调用 append_turn_transcript()
确认 JSONL 有两行
每行 json.loads 成功
assistant 行包含 tool_evidence 摘要
```

完成标准：

```text
transcripts.py 存在
test_memory_transcripts.py 通过
JSONL 每行可独立解析
后台 source 默认不能写主 transcript
cursor 成功读写
所有读写显式 UTF-8
没有修改 main.py
```

## 5.8 风险和暂缓项

风险：

```text
JSONL 文件会增长，需要 AutoDream 或归档策略。
工具证据摘要过长会泄漏敏感信息或撑大磁盘。
cursor 推进时机错误会漏抽或重复抽。
```

暂缓：

```text
压缩旧 transcript
加密 transcript
按天分片
对象存储同步
transcript 管理 UI
```

