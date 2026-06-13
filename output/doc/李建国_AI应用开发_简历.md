# 李建国

156-0614-6920 | 1460952065@qq.com | 武汉大学 | 22岁  
求职意向：AI应用开发 / LLM Agent工程 / AI后端开发

## 教育背景

**武汉大学 | 计算机科学与技术 | 本科** `2022.09 - 2026.06`  
GPA：3.82/4.00（专业前30%）  
主修课程：操作系统、计算机组成原理、计算机体系结构、编译原理、数据结构与算法、计算机网络、软件工程  
荣誉与证书：英语六级 628、优秀学生奖学金、蓝桥杯省赛三等奖、获本校推免资格

## 专业技能

- **AI应用开发**：熟悉 LangGraph、RAG/GraphRAG、Text2Cypher、Neo4j、工具调用、SSE 流式响应、安全护栏、幻觉检测与 Agent 评测；了解多轮上下文管理、上下文压缩、短期/长期记忆、情景记忆/语义记忆/经验记忆/程序记忆等记忆组织方式，以及 Skill、MCP 工具扩展机制。
- **LLM基础**：熟悉 Transformer、Attention、KV Cache、Prefill/Decode 等基本机制，理解端侧 LLM 推理中的线程调度、访存瓶颈和负载均衡问题。
- **后端开发**：熟悉 Python/FastAPI、Java/Spring Boot、Go/Gin、MyBatis/GORM、JWT、WebSocket、RESTful API，具备前后端分离系统开发经验。
- **Redis/MySQL**：熟悉 MySQL 表结构设计、索引优化和事务；熟悉 Redis 缓存、分布式锁、Stream、TTL、缓存穿透/击穿/雪崩处理及缓存一致性方案。
- **工程与工具**：熟悉 Linux 常用命令、Git、Perfetto、Simpleperf、SQL Trace；了解 Vue 3、TypeScript、Pinia、Element Plus。

## 项目经历

### AI智能客服 Agent 系统 `2026.05 - 至今`

**项目角色**：核心开发者  
**技术栈**：Python、FastAPI、LangGraph、DeepSeek/Ollama、Neo4j、GraphRAG、Redis、MySQL、Spring Boot、SSE

**项目背景**：电商客服高度依赖 FAQ 与人工经验，面对售后政策、优惠券规则、订单状态、库存与多轮追问时，容易出现命中率低、结构化数据与非结构化文档割裂、回答缺少证据链等问题。

**AI客服 Agent 部分**

- **Agent 编排**：基于 FastAPI + SSE 封装 LLM 服务，使用 LangGraph 设计 Router -> 安全护栏 -> Planner 子任务分解 -> 并行 Tools -> 幻觉校验 -> Final Answer 的客服 Agent 流程。
- **意图识别**：使用 Prompt-template + DeepSeek 进行 JSON 结构化路由，区分普通对话、知识库查询、图片理解、实时业务查询等意图，并结合评测日志沉淀难例用于 few-shot 迭代。
- **混合检索**：结构化数据走 Neo4j Text2Cypher / 预定义 Cypher，非结构化售后政策与说明文档走 GraphRAG，高频查询优先模板化，长尾问题交给 Planner 动态选择工具。
- **上下文管理**：借鉴 Claude Code 源码中的 Agent runtime 思路，将上下文拆为用户目标、确认事实、工具证据、失败路径、长期偏好等不同生命周期信息；短期上下文保留原文，工具结果保留可追溯摘要，Redis 只做派生缓存。
- **可观测性**：借鉴 Claude Code 的 trace/timeline 思路，建设统一结构化日志入口，用 X-Request-ID 串联 access/app/error/trace 日志，记录 route、node、tool、model、request_id 等字段，便于复盘工具调用、失败路径和幻觉来源。
- **工程化评测**：设计语义正确率、工具选择正确率、安全识别率等指标，沉淀覆盖路由、Text2Cypher、GraphRAG、安全拒答、多轮记忆等场景的 smoke eval；阶段性评测中语义正确率约 86%，工具选择正确率约 91%，安全识别率约 96%。

**Redis 电商平台部分**

- **数据边界**：将店铺信息、优惠券规则、活动说明、售后政策同步到 Neo4j/GraphRAG；将订单、库存、秒杀资格等强实时数据保留在 Spring Boot + MySQL + Redis 业务系统中，Agent 通过工具调用读取。
- **缓存治理**：使用 Redis 缓存商铺信息，通过空值缓存避免缓存穿透，按业务热度设置差异化 TTL 防止缓存雪崩，针对热点 key 使用互斥锁解决缓存击穿。
- **并发控制**：使用 Redisson 分布式锁与 Lua 原子校验处理秒杀链路，保证库存扣减和一人一单判断的并发安全，避免超卖和重复下单。
- **一致性策略**：采用主动更新 + 延迟删除 + 超时删除的缓存更新方案，在写库后清理缓存并通过延迟删除降低并发读写下的脏缓存风险，兼顾查询性能与较高数据一致性。

### 基于 MNN 的移动端 LLM 异构多核 CPU 推理调度优化 `科研项目 | 2025.01 - 2026.04`

**项目角色**：个人独立研究 / 本科毕业设计  
**技术栈**：C++、MNN、Android/Linux、Perfetto、Simpleperf、SQL、sched_setaffinity、计算机体系结构

- **研究问题**：针对移动端 LLM 在手机 CPU 上的推理稳定性问题，深入 MNN 移动端 CPU 推理路径，分析 Prefill 与 Decode 在计算密度、访存压力、同步开销和最优线程数上的差异。
- **性能观测**：基于 Perfetto、Simpleperf 与 Trace SQL 建立无 root 条件下的性能观测流程，结合线程迁移、主线程等待、工作线程空转、L1 dcache miss、IPC 等指标定位长尾与负载不均。
- **阶段感知调度**：为 Prefill 和 Decode 分别配置线程数与 CPU 亲和性集合，使用离线标定得到的真实性能比生成 Prefill 初始任务区间，避免统一线程数和统一绑核集合带来的折中配置。
- **Prefill 任务窃取**：将连续任务空间抽象为区间队列，工作线程优先执行本地区间，耗尽后从其他线程尾部窃取剩余任务，缓解高负载窗口下少数慢线程拖尾的问题。
- **Decode 选核策略**：借鉴 MNN-AECS 的配置选择思想，在速度约束下优先选择启发式能耗目标更低的核心集合，避免访存受限阶段持续占满所有高性能核心。
- **实验结果**：统一配置改为分阶段配置后，估算端到端时延下降约 3.09%；真实高负载窗口下，相比静态 Prefill 对照组，任务窃取方案将 Prefill 吞吐提升约 36.11%，估算端到端时延降低约 10.09%。

### 蹭课助手 - 高校课程信息与学习交流平台 `2025.05 - 2025.06`

**项目角色**：项目负责人 / 全栈开发  
**技术栈**：Go、Gin、GORM、MySQL、Redis、JWT、Vue 3、TypeScript、Pinia、Element Plus、Vant

- **系统架构**：负责课程信息查询、课程评价、社区论坛、用户认证与多端页面的整体设计和核心开发，完成 Go/Gin 后端与 Vue 3 前端的前后端分离架构。
- **认证鉴权**：实现基于 JWT + Redis 的无状态认证与多角色权限管理，使用拦截器与登录态缓存解决跨域、多端登录和接口鉴权问题。
- **数据与缓存**：使用 GORM 进行数据库建模，引入软删除、索引优化与热点数据缓存；采用主动更新 + 超时剔除策略降低课程/帖子等热点查询对 MySQL 的压力。
- **ReAct 查询**：参考 ReAct 思路扩展课程查询 Agent Loop，将课程查询、教师信息、课程评价等能力抽象为 tool call，通过“问题理解 -> 工具调用 -> 结果观察 -> 回答生成”的闭环辅助用户检索课程信息。
- **前端工程**：使用 TypeScript、Pinia 和组件化开发方式实现移动端优先的响应式布局，结合 Vite、组件懒加载与骨架屏优化首屏体验。
- **项目链接**：前端 `https://github.com/whu-study/cengke-helper-front`；后端 `https://github.com/whu-study/cengkeHelperBackGo`

## 实习经历

### HarmonyOS 内核调度与频率控制优化 `2025.12 - 至今`

**公司/角色**：华为技术有限公司 | 内核研发实习生  
**技术栈**：C、HarmonyOS Kernel、CPU Scheduling、CPUFreq、PID 控制、SMT

- 参与 CPU 调度与频率调节子系统研发，负责对齐软硬件接口规范并验证调度策略在工程样机上的稳定性。
- 设计动态 target_load 映射方案，将传统 PID 调频策略改造为更适应突发负载的动态控制逻辑，缓解频率过冲与响应滞后问题。
- 在 PID 控制中引入负载变化率参数，根据 CPU duty cycle 增长趋势预测频率演化方向，提高调频响应速度。
- 针对图形渲染链路优化 SMT 使用机制，放宽 render_service 实时线程的严格隔离限制，使 RT 线程可在小核上与其他任务并行执行。
- 工程样机测试中，整体软硬件协同调度方案降低整机平均功耗 120mW 以上，约占整机功耗 3%。
