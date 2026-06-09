---
name: ai-kefu-benchmark-eval
description: ai_kefu benchmark 与 evaluation 流程的草稿占位。用户询问 benchmark 设计、Agent 效果评测、tool-call evaluation、LangGraph/Text2Cypher 质量检查、latency、token usage、pass rate、回归对比，或如何衡量工具调用是否提升最终答案时，应使用这个 skill。正文尚未完成，不能当作完整评测规范。
---

# ai_kefu Benchmark 与评测

状态：草稿占位。

这个 skill 目前故意没有完成。后续补全时应覆盖：

- 应该 benchmark 哪些任务
- 如何定义 eval case 和 expected output
- 如何比较普通对话、LangGraph、Text2Cypher、GraphRAG、缓存链路
- 应采集哪些指标：pass rate、latency、token usage、tool-call correctness、answer quality
- benchmark 脚本和结果摘要应该放在哪里
- 如何避免把当前环境没有实际跑过的结果包装成已验证结论
