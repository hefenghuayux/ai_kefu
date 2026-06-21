# 1. 当前前提和设计边界

本文是 `ai_kefu` 迁移 Claude-Code 风格记忆系统的分步开发计划第 1 个文件。它只定义前提、边界和必须先确认的事实，不包含代码实现。

本计划基于当前设计文档：

```text
E:/workspacce/AI/ai_kefu/docs/claude-code-memory-system-design.md
```

也参考 Claude-Code 记忆系统的核心实现：

```text
E:/workspacce/AI/Claude-Code/src/memdir/memoryTypes.ts
E:/workspacce/AI/Claude-Code/src/memdir/memoryScan.ts
E:/workspacce/AI/Claude-Code/src/memdir/findRelevantMemories.ts
E:/workspacce/AI/Claude-Code/src/services/SessionMemory/
E:/workspacce/AI/Claude-Code/src/services/extractMemories/
E:/workspacce/AI/Claude-Code/src/services/autoDream/
E:/workspacce/AI/Claude-Code/src/utils/forkedAgent.ts
```

## 1.1 核心目标

### 阶段目标

为 `ai_kefu` 建立一套客服 Agent 使用的应用层记忆系统，使系统能够在不训练模型权重的前提下，完成以下闭环：

```text
请求前召回相关记忆
-> 主 Agent 完成客服业务回答
-> 记录 transcript
-> 后台更新 session memory
-> 后台抽取长期 memory
-> 周期整理、合并、删除过期记忆
-> 下一次请求继续召回
```

这个目标不是把所有聊天历史塞进 prompt，也不是把当前 DB 里的 `UserMemoryItem` 简单改名，而是尽量参考 Claude-Code 的架构骨架：

```text
Markdown memory files
frontmatter
MEMORY.md manifest/index
memory_scan
findRelevantMemories
SessionMemory
ExtractMemories
ForkedAgent
Tool permission boundary
AutoDream
transcripts JSONL
debug trace
```

### 为什么先定义边界

记忆系统会持续影响未来请求。如果边界不先定清楚，后续实现很容易出现三个问题：

1. 把客服场景不该记的开发信息写进长期记忆。
2. 后台记忆 Agent 越权调用业务工具或修改源码。
3. 新系统和现有 `context_manager.py` 的 DB 型 session note 互相覆盖，导致行为不可解释。

因此，第一步必须明确哪些机制要保留，哪些机制要改写，哪些东西绝对不能写入 memory。

## 1.2 ai_kefu 当前已确认的接入点

### 真实主入口

当前主聊天链路应接入：

```text
deepseek_agent/llm_backend/main.py
POST /api/langgraph/query
```

当前代码中 `/api/langgraph/query` 的关键位置：

```text
deepseek_agent/llm_backend/main.py
  langgraph_query()
  load_context_bundle(...)
  graph.ainvoke(...)
  ConversationService.save_message(...)
  save_tool_evidence_items(...)
  _handle_session_note_update(...)
```

现有 `/api/chat` 是兼容或旧路径，不作为新记忆系统的主接入点。除非后续明确要求兼容，否则第一版只保证 `/api/langgraph/query`。

### 查询前上下文入口

当前代码已经在请求执行前调用：

```python
context_bundle = await load_context_bundle(
    user_id=user_id,
    conversation_id=conversation_id,
    query=query,
)
```

对应文件：

```text
deepseek_agent/llm_backend/app/lg_agent/context_manager.py
```

当前 `load_context_bundle()` 会加载：

```text
recent_messages
session_note
current_goal
confirmed_facts
tool_evidence
failed_paths
user_preferences
prompt_context
history_records
```

新系统第一版不应删除这些已有字段，而是在 `context_bundle` 中增加文件型 memory 的字段，例如：

```python
context_bundle["file_session_memory"] = ...
context_bundle["selected_memories"] = ...
context_bundle["memory_trace"] = ...
context_bundle["prompt_context"] = format_context_bundle(context_bundle)
```

### Prompt 注入入口

当前 `prompt_context` 注入点在：

```text
deepseek_agent/llm_backend/app/lg_agent/lg_builder.py
```

关键函数：

```python
def _state_messages_with_context(state: AgentState) -> list[Any]:
    context_bundle = getattr(state, "context_bundle", {}) or {}
    context_text = context_bundle.get("prompt_context")
    if context_text:
        return [{"role": "system", "content": context_text}] + state.messages
    return state.messages
```

这意味着新记忆系统最小可用接入方式是：

1. 在 `load_context_bundle()` 内或其附近加载 memory。
2. 把 memory 渲染进 `prompt_context`。
3. 不直接改 LangGraph 节点内部业务逻辑。

### 请求后更新入口

当前请求完成后已经调用：

```python
await _handle_session_note_update(...)
```

当 `debug_trace=False` 时，它会调用：

```python
maybe_schedule_session_note_update(...)
```

当 `debug_trace=True` 时，它会同步调用：

```python
update_session_note_for_trace(...)
```

新系统后续应在这个请求后阶段追加：

```text
append_transcript
schedule_session_memory_update
schedule_extract_memories
maybe_auto_dream
```

第一版要避免直接替换旧 `_handle_session_note_update()`，否则会影响已有 debug trace 和 DB 型上下文。

## 1.3 Claude-Code 机制中必须保留的部分

### 文件型长期记忆

保留 Markdown 文件作为长期 memory 主存储：

```text
deepseek_agent/runtime/memory/
```

原因：

1. Markdown 适合保存带原因、边界、用法的经验。
2. frontmatter 可以快速扫描。
3. 文件便于人工审查和回滚。
4. 与 Claude-Code 的 `MEMORY.md`、`memory_scan`、`extractMemories` 机制一致。

数据库可以后置作为索引、审计、管理后台加速，但不作为第一版 memory 主源。

### MEMORY.md 只做索引

`MEMORY.md` 不存正文，只存短索引：

```md
- [库存回答偏好](feedback/inventory_answer_style.md) - 客户希望库存回答简洁，不重复解释字段
- [智能门锁售后规则](business_rule/smart_lock_after_sales.md) - 智能门锁安装后 7 天内支持质量问题换货
```

原因：

1. `MEMORY.md` 变成主索引后，召回和人工审查都更快。
2. 正文分散在独立文件里，便于更新、合并和删除。
3. 避免一个大文件无限膨胀。

### frontmatter 扫描

参考 Claude-Code：

```text
MAX_MEMORY_FILES = 200
FRONTMATTER_MAX_LINES = 30
```

第一版也采用：

```python
MAX_MEMORY_FILES = 200
FRONTMATTER_MAX_LINES = 30
```

扫描时只读前 30 行 frontmatter，不读取全文。

### 查询前相关记忆选择

保留 `findRelevantMemories` 的设计：

```text
scan memory headers
-> format manifest
-> side LLM query 选择最多 5 条
-> 读取选中文件正文
-> 注入 prompt_context
```

输出 schema 保留：

```json
{
  "selected_memories": [
    "feedback/inventory_answer_style.md"
  ]
}
```

第一版可以增加确定性关键词预筛，但最终接口和 trace 字段要向 Claude-Code 靠拢。

### 后台 forked agent

长期目标要保留 `ForkedAgent` 语义：

```text
主对话不被记忆更新污染
后台 Agent 有独立 prompt
后台 Agent 有独立工具权限
后台 Agent 默认 skip_transcript
后台 Agent 有 max_turns
```

第一版可以先用服务端函数直接写文件实现 MVP，但 Phase 7 必须补上 forked agent 和权限边界，否则不能认为完成 Claude-Code 风格迁移。

### AutoDream 周期整理

保留 Claude-Code 默认阈值：

```text
minHours = 24
minSessions = 5
```

第一版 AutoDream 不自动每轮运行，可以先做手动命令：

```text
python -m app.memory_system.auto_dream --force
```

但目录、状态文件、lock 文件要在早期设计中预留。

## 1.4 客服场景下必须改写的部分

### 禁止引入 project memory type

Claude-Code 原始类型是：

```text
user
feedback
project
reference
```

`ai_kefu` 是客服 Agent，不应该把项目代码、接口入口、开发计划、git 信息、源码结构保存为业务记忆。因此不能保留 `project` 类型。

`ai_kefu` 的长期 memory 类型固定为：

```text
customer
feedback
business_rule
reference
```

含义：

```text
customer:
  客户长期偏好、稳定需求约束、服务沟通偏好。

feedback:
  客户或运营人员对客服 Agent 回答方式、流程、语气、证据使用方式的纠正或确认。

business_rule:
  客服业务规则、售后政策、商品服务约束、人工转接规则。
  必须带可信 source_type 和有效期/验证字段。

reference:
  外部业务系统、知识库、售后文档、商品资料、运营资料入口。
```

### business_rule 的来源必须受限

`business_rule` 只能来自可信来源：

```text
operator_confirmed       运营人员或客服主管确认
official_doc             售后政策、商品资料、知识库、合同条款、官方公告
tool_verified            权威业务系统返回并明确表示为长期规则
policy_import            后台政策导入
manual_review            人工审核后确认
```

不能来自：

```text
普通客户的一句话或猜测
项目源码
API 实现
数据库表结构
git history
开发者经验推断
临时测试数据
```

例如：

```text
用户说“这个商品应该能七天退”
  不能保存为 business_rule。
  可以保存为 customer 当前认知或 feedback 信号，或者触发后续向官方政策/运营确认。

运营确认“智能门锁安装后 7 天内质量问题支持换货”
  可以保存为 business_rule，并设置 source_type=operator_confirmed。
```

`business_rule` frontmatter 必须包含：

```yaml
source_type: operator_confirmed
effective_from: "2026-06-21"
effective_to: null
verified_by: "operator:123"
verified_at: "2026-06-21T10:00:00+08:00"
```

原因是源码只能说明系统如何实现，不一定说明客服政策真实有效。把源码实现推断为业务规则，会让 Agent 在客户面前输出未经确认的政策。

### 记忆不是订单事实缓存

订单状态、库存、价格、物流、售后进度都必须实时查业务系统，不要把单次工具查询结果作为长期 memory：

```text
错误：
  客户 1001 的订单 888 当前状态是待发货。

正确：
  客户偏好：该客户询问订单时希望直接给出物流节点和预计发货时间。
  业务规则：智能门锁类商品安装后 7 天内质量问题支持换货。
```

订单、库存、价格、物流、售后进度属于高频变化事实，应通过业务工具实时查询，不应进入长期 memory。

实现时必须把这条边界写成校验规则：

```text
ExtractMemories 输出中如果出现 order_status、inventory_count、price、shipment_status、after_sales_progress 等实时事实类型，应拒绝写入长期 memory。
FindRelevantMemories 注入 prompt 时也必须声明 memory 不能覆盖当前工具证据。
```

### 记忆不能覆盖当前事实

Prompt 中必须明确：

```text
长期记忆是历史经验，不是实时数据库结果。
如果长期记忆与本轮用户明确要求、工具查询结果或权威业务系统冲突，以当前事实为准。
```

这条规则要写进：

```text
render.py
find_relevant_memories.py prompt
extract_memories.py prompt
auto_dream.py prompt
```

## 1.5 当前系统与新系统的共存边界

### Source of truth 必须明确

`ai_kefu` 当前已有 `conversation_context_items` 和 `user_memory_items` 表，新方案又引入 Markdown 文件型 memory。如果不先定义谁是事实源，会出现双写一致性问题，例如 Markdown 更新了客户偏好，但 MySQL 仍是旧值；管理 UI 修改了 MySQL，但 Markdown 没更新；ExtractMemories 写了文件，旧 `context_manager.py` 又从 DB 召回另一份冲突内容。

本方案明确采用：

```text
长期 memory source of truth = Markdown memory files
MySQL = 索引、审计、管理 UI、查询加速、旧数据兼容
```

具体边界：

```text
Markdown memory files:
  保存 customer/feedback/business_rule/reference 的完整正文。
  保存 Why、How to apply、source_type、effective_from、effective_to、verified_by 等字段。
  ExtractMemories 和 AutoDream 的写入目标只能是 Markdown。

conversation_context_items:
  继续保存当前系统已有的会话上下文、session_note、confirmed_fact、tool_evidence、failed_path。
  它属于运行期上下文，不是 Claude-Code 风格长期 memory 主库。

user_memory_items:
  MVP 阶段只读兼容旧用户偏好。
  后续如果写入，只能保存 Markdown 文件索引、摘要、状态、审核记录或 UI 加速字段。
  不允许与 Markdown 各自维护一份可独立修改的长期 memory 正文。
```

不采用双主设计：

```text
禁止 Markdown 和 MySQL 同时作为长期 memory 主库。
禁止一个长期 memory 的正文既能从 Markdown 修改，又能从 MySQL 修改。
禁止没有同步协议的双写。
```

如果团队未来决定 MySQL 为主，则必须反向调整为：

```text
MySQL 是长期 memory source of truth
Markdown 只是导出、审查或备份视图
```

但这不是当前推荐方案，因为它会偏离 Claude-Code 的文件编辑和 manifest 机制。

### 现有 DB 型上下文暂不删除

当前 `context_manager.py` 已经有：

```text
ConversationContextItem
UserMemoryItem
session_note
confirmed_fact
tool_evidence
failed_path
user_preferences
```

这些功能可能已经被当前请求链路依赖。第一版不得删除。

推荐共存策略：

```text
Phase 1-4:
  新增 memory_system 模块，不改旧 DB 结构。

Phase 5:
  文件型 SessionMemory 与旧 session_note 并行。
  prompt_context 同时渲染旧 session_note 和新 file_session_memory。

Phase 6-9:
  长期 memory 逐步接管 user_preferences 的新写入。
  旧 UserMemoryItem 只读保留，是否迁移另开任务确认。
```

### 不直接改变 LangGraph 业务节点

第一轮迁移不修改：

```text
deepseek_agent/llm_backend/app/lg_agent/multi_tool.py
deepseek_agent/llm_backend/app/lg_agent/lg_builder.py 的业务节点逻辑
GraphRAG/Text2Cypher 节点逻辑
业务工具实现
```

只在上下文准备、请求后记录、debug trace 处接入。

原因：

1. 记忆系统应是基础设施，不应改变工具选择本身。
2. 可以用 feature flag 快速关闭。
3. 验证范围更小。

## 1.6 运行时目录边界

建议运行时目录：

```text
deepseek_agent/runtime/memory/
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

### 为什么分 customer 和 business

`customer` 目录用于客户个人长期偏好：

```text
customers/{customer_id}/memory/customer/
customers/{customer_id}/memory/feedback/
customers/{customer_id}/memory/reference/
```

`business` 目录用于租户或业务域共享规则：

```text
business/{tenant_id}/memory/business_rule/
business/{tenant_id}/memory/feedback/
business/{tenant_id}/memory/reference/
```

这样可以避免把单个客户偏好误当作全局业务规则，也避免把全局售后政策写到某个客户目录。

### 需要先确认的业务身份字段

当前 `/api/langgraph/query` 已确认有：

```text
user_id
conversation_id
request_id
thread_id
```

但以下字段需要后续实现前确认：

```text
customer_id 是否等同于 user_id
tenant_id 是否存在
operator_id 是否存在
当前请求能否区分客户、运营人员、内部测试人员
```

MVP 推荐：

```text
customer_id = str(user_id)
tenant_id = "default"
actor_type = "customer"
```

但这只是 MVP 假设，不能写进长期不可变协议。

## 1.7 Feature Flag 边界

所有新能力都要能被关闭。

建议配置项：

```text
AI_KEFU_MEMORY_ENABLED=false
AI_KEFU_MEMORY_ROOT=deepseek_agent/runtime/memory
AI_KEFU_MEMORY_RECALL_ENABLED=false
AI_KEFU_MEMORY_TRANSCRIPT_ENABLED=false
AI_KEFU_SESSION_MEMORY_ENABLED=false
AI_KEFU_EXTRACT_MEMORIES_ENABLED=false
AI_KEFU_AUTO_DREAM_ENABLED=false
AI_KEFU_MEMORY_DEBUG_TRACE_ENABLED=true
```

MVP 默认建议：

```text
AI_KEFU_MEMORY_ENABLED=false
```

原因：

1. 避免新系统半成品影响现有客服流程。
2. 方便先跑单元测试和手动接口验证。
3. 发生错误时可以快速回滚到原系统行为。

## 1.8 日志和 trace 边界

新系统必须写入 grep-friendly 的日志事件，但不能把完整敏感对话直接打进日志。

建议事件名：

```text
memory_paths_resolved
memory_scan_started
memory_scan_finished
memory_recall_started
memory_recall_finished
memory_context_rendered
memory_transcript_appended
session_memory_loaded
session_memory_update_started
session_memory_update_finished
extract_memories_started
extract_memories_finished
auto_dream_skipped
auto_dream_finished
memory_tool_denied
```

`debug_trace` 可以返回结构化摘要：

```json
{
  "memory_trace": {
    "enabled": true,
    "session_memory_loaded": true,
    "selected_memory_count": 2,
    "selected_memory_paths": [
      "feedback/inventory_answer_style.md",
      "business_rule/smart_lock_after_sales.md"
    ],
    "transcript_status": "appended",
    "extract_status": "scheduled",
    "auto_dream_status": "skipped",
    "auto_dream_reason": "min_sessions_not_met"
  }
}
```

不得在 trace 中直接暴露：

```text
完整客户手机号
完整地址
完整订单号
身份证号
支付信息
大段原始对话
```

## 1.9 必须一开始做对的事项

### memory type 不允许 project

任何实现、测试、prompt、示例都不能重新引入：

```text
project
```

如果需要表达业务范围，使用：

```text
business_rule
reference
feedback
customer
```

### 后台记忆过程不能污染主 transcript

所有后台任务默认：

```text
skip_transcript = true
```

主 transcript 只记录用户请求、主 Agent 回答、主业务工具证据。

SessionMemory、ExtractMemories、AutoDream 自己的内部 prompt、工具调用和中间回答不应追加到主 transcript。

### 写操作必须限制在 memory root

任何自动写文件的能力都必须先经过 resolved path 校验。

后续 `permissions.py` 中要用：

```python
root = memory_root.resolve()
target = requested_path.resolve()
target.relative_to(root)
```

不要用简单字符串前缀判断作为最终安全策略：

```python
str(target).startswith(str(root))  # 禁止
```

原因是 Windows 上相似前缀目录、路径大小写、符号链接和 `..` 归一化都可能绕过弱校验。需要兼容旧 Python 时，使用 `os.path.commonpath()` 做同等校验。

### 相对日期必须转绝对日期

写入长期 memory 时，如果输入里出现：

```text
今天
明天
下周四
月底
618 后
```

必须转成绝对日期，并保存生成时区：

```text
2026-06-21 Asia/Shanghai
```

否则 memory 在未来会失去语义。

## 1.10 本阶段不做的事情

本文件只是边界定义，不做以下事情：

```text
不实现代码
不修改 /api/langgraph/query
不迁移数据库
不删除 UserMemoryItem 或 ConversationContextItem
不实现前端管理页面
不开放后台 Agent 的业务工具
不做向量库检索
不做多实例共享存储
```

## 1.11 完成标准

本阶段完成后，开发者应能明确回答：

```text
新记忆系统为什么以文件为主
为什么不能保留 project memory type
哪些信息可以写入 customer/feedback/business_rule/reference
哪些信息必须通过工具实时查询而不是写入 memory
新系统接入 /api/langgraph/query 的哪些位置
旧 context_manager.py 能力为什么先保留
哪些配置项控制功能开关
哪些 trace/log 事件用于观察行为
哪些身份字段需要后续先确认
```

可检查项：

```text
本文件存在于 docs/claude-code-memory-system-implementation-plan/
没有要求开发者删除现有 DB 型上下文
没有出现 project 作为 ai_kefu memory type
明确写出 /api/langgraph/query 是主接入点
明确写出后台记忆过程 skip_transcript
明确写出 memory root 权限边界
```

## 1.12 风险和不足分析

### 文件型 memory 与生产多实例存在天然张力

文件型 memory 非常适合本地开发、单机部署和人工审查，但如果 `ai_kefu` 未来多实例部署，需要共享存储、对象存储、数据库索引或同步机制。否则不同实例会看到不同 memory。

### customer_id 与 user_id 的映射可能不准确

当前接口只有 `user_id`，但真实客服系统里 `user_id` 可能是登录用户、客户、运营人员或测试账号。MVP 可以先用 `user_id`，但正式上线前必须确认身份模型。

### 与旧 DB 记忆共存会带来重复上下文

短期共存能降低迁移风险，但也可能让 prompt 同时包含旧 `user_preferences` 和新 `selected_memories`，造成重复或冲突。Phase 9 必须设计优先级和 trace，后续再决定是否迁移旧数据。
