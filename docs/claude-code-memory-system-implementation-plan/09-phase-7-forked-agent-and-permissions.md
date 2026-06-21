# 9. Phase 7: ForkedAgent 和权限边界

本文是实施计划第 9 个文件，对应 Phase 7。目标是把 SessionMemory、ExtractMemories、AutoDream 的后台 LLM 工作放入受限 forked agent，并强制工具权限边界。

## 9.1 阶段目标

Phase 7 要完成：

```text
1. 新增 forked_agent.py
2. 新增 permissions.py
3. 新增 tools.py
4. 定义 ToolPolicy
5. 实现 read/grep/glob/write/edit 文件工具
6. 写操作只能发生在 memory_root 下
7. 禁止业务工具、数据库写、shell 写操作
8. 后台任务默认 skip_transcript=True
9. max_turns 生效
10. 编写权限单元测试
```

## 9.2 为什么先做

MVP 可以直接服务端写文件，但自动长期写入上线前必须有权限边界。否则后台 Agent 可能：

```text
误改源码
误写业务数据库
调用下单/支付/库存修改工具
把内部 prompt 写入主 transcript
无限工具循环
```

Claude-Code 的核心价值之一就是 forked agent 与工具权限隔离，这一阶段是从 MVP 走向可上线的关键。

## 9.3 文件变更

新增：

```text
deepseek_agent/llm_backend/app/memory_system/forked_agent.py
deepseek_agent/llm_backend/app/memory_system/permissions.py
deepseek_agent/llm_backend/app/memory_system/tools.py
deepseek_agent/llm_backend/app/test/test_memory_permissions.py
deepseek_agent/llm_backend/app/test/test_forked_agent.py
```

可能修改：

```text
session_memory.py
extract_memories.py
auto_dream.py
```

用于把直接 LLM 调用替换为 `run_forked_agent()`。

## 9.4 核心数据结构

### ToolDecision

```python
@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str
```

### ToolPolicy

```python
@dataclass(frozen=True)
class ToolPolicy:
    memory_root: Path
    allowed_read_roots: tuple[Path, ...]
    allowed_write_root: Path
    allow_shell: bool = False
    allow_business_tools: bool = False
```

### ForkedAgentRequest

```python
@dataclass(frozen=True)
class ForkedAgentRequest:
    prompt_messages: list[dict[str, str]]
    query_source: str
    fork_label: str
    tool_policy: ToolPolicy
    skip_transcript: bool = True
    max_turns: int = 5
```

### ForkedAgentResult

```python
@dataclass(frozen=True)
class ForkedAgentResult:
    status: str
    content: str
    tool_calls: int
    denied_tool_calls: int
    elapsed_ms: int
    error_type: str | None = None
```

## 9.5 permissions.py 设计

### create_auto_mem_tool_policy()

```python
def create_auto_mem_tool_policy(
    *,
    memory_root: Path,
    transcript_root: Path,
) -> ToolPolicy:
    ...
```

允许：

```text
read_file: memory_root、transcript_root
grep: memory_root、transcript_root
glob: memory_root、transcript_root
write_file: memory_root
edit_file: memory_root
```

禁止：

```text
业务数据库写
业务工具调用
任意 shell
memory_root 外写
读取 .env、密钥、数据库文件
```

### assert_path_allowed()

```python
def assert_path_allowed(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PermissionDenied(f"path outside allowed root: {resolved}") from exc
    return resolved
```

Python 支持时可用：

```python
resolved.is_relative_to(resolved_root)
```

不要用：

```python
str(resolved).startswith(str(resolved_root))
```

## 9.6 tools.py 设计

工具函数：

```python
async def read_file(path: Path, policy: ToolPolicy) -> str: ...
async def grep(pattern: str, root: Path, policy: ToolPolicy) -> list[str]: ...
async def glob(pattern: str, root: Path, policy: ToolPolicy) -> list[str]: ...
async def write_file(path: Path, content: str, policy: ToolPolicy) -> None: ...
async def edit_file(path: Path, old: str, new: str, policy: ToolPolicy) -> None: ...
```

规则：

```text
所有读写显式 UTF-8
write/edit 前必须 assert_path_allowed(path, policy.allowed_write_root)
read/grep/glob 只能在 allowed_read_roots 中
edit_file 找不到 old 时抛 ValueError，不做静默追加
```

## 9.7 forked_agent.py 设计

### run_forked_agent()

```python
async def run_forked_agent(
    request: ForkedAgentRequest,
) -> ForkedAgentResult:
    ...
```

MVP 实现策略：

```text
第一版可以只支持单轮 LLM JSON/Markdown 输出。
工具循环可以先限制为 0 或 1 轮。
保留 max_turns 参数和 denied_tool_calls 统计。
```

增强版：

```text
支持多 turn 工具调用
每次工具调用经过 ToolPolicy
达到 max_turns 立即停止
skip_transcript=True 时不创建 transcript event
```

## 9.8 接入点

替换：

```text
session_memory.py:
  direct LLM -> run_forked_agent(query_source="session_memory")

extract_memories.py:
  direct LLM -> run_forked_agent(query_source="extract_memories", max_turns=5)

auto_dream.py:
  direct LLM -> run_forked_agent(query_source="auto_dream")
```

## 9.9 验证方式

单元测试：

```text
test_assert_path_allowed_accepts_memory_root_child
test_assert_path_allowed_rejects_sibling_prefix
test_assert_path_allowed_rejects_dotdot
test_write_file_denied_outside_memory_root
test_read_file_denied_sensitive_env
test_tool_denied_logs_reason
test_run_forked_agent_respects_skip_transcript
test_run_forked_agent_stops_at_max_turns
```

完成标准：

```text
permissions.py/forked_agent.py/tools.py 存在
memory_root 外写入被拒绝
相似前缀目录不会误判为 root 内
memory_tool_denied 日志可观察
后台任务不写主 transcript
单测通过
```

## 9.10 风险和暂缓项

风险：

```text
过早实现完整 tool loop 会复杂。
权限过宽风险高，过窄会影响 AutoDream 整理能力。
Windows 路径和符号链接必须重点测。
```

暂缓：

```text
shell 工具
业务系统只读工具
MCP 工具
复杂 diff edit
prompt cache
```

