# 智能客服 Agent 项目面试讲解文档

这份文档用于把当前项目讲成一个有技术主线、有工程证据、也能经得起追问的 Agent 开发项目。面试时不要把它讲成“我接了一个大模型接口”，而要讲成：

> 我做的是一个面向电商客服场景的多工具 Agent 后端系统。它不是单纯把用户问题转发给大模型，而是用 LangGraph 把一次请求拆成路由判断、状态流转、工具选择、图谱查询、GraphRAG 检索、结果总结和流式返回等步骤。系统通过 FastAPI 暴露真实接口，通过 SSE 返回增量结果，通过会话状态和 thread_id 维持多轮上下文，通过模型服务工厂适配 DeepSeek、Ollama 和 embedding 模型，并引入 Redis 语义缓存降低高频客服问答的成本。我的重点不是“模型能不能回答”，而是让 Agent 的执行过程可编排、可解释、可排障、可评测。

面试时最稳的主线是：

1. LangGraph 把 Agent 从一段 prompt 变成显式状态图。
2. GraphRAG + Neo4j + Text2Cypher 子图体现工具选择和数据访问能力。
3. FastAPI、SSE、会话、上传、缓存让它成为真实服务，而不是 Notebook demo。
4. 可观测性、评测、权限控制和错误排查是后续把项目做深的关键。

## 1. LangGraph 状态机编排能力

### 你要讲的核心观点

这个项目不是用一个大 prompt 回答所有问题，而是把客服 Agent 拆成多个有职责边界的节点。用户问题进入后，系统先做结构化路由判断，再由 LangGraph 根据路由结果进入不同分支。普通问题可以走轻量聊天链路，图谱问题进入多工具子图，图片和文件问题进入各自处理链路。这样做的价值是把 Agent 的决策过程显式化：每个节点负责什么、读写哪些状态、什么时候跳到下一个节点，都能被调试和扩展。

你可以强调这几个点：

- Router 不是普通字符串判断，而是让模型输出结构化分类结果，例如 `general-query`、`additional-query`、`graphrag-query`、`image-query`、`file-query`。
- LangGraph 的节点不是孤立函数，而是围绕共享 state 工作；节点读入当前 state，返回局部 state 更新，再由 reducer 合并。
- 复杂图谱类问题不会直接回答，而是进入子图继续做 guardrails、planner、tool_selection、工具执行和总结。
- `thread_id` / conversation id 的设计让一次请求不只是无状态调用，而是可以关联多轮对话、checkpoint 和中断恢复。

### 可以这样说

> 我在项目里没有把所有逻辑写成一个超长 prompt，而是用 LangGraph 把 Agent 拆成可编排的状态图。入口节点先调用结构化输出模型，把用户问题分类成普通问答、补充信息、图谱查询、图片问题或文件问题，然后 `route_query` 根据分类结果把流程分发到不同节点。
>
> 这样设计的核心价值是把 Agent 的控制流显式化。以前如果用一个 prompt 让模型自己决定查不查数据库，排障时只能看最终回答，很难知道它为什么走错；现在 Router 的分类、节点输入输出、状态字段和工具调用都可以单独记录。比如一个商品库存问题如果没有进入图谱查询，我可以先看 router 是否把它分成了 `graphrag-query`，再看子图的 tool_selection 是否选择了预定义 Cypher 或 Text2Cypher，而不是直接怀疑大模型效果。

### 主图流程图

下面这张图对应 `deepseek_agent/llm_backend/app/lg_agent/lg_builder.py` 里的主图定义，并展开了 `create_research_plan` 内部调用的 `create_multi_tool_workflow()` 子图。外层主图负责把问题分到普通问答、补充信息、图谱、图片、文件分支；内层子图负责 GraphRAG / Neo4j / Text2Cypher 的工具选择、执行和总结。

```mermaid
flowchart TD
    START([START])
    A[analyze_and_route_query]
    R{route_query}
    G[respond_to_general_query]
    I[get_additional_info]
    K[create_research_plan<br/>GraphRAG / Neo4j / Text2Cypher 子图]
    V[create_image_query]
    F[create_file_query]
    END([END])

    START -->|输入 state.messages<br/>来自 InputState.messages| A
    A -->|写入 state.router<br/>依赖 state.messages + ROUTER_SYSTEM_PROMPT| R

    R -->|router.type = general-query| G
    R -->|router.type = additional-query| I
    R -->|router.type = graphrag-query| K
    R -->|router.type = image-query| V
    R -->|router.type = file-query| F

    G -->|返回 messages<br/>由 add_messages 合并| END
    I -->|返回 messages<br/>由 add_messages 合并| END
    V -->|图片链路输出 AIMessage<br/>写回 state.messages| END
    F -->|文件链路输出 AIMessage<br/>写回 state.messages| END

    K -->|读取父图 state.messages[-1].content| RP0

    subgraph RP[create_research_plan 父图节点内部]
        RP0[提取 last_message]
        RP1[初始化 Neo4jGraph<br/>NorthwindCypherRetriever<br/>tool_schemas<br/>predefined_cypher_dict<br/>scope_description]
        RP2[构造子图 input_state<br/>question = last_message<br/>data = []<br/>history = []]
        RP0 --> RP1 --> RP2
    end

    RP2 -->|multi_tool_workflow.ainvoke input_state| SG_START

    subgraph SG[create_multi_tool_workflow 子图]
        SG_START([START])
        GR[guardrails]
        PL[planner]
        TS[tool_selection]
        CQ[cypher_query<br/>Text2Cypher -> validate -> execute Neo4j]
        PC[predefined_cypher<br/>执行预定义 Neo4j Cypher]
        CT[customer_tools<br/>Microsoft GraphRAG query]
        SM[summarize]
        FA[final_answer]
        SG_END([END])

        SG_START -->|InputState.question| GR
        GR -->|next_action = planner| PL
        GR -->|next_action = end / final_answer| FA
        PL -->|tasks 通过 Send 拆成多个 tool_selection| TS
        TS -->|tool_name = cypher_query<br/>或未选工具且 default_to_text2cypher = true| CQ
        TS -->|tool_name = predefined_cypher| PC
        TS -->|其它工具名<br/>如 microsoft_graphrag_query| CT
        CQ -->|写入 cyphers + steps| SM
        PC -->|写入 cyphers + steps| SM
        CT -->|写入 cyphers + steps| SM
        SM -->|读取 cyphers<br/>写入 summary| FA
        FA -->|输出 answer / question / steps / cyphers / history| SG_END
    end

    SG_END -->|response.answer| RP3[包装为 AIMessage<br/>返回父图 messages]
    RP3 --> END
```

边依赖可以这样理解：

| 边                                                                 | 代码位置                                                                  | 依赖的 state 字段                                                                     | 作用                                                                                                                                                    |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `START -> analyze_and_route_query`                               | `builder.add_edge(START, "analyze_and_route_query")`                    | `state.messages`                                                                    | 把本轮用户输入和历史消息交给路由分析节点。                                                                                                              |
| `analyze_and_route_query -> route_query`                         | `builder.add_conditional_edges("analyze_and_route_query", route_query)` | `state.router`                                                                      | `analyze_and_route_query` 调用结构化输出模型，返回 `{"router": response}`，后续条件边基于这个字段分支。                                             |
| `route_query -> respond_to_general_query`                        | `route_query()`                                                         | `state.router["type"] == "general-query"`                                           | 普通问答，不进入图谱、文件或图片工具链。                                                                                                                |
| `route_query -> get_additional_info`                             | `route_query()`                                                         | `state.router["type"] == "additional-query"`                                        | 用户问题缺少必要信息时，引导用户补充。                                                                                                                  |
| `route_query -> create_research_plan`                            | `route_query()`                                                         | `state.router["type"] == "graphrag-query"`                                          | 进入图谱/GraphRAG 多工具子图，是商品、库存、供应商、售后文档类复杂问题的主路径。                                                                        |
| `route_query -> create_image_query`                              | `route_query()`                                                         | `state.router["type"] == "image-query"`                                             | 进入图片理解链路，处理图片相关问题。                                                                                                                    |
| `route_query -> create_file_query`                               | `route_query()`                                                         | `state.router["type"] == "file-query"`                                              | 进入文件问答链路，后续应对接用户文件索引。                                                                                                              |
| `create_research_plan -> 子图 input_state`                       | `create_research_plan()`                                                | 父图 `state.messages[-1].content`                                                   | 把最后一条用户消息转成子图 `question`，并初始化 `data=[]`、`history=[]`。                                                                         |
| `子图 START -> guardrails`                                       | `main_graph_builder.add_edge(START, "guardrails")`                      | 子图 `InputState.question`                                                          | 判断问题是否在智能家居电商业务范围内，并结合 Neo4j schema / scope_description 做范围约束。                                                              |
| `guardrails -> planner`                                          | `guardrails_conditional_edge()`                                         | `state["next_action"] == "planner"`                                                 | 问题在业务范围内，继续进入任务拆解。                                                                                                                    |
| `guardrails -> final_answer`                                     | `guardrails_conditional_edge()`                                         | `state["next_action"] == "end"` 或 `final_answer`                                 | 问题越界或需要提前结束时，直接进入最终回答。                                                                                                            |
| `planner -> tool_selection`                                      | `map_reduce_planner_to_tool_selection()`                                | `state["tasks"]`                                                                    | planner 产出一个或多个 `Task`，每个 task 通过 `Send("tool_selection", {"question": task.question, "parent_task": task.parent_task})` 进入工具选择。 |
| `tool_selection -> cypher_query`                                 | `create_tool_selection_node()`                                          | LLM 选择出的工具名 `cypher_query`，或没有选出工具且 `default_to_text2cypher=True` | 进入 Text2Cypher：生成 Cypher、校验、执行 Neo4j，并把结果写入 `cyphers`。                                                                             |
| `tool_selection -> predefined_cypher`                            | `create_tool_selection_node()`                                          | LLM 选择出的工具名 `predefined_cypher`                                              | 执行预定义 Cypher 模板，适合高频稳定查询。                                                                                                              |
| `tool_selection -> customer_tools`                               | `create_tool_selection_node()`                                          | 工具名不是 `cypher_query` / `predefined_cypher` 时                                | 当前会进入 GraphRAG 查询节点，例如 `microsoft_graphrag_query`。                                                                                       |
| `cypher_query / predefined_cypher / customer_tools -> summarize` | `main_graph_builder.add_edge(...)`                                      | 工具节点写回的 `cyphers` 和 `steps`                                               | 多个工具结果统一汇总到 `summarize`。                                                                                                                  |
| `summarize -> final_answer`                                      | `main_graph_builder.add_edge("summarize", "final_answer")`              | `state["cyphers"]`、`state["question"]`、`state["summary"]`                     | 把工具返回的结构化结果或 GraphRAG 结果总结成用户可读内容。                                                                                              |
| `final_answer -> 子图 END`                                       | `main_graph_builder.add_edge("final_answer", END)`                      | `answer`、`question`、`steps`、`cyphers`、`history`                         | 形成子图输出。                                                                                                                                          |
| `子图 END -> 父图 END`                                           | `create_research_plan()`                                                | `response["answer"]`                                                                | 父图把子图 `answer` 包装成 `AIMessage`，返回 `{"messages": [...]}`，本轮执行结束。                                                                |
| `其它业务节点 -> END`                                            | 分支节点没有继续添加出边                                                  | 主要写回 `state.messages`                                                           | 普通问答、补充信息、图片、文件分支当前都是终止节点。                                                                                                    |

补充说明：`route_query()` 里有一个图片路径优先分支，代码判断的是 `state.config.configurable.image_path`。但当前 `AgentState` 没有显式定义 `config` 字段，所以这条逻辑在主图 state schema 里不是稳定的状态依赖。更稳的讲法是：当前主图条件分支主要依赖 `state.router["type"]`，图片上传能力应通过接口层或明确的 state 字段传入。

### 面试官可能追问

**为什么不用普通 if-else？**

可以回答：

> if-else 可以做简单路由，但它只适合表达线性的、无状态的分支判断。Agent 流程更复杂：它有共享状态、节点间状态合并、条件边、子图、工具调用结果回写、interrupt/resume、checkpoint 以及后续可观测性需求。LangGraph 的价值不是“语法上替代 if-else”，而是把 Agent 执行过程建模成状态机。
>
> 在这个项目里，主图需要先分析问题类型，再根据类型进入普通问答、图谱子图、图片处理或文件处理；图谱子图内部还会继续拆任务、选择工具、执行查询、总结结果。如果全部用 if-else 写，短期能跑，但状态协议、节点边界、失败恢复和单节点测试都会变得很混乱。LangGraph 让每个节点的职责、输入输出和状态变化都更明确，后续补 trace、eval 或 checkpoint 时也更自然。

**LangGraph 状态里最关键的是什么？**

可以回答：

> 最关键的是把 state 当成节点之间的协议，而不是普通临时变量。比如 `messages` 保存对话历史，通常会用 `add_messages` 这类 reducer 追加而不是覆盖；`question` 表示本轮用户问题；`router` 保存结构化分类结果；`answer` 保存最终回复或中间节点产出的回答。
>
> 这种 state 设计决定了系统能不能稳定扩展。如果某个节点只靠函数局部变量保存中间结果，后续节点就无法复用，也无法做 trace 和恢复。相反，如果每个关键节点都把必要信息写回 state，就可以在日志里复盘一次请求：用户问了什么、Router 怎么判断、进入了哪个分支、调用了什么工具、工具返回了什么、最后为什么生成这个答案。

**LangGraph 在这个项目里最能体现 Agent 能力的地方是什么？**

可以回答：

> 最能体现 Agent 能力的不是“用了 LangGraph”这个框架标签，而是它把 `plan -> tool call -> observe -> verify/summarize -> answer` 这种 Agent loop 落到了工程结构里。主图负责粗粒度路由，子图负责复杂任务处理。尤其是图谱查询分支，不是一次性让模型回答，而是先做业务范围判断，再拆解任务，再选择合适工具，最后把工具结果总结成用户能读的回答。
>
> 这说明项目关注的是可控的任务执行流程，而不是把所有判断都交给模型隐式完成。

### 对应代码

- `deepseek_agent/llm_backend/app/lg_agent/lg_builder.py`
- `deepseek_agent/llm_backend/app/lg_agent/lg_states.py`
- `deepseek_agent/llm_backend/main.py`

### 为了加深理解要做的实践

1. 打印一次完整路由结果：给 5 类问题各发一条请求，记录 router 输出的 type、logic、置信依据和最终进入的节点。
2. 画一张主图流程图：`START -> analyze_and_route_query -> 条件分支 -> 各节点 -> END`，并标注每条边依赖哪个 state 字段。
3. 增加一个新的路由类型，例如 `order-query`，只做 mock 节点返回，验证 LangGraph 扩展流程是否需要改动主图、state 和接口层。
4. 验证 thread_id：同一个 conversation_id 连续问两轮，观察 LangGraph 是否复用状态，并记录第二轮是否能利用上一轮上下文。
5. 给每个节点增加 trace 日志：记录 node_name、input_state_keys、output_state_keys、耗时和异常，形成面试时可以展示的执行轨迹。

## 2. GraphRAG + Neo4j + Text2Cypher 子图

### 你要讲的核心观点

这是项目里最像 Agent 开发的部分。它不是简单 RAG，也不是直接把所有问题转成 Cypher，而是让模型在多种数据访问方式之间做选择。结构化商品、分类、库存、供应商这类信息适合图数据库查询；固定高频问题适合预定义 Cypher；用户问法灵活但能落到 schema 的问题适合 Text2Cypher；售后政策、说明文档、跨文档总结适合 GraphRAG。

这部分可以讲成一个多工具子图：

- guardrails 判断问题是否属于当前业务域，避免无关问题进入数据库查询。
- planner 把复杂问题拆成可执行子任务，避免一个模糊问题直接扔给工具。
- tool_selection 根据任务类型选择预定义 Cypher、Text2Cypher、GraphRAG 或其它工具。
- 工具执行节点拿到结构化结果或检索结果。
- summarize / final_answer 把工具结果转成用户可读答案。

### 可以这样说

> 图谱查询部分我做成了一个多工具 Agent 子图。用户问题进入 `graphrag-query` 后，系统不会直接把问题塞给 Neo4j 或 RAG，而是先做 guardrails，判断它是否在智能家居电商业务范围内；然后 planner 把复杂问题拆成子任务；tool_selection 决定每个子任务走预定义 Cypher、动态 Text2Cypher，还是 GraphRAG；工具返回结果后，再由 summarize 和 final_answer 生成最终回答。
>
> 这个设计解决的是“不同问题应该访问不同知识源”的问题。比如“有哪些空气净化器库存不足”更适合结构化图查询；“某个品类有哪些供应商关系”适合 Neo4j；“售后政策里超过 7 天怎么处理”更适合文档检索或 GraphRAG。多工具子图让模型不是直接生成答案，而是先决定应该用什么数据来源，再基于工具结果回答。

### 面试官可能追问

**预定义 Cypher 和 Text2Cypher 的区别是什么？**

可以回答：

> 预定义 Cypher 适合高频、确定、风险低、schema 固定的问题，例如查库存、按品类查商品、查供应商、查商品属性。这类问题最好不要每次都让模型自由生成 Cypher，因为固定模板更稳定、延迟更低、也更容易做权限控制和单元测试。
>
> Text2Cypher 适合问法灵活、条件组合更多，但仍能映射到图数据库 schema 的问题。它的优势是灵活，用户不需要按固定模板提问；风险是模型可能生成不存在的字段、错误关系，甚至危险写操作。因此 Text2Cypher 必须配合 schema 约束、只读限制、语法校验、执行前日志和失败回退。面试时我会把两者讲成稳定性和灵活性的权衡，而不是谁完全替代谁。

**GraphRAG 和 Neo4j 查询有什么区别？**

可以回答：

> Neo4j 查询面向确定的结构化图数据，适合回答“某个实体和另一个实体有什么关系”“某类商品有哪些属性”“库存、价格、供应商、类目之间如何关联”这类问题。它依赖的是明确 schema 和图关系，查询结果通常是可枚举、可验证的。
>
> GraphRAG 面向非结构化或半结构化文档，适合售后政策、维修说明、使用手册、跨文档总结这类问题。它不是简单向量检索，而是离线把文档切分、抽取实体和关系、聚合社区摘要，在线查询时利用这些索引产物提升全局性和可解释性。
>
> 所以两者不是同一个东西：Neo4j 是业务结构化数据查询，GraphRAG 是文档知识组织和检索增强。项目里把二者放在同一个子图里，是为了让 Agent 根据问题类型选择合适的数据访问方式。

**为什么需要 guardrails？**

可以回答：

> 客服 Agent 不能什么问题都查数据库，也不能让模型随意生成数据库查询。guardrails 的作用是把业务范围、数据范围和安全边界前置。比如用户问天气、闲聊或要求删除所有商品，这些请求不应该进入图谱查询或写操作。
>
> 在这个项目里，guardrails 至少解决三类风险：第一，减少无关问题带来的无意义检索；第二，降低模型幻觉，因为模型不会在没有业务数据支撑时硬查；第三，保护数据库，尤其是 Text2Cypher 场景下要避免 DELETE、CREATE、MERGE、SET 这类写操作。面试时可以主动说，guardrails 不是装饰性 prompt，而是 Agent 工具调用前的权限和范围控制层。

**如果 Text2Cypher 生成了错误查询怎么办？**

可以回答：

> 我会从三层处理。第一层是生成前约束，把可用 schema、节点、关系、字段和只读要求放进提示词或工具描述里；第二层是执行前校验，对 Cypher 做只读关键字检查、语法检查、字段白名单检查；第三层是执行后观测，如果返回为空、报错或结果异常，要记录生成的 Cypher、错误信息和用户问题，用于后续修正模板或评测集。
>
> 这里不能简单说“模型会生成正确查询”。Text2Cypher 的工程重点恰恰是承认模型可能出错，然后通过 schema 约束、只读策略、日志和 eval 把风险控制住。

### 对应代码

- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/workflows/multi_agent/multi_tool.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/kg_tools_list.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/*`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/predefined_cypher/cypher_dict.py`

### 为了加深理解要做的实践

1. 准备 10 个结构化商品问题，手工标注应该走预定义 Cypher、Text2Cypher、GraphRAG 还是拒答。
2. 打印 tool_selection 的选择结果，记录模型选择某个工具的理由，并人工判断是否合理。
3. 对一个 Text2Cypher 问题，记录用户问题、schema 片段、生成的 Cypher、执行结果、最终回答和耗时。
4. 加一个危险问题，例如“删除所有商品”，验证是否会被拦截，至少要确认不会执行写操作。
5. 做一个对比：同一个售后政策问题分别用 Neo4j、普通 RAG、GraphRAG 思路解释，说明为什么 GraphRAG 更合适或不合适。
6. 建一个小型工具选择评测表：问题、期望工具、实际工具、是否正确、失败原因、修复建议。

## 3. 真实工程接口，而不是 Notebook Demo

### 你要讲的核心观点

这个项目已经接到 FastAPI 后端，而不是只停留在 notebook 或单脚本。面试时要把接口边界讲清楚，因为这能体现你做的是工程服务，不是一次性实验。

主要接口可以这样归类：

- `/api/chat`：普通 LLM SSE 聊天链路，适合不需要 Agent 工具调用的问题。
- `/api/langgraph/query`：LangGraph Agent 入口，图谱查询、文件、图片等复杂问题应该走这里。
- `/api/langgraph/resume`：中断恢复入口，服务于 interrupt/resume 或人工确认类流程。
- `/api/upload`：文件上传并触发索引构建。
- `/api/upload/image`：图片上传和图片理解相关链路。
- 会话接口：创建、读取、重命名、删除会话。
- SSE：支持流式返回，降低用户等待感。

### 可以这样说

> 我把 Agent 接成了 FastAPI 服务，而不是只做 notebook 演示。普通聊天和 LangGraph Agent 是两个入口：`/api/chat` 只走普通 LLM 流式输出，`/api/langgraph/query` 才会进入 LangGraph 和图查询链路。这个区分很重要，因为我排查过一次“为什么没有查数据库”的问题，最后发现请求实际打到了 `/api/chat`，根本没有进入 Agent 图。
>
> 这个经历让我意识到，Agent 项目的工程排障不能一上来就怀疑模型或数据库。要先确认真实命中路由、请求体格式、FastAPI 参数校验、content-type、SSE 输出和后端日志。很多看起来像 Agent 推理失败的问题，其实发生在 HTTP 层或接口契约层。

### 面试官可能追问

**你遇到过什么真实工程问题？**

可以回答：

> 我遇到过 FastAPI 422 的问题。表面看是 LangGraph 接口不能用，但真正原因不是 LangGraph 报错，而是接口签名要求 `Form(...)`，调用方发的却是 JSON。FastAPI 在进入业务逻辑之前就完成参数校验，所以请求根本没有走到 Agent 节点。
>
> 后来我的处理思路是：先确认请求实际命中的 endpoint，再看请求头里的 content-type，然后对齐接口参数声明。为了兼容调用方，我把文本参数改成可选 Form，并在 handler 内根据 content-type 兼容 JSON，同时保留 multipart 图片上传能力。这个问题体现了一个经验：Agent 后端排障要从路由、请求体、框架校验层开始，而不是直接跳到模型、LangGraph 或数据库。

**为什么用 SSE，而不是等完整回答后一次性返回？**

可以回答：

> 客服场景对响应体感很敏感，大模型或 Agent 工具链可能需要几秒甚至更久。如果等完整结果再返回，用户会觉得系统卡住。SSE 可以让前端边生成边展示，先返回模型 token 或阶段性事件，降低等待感。
>
> 从工程角度看，SSE 也适合 Agent trace。除了最终答案，后续可以把 `router`、`tool_call`、`tool_result`、`final_answer` 做成不同事件类型，让前端展示“系统正在判断问题类型”“正在查询图谱”“正在总结答案”。这样不仅体验更好，也能提升可观测性。

**怎么证明这不是 demo，而是服务化项目？**

可以回答：

> 我会从四个证据证明：第一，有明确 API 边界，普通聊天、Agent 查询、resume、上传、会话管理分开；第二，有会话模型和消息模型，不是单次脚本调用；第三，有流式响应和 content-type 兼容处理，考虑了前后端真实调用；第四，有日志和排障经验，能定位 422、路由误用、multipart/JSON 兼容这类问题。
>
> 当然我不会说它已经完全生产级。更准确的说法是：它已经从 notebook demo 进入后端服务形态，具备继续补鉴权、监控、评测和部署的基础。

### 对应代码

- `deepseek_agent/llm_backend/main.py`
- `deepseek_agent/llm_backend/app/services/conversation_service.py`
- `deepseek_agent/llm_backend/app/models/conversation.py`
- `deepseek_agent/llm_backend/app/models/message.py`

### 为了加深理解要做的实践

1. 用接口工具分别请求 `/api/chat` 和 `/api/langgraph/query`，观察日志差异，确认哪条链路会进入 LangGraph。
2. 分别发送 JSON 和 multipart 请求到 `/api/langgraph/query`，验证参数解析和图片上传能力没有互相破坏。
3. 模拟一个缺少 query 的请求，确认返回 400 或明确错误，而不是 500。
4. 给 SSE 返回加上事件类型，例如 `router`、`tool_call`、`tool_result`、`final_answer`，方便前端展示 Agent 执行轨迹。
5. 补一个 TestClient 测试，覆盖 JSON、multipart、缺参三类情况。
6. 在日志中加入 request_id / conversation_id / thread_id，保证一次请求可以被完整追踪。

## 4. 多模型与本地模型适配

### 你要讲的核心观点

项目不是绑定单一模型，而是按服务职责支持不同模型来源。普通聊天、推理、Agent 路由、embedding、图片理解这些能力对模型要求不同，因此应该通过配置和工厂层隔离，而不是在业务代码里写死某个模型。

可以讲这几个点：

- DeepSeek 适合在线 API 场景，效果和推理能力更稳定。
- Ollama 适合本地开发和低成本调试。
- chat / reason / agent / embedding 可以分别配置，避免一个模型承担所有职责。
- LLMFactory 负责创建具体服务，业务入口不用关心底层模型实现细节。

### 可以这样说

> 我把模型调用做成了可配置服务，而不是在业务代码里写死某一个模型。普通聊天、推理模型、Agent 路由模型、embedding 模型可以分别配置。开发阶段可以用 Ollama 本地模型降低成本，演示或复杂推理时可以切到 DeepSeek 这类在线 API。
>
> 这个设计对 Agent 项目很重要，因为不同节点对模型能力的要求并不一样。Router 需要稳定的结构化输出，Text2Cypher 需要更强的 schema 理解和代码生成能力，语义缓存需要 embedding，图片问题可能需要 vision。如果所有节点都隐式依赖同一个模型，后续调优和排障会很困难。

### 面试官可能追问

**这样设计有什么好处？**

可以回答：

> 好处是解耦和可替换。接口层、Agent 节点和工具逻辑不直接依赖 DeepSeek 或 Ollama 的具体调用方式，而是通过服务工厂拿到 chat service、reasoner service 或 embedding service。后续如果接 Qwen、OpenAI 兼容 API 或本地其它模型，理论上主要改配置和工厂适配层，而不是改每个业务节点。
>
> 另一个好处是可以按成本和效果做分层。简单客服问答可以走低成本模型；路由、Text2Cypher、总结这类高风险节点可以走能力更强的模型；embedding 单独用向量模型。这样比“所有任务都走最贵模型”更符合工程成本控制。

**有什么不足？**

可以回答：

> 当前更像基础工厂模式，还没有完整的模型能力注册表。也就是说，系统知道可以创建某个模型服务，但还没有显式声明这个模型是否支持 vision、tool calling、structured output、embedding、多模态输入或最大上下文长度。
>
> 这会带来一个风险：某个节点可能调用了模型不支持的能力，直到运行时才报错。后续可以补 capability registry，在启动时检查配置，例如 Router 必须使用支持结构化输出的模型，图片链路必须使用 vision 模型，embedding 服务必须返回固定维度向量。这样错误会更早暴露。

**本地模型和在线模型怎么取舍？**

可以回答：

> 我会按开发阶段和任务风险取舍。本地模型的优势是成本低、可离线、适合频繁调试，但效果、结构化输出稳定性和推理能力可能不如在线模型。在线模型效果更稳定，适合演示和关键节点，但有成本、网络和密钥管理问题。
>
> 在这个项目里，比较合理的策略是：普通聊天或开发调试可以走 Ollama；Router、Text2Cypher、总结这类对正确性影响大的节点优先走能力更强的在线模型；embedding 使用稳定的向量模型并固定维度，避免缓存和索引不兼容。

### 对应代码

- `deepseek_agent/llm_backend/app/services/llm_factory.py`
- `deepseek_agent/llm_backend/app/services/deepseek_service.py`
- `deepseek_agent/llm_backend/app/services/ollama_service.py`
- `deepseek_agent/llm_backend/app/core/config.py`

### 为了加深理解要做的实践

1. 分别用 DeepSeek 和 Ollama 跑同一个普通问答，比较延迟、答案稳定性和失败率。
2. 用本地 embedding 模型跑语义缓存，确认向量维度、相似度计算和缓存命中逻辑正常。
3. 写一张模型配置表：chat、reason、agent、embedding、vision 分别使用哪个模型、为什么。
4. 增加一个模型能力检查函数，只检查配置和能力声明，不做兜底执行。
5. 记录一次模型切换过程中需要改哪些配置，整理成 README。
6. 为关键节点记录 model_name、latency、token_usage、error_type，方便后续做成本和质量分析。

## 5. 语义缓存与性能意识

### 你要讲的核心观点

客服系统有大量重复问题，语义缓存可以减少重复调用大模型。这里的重点不是“用了 Redis”，而是你知道高频问答场景下大模型调用有成本和延迟，知道可以用 embedding 把近义问题归并，并且知道语义缓存有误命中风险。

语义缓存链路可以这样讲：

- 从 messages 中提取用户最后一条问题。
- 调用 embedding 模型生成向量。
- 和 Redis 中已有问题向量做余弦相似度。
- 相似度超过阈值则直接返回缓存回答。
- 按 user_id 或业务范围隔离缓存。
- 记录访问次数、最近访问时间、过期时间、similarity 和 hit/miss。

### 可以这样说

> 客服场景里很多问题是重复或近似重复的，比如“怎么退货”“退货流程是什么”“超过 7 天还能不能退”。如果每次都完整调用大模型，成本和延迟都会比较高。我做了一个 Redis 语义缓存，不是简单按字符串完全匹配，而是用 embedding 计算语义相似度。命中后可以直接流式返回缓存内容，降低模型调用成本和平均响应时间。
>
> 但我不会把语义缓存讲成万能优化。它适合高频、答案稳定、业务约束明确的问题；对于强上下文、强时效、涉及订单状态或金额的问题，必须谨慎命中，最好结合 metadata 过滤或直接绕过缓存。

### 面试官可能追问

**为什么不用普通 key-value 缓存？**

可以回答：

> 普通 key-value 缓存要求 key 基本一致，而客服用户问法非常不固定。同一个意图可能有很多表达，比如“怎么退货”“退货流程是什么”“不想要了怎么处理”。如果只按原始字符串做 key，命中率会很低。
>
> 语义缓存用 embedding 表示问题含义，再用相似度判断是否可以复用回答，更适合自然语言问答。但它也牺牲了一部分确定性，所以需要阈值、业务隔离和日志监控。

**语义缓存有什么风险？**

可以回答：

> 最大风险是误命中。两个问题语义相近但业务约束不同，可能返回错误答案。例如“7 天内退货”和“超过 7 天退货”都和退货相关，但规则可能不同；“查询我的订单状态”和“查询订单退款状态”也不能随便共用答案。
>
> 所以语义缓存不能只看相似度。更稳的做法是结合业务类型、用户 id、问题意图、时间有效期和 metadata 过滤；对高风险问题提高阈值或禁用缓存；对每次命中记录 query、matched_query、similarity、answer_id 和 user_id，方便排查误命中。

**当前 Redis 语义缓存能支撑大规模吗？**

可以回答：

> 如果当前实现是把 Redis 中的向量取出来做线性扫描，那它更适合 demo、小规模或早期验证。数据量变大后，线性扫描会带来明显延迟和 CPU 开销。
>
> 后续更合理的升级方向是 Redis Vector Search、FAISS、Milvus 或其它向量索引，并且要做分桶和过滤，例如按 user_id、业务域、问题类型先缩小候选集，再做向量召回。面试里主动说出这个限制，比只说“用了缓存所以性能好”更专业。

### 对应代码

- `deepseek_agent/llm_backend/app/services/redis_semantic_cache.py`
- `deepseek_agent/llm_backend/app/services/deepseek_service.py`

### 为了加深理解要做的实践

1. 准备 5 组近义问题，观察缓存是否命中，并记录 similarity。
2. 准备 5 组容易误命中的问题，例如同一业务但约束不同，调试阈值。
3. 给缓存日志增加 query、matched_query、similarity、hit/miss、user_id、ttl。
4. 压测缓存前后的平均响应时间、P95 延迟和模型调用次数。
5. 思考替代方案：Redis Vector Search、FAISS、Milvus，并说明当前线性扫描为什么只适合 demo 或小规模。
6. 为缓存命中建立人工抽样检查机制，避免错误答案长期被复用。

## 6. 文件索引与知识库构建链路

### 你要讲的核心观点

项目具备把上传文件变成知识库索引的工程链路。这里要谨慎表述：如果文件问答入口还没有完整打通，就不要说成生产级文件问答系统；更准确的讲法是“已经具备文件上传、用户隔离和 GraphRAG 索引构建基础，后续要补查询闭环和状态管理”。

当前可以讲的工程链路：

- 用户上传文件后保存到用户目录。
- 按 user_id 做输入目录和输出目录隔离。
- 将文件复制或写入 GraphRAG input 目录。
- 调用 GraphRAG `build_index` 构建索引。
- 后续查询阶段可以加载对应用户的索引产物。

### 可以这样说

> 文件知识库这块我关注的是工程链路：用户上传文件后，不是临时把整份文档塞给模型，而是保存到用户目录，按用户隔离输入输出，再调用 GraphRAG 构建索引。GraphRAG 的模式是先离线索引，在线查询时加载索引产物，这比每次用户提问时临时解析文档更可控。
>
> 我会把这部分描述为“具备文件索引构建基础”，而不是夸成完整生产级文档问答。因为完整闭环还需要补充文件索引状态、失败重试、索引版本、查询入口、权限隔离和效果评测。

### 面试官可能追问

**为什么 GraphRAG 要离线构建？**

可以回答：

> GraphRAG 不只是 embedding 检索，它还涉及文本切分、实体抽取、关系抽取、社区发现、社区报告和索引产物生成。这些步骤成本较高，不适合每次用户提问时实时执行。
>
> 离线构建的好处是把重计算前置，在线查询阶段只加载已经生成的索引产物，从而降低响应延迟，也更方便复用同一份文档知识。代价是索引构建需要状态管理：文件上传后可能处于 pending、indexing、success、failed，不同状态下用户查询应该得到不同反馈。

**文件问答链路现在完整吗？**

可以回答：

> 当前文件上传和索引构建链路已经有基础，但文件问答入口还需要进一步打通和验证。面试时我会明确说：现在可以展示上传文件、保存目录、GraphRAG input/output、索引构建产物；但如果要说完整文档问答，还需要证明 `file-query` 能根据 user_id 找到对应索引，并能稳定返回 grounded answer。
>
> 这种表述更稳，因为它区分了“工程链路已经存在”和“端到端效果已经验证”。

**多用户文件索引有什么风险？**

可以回答：

> 最大风险是数据隔离和索引版本。不同用户上传的文件不能混到同一个 input/output 目录，否则会出现越权查询；同一个用户多次上传也要区分索引版本，否则旧索引和新文件可能不一致。
>
> 后续应该为文件索引引入 user_id、dataset_id、index_version、status、created_at、updated_at 等元数据，并在查询时强制按用户和数据集过滤。否则功能看起来能跑，但安全边界不清晰。

### 对应代码

- `deepseek_agent/llm_backend/app/services/indexing_service.py`
- `deepseek_agent/llm_backend/main.py`
- `deepseek_agent/llm_backend/app/graphrag/data/settings.yaml`

### 为了加深理解要做的实践

1. 上传一个小 TXT 文件，确认文件保存目录、GraphRAG input 目录和 output 目录。
2. 记录一次 build_index 的输入、输出、耗时、日志和失败情况。
3. 检查索引产物里有哪些 parquet、lancedb 或报告文件，并说明它们分别用于什么。
4. 打通 `file-query` 分支，让用户问题可以真正查询某个用户的索引产物。
5. 给文件索引加状态字段：pending、indexing、success、failed。
6. 增加用户隔离验证：用户 A 上传的文件，用户 B 不能查询到。

## 7. 面试时的整体讲法

### 1 分钟版本

> 这个项目是一个面向电商客服场景的 Agent 后端系统。我用 FastAPI 提供接口，用 LangGraph 编排 Agent 流程。用户问题进来后，Router 会先判断是普通问答、图谱查询、文件问题还是图片问题。普通问题直接调用 LLM；复杂商品、库存、供应商和售后问题会进入多工具子图，由 guardrails、planner、tool_selection 决定走预定义 Cypher、Text2Cypher、Neo4j 查询或 GraphRAG。
>
> 工程上我还接了 SSE 流式返回、会话状态、模型服务工厂、Redis 语义缓存和文件索引构建。这个项目最核心的价值是把 Agent 从一次性 demo 接成真实后端服务，并且能解释每条请求为什么进入某个节点、为什么选择某个工具、工具结果如何变成最终回答。

### 3 分钟版本

> 我会从三层讲这个项目。第一层是接口层，FastAPI 提供普通聊天、LangGraph 查询、resume、文件上传、图片上传和会话管理，前端通过 SSE 获得流式回答。这里我特别区分 `/api/chat` 和 `/api/langgraph/query`：前者是普通 LLM 聊天，后者才会进入 Agent 图和图谱查询链路。
>
> 第二层是 Agent 编排层。LangGraph 主图先用结构化输出做 Router，把用户问题分成普通问答、补充信息、GraphRAG、图片和文件几类。这个设计不是为了堆框架，而是为了把 Agent 的控制流显式化：每个节点读写哪些 state、根据什么条件跳转、什么时候进入子图，都可以被日志记录和测试。
>
> 第三层是工具层。图谱问题会进入多工具子图，先做业务 guardrails，再由 planner 拆任务，由 tool_selection 在预定义 Cypher、Text2Cypher 和 GraphRAG 之间选择。结构化商品关系走 Neo4j，固定高频查询走预定义 Cypher，灵活结构化问题走 Text2Cypher，文档类政策和说明走 GraphRAG，最后把工具结果总结成用户回答。
>
> 工程能力上，我还做了模型适配和缓存优化。模型侧支持 DeepSeek 和 Ollama，chat、reason、agent、embedding 可以分开配置；缓存侧用 Redis 存储问题 embedding 和回答，相似问题可以命中缓存，降低高频客服问答成本。项目里我也遇到过真实排障，例如请求误打到 `/api/chat` 导致没有查数据库，以及 FastAPI 422 是因为接口要求 Form 但调用方发 JSON。这些经历让我更重视从路由、请求体、框架校验、日志和 trace 层面定位 Agent 工程问题。

### 5 分钟版本

> 如果时间更充分，我会把这个项目讲成一个“可观测、可评测、可控权”的智能客服 Agent Runtime。
>
> 首先是可编排。LangGraph 主图负责路由，子图负责复杂工具调用，state 负责在节点之间传递上下文。这样系统不是靠一个 prompt 隐式决定所有事情，而是把决策过程拆成可观察的步骤。
>
> 其次是多工具。电商客服问题不是一种数据源能解决的：商品、库存、供应商适合图数据库；固定高频查询适合预定义 Cypher；灵活 schema 问题适合 Text2Cypher；售后政策和说明文档适合 GraphRAG。因此项目里用 tool_selection 选择工具，而不是所有问题都走同一个检索器。
>
> 第三是工程化。FastAPI 提供真实接口，SSE 支持流式输出，会话和 thread_id 支持多轮上下文，模型工厂支持本地和在线模型切换，Redis 语义缓存降低重复问答成本，文件上传链路具备索引构建基础。
>
> 最后是下一步演进。我不会把当前项目说成已经完全生产级，而是会主动讲还需要补 Agent trace、只读 Cypher 安全层、持久化 checkpointer、文件问答闭环、小型 eval 数据集和 groundedness 评测。这样项目的深度不只体现在用了哪些框架，而体现在我知道一个 Agent 系统要怎样从 demo 走向可维护服务。

## 8. 建议你按这个顺序实践

1. 路由实践：准备 20 条问题，覆盖普通问答、补充信息、图谱查询、图片、文件，记录 router 分类、路由理由和最终节点。
2. 图谱实践：准备 10 条商品问题，分别走预定义 Cypher 和 Text2Cypher，保存生成的 Cypher、执行结果、错误信息和最终回答。
3. GraphRAG 实践：上传一份售后政策文档，构建索引，记录索引产物、构建耗时和一次查询结果。
4. 接口实践：用 JSON、multipart、缺参请求测试 `/api/langgraph/query`，确认兼容性和错误返回。
5. 缓存实践：用近义问题验证 Redis 语义缓存命中率、误命中和阈值影响。
6. 可观测性实践：给每次 Agent 请求输出 trace，包括 request_id、thread_id、router、tool、Cypher、耗时、错误和最终回答。
7. 评测实践：做一个小型 eval 表格，包含问题、期望路由、实际路由、期望工具、实际工具、答案是否正确、失败原因。
8. 安全实践：给 Cypher 执行层加只读限制，验证 DELETE、CREATE、MERGE、SET 等写操作不会执行。
9. 简历实践：把上述实践结果整理成 3 到 5 个数字，例如路由准确率、工具选择准确率、缓存命中延迟下降、GraphRAG 索引耗时、Text2Cypher 成功率。

## 9. 你可以补到项目里的加分功能

1. Agent trace 页面：展示一次请求经过哪些节点、选择了哪些工具、每步耗时多少、哪里失败。
2. Cypher 安全层：只允许只读查询，禁止 DELETE、CREATE、MERGE、SET，并对节点、关系和字段做白名单校验。
3. 持久化 checkpointer：把 MemorySaver 替换成 SQLite 或 Postgres，让中断恢复不依赖进程内存。
4. 文件问答闭环：打通 `file-query` 到用户 GraphRAG 索引，支持按 user_id 和 dataset_id 查询。
5. 业务工具 mock：查订单、查库存、创建售后单、推荐相似商品，用来展示真实客服工具调用。
6. 小型自动评测：固定问题集跑路由准确率、工具选择准确率、Text2Cypher 成功率和回答 groundedness。
7. 人工确认节点：对退款、取消订单、创建售后单等高风险操作加入 interrupt/resume 和人工确认。
8. 成本与延迟看板：记录每个模型、每个节点、每个工具的调用耗时、token 成本和错误率。

## 10. 简历和面试表达可以落成的成果指标

如果要把这个项目写进简历，不要只写“基于 LangGraph 和 GraphRAG 实现智能客服”。更有说服力的是把能力和指标绑定：

- 设计 LangGraph 多分支 Agent 流程，将用户问题路由到普通问答、图谱查询、图片和文件链路，并通过 trace 记录节点执行过程。
- 构建 GraphRAG + Neo4j + Text2Cypher 多工具子图，支持结构化商品查询、文档知识检索和工具结果总结。
- 接入 FastAPI 和 SSE，实现 Agent 流式响应、会话管理、文件上传和中断恢复入口。
- 实现 Redis 语义缓存，用 embedding 命中近义客服问题，降低重复问答延迟和模型调用次数。
- 建立小型 eval 集，评估路由准确率、工具选择准确率、Text2Cypher 执行成功率和答案 groundedness。

可以准备这些数字：

1. 路由准确率：20 到 50 条人工标注问题中，Router 分类正确比例。
2. 工具选择准确率：图谱类问题中，tool_selection 选择预定义 Cypher、Text2Cypher、GraphRAG 是否符合预期。
3. Text2Cypher 成功率：生成 Cypher 能成功执行并返回合理结果的比例。
4. 缓存收益：缓存命中前后平均延迟、P95 延迟、模型调用次数下降比例。
5. 索引成本：GraphRAG 构建一个样本文档索引的耗时和产物规模。

## 合理性批判/不足分析

1. 当前项目的面试亮点很多，但不能平均展开。最稳的主线是 LangGraph 编排、GraphRAG/Text2Cypher 子图、真实接口排障、可观测性和评测；图片分支、文件问答、幻觉检测等能力如果没有端到端验证，应作为后续规划而不是核心成果。
2. Text2Cypher 和工具调用是亮点，也是风险点。面试中必须主动讲 schema 约束、只读限制、执行前校验和日志追踪，否则容易被追问“模型生成错误查询怎么办”。
3. 语义缓存当前更适合 demo 或小规模数据。如果实现仍是 Redis 向量线性扫描，规模变大后会有性能瓶颈；更专业的说法是把它定位为早期性能优化，并说明下一步会升级到向量索引和 metadata 过滤。
4. 文件知识库链路需要谨慎表述。上传和索引构建不等于完整文档问答；只有打通 `file-query`、用户隔离、索引状态和查询效果验证后，才能说是端到端闭环。
5. 项目后续真正能支撑 Agent 开发求职的，不是继续堆更多模型入口，而是补齐 trace、eval、安全权限、human-in-the-loop 和可复盘失败案例。这些能力更能证明你理解 Agent 工程化，而不是只会调用大模型 API。
