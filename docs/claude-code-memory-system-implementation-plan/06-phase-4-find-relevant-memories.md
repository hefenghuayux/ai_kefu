# 6. Phase 4: FindRelevantMemories 查询前召回

本文是实施计划第 6 个文件，对应 Phase 4。目标是在请求进入 LangGraph 前，根据用户 query 从 Markdown memory 中选择最多 5 条相关记忆，并渲染到 `prompt_context`。

## 6.1 阶段目标

Phase 4 要完成：

```text
1. 新增 find_relevant_memories.py
2. 新增 render.py
3. 使用 memory_scan.py 生成 manifest
4. 实现 deterministic selector 和 LLM selector 接口
5. 读取选中 memory 正文
6. 渲染长期 memory prompt section
7. 记录 recall trace
8. 编写单元测试
```

本阶段可以先不接入 `context_manager.py`，但函数签名要为 Phase 9 接入准备。

## 6.2 为什么先做

这是长期 memory 对主 Agent 产生价值的第一个闭环。它只依赖 Phase 1-3，不依赖 ExtractMemories。开发者可以手工创建 memory 文件，验证召回和 prompt 注入。

如果等 ExtractMemories 完成后再做 recall，问题会难以定位：

```text
不知道是抽取没写对
还是扫描没扫到
还是 selector 没选中
还是 prompt 没注入
```

所以先做查询前召回。

## 6.3 文件变更

新增：

```text
deepseek_agent/llm_backend/app/memory_system/find_relevant_memories.py
deepseek_agent/llm_backend/app/memory_system/render.py
deepseek_agent/llm_backend/app/test/test_find_relevant_memories.py
deepseek_agent/llm_backend/app/test/test_memory_render.py
```

依赖：

```text
memory_scan.py
frontmatter.py
schemas.py
paths.py
config.py
```

本阶段不修改：

```text
main.py
context_manager.py
lg_builder.py
```

## 6.4 核心数据结构

### RelevantMemory

```python
@dataclass(frozen=True)
class RelevantMemory:
    header: MemoryHeader
    content: str
    truncated: bool
```

### MemoryRecallResult

```python
@dataclass(frozen=True)
class MemoryRecallResult:
    selected: list[RelevantMemory]
    manifest_count: int
    selected_paths: list[str]
    skipped_paths: list[str]
    selector: str
    elapsed_ms: int
    reason: str | None = None
```

### SelectedMemoriesSchema

LLM 输出必须符合：

```json
{
  "selected_memories": [
    "feedback/inventory_answer_style.md"
  ]
}
```

服务端要过滤：

```text
不在 manifest 中的路径
绝对路径
包含 .. 的路径
超过 max_selected_memories 的路径
重复路径
```

## 6.5 关键函数设计

### find_relevant_memories()

```python
async def find_relevant_memories(
    *,
    query: str,
    paths: MemoryPaths,
    config: MemorySystemConfig,
    recent_tools: list[str] | None = None,
    already_surfaced: set[str] | None = None,
    selector: MemorySelector | None = None,
) -> MemoryRecallResult:
    """查询前召回相关 memory。"""
```

流程：

```text
1. 如果 config.enabled 或 recall_enabled 为 false，返回 skipped。
2. scan_memory_roots(paths)
3. 过滤 already_surfaced
4. format_memory_manifest(headers)
5. 调用 selector 选择 filename
6. 服务端过滤 selector 输出
7. 读取选中文件正文
8. 截断正文到 max_memory_body_chars
9. 返回 MemoryRecallResult
```

### select_relevant_memories_with_llm()

```python
async def select_relevant_memories_with_llm(
    *,
    query: str,
    manifest: str,
    valid_paths: set[str],
    recent_tools: list[str],
) -> list[str]:
    """LLM selector，输出 selected_memories。"""
```

Prompt 要求：

```text
只选择明确有用的 memory。
不确定就不选。
最多 5 条。
没有相关 memory 返回空列表。
memory 是历史经验，不是实时事实。
不要选择会替代订单/库存/价格/物流实时查询的 memory。
```

### select_relevant_memories_deterministic()

```python
def select_relevant_memories_deterministic(
    *,
    query: str,
    headers: list[MemoryHeader],
    max_selected: int,
) -> list[str]:
    """MVP 或测试用 selector。"""
```

推荐规则：

```text
按 query 与 description/filename 的关键词重叠计分
business_rule/customer/feedback/reference 不做硬优先级
得分 <= 0 不选
最多 max_selected
```

取舍：

```text
LLM selector 更接近 Claude-Code，但测试不稳定且需要模型。
deterministic selector 可用于单测和离线验证，但召回质量有限。
推荐：生产默认 LLM selector，测试和无模型环境用 deterministic selector。
```

### read_selected_memory()

```python
async def read_selected_memory(
    header: MemoryHeader,
    *,
    max_chars: int,
) -> RelevantMemory:
    """读取 memory 正文并截断。"""
```

规则：

```text
显式 UTF-8
读取前 assert_under_memory_root
超长截断并标 truncated=True
坏文件抛错并记录 skipped_paths
```

### render_memory_context()

```python
def render_memory_context(
    *,
    session_summary: str | None,
    relevant_memories: list[RelevantMemory],
) -> str:
    """渲染要并入 prompt_context 的 memory section。"""
```

输出示例：

```text
以下是与本轮请求相关的长期记忆。它们是历史经验，不是实时数据库结果；订单、库存、价格、物流和售后进度必须以本轮工具查询为准。

<memory path="feedback/inventory_answer_style.md" type="feedback" updated_at="...">
...
</memory>
```

## 6.6 与 ai_kefu 接入点

Phase 9 中接入：

```text
context_manager.py::load_context_bundle()
```

推荐添加字段：

```python
context["selected_memories"] = recall_result.selected
context["memory_trace"]["recall"] = {
    "selected_memory_count": len(recall_result.selected),
    "selected_memory_paths": recall_result.selected_paths,
    "selector": recall_result.selector,
}
```

`lg_builder.py` 不需要改，因为它已经注入 `prompt_context`。

## 6.7 验证方式

单元测试：

```text
test_recall_returns_empty_when_disabled
test_deterministic_selector_selects_by_description
test_selector_filters_invalid_absolute_path
test_selector_filters_path_traversal
test_recall_reads_selected_memory_body
test_recall_truncates_large_memory
test_render_memory_context_warns_not_realtime_fact
test_render_memory_context_does_not_include_empty_section
```

手动验证：

```text
创建 feedback/inventory_answer_style.md
query = "帮我查库存，别解释字段"
调用 find_relevant_memories()
确认 selected_paths 包含该文件
调用 render_memory_context()
确认包含 memory 标签和实时事实警告
```

完成标准：

```text
find_relevant_memories.py 和 render.py 存在
selector 输出被服务端过滤
最多返回 5 条
不泄漏绝对路径
prompt 明确 memory 不能覆盖当前工具证据
单测通过
尚未修改主链路
```

## 6.8 风险和暂缓项

风险：

```text
LLM selector 可能误选过期 memory。
关键词 selector 召回率有限。
召回过多会污染 prompt。
业务规则 memory 如果未校验来源，可能误导回答。
```

暂缓：

```text
向量检索
rerank
hit_count/last_used_at 持久化
already_surfaced 跨请求持久化
基于用户反馈的召回质量训练集
```

