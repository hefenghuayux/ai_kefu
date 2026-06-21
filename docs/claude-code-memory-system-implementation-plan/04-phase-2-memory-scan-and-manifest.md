# 4. Phase 2: Memory Scan 和 Manifest

本文是 `ai_kefu` Claude-Code 风格记忆系统实施计划第 4 个文件，对应 Phase 2。目标是实现 frontmatter 浅扫描和 manifest 格式化，为查询前召回、长期记忆抽取和 AutoDream 整理提供共同基础。

## 4.1 阶段目标

Phase 2 要完成：

```text
1. 实现 memory_scan.py
2. 扫描 customer memory 和 business memory
3. 排除 MEMORY.md
4. 只读取每个 Markdown 文件前 30 行
5. 解析 frontmatter 中的 type 和 description
6. 生成 MemoryHeader 列表
7. 按 mtime 新到旧排序
8. 最多返回 200 个
9. 格式化 Claude-Code 风格 manifest
10. 记录 scan trace 和解析失败原因
11. 编写单元测试
```

本阶段仍然不接入 `/api/langgraph/query`，不调用 LLM，不读取 memory 正文。

## 4.2 为什么先做

Claude-Code 把扫描逻辑拆到 `memoryScan.ts`，原因是它同时服务两条链路：

```text
findRelevantMemories:
  查询前读取 headers，让 selector 从 manifest 中选最多 5 条。

extractMemories:
  抽取前预注入 manifest，让后台 Agent 优先更新已有 memory，避免重复创建。
```

`ai_kefu` 也应复用同一套扫描函数。否则后续会出现：

```text
召回看到一组 memory
抽取看到另一组 memory
AutoDream 又用第三套扫描规则
MEMORY.md 和实际文件不一致
```

Phase 2 是低风险、可完全单测的模块，适合在接入 LLM 前先做实。

## 4.3 参考 Claude-Code 行为

Claude-Code 的核心行为：

```text
MAX_MEMORY_FILES = 200
FRONTMATTER_MAX_LINES = 30
recursive scan .md
basename != MEMORY.md
readFileInRange(file, 0, FRONTMATTER_MAX_LINES)
parseFrontmatter(content)
parseMemoryType(frontmatter.type)
sort newest first
slice 0..MAX_MEMORY_FILES
format as "- [type] filename (timestamp): description"
```

`ai_kefu` 推荐保持这些语义，但加入客服系统需要的 scope：

```text
customer scope
business scope
```

## 4.4 文件变更

### 新增文件

```text
deepseek_agent/llm_backend/app/memory_system/memory_scan.py
deepseek_agent/llm_backend/app/test/test_memory_scan.py
```

### 依赖 Phase 1 文件

```text
deepseek_agent/llm_backend/app/memory_system/config.py
deepseek_agent/llm_backend/app/memory_system/paths.py
deepseek_agent/llm_backend/app/memory_system/memory_types.py
deepseek_agent/llm_backend/app/memory_system/schemas.py
deepseek_agent/llm_backend/app/memory_system/frontmatter.py
```

### 本阶段不修改文件

```text
deepseek_agent/llm_backend/main.py
deepseek_agent/llm_backend/app/lg_agent/context_manager.py
deepseek_agent/llm_backend/app/lg_agent/lg_builder.py
```

## 4.5 memory_scan.py 文件职责

`memory_scan.py` 只负责：

```text
列举 memory Markdown 文件
读取 frontmatter 前缀
解析 header
生成 MemoryHeader
格式化 manifest
合并 customer/business scope 扫描结果
```

它不负责：

```text
判断 query 相关性
读取正文
调用 LLM
写 memory 文件
更新 MEMORY.md
做 AutoDream 整理
```

## 4.6 数据结构设计

### MemoryHeader

复用 Phase 1 的结构：

```python
@dataclass(frozen=True)
class MemoryHeader:
    relative_path: str
    absolute_path: Path
    mtime_ms: float
    description: str | None
    type: MemoryType | None
    scope: MemoryScope
    source_type: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    parse_error: str | None = None
```

### MemoryScanResult

建议新增：

```python
@dataclass(frozen=True)
class MemoryScanResult:
    headers: list[MemoryHeader]
    scanned_file_count: int
    skipped_file_count: int
    skipped_reasons: list[str]
    memory_dirs: tuple[Path, ...]
```

用途：

```text
headers 给 recall/extract 使用
scanned_file_count/skipped_file_count 给日志和 debug trace
skipped_reasons 给测试和排查
memory_dirs 方便确认扫描范围
```

### MemoryManifest

可以先不定义类，直接用函数返回字符串：

```python
def format_memory_manifest(headers: Sequence[MemoryHeader]) -> str:
    ...
```

如果后续需要同时返回文本和 metadata，再抽成 dataclass。

## 4.7 关键函数设计

### scan_memory_files()

```python
async def scan_memory_files(
    memory_dir: Path,
    *,
    scope: MemoryScope,
    config: MemorySystemConfig,
) -> MemoryScanResult:
    """扫描单个 memory 目录下的 Markdown 文件，返回 headers。"""
```

输入：

```text
memory_dir:
  customers/{customer_id}/memory 或 business/{tenant_id}/memory

scope:
  customer 或 business

config:
  提供 max_memory_files 和 frontmatter_max_lines
```

行为：

```text
目录不存在 -> 返回空 result，不抛错
递归查找 .md
排除 MEMORY.md
只读取前 frontmatter_max_lines 行
解析 type/description
解析 source_type/effective_from/effective_to/verified_by/verified_at 等关键 frontmatter 字段，但 manifest 默认不展示这些字段
无法解析 type -> type=None，但保留 header 和 parse_error
无法读取单个文件 -> skipped_file_count +1，继续扫描
按 mtime_ms 新到旧排序
最多返回 config.max_memory_files
```

注意：

```text
目录不存在返回空是合理的，因为新用户可能还没有 memory。
单个坏文件不应导致整个 recall 失败。
但错误必须记录 skipped_reasons，不能静默。
```

### scan_memory_roots()

```python
async def scan_memory_roots(
    paths: MemoryPaths,
    *,
    config: MemorySystemConfig,
) -> MemoryScanResult:
    """同时扫描 customer memory 和 business memory，并合并结果。"""
```

扫描范围：

```text
paths.customer_memory_dir
paths.business_memory_dir
```

排序：

```text
先合并，再按 mtime_ms 新到旧排序，再截断 max_memory_files。
```

为什么合并后截断：

```text
如果先分别截断，会导致 customer 200 + business 200，突破全局上限。
Claude-Code 的上限是每个 memoryDir 200；ai_kefu 多 scope 合并后 prompt 预算更紧，因此推荐全局 200。
```

如需更贴近 Claude-Code，也可以后续改为每个 scope 各 200，但 MVP 推荐全局 200。

### parse_memory_header()

```python
def parse_memory_header(
    *,
    file_path: Path,
    base_dir: Path,
    scope: MemoryScope,
    prefix_content: str,
    mtime_ms: float,
) -> MemoryHeader:
    """从 frontmatter prefix 解析 MemoryHeader。"""
```

规则：

```text
relative_path 使用相对 base_dir 的 POSIX 风格路径
description 缺失时为 None
type 缺失或非法时为 None
business_rule 缺少 source_type/effective_from/effective_to/verified_by/verified_at 时 parse_error 记录 validation warning
business_rule 的 source_type 是 customer_statement 时 parse_error 记录 forbidden_source_type
parse_error 记录缺失 frontmatter、非法 type、非法 description 等
```

POSIX 风格路径示例：

```text
feedback/inventory_answer_style.md
business_rule/smart_lock_after_sales.md
```

不要在 manifest 中暴露 Windows 绝对路径。

### format_memory_manifest()

```python
def format_memory_manifest(headers: Sequence[MemoryHeader]) -> str:
    """把 headers 格式化为 selector/extractor 可读的 manifest。"""
```

输出示例：

```text
- [customer] customer/vip_answer_style.md (2026-06-21T10:00:00+08:00): 客户希望回答简洁
- [feedback] feedback/inventory_answer_style.md (2026-06-21T10:01:00+08:00): 客户纠正库存回答不要解释字段
- [business_rule] business_rule/smart_lock_after_sales.md (2026-06-21T10:02:00+08:00): 智能门锁安装后 7 天内质量问题支持换货
```

如果没有 description：

```text
- [reference] reference/after_sales_kb.md (2026-06-21T10:03:00+08:00)
```

如果 type 解析失败：

```text
- [unknown] feedback/bad_type.md (2026-06-21T10:04:00+08:00): ...
```

建议 manifest 里不要包含 parse_error，避免污染 selector prompt。parse_error 只进入日志和 trace。

### filter_headers_by_type()

```python
def filter_headers_by_type(
    headers: Sequence[MemoryHeader],
    allowed_types: set[MemoryType],
) -> list[MemoryHeader]:
    """按类型过滤，供后续 extract/auto_dream 使用。"""
```

用途：

```text
customer scope 中不应该出现 business_rule。
business scope 中可以有 business_rule/feedback/reference。
```

是否在 Phase 2 强制过滤：

```text
推荐 scan 先不强制丢弃，只记录 parse/scope warning。
后续写入和整理时再严格处理。
```

原因：

```text
扫描层应该尽量客观反映文件状态，避免把坏文件从可观测性中隐藏掉。
```

## 4.8 扫描规则细化

### 文件发现

使用：

```python
memory_dir.rglob("*.md")
```

排除：

```text
MEMORY.md
隐藏目录可暂不特殊处理
非 .md 文件
```

需要注意：

```text
Windows 上 Path.rglob 返回反斜杠路径，relative_path 要统一成 POSIX。
```

### frontmatter 读取

读取方式：

```python
with path.open("r", encoding="utf-8") as f:
    for _ in range(config.frontmatter_max_lines):
        line = f.readline()
```

不要：

```text
read_text() 读取全文
```

原因：

```text
Claude-Code 明确只读前 30 行，避免扫描阶段把 memory 正文全部读入。
```

### mtime 获取

使用：

```python
stat = path.stat()
mtime_ms = stat.st_mtime * 1000
```

`updated_at` 展示可以由 `mtime_ms` 转 ISO：

```python
datetime.fromtimestamp(mtime_ms / 1000, tz=timezone.utc).isoformat()
```

是否用 frontmatter.updated_at：

```text
排序建议用文件 mtime。
manifest 可优先展示 frontmatter.updated_at，但 Phase 2 为贴近 Claude-Code，推荐展示 mtime。
```

### 异常处理

单文件异常：

```text
PermissionError
UnicodeDecodeError
frontmatter parse error
OSError
```

处理：

```text
skipped_file_count +1
skipped_reasons append 简短 reason
log_event WARNING memory_scan_file_skipped
继续扫描
```

目录级异常：

```text
memory_dir 不存在 -> 空 result
memory_dir 不是目录 -> skipped reason，空 result
```

不要静默返回空，至少 result 中要有 skipped reason。

## 4.9 Scope 规则

### customer memory dir

允许类型：

```text
customer
feedback
reference
```

不推荐出现：

```text
business_rule
```

原因：

```text
business_rule 应该是业务域共享规则，不应存在某个客户私有目录下。
```

Phase 2 处理方式：

```text
扫描保留，但 parse_error 或 warning 标记 scope_type_mismatch。
```

### business memory dir

允许类型：

```text
business_rule
feedback
reference
```

不推荐出现：

```text
customer
```

原因：

```text
customer 偏好不应提升为业务域共享规则。
```

Phase 2 处理方式同上。

## 4.10 Manifest 设计取舍

### 推荐 manifest 格式

```text
- [scope/customer][customer] customer/vip_answer_style.md (2026-06-21T02:00:00+00:00): 客户希望回答简洁
- [scope/business][business_rule] business_rule/smart_lock_after_sales.md (2026-06-21T02:01:00+00:00): 智能门锁安装后 7 天内质量问题支持换货
```

或者更接近 Claude-Code：

```text
- [customer] customer/vip_answer_style.md (2026-06-21T02:00:00+00:00): 客户希望回答简洁
- [business_rule] business_rule/smart_lock_after_sales.md (2026-06-21T02:01:00+00:00): 智能门锁安装后 7 天内质量问题支持换货
```

推荐方案：

```text
Phase 2 manifest 默认接近 Claude-Code，只显示 type。
debug trace 和 MemoryHeader 保留 scope。
```

原因：

```text
selector prompt 越短越稳定。
scope 对选择有用，但 type 已经能表达大部分语义。
如后续发现 customer/business 混淆，再把 scope 加入 manifest。
```

### 是否读取 MEMORY.md

Phase 2 的 `scan_memory_files()` 不读取 `MEMORY.md`。

原因：

```text
Claude-Code 排除 MEMORY.md，因为 MEMORY.md 是索引，实际 headers 来自每个 memory 文件 frontmatter。
如果 MEMORY.md 和文件 frontmatter 冲突，应以文件为准。
```

后续 AutoDream 会负责维护 `MEMORY.md`。

## 4.11 与现有 ai_kefu 代码的接入点

本阶段仍不直接接入现有代码，但会被后续模块调用。

### Phase 4 使用

`find_relevant_memories.py` 会调用：

```python
scan_result = await scan_memory_roots(paths, config=config)
manifest = format_memory_manifest(scan_result.headers)
```

### Phase 6 使用

`extract_memories.py` 会调用：

```python
scan_result = await scan_memory_roots(paths, config=config)
manifest = format_memory_manifest(scan_result.headers)
```

然后把 manifest 注入 extraction prompt，要求后台 Agent 优先更新已有 memory。

### Phase 8 使用

`auto_dream.py` 会调用：

```python
scan_result = await scan_memory_roots(paths, config=config)
```

用于查找重复、过期、矛盾或缺失索引的文件。

### Phase 9 trace 使用

`context_manager.py` 后续会把摘要写入：

```python
context_bundle["memory_trace"]["scan"] = {
    "scanned_file_count": scan_result.scanned_file_count,
    "skipped_file_count": scan_result.skipped_file_count,
}
```

## 4.12 实现步骤

### Step 1: 定义 MemoryScanResult

如果 Phase 1 未放入 `schemas.py`，就在 Phase 2 补充：

```python
@dataclass(frozen=True)
class MemoryScanResult:
    ...
```

### Step 2: 实现 prefix 读取

可放在 `frontmatter.py`：

```python
def read_frontmatter_prefix(path: Path, max_lines: int) -> str:
    ...
```

或放在 `memory_scan.py` 私有函数：

```python
def _read_prefix(path: Path, max_lines: int) -> str:
    ...
```

推荐：

```text
放在 frontmatter.py，因为 Phase 2 以后可能复用。
```

### Step 3: 实现单文件解析

```python
def parse_memory_header(...):
    parsed = parse_frontmatter_markdown(prefix_content)
    raw_type = parsed.frontmatter.get("type")
    memory_type = parse_memory_type(raw_type)
    description = parsed.frontmatter.get("description")
    ...
```

处理细节：

```text
description 不是 str -> description=None + parse_error
type 非法 -> type=None + parse_error
无 frontmatter -> type=None/description=None + parse_error
```

### Step 4: 实现目录扫描

```python
async def scan_memory_files(...):
    ...
```

虽然函数是 async，但内部可以先同步文件 IO。保留 async 是为了后续如果要 `asyncio.to_thread()` 或并发读取，不影响调用方接口。

第一版可同步实现，但注意文件数量最多 200，扫描开销可控。

### Step 5: 实现多 root 合并

```python
async def scan_memory_roots(paths, config):
    customer = await scan_memory_files(...)
    business = await scan_memory_files(...)
    merged = ...
```

合并 skipped reason：

```python
skipped_reasons = customer.skipped_reasons + business.skipped_reasons
```

### Step 6: 实现 manifest formatting

```python
def format_memory_manifest(headers):
    if not headers:
        return ""
    ...
```

时间格式：

```text
ISO 8601 UTC 即可。
```

### Step 7: 加日志

使用项目现有 logger：

```python
from app.core.logger import get_logger, log_event

logger = get_logger(service="memory_system")
```

事件：

```text
memory_scan_started
memory_scan_finished
memory_scan_file_skipped
```

字段：

```text
memory_dir
scope
scanned_file_count
header_count
skipped_file_count
elapsed_ms
reason
error_type
```

注意：

```text
日志中可以记录路径和 description 长度，但不建议记录完整 memory 正文。
Phase 2 不读取正文，所以不存在正文泄漏。
```

## 4.13 单元测试设计

### test_scan_excludes_memory_index

准备：

```text
tmp/customer/memory/MEMORY.md
tmp/customer/memory/feedback/a.md
```

断言：

```text
headers 只包含 feedback/a.md
```

### test_scan_reads_frontmatter_only

准备：

```text
a.md 前 30 行内有 frontmatter
第 100 行有特殊内容
```

断言：

```text
scan 不需要读取正文。
```

实现方式：

```text
可通过构造超大正文并确认扫描仍快速。
不需要复杂 mock 文件对象。
```

### test_scan_limits_to_max_memory_files

准备：

```text
创建 205 个 .md
config.max_memory_files=200
```

断言：

```text
len(headers) == 200
```

### test_scan_sorts_newest_first

准备：

```text
a.md mtime older
b.md mtime newer
```

断言：

```text
headers[0].relative_path == "feedback/b.md"
```

### test_scan_invalid_type_does_not_crash

准备：

```md
---
type: project
description: bad type
---
```

断言：

```text
header.type is None
header.parse_error is not None
scan_result.skipped_file_count == 0
```

原因：

```text
非法 type 是文件质量问题，但不一定要跳过文件。selector 仍可能看到 unknown 文件，AutoDream 可以后续修复。
```

### test_scan_business_rule_requires_trusted_source

准备：

```md
---
type: business_rule
description: 用户说这个商品应该能七天退
source_type: customer_statement
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.7
---
```

断言：

```text
header.type == MemoryType.BUSINESS_RULE
header.parse_error 包含 forbidden_source_type 或 trusted source
manifest 可以暂时包含该文件，但后续 ExtractMemories/AutoDream 必须修复或拒绝使用
```

### test_scan_business_rule_keeps_verification_metadata

准备：

```md
---
type: business_rule
description: 智能门锁安装后 7 天内质量问题支持换货
source_type: operator_confirmed
effective_from: "2026-06-21"
effective_to: null
verified_by: "operator:123"
verified_at: "2026-06-21T10:00:00+08:00"
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.95
---
```

断言：

```text
header.source_type == "operator_confirmed"
header.effective_from == "2026-06-21"
header.effective_to is None
header.verified_by == "operator:123"
header.verified_at == "2026-06-21T10:00:00+08:00"
header.parse_error is None
```

### test_scan_bad_encoding_skips_file

准备：

```text
写入非 UTF-8 bytes
```

断言：

```text
skipped_file_count == 1
headers 不包含该文件
skipped_reasons 包含 UnicodeDecodeError 或 utf-8
```

### test_format_memory_manifest

准备：

```python
headers = [
    MemoryHeader(
        relative_path="feedback/inventory_answer_style.md",
        type=MemoryType.FEEDBACK,
        description="客户希望库存回答简洁",
        ...
    )
]
```

断言：

```text
manifest 包含 [feedback]
manifest 包含 feedback/inventory_answer_style.md
manifest 包含 description
manifest 不包含 absolute Windows path
```

### test_scan_memory_roots_merges_customer_and_business

准备：

```text
customers/1/memory/feedback/a.md
business/default/memory/business_rule/b.md
```

断言：

```text
headers 同时包含 a.md 和 b.md
scope 分别正确
```

## 4.14 验证方式

### 单元测试命令

```text
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_scan.py
```

建议同时跑 Phase 1 测试：

```text
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_types.py deepseek_agent/llm_backend/app/test/test_memory_paths.py deepseek_agent/llm_backend/app/test/test_frontmatter.py deepseek_agent/llm_backend/app/test/test_memory_scan.py
```

### 手动验证

构造文件：

```text
deepseek_agent/runtime/memory/customers/1/memory/feedback/inventory_answer_style.md
deepseek_agent/runtime/memory/business/default/memory/business_rule/smart_lock_after_sales.md
```

内容：

```md
---
type: feedback
description: 客户希望库存回答简洁，不重复解释字段
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.9
source_conversation_id: "123"
source_request_id: "req-xxx"
---

客户在库存咨询中希望回答简洁。
```

运行一个临时脚本调用 `scan_memory_roots()`，应输出类似：

```text
- [feedback] feedback/inventory_answer_style.md (2026-06-21T02:00:00+00:00): 客户希望库存回答简洁，不重复解释字段
- [business_rule] business_rule/smart_lock_after_sales.md (2026-06-21T02:01:00+00:00): 智能门锁安装后 7 天内质量问题支持换货
```

## 4.15 完成标准

Phase 2 完成必须满足：

```text
memory_scan.py 存在
scan_memory_files() 可扫描单个 memory dir
scan_memory_roots() 可合并 customer/business memory
format_memory_manifest() 输出 Claude-Code 风格 manifest
扫描排除 MEMORY.md
扫描只读前 30 行
扫描最多返回 200 个
扫描按 mtime 新到旧排序
非法 type 不导致崩溃
坏编码文件会被跳过并记录 reason
manifest 不泄漏绝对路径
business_rule 缺可信来源字段会进入 parse_error
business_rule 使用 source_type=customer_statement 会进入 parse_error
所有 Phase 2 单测通过
仍未修改 main.py/context_manager.py/lg_builder.py
```

## 4.16 风险和暂缓项

### 风险 1: scope 和 type 可能重复表达

`customer` scope 下有 `customer` type，`business` scope 下有 `business_rule` type。manifest 如果同时展示 scope 和 type，会变长。MVP 推荐 manifest 只展示 type，trace 保留 scope。

### 风险 2: 坏文件保留在 scan 结果里会影响 selector

非法 type 的文件如果仍进入 manifest，selector 可能选中它。替代方案是非法 type 直接跳过。推荐当前方案是保留但标 unknown，因为这样 AutoDream 或人工审查能发现坏文件。Phase 4 读取正文时仍要过滤路径和大小。

### 风险 3: 全局 200 上限可能压掉业务规则

如果某客户 memory 很多，合并后全局 200 可能让较旧的 business_rule 被截掉。MVP 可接受，但后续可以改成：

```text
customer 最多 120
business 最多 80
```

或在排序时提高 `business_rule` 优先级。当前不建议过早复杂化。

### 可暂缓内容

```text
向量索引
SQLite manifest cache
增量扫描缓存
MEMORY.md 与文件一致性检查
scope/type 自动修复
按命中次数排序
按 confidence 排序
```
