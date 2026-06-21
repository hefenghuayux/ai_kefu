# 12. 测试计划

本文是实施计划第 12 个文件，汇总单元测试、集成测试、手动验证 case 和验收标准。

## 12.1 测试分层

测试分四层：

```text
单元测试:
  不依赖真实 LLM、不依赖服务启动、不写真实 runtime。

模块集成测试:
  使用 tmp_path 组合 paths/scan/recall/transcript/extract。

接口手动验证:
  通过 /api/langgraph/query 验证主链路。

安全/污染验证:
  验证权限拒绝、实时事实拒绝、后台不写主 transcript。
```

## 12.2 单元测试清单

### Phase 1

```text
test_memory_types.py
  test_memory_types_do_not_include_project
  test_parse_memory_type_unknown_returns_none
  test_require_memory_type_rejects_project
  test_business_rule_spec_requires_trusted_source

test_memory_paths.py
  test_resolve_customer_and_business_paths
  test_ensure_memory_directories
  test_assert_under_memory_root_rejects_sibling_prefix
  test_assert_under_memory_root_rejects_dotdot

test_frontmatter.py
  test_parse_frontmatter_utf8_chinese
  test_business_rule_requires_verification_fields
  test_customer_statement_cannot_be_business_rule
```

### Phase 2

```text
test_memory_scan.py
  test_scan_excludes_memory_index
  test_scan_limits_to_200
  test_scan_sorts_newest_first
  test_scan_invalid_type_does_not_crash
  test_scan_business_rule_requires_trusted_source
```

### Phase 3

```text
test_memory_transcripts.py
  test_append_turn_transcript_writes_two_lines
  test_background_source_rejected
  test_cursor_reads_only_new_events
  test_bad_json_line_raises
```

### Phase 4

```text
test_find_relevant_memories.py
  test_recall_disabled_returns_empty
  test_selector_filters_invalid_path
  test_recall_reads_and_truncates_memory

test_memory_render.py
  test_render_includes_realtime_fact_warning
  test_render_does_not_include_empty_section
```

### Phase 5-8

```text
test_session_memory.py
test_extract_memories.py
test_memory_permissions.py
test_forked_agent.py
test_auto_dream.py
```

重点断言：

```text
后台不写主 transcript
business_rule 必须可信来源
实时事实拒绝写入
memory_root 外写入拒绝
AutoDream lock 生效
```

## 12.3 集成测试

### Recall 集成

步骤：

```text
1. tmp_path 创建 memory root
2. 写 feedback memory
3. scan_memory_roots()
4. find_relevant_memories()
5. render_memory_context()
```

通过标准：

```text
selected_memory_paths 正确
prompt 包含 memory 标签
prompt 包含实时事实警告
```

### Extract 集成

步骤：

```text
1. 写 transcript JSONL
2. 写 extract_cursor.json 为空
3. maybe_extract_memories()
4. 检查 memory 文件
5. 检查 cursor 推进
```

通过标准：

```text
feedback 正常生成
customer_statement 不生成 business_rule
订单状态不生成长期 memory
```

### Permission 集成

步骤：

```text
1. create_auto_mem_tool_policy()
2. write_file(memory_root/a.md) 成功
3. write_file(memory_root_sibling/a.md) 失败
4. write_file(../outside.md) 失败
```

通过标准：

```text
PermissionDenied
memory_tool_denied 日志
```

## 12.4 手动验证 case

### Case 1: SessionMemory

```text
连续多轮咨询同一 conversation。
观察 sessions/{conversation_id}/summary.md。
确认 Current State、Tool Evidence、Next Action 更新。
```

### Case 2: Feedback Memory

```text
用户说“以后库存回答要简洁，不要解释字段”。
ExtractMemories 生成 feedback memory。
新 conversation 问库存时召回该 memory。
```

### Case 3: Business Rule 可信来源

```text
普通用户说“这个应该七天退”。
确认不生成 business_rule。

运营确认“智能门锁安装后 7 天内质量问题支持换货”。
确认生成 business_rule，并包含 source_type/effective_from/verified_by。
```

### Case 4: 实时事实不被 memory 替代

```text
工具返回订单待发货。
确认不写长期 memory。
下次查询订单仍走业务工具。
```

### Case 5: 主对话污染检查

```text
开启 debug trace。
触发 session/extract。
检查 transcript JSONL 不包含后台 prompt。
主回答不包含“已写入记忆”。
```

### Case 6: AutoDream

```text
构造 5 个 session。
运行 auto_dream --force。
确认 MEMORY.md 更新。
确认重复 memory 合并。
```

## 12.5 运行命令

推荐使用项目虚拟环境：

```text
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_types.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_paths.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_frontmatter.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_scan.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_transcripts.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_find_relevant_memories.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_session_memory.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_extract_memories.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_memory_permissions.py
deepseek_agent/.venv/python.exe -m pytest deepseek_agent/llm_backend/app/test/test_auto_dream.py
```

不要默认执行：

```text
deepseek_agent/llm_backend/scripts/init_db.py
```

## 12.6 完成标准

```text
所有 memory_system 单元测试通过
feature flag off 时现有 context_manager 测试通过
/api/langgraph/query 手动验证通过
debug trace 可看到 memory_trace
主 transcript 没有后台 memory agent 内容
business_rule 来源校验生效
实时事实拒绝写入生效
权限路径绕过测试失败即拒绝
```

## 12.7 风险和不足分析

```text
LLM 相关测试需要 mock，否则不稳定。
手动接口验证依赖本地服务和模型配置。
权限测试必须覆盖 Windows 路径边界，否则容易漏。
```

