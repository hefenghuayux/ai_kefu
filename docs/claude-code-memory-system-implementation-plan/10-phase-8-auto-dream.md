# 10. Phase 8: AutoDream 周期整理

本文是实施计划第 10 个文件，对应 Phase 8。目标是实现周期性 memory 整理能力，合并重复、修正过期、删除被证伪记忆，并维护 MEMORY.md 索引。

## 10.1 阶段目标

Phase 8 要完成：

```text
1. 新增 auto_dream.py
2. 新增 prompts/consolidation.md
3. 实现 minHours/minSessions 阈值
4. 实现 auto_dream.lock
5. 扫描近期 transcript 和 memory
6. 使用 forked agent 整理 memory
7. 更新 MEMORY.md
8. 支持手动 --force
9. 编写单元测试
```

MVP 只做手动命令，不自动每轮触发。

## 10.2 为什么先做

只有 ExtractMemories 积累了一段时间，AutoDream 才有整理价值。过早接入会：

```text
没有足够 session 可整理
调试困难
可能错误删除刚生成的 memory
```

因此 Phase 8 放在 ExtractMemories 和权限边界之后。

## 10.3 文件变更

新增：

```text
deepseek_agent/llm_backend/app/memory_system/auto_dream.py
deepseek_agent/llm_backend/app/memory_system/prompts/consolidation.md
deepseek_agent/llm_backend/app/test/test_auto_dream.py
```

运行时文件：

```text
deepseek_agent/runtime/memory/state/auto_dream.lock
deepseek_agent/runtime/memory/state/auto_dream_state.json
```

## 10.4 核心数据结构

```python
@dataclass(frozen=True)
class AutoDreamConfig:
    min_hours: int = 24
    min_sessions: int = 5


@dataclass(frozen=True)
class AutoDreamDecision:
    should_run: bool
    reason: str
    session_ids: list[str]


@dataclass(frozen=True)
class AutoDreamResult:
    status: str
    reason: str | None
    session_count: int
    updated_paths: list[str]
    deleted_paths: list[str]
    index_updated: bool
    error_type: str | None = None
```

## 10.5 关键函数设计

### should_run_auto_dream()

```python
def should_run_auto_dream(
    *,
    state_path: Path,
    transcript_root: Path,
    config: AutoDreamConfig,
    force: bool = False,
) -> AutoDreamDecision:
    ...
```

规则：

```text
force=True 直接运行
距离 last_consolidated_at < min_hours -> skipped
新增 session 数 < min_sessions -> skipped
排除当前正在处理 session
```

### acquire_auto_dream_lock()

```python
@asynccontextmanager
async def acquire_auto_dream_lock(lock_path: Path):
    ...
```

规则：

```text
已有 lock 且未过期 -> skipped/locked
运行失败要释放或标记失败
不能并发整理同一 memory root
```

### run_auto_dream()

```python
async def run_auto_dream(
    *,
    paths: MemoryPaths,
    config: MemorySystemConfig,
    force: bool = False,
) -> AutoDreamResult:
    ...
```

流程：

```text
1. 判断 feature flag
2. 判断 should_run
3. 获取 lock
4. scan_memory_roots()
5. 读取近期 transcript 摘要
6. build_consolidation_prompt()
7. run_forked_agent(query_source="auto_dream", skip_transcript=True)
8. 更新 memory 文件和 MEMORY.md
9. 写 auto_dream_state.json
```

### update_memory_index()

```python
async def update_memory_index(memory_dir: Path, headers: list[MemoryHeader]) -> None:
    """重建 MEMORY.md 短索引。"""
```

索引规则：

```text
每条一行
不写正文
不包含绝对路径
description 短而准
坏文件可标记或跳过，推荐先跳过并记录日志
```

## 10.6 Prompt 设计

`prompts/consolidation.md` 分四段：

```text
Phase 1 - Orient:
  查看 memory manifest 和 MEMORY.md。

Phase 2 - Gather recent signal:
  只读取相关 transcript，避免全量读大文件。

Phase 3 - Consolidate:
  合并重复 memory，修正矛盾和过期项。
  business_rule 必须保留可信来源字段。
  不得把普通客户表达升级为 business_rule。

Phase 4 - Prune and index:
  更新 MEMORY.md。
  删除 stale/superseded 指针。
```

## 10.7 接入点

MVP 手动：

```text
deepseek_agent/.venv/python.exe -m app.memory_system.auto_dream --force
```

Phase 9 可选后台触发：

```python
background_tasks.add_task(maybe_auto_dream, ...)
```

但默认建议：

```text
AI_KEFU_AUTO_DREAM_ENABLED=false
```

## 10.8 验证方式

单元测试：

```text
test_auto_dream_skips_before_min_hours
test_auto_dream_skips_before_min_sessions
test_auto_dream_force_runs
test_auto_dream_lock_prevents_concurrent_run
test_update_memory_index_excludes_body
test_business_rule_metadata_preserved
```

手动验证：

```text
构造 5 个 transcript
构造两个重复 feedback memory
运行 --force
确认 MEMORY.md 重建
确认重复项被合并或标记
确认 auto_dream_state.json 更新
```

完成标准：

```text
auto_dream.py 存在
consolidation.md 存在
--force 可运行
minHours/minSessions 生效
lock 生效
MEMORY.md 可更新
后台过程不写主 transcript
单测通过
```

## 10.9 风险和暂缓项

风险：

```text
AutoDream 可能错误删除低频但重要的记忆。
整理 prompt 可能把客户表达误升为业务规则。
并发 lock 处理不当会损坏文件。
```

暂缓：

```text
自动定时调度
人工审核后删除
复杂冲突检测
基于 hit_count 的保留策略
多实例分布式锁
```

