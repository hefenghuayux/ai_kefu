# 11. Phase 9: 接入 /api/langgraph/query 和 debug trace

本文是实施计划第 11 个文件，对应 Phase 9。目标是把前面模块接入 `ai_kefu` 当前主链路 `/api/langgraph/query`，并通过 `memory_trace` 观察完整行为。

## 11.1 阶段目标

Phase 9 要完成：

```text
1. 在 context_manager.py 接入 session memory 和 relevant memory recall
2. 在 main.py 请求完成后追加 transcript
3. 调度 session_memory/update、extract_memories、maybe_auto_dream
4. 扩展 memory_trace/debug_trace
5. feature flag 关闭时保持旧行为
6. 验证不会污染主 transcript 和主对话
```

## 11.2 为什么最后做

主接口接入风险最大。只有底层模块都可单测后，才能把它们串进 `/api/langgraph/query`。这样可以把问题定位到：

```text
scan/recall/transcript/session/extract/permission/auto_dream
```

而不是在主请求里混合排查。

## 11.3 需要修改的文件

```text
deepseek_agent/llm_backend/main.py
deepseek_agent/llm_backend/app/lg_agent/context_manager.py
```

尽量不改：

```text
deepseek_agent/llm_backend/app/lg_agent/lg_builder.py
```

原因：

```text
lg_builder.py 已经通过 _state_messages_with_context() 注入 context_bundle["prompt_context"]。
```

## 11.4 context_manager.py 接入设计

修改 `load_context_bundle()`：

```python
async def load_context_bundle(
    user_id: int,
    conversation_id: Optional[str | int],
    query: str,
) -> dict[str, Any]:
    ...
```

新增流程：

```text
1. 原有 DB 上下文加载保持不变
2. load_memory_config()
3. 如果 memory enabled:
   - build_memory_identity()
   - resolve_memory_paths()
   - load_session_memory()
   - find_relevant_memories()
   - render_memory_context()
4. 合并到 prompt_context
5. 填充 context["memory_trace"]
```

新增 context 字段：

```python
context["memory_identity"] = identity
context["memory_paths"] = paths
context["file_session_memory"] = session_state.content
context["selected_memories"] = recall_result.selected
context["memory_trace"] = {...}
```

注意：

```text
不要把 Path/dataclass 直接塞入 LangGraph state，除非确认可序列化。
如果 state 需要序列化，memory_paths 只放字符串。
```

## 11.5 prompt_context 合并规则

推荐顺序：

```text
CONTEXT_SYSTEM_PREFIX
文件型 SessionMemory
旧 DB session_note
最近对话摘录
工具证据摘要
失败路径
用户偏好
长期 Relevant Memories
实时事实警告
```

实时事实警告必须包含：

```text
订单、库存、价格、物流、售后进度必须以本轮工具查询为准；memory 不能替代实时业务系统。
```

## 11.6 main.py 请求后接入

接入位置：

```text
final_message 已生成
tool_evidence 已拿到
ConversationService.save_message 已执行或已跳过
save_tool_evidence_items 已执行
```

新增调用：

```python
await append_turn_transcript(...)

schedule_session_memory_update(...)
schedule_extract_memories(...)
schedule_maybe_auto_dream(...)
```

debug_trace=True：

```text
可以同步等待 session/extract 的轻量结果，用于 trace 验证。
AutoDream 仍建议只返回 skipped/scheduled。
```

debug_trace=False：

```text
使用 background_tasks 或 asyncio.create_task。
```

## 11.7 memory_trace 设计

返回结构：

```json
{
  "memory_trace": {
    "enabled": true,
    "source_of_truth": "markdown",
    "mysql_mode": "index_audit_compat",
    "session_memory_loaded": true,
    "selected_memory_count": 2,
    "selected_memory_paths": [
      "feedback/inventory_answer_style.md"
    ],
    "transcript_status": "appended",
    "session_update_status": "scheduled",
    "extract_status": "scheduled",
    "auto_dream_status": "skipped",
    "auto_dream_reason": "min_sessions_not_met"
  }
}
```

日志事件：

```text
memory_recall_started
memory_recall_finished
memory_context_rendered
memory_transcript_appended
session_memory_update_started
session_memory_update_finished
extract_memories_started
extract_memories_finished
auto_dream_skipped
memory_tool_denied
```

## 11.8 如何判断没有污染主对话

验证点：

```text
transcripts/{conversation_id}.jsonl 只包含 user/assistant 主事件。
不包含 session_memory/extract_memories/auto_dream prompt。
SSE 正常只返回 final answer 和 trace event。
主回答不出现“我已更新记忆”等后台元信息。
LangGraph messages 不包含后台 memory agent messages。
```

## 11.9 验证方式

单元/集成测试：

```text
test_context_bundle_memory_disabled_keeps_old_prompt
test_context_bundle_memory_enabled_adds_relevant_memories
test_langgraph_query_appends_transcript
test_langgraph_query_schedules_extract
test_debug_trace_includes_memory_trace
test_background_memory_not_in_transcript
```

手动接口：

```text
POST /api/langgraph/query
Header: X-Debug-Trace: 1
Body:
{
  "query": "帮我查智能门锁库存，回答简洁点",
  "user_id": 1,
  "conversation_id": "123"
}
```

期望：

```text
SSE data 返回主回答
SSE trace event 包含 memory_trace
runtime/memory/transcripts/123.jsonl 生成
runtime/memory/sessions/123/summary.md 视阈值生成或 skipped
```

完成标准：

```text
feature flag off 时旧测试通过
feature flag on 时可召回手工 memory
debug_trace 可见 memory_trace
transcript 生成
后台任务不污染主 transcript
/api/langgraph/query 可手动验证
```

## 11.10 风险和暂缓项

风险：

```text
context_bundle 中放不可序列化对象可能破坏 LangGraph state。
prompt_context 过长影响模型效果。
debug_trace 同步等待后台任务会增加延迟。
```

暂缓：

```text
/api/chat 兼容接入
前端 memory trace UI
完整 E2E 自动化
生产自动 AutoDream
```

