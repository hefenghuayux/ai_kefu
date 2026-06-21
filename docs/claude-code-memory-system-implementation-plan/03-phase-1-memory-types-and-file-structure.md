# 3. Phase 1: 基础文件结构和 Memory 类型

本文是 `ai_kefu` Claude-Code 风格记忆系统实施计划第 3 个文件，对应 Phase 1。目标是先建立不可变的类型、路径、配置、frontmatter 和 schema 基础。

## 3.1 阶段目标

Phase 1 要完成：

```text
1. 新增 memory_system Python 包
2. 定义客服场景 memory type
3. 定义 memory scope 和路径规则
4. 定义 runtime memory 目录结构
5. 定义 frontmatter schema
6. 提供基础 frontmatter 解析和序列化
7. 提供目录初始化函数
8. 提供单元测试
```

本阶段不接入 `/api/langgraph/query`，不调用 LLM，不写 transcript，不调度后台任务。

## 3.2 为什么先做

Claude-Code 的后续模块都依赖固定 memory 类型和 frontmatter：

```text
memory_scan 需要 type/description/mtime
findRelevantMemories 需要 manifest
extractMemories 需要知道哪些类型可写
AutoDream 需要知道哪些文件可合并
permissions 需要知道 memory root
render 需要知道哪些 memory 能注入 prompt
```

如果 Phase 1 没做扎实，后面会出现：

```text
类型名到处写字符串
customer/business 目录混乱
project 类型被误引入
frontmatter 字段不统一
测试 fixture 和实际文件格式不一致
权限校验没有稳定 root
```

所以 Phase 1 是整个系统的地基。

## 3.3 文件变更

### 新增目录

```text
deepseek_agent/llm_backend/app/memory_system/
```

职责：

```text
承载所有 Claude-Code 风格 memory 子系统。
避免继续把新逻辑塞进 context_manager.py。
```

### 新增文件清单

```text
deepseek_agent/llm_backend/app/memory_system/__init__.py
deepseek_agent/llm_backend/app/memory_system/config.py
deepseek_agent/llm_backend/app/memory_system/paths.py
deepseek_agent/llm_backend/app/memory_system/memory_types.py
deepseek_agent/llm_backend/app/memory_system/schemas.py
deepseek_agent/llm_backend/app/memory_system/frontmatter.py
deepseek_agent/llm_backend/app/test/test_memory_types.py
deepseek_agent/llm_backend/app/test/test_memory_paths.py
deepseek_agent/llm_backend/app/test/test_frontmatter.py
```

### 本阶段不修改文件

```text
deepseek_agent/llm_backend/main.py
deepseek_agent/llm_backend/app/lg_agent/context_manager.py
deepseek_agent/llm_backend/app/lg_agent/lg_builder.py
deepseek_agent/llm_backend/app/models/user_memory.py
```

原因：

```text
Phase 1 只建立基础模块，不接主流程。
避免未完成的 memory 系统影响现有客服请求。
```

## 3.4 config.py 设计

### 文件职责

`config.py` 负责读取 memory 相关配置，不负责创建目录、不负责业务判断。

### 推荐配置项

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MemorySystemConfig:
    enabled: bool
    memory_root: Path
    recall_enabled: bool
    transcript_enabled: bool
    session_memory_enabled: bool
    extract_memories_enabled: bool
    auto_dream_enabled: bool
    debug_trace_enabled: bool
    default_tenant_id: str
    max_memory_files: int
    frontmatter_max_lines: int
    max_selected_memories: int
    max_memory_body_chars: int
```

### 默认值

```text
enabled = false
memory_root = deepseek_agent/runtime/memory
recall_enabled = false
transcript_enabled = false
session_memory_enabled = false
extract_memories_enabled = false
auto_dream_enabled = false
debug_trace_enabled = true
default_tenant_id = "default"
max_memory_files = 200
frontmatter_max_lines = 30
max_selected_memories = 5
max_memory_body_chars = 6000
```

### 环境变量

```text
AI_KEFU_MEMORY_ENABLED
AI_KEFU_MEMORY_ROOT
AI_KEFU_MEMORY_RECALL_ENABLED
AI_KEFU_MEMORY_TRANSCRIPT_ENABLED
AI_KEFU_SESSION_MEMORY_ENABLED
AI_KEFU_EXTRACT_MEMORIES_ENABLED
AI_KEFU_AUTO_DREAM_ENABLED
AI_KEFU_MEMORY_DEBUG_TRACE_ENABLED
AI_KEFU_MEMORY_DEFAULT_TENANT_ID
AI_KEFU_MEMORY_MAX_FILES
AI_KEFU_MEMORY_FRONTMATTER_MAX_LINES
AI_KEFU_MEMORY_MAX_SELECTED
AI_KEFU_MEMORY_MAX_BODY_CHARS
```

### 关键函数

```python
def load_memory_config() -> MemorySystemConfig:
    """从 settings 或环境变量读取配置，并做类型校验。"""
```

设计要求：

```text
布尔值只接受 true/false/1/0/yes/no/on/off
数字必须为正整数
memory_root 转成 Path，但不在这里 mkdir
非法配置直接抛 ValueError
不要静默兜底到默认值
```

### 为什么不静默兜底

项目 AGENTS 规则要求不要用兜底函数掩盖错误。memory 系统如果配置错了还继续运行，会导致文件写到错误位置或 feature flag 行为不可解释。因此配置值非法时应明确报错。

## 3.5 memory_types.py 设计

### 文件职责

`memory_types.py` 定义客服场景可用的 memory 类型、类型解析、类型描述、保存边界和目录映射。

### 核心类型

```python
from enum import StrEnum


class MemoryType(StrEnum):
    CUSTOMER = "customer"
    FEEDBACK = "feedback"
    BUSINESS_RULE = "business_rule"
    REFERENCE = "reference"
```

严禁出现：

```python
PROJECT = "project"
```

### 类型说明结构

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryTypeSpec:
    type: MemoryType
    directory: str
    description: str
    when_to_save: str
    how_to_use: str
    body_structure: str
    not_allowed: tuple[str, ...]
```

### 类型规格

```python
MEMORY_TYPE_SPECS: dict[MemoryType, MemoryTypeSpec] = {
    MemoryType.CUSTOMER: MemoryTypeSpec(
        type=MemoryType.CUSTOMER,
        directory="customer",
        description="客户长期偏好、稳定需求约束、服务沟通偏好。",
        when_to_save="客户明确表达稳定偏好，或多次表现出一致服务约束。",
        how_to_use="调整客服回答方式，但不能替代实时订单、库存、价格查询。",
        body_structure="Lead with the preference, then Why and How to apply.",
        not_allowed=(
            "单次临时购买意图",
            "实时订单状态",
            "实时库存状态",
            "敏感身份信息",
        ),
    ),
    ...
}
```

### business_rule 约束

`business_rule` 的 `not_allowed` 必须包含：

```text
从源码推断出的业务规则
API 实现细节
git history
临时测试数据
未经确认的客服猜测
单个客户的个人偏好
```

`when_to_save` 必须强调只允许来自：

```text
客户明确陈述
运营或客服主管确认
售后政策
商品资料
知识库
权威业务系统
```

### 关键函数

```python
def parse_memory_type(raw: object) -> MemoryType | None:
    """解析 frontmatter 的 type。未知或缺失返回 None，供 scan 降级处理。"""


def require_memory_type(raw: object) -> MemoryType:
    """写入 memory 时使用。未知或缺失直接抛 ValueError。"""


def get_memory_type_spec(memory_type: MemoryType) -> MemoryTypeSpec:
    """返回类型说明，用于 prompt 和校验。"""


def memory_type_directory(memory_type: MemoryType) -> str:
    """返回该类型对应目录名。"""


def list_memory_types_for_prompt() -> str:
    """生成 extract prompt 可直接嵌入的类型说明。"""
```

### 解析策略

Claude-Code 对旧文件较宽容：frontmatter 里未知 type 会返回 `undefined`，扫描不中断。`ai_kefu` 也建议采用双函数策略：

```text
scan 阶段:
  parse_memory_type() 返回 None，文件仍可进入 manifest，但标记 type=None 或 invalid。

write 阶段:
  require_memory_type() 必须严格抛错，避免写入非法类型。
```

这样既兼容旧文件，又保证新写入质量。

## 3.6 schemas.py 设计

### 文件职责

`schemas.py` 定义 memory 系统跨模块传递的数据结构。它不读写文件，不调用 LLM。

### MemoryScope

```python
class MemoryScope(StrEnum):
    CUSTOMER = "customer"
    BUSINESS = "business"
```

含义：

```text
CUSTOMER:
  某个客户私有或长期偏好级 memory。

BUSINESS:
  某个租户或业务域共享 memory。
```

### MemoryIdentity

```python
@dataclass(frozen=True)
class MemoryIdentity:
    customer_id: str
    tenant_id: str
    conversation_id: str | None
    user_id: int | None
```

职责：

```text
把 /api/langgraph/query 中的 user_id/conversation_id 映射为 memory 路径所需身份。
```

MVP 映射：

```text
customer_id = str(user_id)
tenant_id = config.default_tenant_id
conversation_id = str(conversation_id) if present
user_id = original int
```

需要先确认：

```text
正式 customer_id 是否等于 user_id
tenant_id 是否来自请求、配置还是数据库
```

### MemoryFrontmatter

```python
@dataclass(frozen=True)
class MemoryFrontmatter:
    type: MemoryType
    description: str
    created_at: str
    updated_at: str
    confidence: float
    source_conversation_id: str | None = None
    source_request_id: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    expires_at: str | None = None
    tags: tuple[str, ...] = ()
```

字段说明：

```text
type:
  customer/feedback/business_rule/reference。

description:
  一句话描述，用于 manifest 和 selector。

created_at:
  首次创建时间，ISO 8601。

updated_at:
  最近更新时间，ISO 8601。

confidence:
  0 到 1，表示抽取置信度。

source_conversation_id:
  原始对话来源。

source_request_id:
  原始请求来源。

source_type:
  customer_statement/operator_confirmed/official_doc/tool_verified/policy_import/manual_review 等。

source_ref:
  来源引用，例如 doc:after-sales-v3、operator:123、tool:policy_api。

effective_from:
  规则或记忆生效开始日期。business_rule 必填。

effective_to:
  规则或记忆生效结束日期。长期有效时可为空。business_rule 字段必须存在但可为 None。

verified_by:
  规则确认人、确认系统或确认文档。business_rule 必填。

verified_at:
  规则确认时间。business_rule 必填。

expires_at:
  可选。适合促销、活动、阶段性政策。

tags:
  可选短标签，便于后续检索。
```

### MemoryHeader

```python
@dataclass(frozen=True)
class MemoryHeader:
    relative_path: str
    absolute_path: Path
    mtime_ms: float
    description: str | None
    type: MemoryType | None
    scope: MemoryScope
    parse_error: str | None = None
```

用途：

```text
memory_scan.py 返回。
find_relevant_memories.py 使用。
extract_memories.py 写入前检查重复。
auto_dream.py 整理索引。
```

### SelectedMemory

```python
@dataclass(frozen=True)
class SelectedMemory:
    header: MemoryHeader
    content: str
    truncated: bool
```

用途：

```text
render.py 将其渲染进 prompt_context。
debug_trace 只返回 header.relative_path，不返回完整 content。
```

### MemoryTrace

```python
@dataclass
class MemoryTrace:
    enabled: bool = False
    recall_enabled: bool = False
    selected_memory_count: int = 0
    selected_memory_paths: list[str] = field(default_factory=list)
    session_memory_loaded: bool = False
    transcript_status: str | None = None
    extract_status: str | None = None
    auto_dream_status: str | None = None
    skipped_reasons: list[str] = field(default_factory=list)
```

第一版也可以用 dict，但建议先定义 dataclass，避免 trace 字段散落在 `main.py` 和 `context_manager.py`。

## 3.7 paths.py 设计

### 文件职责

`paths.py` 负责根据配置和身份生成 memory 运行时路径，并做路径合法性校验。

它不解析 frontmatter，不读取 memory 内容。

### Runtime 目录

```text
{memory_root}/
  customers/{customer_id}/memory/
    MEMORY.md
    customer/
    feedback/
    reference/
  business/{tenant_id}/memory/
    MEMORY.md
    business_rule/
    feedback/
    reference/
  sessions/{conversation_id}/summary.md
  transcripts/{conversation_id}.jsonl
  state/
    extract_cursor.json
    auto_dream.lock
    auto_dream_state.json
    surfaced_memories.json
```

### MemoryPaths

```python
@dataclass(frozen=True)
class MemoryPaths:
    root: Path
    customer_memory_dir: Path
    business_memory_dir: Path
    session_summary_path: Path | None
    transcript_path: Path | None
    state_dir: Path
    extract_cursor_path: Path
    auto_dream_lock_path: Path
    auto_dream_state_path: Path
    surfaced_memories_path: Path
```

### 关键函数

```python
def build_memory_identity(
    *,
    user_id: int,
    conversation_id: str | int | None,
    tenant_id: str | None,
    config: MemorySystemConfig,
) -> MemoryIdentity:
    """把请求字段转换为 memory identity。MVP 中 customer_id=str(user_id)。"""


def resolve_memory_paths(
    *,
    identity: MemoryIdentity,
    config: MemorySystemConfig,
) -> MemoryPaths:
    """根据 identity 和 config 返回所有 runtime 路径。"""


def ensure_memory_directories(paths: MemoryPaths) -> None:
    """创建必要目录和空 MEMORY.md。只创建 memory root 内目录。"""


def memory_file_path(
    *,
    base_memory_dir: Path,
    memory_type: MemoryType,
    filename: str,
) -> Path:
    """根据类型和文件名生成 memory 文件路径。"""


def assert_under_memory_root(path: Path, root: Path) -> Path:
    """校验 path resolve 后位于 root 下，否则抛 PermissionError。"""
```

### 路径安全要求

必须使用：

```python
resolved = path.resolve()
root = memory_root.resolve()
resolved.relative_to(root)
```

不要只用：

```python
str(resolved).startswith(str(root))
```

原因：

```text
字符串前缀在 Windows 大小写、路径分隔符、符号链接和 .. 归一化上容易出错。
```

Python 版本支持时推荐：

```python
def assert_under_memory_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if not resolved.is_relative_to(resolved_root):
        raise PermissionError(f"path outside memory root: {resolved}")
    return resolved
```

如果需要兼容没有 `Path.is_relative_to()` 的版本：

```python
def assert_under_memory_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PermissionError(f"path outside memory root: {resolved}") from exc
    return resolved
```

也可以使用：

```python
os.path.commonpath([str(resolved), str(resolved_root)]) == str(resolved_root)
```

### 文件名规范

第一版建议只允许：

```text
a-z
0-9
-
_
.md
```

函数：

```python
def normalize_memory_filename(title: str) -> str:
    """把标题转成安全文件名。无法转换时抛 ValueError。"""
```

注意：

```text
不要用随机兜底文件名掩盖标题为空的问题。
如果 LLM 生成非法 filename，应拒绝并记录错误。
```

## 3.8 frontmatter.py 设计

### 文件职责

`frontmatter.py` 负责 Markdown frontmatter 的解析和序列化。

不建议第一版依赖复杂第三方库。可以实现严格的 YAML-like 子集，或使用项目已有依赖中的 YAML 库。如果使用 PyYAML，需要先确认依赖是否存在。

### 推荐策略

MVP 推荐支持简单字段：

```text
string
number
list[str]
null
```

frontmatter 示例：

```md
---
type: feedback
description: 客户希望库存回答简洁，不重复解释字段
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.9
source_conversation_id: "123"
source_request_id: "req-xxx"
source_type: customer_statement
tags:
  - inventory
  - answer_style
---

客户在库存咨询中希望回答简洁。

Why:
客户明确表示只想知道是否有货和预计发货时间。

How to apply:
当该客户继续咨询库存或发货问题时，直接给出结论、数量、时效和必要提醒。
```

### 数据结构

```python
@dataclass(frozen=True)
class ParsedMarkdownMemory:
    frontmatter: dict[str, Any]
    body: str
    has_frontmatter: bool
```

### 关键函数

```python
def parse_frontmatter_markdown(content: str) -> ParsedMarkdownMemory:
    """解析 Markdown frontmatter。没有 frontmatter 时 has_frontmatter=False。"""


def parse_memory_frontmatter(raw: dict[str, Any]) -> MemoryFrontmatter:
    """把 dict 校验并转换为 MemoryFrontmatter。写入和读取严格校验用。"""


def dump_frontmatter_markdown(frontmatter: MemoryFrontmatter, body: str) -> str:
    """序列化为带 frontmatter 的 Markdown。"""


def read_frontmatter_prefix(path: Path, max_lines: int) -> str:
    """只读取前 max_lines 行，用于 memory_scan。"""
```

### 校验规则

```text
type 必须存在且合法
description 必须为非空字符串
created_at/updated_at 必须为 ISO-like 字符串
confidence 必须在 0 到 1
source_conversation_id/source_request_id 可为空
source_type 可为空，但 business_rule 必须为 operator_confirmed/official_doc/tool_verified/policy_import/manual_review 之一
business_rule 必须包含 effective_from、effective_to、verified_by、verified_at 字段
普通 customer_statement 不能写入 business_rule
tags 必须是字符串列表
body 可以为空，但写入长期 memory 时不建议为空
```

### Source of truth 校验

Phase 1 需要把长期 memory 的事实源边界写进 schema 注释和测试：

```text
Markdown memory files 是长期 memory source of truth。
MySQL conversation_context_items 是运行期上下文。
MySQL user_memory_items 在 MVP 中只读兼容旧偏好，后续只做索引/审计/UI 加速。
```

这不是代码运行逻辑，但要写入文档和测试命名，防止后续开发误做双主写入。

### 读取编码

所有读写 Markdown 必须显式使用：

```python
encoding="utf-8"
```

不要依赖 PowerShell 或系统默认编码。

## 3.9 __init__.py 设计

### 文件职责

`__init__.py` 只暴露稳定 API，不放业务逻辑。

推荐：

```python
from .config import MemorySystemConfig, load_memory_config
from .memory_types import MemoryType
from .paths import MemoryPaths, resolve_memory_paths
from .schemas import MemoryIdentity, MemoryFrontmatter, MemoryHeader
```

不要在 `__init__.py` 中执行：

```text
读取配置
创建目录
初始化 LLM
导入 context_manager.py
```

原因：

```text
避免循环 import。
避免测试导入时产生副作用。
```

## 3.10 单元测试设计

### test_memory_types.py

测试点：

```text
MemoryType 只有 customer/feedback/business_rule/reference
parse_memory_type("customer") 返回 MemoryType.CUSTOMER
parse_memory_type("project") 返回 None
require_memory_type("project") 抛 ValueError
business_rule spec 明确禁止源码/API/git 推断
list_memory_types_for_prompt() 不包含 project
```

示例断言：

```python
def test_memory_types_do_not_include_project():
    assert "project" not in {item.value for item in MemoryType}
```

### test_memory_paths.py

测试点：

```text
resolve_memory_paths 生成 customers/{customer_id}/memory
resolve_memory_paths 生成 business/{tenant_id}/memory
conversation_id 缺失时 session_summary_path/transcript_path 可为 None
ensure_memory_directories 创建 MEMORY.md 和类型目录
assert_under_memory_root 允许 root 内路径
assert_under_memory_root 拒绝 ../outside.md
normalize_memory_filename 拒绝空标题和路径穿越
```

### test_frontmatter.py

测试点：

```text
parse_frontmatter_markdown 可解析合法 frontmatter
没有 frontmatter 时 has_frontmatter=False
parse_memory_frontmatter 校验 type
parse_memory_frontmatter 校验 confidence 范围
parse_memory_frontmatter 拒绝 source_type=customer_statement 的 business_rule
parse_memory_frontmatter 要求 business_rule 包含 effective_from/effective_to/verified_by/verified_at
dump_frontmatter_markdown 输出以 --- 开头
read_frontmatter_prefix 只读取 max_lines
UTF-8 中文内容可读写
```

## 3.11 与现有 ai_kefu 代码的接入点

本阶段不接入主链路，但要为后续接入预留稳定接口。

后续 `context_manager.py` 会用：

```python
config = load_memory_config()
identity = build_memory_identity(
    user_id=user_id,
    conversation_id=conversation_id,
    tenant_id=None,
    config=config,
)
paths = resolve_memory_paths(identity=identity, config=config)
```

后续 `main.py` 会用：

```python
paths.transcript_path
paths.session_summary_path
paths.extract_cursor_path
paths.auto_dream_lock_path
```

后续 `permissions.py` 会用：

```python
assert_under_memory_root(target_path, paths.root)
```

## 3.12 实现步骤

### Step 1: 创建包和空导出

创建：

```text
app/memory_system/__init__.py
```

只放稳定导出，避免副作用。

### Step 2: 实现 MemoryType

创建：

```text
app/memory_system/memory_types.py
```

先写：

```text
MemoryType
MemoryTypeSpec
MEMORY_TYPE_SPECS
parse_memory_type
require_memory_type
```

立即写测试，防止后续误引入 `project`。

### Step 3: 实现 config

创建：

```text
app/memory_system/config.py
```

先不接 `settings` 也可以，只读 `os.environ`。如果要接 `app.core.config.settings`，需要确认不会造成循环 import。

推荐先直接读环境变量，降低耦合。

### Step 4: 实现 schemas

创建：

```text
app/memory_system/schemas.py
```

写 dataclass，保持纯数据结构。

### Step 5: 实现 paths

创建：

```text
app/memory_system/paths.py
```

实现目录解析、创建和路径安全校验。

### Step 6: 实现 frontmatter

创建：

```text
app/memory_system/frontmatter.py
```

优先支持足够用于 memory 文件的 YAML-like 格式。

如果使用 PyYAML，先执行：

```text
deepseek_agent/.venv/python.exe -c "import yaml; print(yaml.__version__)"
```

如果不存在，不要为了 Phase 1 引入依赖，先实现受限 parser 或用标准库简单解析。

### Step 7: 写单元测试

创建：

```text
app/test/test_memory_types.py
app/test/test_memory_paths.py
app/test/test_frontmatter.py
```

测试应使用 `tmp_path`，不要写真实 runtime 目录。

## 3.13 验证方式

### 单元测试命令

在仓库根目录执行：

```text
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_types.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_paths.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_frontmatter.py
```

### 手动验证

用临时目录验证：

```python
from pathlib import Path
from app.memory_system.config import MemorySystemConfig
from app.memory_system.paths import build_memory_identity, resolve_memory_paths, ensure_memory_directories

config = MemorySystemConfig(
    enabled=True,
    memory_root=Path("tmp/memory-test"),
    recall_enabled=False,
    transcript_enabled=False,
    session_memory_enabled=False,
    extract_memories_enabled=False,
    auto_dream_enabled=False,
    debug_trace_enabled=True,
    default_tenant_id="default",
    max_memory_files=200,
    frontmatter_max_lines=30,
    max_selected_memories=5,
    max_memory_body_chars=6000,
)
identity = build_memory_identity(user_id=1, conversation_id="abc", tenant_id=None, config=config)
paths = resolve_memory_paths(identity=identity, config=config)
ensure_memory_directories(paths)
```

应生成：

```text
tmp/memory-test/customers/1/memory/MEMORY.md
tmp/memory-test/customers/1/memory/customer/
tmp/memory-test/customers/1/memory/feedback/
tmp/memory-test/customers/1/memory/reference/
tmp/memory-test/business/default/memory/MEMORY.md
tmp/memory-test/business/default/memory/business_rule/
tmp/memory-test/business/default/memory/feedback/
tmp/memory-test/business/default/memory/reference/
tmp/memory-test/sessions/abc/
tmp/memory-test/transcripts/
tmp/memory-test/state/
```

## 3.14 完成标准

Phase 1 完成必须满足：

```text
memory_system 包可被导入
MemoryType 不包含 project
业务类型说明符合客服场景
config 非法值明确报错
paths 可生成 customer/business/session/transcript/state 路径
ensure_memory_directories 可在 tmp_path 下创建目录
frontmatter 可读写中文 Markdown
business_rule frontmatter 可信来源字段校验通过
source_type=customer_statement 写 business_rule 会失败
所有 Phase 1 单测通过
没有修改 main.py/context_manager.py/lg_builder.py
```

## 3.15 风险和暂缓项

### 风险 1: 身份模型过早固化

MVP 使用 `customer_id=str(user_id)`，但真实系统可能存在独立客户 ID。为降低风险，路径层必须通过 `MemoryIdentity` 抽象，不要在各模块里直接拼 `user_id`。

### 风险 2: 手写 frontmatter parser 能力有限

如果不用 YAML 库，手写 parser 只能支持受限格式。MVP 可接受，但必须在文档中说明格式限制，避免开发者写复杂 YAML。

### 风险 3: 文件目录权限在 Windows 上容易被忽视

Windows 路径大小写、反斜杠、盘符和符号链接会让简单字符串校验不可靠。Phase 1 的 `assert_under_memory_root()` 必须用 `Path.resolve()` 和 `relative_to()`。

### 可暂缓内容

```text
数据库索引表
前端 memory 管理页面
memory 文件迁移工具
向量检索字段
多租户正式 identity 来源
复杂 YAML 语法
```
