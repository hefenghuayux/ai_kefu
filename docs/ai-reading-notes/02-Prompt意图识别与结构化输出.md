# 第二阶段：Prompt、意图识别与结构化输出

本阶段目标：从“会调用模型”升级到“会控制模型行为”。这个项目里，Prompt 不是几句提示语，而是 Agent 流程控制的一部分。

对应代码：

- `deepseek_agent/llm_backend/app/lg_agent/lg_prompts.py`
- `deepseek_agent/llm_backend/app/lg_agent/lg_states.py`
- `deepseek_agent/llm_backend/app/lg_agent/lg_builder.py`
- `deepseek_agent/llm_backend/main.py`

## 1. LangGraph 入口：`/api/langgraph/query`

先看 `main.py` 的 `/api/langgraph/query`。

接口参数：

```python
async def langgraph_query(
    query: str = Form(...),
    user_id: int = Form(...),
    conversation_id: Optional[str] = Form(None),
    image: Optional[UploadFile] = File(None)
):
```

它和普通 `/api/chat` 的区别是：

- `/api/chat` 直接把 messages 交给模型。
- `/api/langgraph/query` 会进入 LangGraph 状态图，先路由，再决定要不要查知识库、图片、文件或普通回答。

代码里使用：

```python
thread_id = conversation_id if conversation_id else new_uuid()
thread_config = {
    "configurable": {
        "thread_id": thread_id,
        "user_id": user_id,
        "image_path": str(image_path) if image_path else None
    }
}
```

`thread_id` 是 LangGraph 记忆状态的关键。它让同一个会话可以复用历史状态。

新会话走：

```python
input_state = InputState(messages=query)
async for c, metadata in graph.astream(
    input=input_state,
    stream_mode="messages",
    config=thread_config
):
```

已有会话走：

```python
graph.astream(
    Command(resume=query),
    stream_mode="messages",
    config=thread_config
)
```

这说明 LangGraph Agent 不是简单函数调用，而是有状态的流程执行器。

## 2. 状态定义：模型输出为什么要结构化

看 `lg_states.py`：

```python
class Router(TypedDict):
    logic: str
    type: Literal[
        "general-query",
        "additional-query",
        "graphrag-query",
        "image-query",
        "file-query"
    ]
    question: str = field(default_factory=str)
```

Router 结构包含三部分：

- `type`：最终分类结果。
- `logic`：模型给出的分类理由。
- `question`：问题本身或改写后的问题。

为什么不用模型直接输出一句话？

因为后续 `route_query` 要根据 `type` 做条件分支：

```python
if _type == "general-query":
    return "respond_to_general_query"
elif _type == "additional-query":
    return "get_additional_info"
elif _type == "graphrag-query":
    return "create_research_plan"
elif _type == "image-query":
    return "create_image_query"
elif _type == "file-query":
    return "create_file_query"
```

如果模型自由输出：

```text
这个问题大概需要查一下数据库
```

程序很难稳定解析。

结构化输出把模型变成“分类器”：

```json
{
  "type": "graphrag-query",
  "logic": "用户询问商品库存，需要查询本地知识库"
}
```

这就是 Agent 工程里的关键思想：让模型输出可以被程序消费的数据，而不是只给人看的自然语言。

## 3. Router Prompt：五类意图怎么定义

看 `lg_prompts.py` 的 `ROUTER_SYSTEM_PROMPT`。

项目把用户问题分为五类：

```text
general-query
additional-query
graphrag-query
image-query
file-query
```

### general-query

Prompt 中定义：

```text
如果是一般性问题，不需要查询知识库就能回答，请将其分类为此类。
包括但不限于：
- 与商品、订单、售后、技术支持无关的闲聊问题
```

它的含义不是“所有简单问题”，而是“不需要本地知识库”。例如：

```text
你好
你是谁
你能做什么
```

这些都可以直接回答。

### additional-query

Prompt 中定义：

```text
如果你需要更多信息才能帮助用户，请将用户询问分类为此类。
例如：
- 用户询问商品但没有提供具体型号或规格
- 用户询问订单状态但没有提供订单号
- 用户描述问题不够具体，无法提供准确帮助
```

典型例子：

```text
我的门锁坏了怎么办？
帮我查一下订单
这个多少钱？
```

这些问题不是无关，也不是能直接查。缺槽位。

### graphrag-query

Prompt 中定义：

```text
如果通过查询本地知识库可以回答用户询问，请将其分类为此类。
包括：
- 商品价格、库存、规格
- 订单状态、物流信息
- 会员积分、优惠活动
- 退换货政策
- 商品使用指导及故障解决方法
```

这是项目最核心的分支，后面会进入多 Agent、Neo4j、GraphRAG。

### image-query

用户上传图片时使用。代码里还有一层规则：

```python
if hasattr(state, "config") and state.config and state.config.get("configurable", {}).get("image_path"):
    return "create_image_query"
```

也就是说，即使 Router 没分到图片，只要配置里发现 `image_path`，也会优先按图片处理。

### file-query

用于文件解析。不过当前 `create_file_query` 还是 `TODO`，所以这条链路在代码中没有完整实现。

## 4. Router 节点：Prompt 如何变成流程分支

看 `lg_builder.py` 的 `analyze_and_route_query`。

模型选择：

```python
if settings.AGENT_SERVICE == ServiceType.DEEPSEEK:
    model = ChatDeepSeek(...)
else:
    model = ChatOllama(...)
```

构造消息：

```python
messages = [
    {"role": "system", "content": ROUTER_SYSTEM_PROMPT}
] + state.messages
```

结构化输出：

```python
response = cast(
    Router, await model.with_structured_output(Router).ainvoke(messages)
)
return {"router": response}
```

核心是：

```python
model.with_structured_output(Router)
```

这会要求模型按照 `Router` 类型返回。你可以把它理解成“让大模型按指定 schema 填表”。

后面 LangGraph 读取 `state.router["type"]`，进入不同节点。

```text
用户问题
  -> ROUTER_SYSTEM_PROMPT
  -> ChatDeepSeek / ChatOllama
  -> Router(type, logic, question)
  -> route_query
  -> 下一个节点
```

## 5. `general-query`：直接回答，不查外部服务

看 `respond_to_general_query`：

```python
system_prompt = GENERAL_QUERY_SYSTEM_PROMPT.format(
    logic=state.router["logic"]
)

messages = [{"role": "system", "content": system_prompt}] + state.messages
response = await model.ainvoke(messages)
return {"messages": [response]}
```

这里把 Router 的分类理由塞回 Prompt：

```text
系统已确定用户正在提出一般性问题，不需要查询特定数据库即可回答。
以下是分类理由：
{logic}
```

这不是为了展示给用户，而是为了让回答模型知道：

- 当前不应该调用知识库。
- 应该按普通客服风格简短回答。

这种写法体现了多节点 Agent 的一个常见模式：

```text
上游节点的判断结果 -> 下游节点的上下文
```

## 6. `additional-query`：缺信息时先过护栏，再追问

看 `get_additional_info`。

它先连接 Neo4j：

```python
neo4j_graph = get_neo4j_graph()
```

然后构造经营范围：

```python
scope_description = """
个人电商经营范围：智能家居产品，包括但不限于：
- 智能照明
- 智能安防
- 智能控制
- 智能音箱
- 智能厨电
- 智能清洁

不包含：服装、鞋类、体育用品、化妆品、食品等非智能家居产品。
"""
```

再动态获取图数据库 Schema：

```python
retrieve_and_parse_schema_from_graph_for_prompts(neo4j_graph)
```

最后用 `GUARDRAILS_SYSTEM_PROMPT` 判断是否继续：

```python
guardrails_chain = full_system_prompt | model.with_structured_output(AdditionalGuardrailsOutput)
guardrails_output = await guardrails_chain.ainvoke(...)
```

如果模型输出：

```json
{"decision": "end"}
```

就拒答：

```python
return {"messages": [AIMessage(content="抱歉，我家暂时没有这方面的商品，可以在别家看看哦~")]}
```

如果输出：

```json
{"decision": "continue"}
```

才进入追问：

```python
system_prompt = GET_ADDITIONAL_SYSTEM_PROMPT.format(
    logic=state.router["logic"]
)
response = await model.ainvoke(messages)
```

所以 `additional-query` 不是简单地“问用户更多信息”，它先判断这个模糊问题是否属于业务范围。

## 7. Prompt 不只是文本，而是控制流

这个项目里 Prompt 对程序流有直接影响：

| Prompt | 输出 | 控制作用 |
|---|---|---|
| `ROUTER_SYSTEM_PROMPT` | `Router.type` | 决定进入哪个主节点 |
| `GUARDRAILS_SYSTEM_PROMPT` | `continue/end` | 决定继续处理还是拒答 |
| `GENERAL_QUERY_SYSTEM_PROMPT` | 自然语言 | 生成普通客服回复 |
| `GET_ADDITIONAL_SYSTEM_PROMPT` | 自然语言 | 生成补充信息追问 |
| `CHECK_HALLUCINATIONS` | `1/0` | 设计上用于判断回答是否基于事实 |

这就是为什么 Agent 项目里 Prompt 要像代码一样维护。它不是“文案”，而是“模型程序”。

## 8. LangGraph 主图如何把节点串起来

看 `lg_builder.py` 底部：

```python
checkpointer = MemorySaver()

builder = StateGraph(AgentState, input=InputState)
builder.add_node(analyze_and_route_query)
builder.add_node(respond_to_general_query)
builder.add_node(get_additional_info)
builder.add_node("create_research_plan", create_research_plan)
builder.add_node(create_image_query)
builder.add_node(create_file_query)

builder.add_edge(START, "analyze_and_route_query")
builder.add_conditional_edges("analyze_and_route_query", route_query)

graph = builder.compile(checkpointer=checkpointer)
```

主图结构：

```text
START
  -> analyze_and_route_query
    -> respond_to_general_query
    -> get_additional_info
    -> create_research_plan
    -> create_image_query
    -> create_file_query
```

`MemorySaver` 是内存态 checkpointer，配合 `thread_id` 保存每个会话的图状态。

## 9. 图片分支：视觉模型如何接入

`create_image_query` 做了几件事：

1. 从 `config["configurable"]["image_path"]` 取图片路径。
2. 用 PIL 打开并压缩图片。
3. base64 编码图片。
4. 调用视觉模型接口。
5. 把视觉模型返回的图片描述塞进 `GET_IMAGE_SYSTEM_PROMPT`。
6. 再让普通对话模型生成客服风格回答。

也就是说图片链路是两段式：

```text
图片
  -> 视觉模型：生成 image_description
  -> 对话模型：结合用户问题和 image_description 回复
```

这比直接让视觉模型回答更可控，因为客服风格、简洁程度、业务口径由第二段 Prompt 统一控制。

## 10. 当前实现里的几个重要风险

1. `create_file_query` 是 `TODO`，所以 `file-query` 分支未完整落地。
2. `check_hallucinations` 函数已经写了，但主图里没有 `add_node(check_hallucinations)`，也没有边连接它。也就是说当前主链路没有真正执行幻觉检测。
3. `route_query` 里检查图片路径用了 `hasattr(state, "config")`，但 `AgentState` 定义里没有 `config` 字段。实际能否取到取决于 LangGraph 运行时状态结构，建议运行时验证。
4. `InputState(messages=query)` 这里 `messages` 类型声明是消息列表，但传入的是字符串。LangGraph 可能会帮忙转换，也可能在特定版本下出问题，建议实测。

## 11. 建议你做的 30 条意图识别练习

自己准备类似下面的问题：

```text
你好
你们有哪些智能音箱？
帮我查订单
订单 10248 到哪了？
这个门锁怎么重置？
我上传的图片里是什么型号？
这份说明书帮我总结一下
我要买一件羽绒服
```

然后建一个表：

| 问题 | 人工标签 | Router 输出 | 是否正确 | 错因 |
|---|---|---|---|---|
| 帮我查订单 | additional-query | ? | ? | 缺订单号 |
| 订单 10248 到哪了 | graphrag-query | ? | ? | 可查知识库 |

这个练习能让你理解：Prompt 优化本质上是分类边界优化，不是单纯“把提示写长”。

## 12. 本阶段方案的不足

当前 Router 完全依赖大模型结构化输出，优点是灵活，缺点是稳定性和成本不如轻量分类模型。项目说明里提到可以通过难负样本和 few-shot 迭代提高 F1，但仓库当前代码没有看到离线评估脚本、样本集和自动化指标计算。因此学习时要区分“代码中已实现的路由能力”和“项目描述中的优化方法”。

