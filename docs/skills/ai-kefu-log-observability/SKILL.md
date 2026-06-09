---
name: ai-kefu-log-observability
description: ai_kefu 日志与可观测性流程的草稿占位。用户询问日志位置、request_id 追踪、X-Request-ID、/api/chat 与 /api/langgraph/query 路由差异、trace 日志、为什么请求没有进入 LangGraph/Text2Cypher/Neo4j 时，应使用这个 skill。正文尚未完成，不能当作完整排查手册。
---

# ai_kefu 日志与可观测性

状态：草稿占位。

这个 skill 目前故意没有完成。后续补全时应覆盖：

- 日志在哪里配置
- 日志文件写到哪里
- 如何用 `X-Request-ID` / `request_id` 串联 access、app、error、trace 日志
- 如何区分 `/api/chat` 和 `/api/langgraph/query`
- 如何查看 trace 输出，同时避免增加控制台噪声
- 常见失败模式和 grep-friendly 查询方式
