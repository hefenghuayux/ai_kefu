# 8. Phase 6: ExtractMemories 长期记忆抽取

本文是实施计划第 8 个文件，对应 Phase 6。目标是从 transcript 新增内容中抽取长期有效的 customer、feedback、business_rule、reference 记忆，并写入 Markdown memory files。

## 8.1 阶段目标

Phase 6 要完成：

```text
1. 新增 extract_memories.py
2. 新增 prompts/extract_memories.md
3. 从 transcript cursor 后读取新增事件
4. 扫描现有 memory manifest
5. 生成抽取候选
6. 服务端校验候选
7. 写入或更新 Markdown memory 文件
8. 推进 extract_cursor.json
9. 记录 extract trace
10. 编写单元测试
```

MVP 可以先不使用完整 ForkedAgent，但必须让接口后续可替换为 `run_forked_agent(max_turns=5, skip_transcript=True)`。

## 8.2 为什么先做

Phase 1-5 已经具备：

```text
类型和路径
frontmatter
scan manifest
transcript
recall
session summary
```

此时做 ExtractMemories，输入、输出和验证面都清楚。过早做抽取会把 LLM prompt、文件写入、cursor、权限、类型校验混在一起。

## 8.3 文件变更

新增：

```text
deepseek_agent/llm_backend/app/memory_system/extract_memories.py
deepseek_agent/llm_backend/app/memory_system/prompts/extract_memories.md
deepseek_agent/llm_backend/app/test/test_extract_memories.py
```

可能修改：

```text
memory_system/memory_types.py
memory_system/frontmatter.py
memory_system/transcripts.py
memory_system/memory_scan.py
```

本阶段不直接修改 `main.py`，Phase 9 再接入调度。

## 8.4 核心数据结构

### ExtractMemoryCandidate

```python
@dataclass(frozen=True)
class ExtractMemoryCandidate:
    memory_type: MemoryType
    scope: MemoryScope
    title: str
    filename: str
    description: str
    body: str
    confidence: float
    source_type: str
    source_conversation_id: str
    source_request_id: str
    effective_from: str | None = None
    effective_to: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    action: Literal["create", "update"] = "create"
    existing_path: str | None = None
```

### ExtractMemoriesResult

```python
@dataclass(frozen=True)
class ExtractMemoriesResult:
    status: str
    reason: str | None
    processed_event_count: int
    written_paths: list[str]
    updated_paths: list[str]
    rejected_count: int
    cursor_advanced: bool
    error_type: str | None = None
```

## 8.5 关键函数设计

### maybe_extract_memories()

```python
async def maybe_extract_memories(
    *,
    paths: MemoryPaths,
    identity: MemoryIdentity,
    config: MemorySystemConfig,
    request_id: str,
) -> ExtractMemoriesResult:
    ...
```

流程：

```text
1. 检查 feature flag
2. 读取 transcript cursor 后新增事件
3. 没有新增事件 -> skipped
4. scan_memory_roots() 生成 manifest
5. build_extract_prompt()
6. 调用 extractor
7. parse candidates
8. validate candidates
9. write/update Markdown
10. 成功后 update_extract_cursor()
```

### build_extract_prompt()

```python
def build_extract_prompt(
    *,
    events: list[TranscriptEvent],
    manifest: str,
    current_date: str,
) -> list[dict[str, str]]:
    ...
```

Prompt 必须包含：

```text
只能根据 transcript 新增事件抽取。
不要调查源码、git、API 实现。
不要调用业务系统重新查。
普通客户表达不能生成 business_rule。
business_rule 必须有可信 source_type。
订单/库存/价格/物流/售后进度不能写长期 memory。
优先更新已有 memory，而不是重复创建。
输出 JSON candidates。
```

### validate_extract_candidate()

```python
def validate_extract_candidate(candidate: ExtractMemoryCandidate) -> None:
    ...
```

必须拒绝：

```text
memory_type == project
business_rule 且 source_type == customer_statement
business_rule 缺 effective_from/effective_to/verified_by/verified_at
body 包含明显实时事实类型但不是策略
filename 非法或路径穿越
confidence 不在 0..1
scope/type 不匹配
```

实时事实关键词不是最终安全机制，但 MVP 可先作为硬校验：

```text
order_status
inventory_count
price
shipment_status
after_sales_progress
```

### write_memory_candidate()

```python
async def write_memory_candidate(
    *,
    candidate: ExtractMemoryCandidate,
    paths: MemoryPaths,
    config: MemorySystemConfig,
) -> Path:
    ...
```

写入规则：

```text
Markdown 是长期 memory source of truth。
MySQL 不写长期 memory 正文。
写入前 assert_under_memory_root。
create 写新文件。
update 只更新 existing_path。
MEMORY.md 索引更新可在 MVP 暂缓到 AutoDream，也可同步追加一行。
```

推荐 MVP：

```text
写 memory 文件
不自动改 MEMORY.md
让 AutoDream 或后续 index updater 统一维护
```

理由：

```text
减少 ExtractMemories 同时改多个文件的复杂度。
避免索引重复。
```

## 8.6 与 ai_kefu 接入点

Phase 9 在 `main.py` 请求完成后调度：

```python
background_tasks.add_task(
    maybe_extract_memories,
    paths=paths,
    identity=identity,
    config=config,
    request_id=request_id,
)
```

debug_trace=True 时可以同步等待：

```text
用于验证 extract_status、written_paths、rejected_count。
生产默认后台执行。
```

## 8.7 验证方式

单元测试：

```text
test_extract_skips_when_disabled
test_extract_reads_only_cursor_after_events
test_validate_rejects_project_type
test_validate_rejects_customer_statement_business_rule
test_validate_requires_business_rule_verification_fields
test_validate_rejects_realtime_order_status_memory
test_write_candidate_creates_markdown
test_write_candidate_rejects_path_traversal
test_cursor_advances_only_after_success
test_duplicate_prefers_update_existing_path
```

手动 case：

```text
Case A:
  transcript 中用户说“以后库存回答别解释字段”
  生成 feedback memory。

Case B:
  transcript 中普通用户说“这个应该七天退”
  不生成 business_rule。

Case C:
  transcript 中运营确认售后规则
  生成 business_rule，source_type=operator_confirmed。

Case D:
  transcript 中工具返回“订单 888 待发货”
  不生成长期 memory。
```

完成标准：

```text
extract_memories.py 存在
prompts/extract_memories.md 存在
可根据 fixture transcript 写入 Markdown memory
business_rule 可信来源校验生效
实时事实拒绝写入生效
cursor 成功后才推进
后台过程不写主 transcript
单测通过
```

## 8.8 风险和暂缓项

风险：

```text
LLM 抽取会误判临时需求为长期偏好。
重复检测不足会生成多个类似 memory。
服务端硬校验过严可能漏掉真实规则。
```

暂缓：

```text
人工审核队列
MySQL 索引表写入
复杂重复合并
向量相似度去重
完整 forked agent 工具循环
```

