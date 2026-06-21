# 13. 里程碑排期、风险、简化和后续增强

本文是实施计划第 13 个文件，说明建议提交顺序、MVP 边界、必须一开始做对的事项，以及后续增强方向。

## 13.1 里程碑排期

### Milestone 1: 基础包和类型

包含：

```text
memory_system/__init__.py
config.py
paths.py
memory_types.py
schemas.py
frontmatter.py
```

完成标准：

```text
MemoryType 无 project
Markdown/MySQL source of truth 边界写清楚
business_rule frontmatter 校验存在
路径安全校验存在
Phase 1 单测通过
```

### Milestone 2: Scan + Transcript

包含：

```text
memory_scan.py
transcripts.py
```

完成标准：

```text
frontmatter 浅扫描
manifest 输出
JSONL transcript 可追加/读取
cursor 可推进
Phase 2/3 单测通过
```

### Milestone 3: Recall MVP

包含：

```text
find_relevant_memories.py
render.py
```

完成标准：

```text
手工 memory 可召回
最多 5 条
prompt 包含实时事实警告
不接主链路也可模块验证
```

### Milestone 4: SessionMemory

包含：

```text
session_memory.py
prompts/session_memory.md
```

完成标准：

```text
summary.md 可生成/更新
固定 section 校验
不污染 transcript
```

### Milestone 5: ExtractMemories MVP

包含：

```text
extract_memories.py
prompts/extract_memories.md
```

完成标准：

```text
feedback/customer/reference 可生成
business_rule 必须可信来源
实时事实拒绝写入
cursor 成功后推进
```

### Milestone 6: ForkedAgent + Permissions

包含：

```text
forked_agent.py
permissions.py
tools.py
```

完成标准：

```text
memory_root 外写入拒绝
skip_transcript 生效
max_turns 生效
memory_tool_denied 可观察
```

### Milestone 7: AutoDream manual

包含：

```text
auto_dream.py
prompts/consolidation.md
```

完成标准：

```text
--force 可运行
minHours/minSessions 生效
lock 生效
MEMORY.md 可重建
```

### Milestone 8: /api/langgraph/query integration

包含：

```text
main.py
context_manager.py
debug_trace/memory_trace
```

完成标准：

```text
feature flag off 旧行为不变
feature flag on 可召回、写 transcript、调度后台任务
SSE trace 可观察
主对话不被后台污染
```

## 13.2 可逐步提交的 commit

```text
01 memory_system skeleton and types
02 paths/frontmatter/schema tests
03 memory_scan manifest
04 transcript jsonl and cursor
05 relevant memory recall and render
06 session_memory summary
07 extract_memories mvp
08 permissions and forked_agent
09 auto_dream manual
10 langgraph query integration behind flags
11 trace and end-to-end docs/tests
```

## 13.3 MVP 可简化项

可以先简化：

```text
FindRelevantMemories:
  先 deterministic selector，后接 LLM selector。

ExtractMemories:
  先 LLM JSON candidates + 服务端写文件，后接完整 forked agent 工具循环。

AutoDream:
  先手动 --force，后自动触发。

MySQL:
  MVP 不写长期 memory 正文，只保留旧表只读兼容。

tenant_id:
  先 default，后接真实租户。

customer_id:
  先 str(user_id)，后接真实客户身份。
```

## 13.4 必须一开始做对

不能简化：

```text
MemoryType 不能包含 project。
Markdown 和 MySQL 不能双主。
business_rule 不能来自普通客户表达。
business_rule 必须有可信 source_type 和验证字段。
订单、库存、价格、物流、售后进度必须实时查询。
memory 不能覆盖当前工具证据。
后台 memory agent 不能写主 transcript。
写文件必须限制在 memory_root。
feature flag 必须能关闭。
```

## 13.5 主要风险

### 双写一致性风险

如果 Markdown 和 MySQL 都保存长期 memory 正文，会出现冲突。推荐 Markdown 为 source of truth，MySQL 只做索引和审计。

### 业务规则误抽取风险

普通客户表达可能被 LLM 误判成规则。必须通过 `source_type`、`verified_by`、`effective_from` 等字段和服务端校验拦住。

### 实时事实污染风险

订单、库存、价格、物流和售后进度变化快，写入 memory 会误导后续回答。ExtractMemories 和 render prompt 都要明确禁止。

### 权限绕过风险

Windows 路径相似前缀、`..`、符号链接可能绕过弱校验。必须使用 `Path.resolve()` + `relative_to()` / `is_relative_to()` / `commonpath()`。

### Prompt 污染风险

召回过多 memory 会干扰主 Agent。必须限制最多 5 条，并保留 `already_surfaced`。

## 13.6 后续增强

```text
Memory 管理 UI
MySQL 索引和审核状态
向量召回和 rerank
人工审核工作流
多实例共享存储
transcript 归档和加密
AutoDream 自动调度
命中率、纠错率、使用次数指标
memory 删除/撤销审计
```

## 13.7 合理性批判和不足分析

这套方案贴近 Claude-Code 的文件型 memory、manifest、forked agent 和 AutoDream 架构，但对客服系统做了更严格的业务约束。它的不足是实现量较大，且前几个阶段主要是基础设施，短期看不到明显智能提升。

最大技术债是 MVP 阶段允许部分模块先不用完整 ForkedAgent，这会让早期实现和最终架构存在差异。因此 ExtractMemories 自动上线前，必须完成 Phase 7 权限边界。

最大产品风险是长期 memory 的人工治理成本。客服系统面对真实客户，错误记忆比普通错误回答更危险。后续必须补管理 UI、审核流和撤销机制。

