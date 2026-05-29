# 第四阶段：LangGraph 多 Agent、图检索与 GraphRAG

本阶段目标：理解项目最核心的 AI 实现：用户问题被 Router 分到 `graphrag-query` 后，如何进入一个多工具 Agent 子图，完成任务拆分、工具选择、Neo4j 查询、GraphRAG 查询和结果汇总。

对应代码：

- `deepseek_agent/llm_backend/app/lg_agent/lg_builder.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/workflows/multi_agent/multi_tool.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/workflows/multi_agent/edges.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/planner/node.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/tool_selection/node.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/kg_tools_list.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/predefined_cypher/node.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/cypher_tools/node.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/cypher_tools/utils.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/customer_tools/node.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/summarize/node.py`
- `deepseek_agent/llm_backend/app/lg_agent/kg_sub_graph/agentic_rag_agents/components/final_answer/node.py`

## 1. 从主图进入子图：`create_research_plan`

主图中 Router 如果输出：

```json
{"type": "graphrag-query"}
```

`route_query` 会返回：

```python
return "create_research_plan"
```

进入 `lg_builder.py` 的 `create_research_plan`。

这里做了 5 件关键事情：

```python
model = ChatDeepSeek(...) or ChatOllama(...)
neo4j_graph = get_neo4j_graph()
cypher_retriever = NorthwindCypherRetriever()
tool_schemas = [cypher_query, predefined_cypher, microsoft_graphrag_query]
predefined_cypher_dict = ...
```

然后创建多工具工作流：

```python
multi_tool_workflow = create_multi_tool_workflow(
    llm=model,
    graph=neo4j_graph,
    tool_schemas=tool_schemas,
    predefined_cypher_dict=predefined_cypher_dict,
    cypher_example_retriever=cypher_retriever,
    scope_description=scope_description,
    llm_cypher_validation=True,
)
```

最后执行：

```python
response = await multi_tool_workflow.ainvoke(input_state)
return {"messages": [AIMessage(content=response["answer"])]}
```

所以主图的 `create_research_plan` 本质上是“创建并执行一个子 Agent 图”。

## 2. 子图结构：`create_multi_tool_workflow`

看 `multi_tool.py`。

节点创建：

```python
guardrails = create_guardrails_node(...)
planner = create_planner_node(llm=llm)
cypher_query = create_cypher_query_node()
predefined_cypher = create_predefined_cypher_node(...)
customer_tools = create_graphrag_query_node()
tool_selection = create_tool_selection_node(...)
summarize = create_summarization_node(llm=llm)
final_answer = create_final_answer_node()
```

子图边：

```python
main_graph_builder.add_edge(START, "guardrails")
main_graph_builder.add_conditional_edges("guardrails", guardrails_conditional_edge)
main_graph_builder.add_conditional_edges(
    "planner",
    map_reduce_planner_to_tool_selection,
    ["tool_selection"],
)

main_graph_builder.add_edge("cypher_query", "summarize")
main_graph_builder.add_edge("predefined_cypher", "summarize")
main_graph_builder.add_edge("customer_tools", "summarize")
main_graph_builder.add_edge("summarize", "final_answer")
main_graph_builder.add_edge("final_answer", END)
```

结构图：

```text
START
  -> guardrails
    -> end: final_answer
    -> planner
      -> map each task to tool_selection
        -> predefined_cypher
        -> cypher_query
        -> customer_tools(GraphRAG)
      -> summarize
      -> final_answer
      -> END
```

这里体现了 Map-Reduce：

- Map：Planner 拆出多个 task，每个 task 进入工具选择。
- Reduce：多个工具结果汇总到 `summarize`。

## 3. 子图状态：为什么能累积多个工具结果

看 `components/state.py`：

```python
class OverallState(TypedDict):
    question: str
    tasks: Annotated[List[Task], add]
    next_action: str
    cyphers: Annotated[List[CypherOutputState], add]
    summary: str
    steps: Annotated[List[str], add]
    history: Annotated[List[HistoryRecord], update_history]
```

`Annotated[List[...], add]` 表示多个节点返回的列表会合并。

例如 Planner 拆出两个任务：

```text
任务 1：查询智能门锁库存
任务 2：查询智能门锁退换货政策
```

两个任务分别执行工具后，都会返回：

```python
{"cyphers": [结果]}
```

由于 `cyphers` 使用 `add` 聚合，最终 state 里会有多个查询结果。

## 4. Guardrails：进入知识库前先做范围检查

看 `guardrails/node.py`。

创建 Prompt：

```python
guardrails_prompt = create_guardrails_prompt_template(
    graph=graph,
    scope_description=scope_description
)
```

结构化输出：

```python
guardrails_chain = guardrails_prompt | llm.with_structured_output(GuardrailsOutput)
```

`GuardrailsOutput`：

```python
class GuardrailsOutput(BaseModel):
    decision: Literal["end", "planner"]
```

如果输出 `end`：

```python
summary = "抱歉，我家暂时没有这方面的商品，可以在别家看看哦~"
```

如果输出 `planner`，继续任务规划。

`guardrails/prompts.py` 里把两个上下文塞给模型：

```python
scope_context = f"参考此范围描述来决策:\n{scope_description}"
graph_context = f"\n参考图表结构来回答:\n{retrieve_and_parse_schema_from_graph_for_prompts(graph)}"
```

这意味着护栏不是只靠业务描述，还会动态参考 Neo4j Schema。

## 5. Planner：为什么要先拆任务

看 `planner/node.py`。

核心链：

```python
planner_chain = planner_prompt | llm.with_structured_output(PlannerOutput)
```

`PlannerOutput`：

```python
class PlannerOutput(BaseModel):
    tasks: List[Task]
```

`Task`：

```python
class Task(BaseModel):
    question: str
    parent_task: str
    requires_visualization: bool = False
```

执行：

```python
planner_output = await planner_chain.ainvoke(
    {"question": state.get("question", "")}
)
```

如果模型没拆出任务：

```python
planner_output.tasks or [
    Task(
        question=state.get("question", ""),
        parent_task=state.get("question", ""),
    )
]
```

为什么要拆？

因为复杂问题可能涉及不同数据源：

```text
某款智能门锁库存还有多少？如果坏了能不能退？
```

可以拆成：

```text
1. 某款智能门锁库存还有多少？
2. 某款智能门锁坏了是否可以退换？
```

第一个适合 Neo4j 结构化查询；第二个适合 GraphRAG 查售后政策。

如果不拆，工具选择会很困难，可能一个工具回答不了全部问题。

## 6. Map：每个任务进入工具选择

看 `edges.py`：

```python
def map_reduce_planner_to_tool_selection(state: OverallState) -> List[Send]:
    return [
        Send(
            "tool_selection",
            {
                "question": task.question,
                "parent_task": task.parent_task,
            },
        )
        for task in state.get("tasks", list())
    ]
```

这段是 LangGraph Map-Reduce 的关键。

它把每个 task 都发送到 `tool_selection`：

```text
tasks = [task1, task2, task3]
  -> Send("tool_selection", task1)
  -> Send("tool_selection", task2)
  -> Send("tool_selection", task3)
```

这些子任务可以独立处理，最后结果汇总。

## 7. Tool Selection：模型如何选择工具

看 `tool_selection/node.py`。

工具选择链：

```python
tool_selection_chain = (
    tool_selection_prompt
    | llm.bind_tools(tools=tool_schemas)
    | PydanticToolsParser(tools=tool_schemas, first_tool_only=True)
)
```

工具 schema 来自 `kg_tools_list.py`：

```python
class cypher_query(BaseModel):
    """如果用户问的是关于产品价格、库存、规格等，则使用这个工具，生成Cypher查询语句进行查询"""
    task: str

class predefined_cypher(BaseModel):
    """这个工具包含预定义的Cypher查询语句，用于快速响应各种电商场景的查询需求。"""
    query: str
    parameters: dict

class microsoft_graphrag_query(BaseModel):
    """如果用户问的问题是关于产品的故障、售后、保修、维修、退换货以及评价等，则使用这个工具"""
    query: str
```

模型不是自由回答，而是在这些工具中选一个，并生成参数。

路由逻辑：

```python
if tool_name == "predefined_cypher":
    return Command(goto=Send("predefined_cypher", ...))
elif tool_name == "cypher_query":
    return Command(goto=Send("cypher_query", ...))
else:
    return Command(goto=Send("customer_tools", ...))
```

一句话理解：

> Tool Selection 是一个由 LLM 驱动的路由器，它根据单个子任务选择结构化查询、预定义查询或 GraphRAG。

## 8. 什么时候走预定义 Cypher

预定义 Cypher 适合高频、稳定、参数明确的问题。

看 `predefined_cypher/cypher_dict.py`：

```python
"product_by_name": "MATCH (p:Product) WHERE p.ProductName CONTAINS $product_name RETURN ...",
"order_by_id": "MATCH (o:Order) WHERE o.orderId = $order_id RETURN ...",
"product_reviews": "MATCH (p:Product)<-[:ABOUT]-(r:Review) WHERE p.ProductName = $product_name RETURN ...",
"smart_speakers": "MATCH (p:Product)-[:BELONGS_TO]->(c:Category) WHERE c.CategoryName = '智能音箱' RETURN ..."
```

执行节点 `predefined_cypher/node.py`：

```python
statement = predefined_cypher_dict.get(params.get("query"))
records = graph.query(query=statement, params=parameters)
```

优势：

- 快。
- 稳。
- 不容易生成错误 Cypher。
- 适合库存、价格、订单、分类等固定查询。

不足：

- 覆盖不了长尾问题。
- 依赖工具选择模型正确填 `query` 和 `parameters`。

## 9. 什么时候走 Text2Cypher

Text2Cypher 适合结构化数据问题，但没有命中预定义模板的情况。

看 `cypher_tools/node.py`：

```python
cypher_generation = create_text2cypher_generation_node(
    llm=model,
    graph=neo4j_graph,
    cypher_example_retriever=cypher_retriever
)

cypher_result = await cypher_generation(state)
```

生成逻辑在 `cypher_tools/utils.py`：

```python
examples = cypher_example_retriever.get_examples(
    **{"query": task, "k": 3}
)

generated_cypher = await text2cypher_chain.ainvoke(
    {
        "question": state.get("task", ""),
        "fewshot_examples": examples,
        "schema": graph.schema,
    }
)
```

Text2Cypher Prompt 里要求：

```text
根据输入的问题，将其转换为Cypher查询语句。
不要添加任何前言。
只返回Cypher语句。
只使用MATCH或WITH子句开始查询。
```

它给模型三类信息：

1. 用户问题。
2. Neo4j Schema。
3. Few-shot Cypher 示例。

这样模型更容易生成符合数据库结构的查询。

## 10. Text2Cypher 的校验链

生成 Cypher 后会校验：

```python
validate_cypher = create_text2cypher_validation_node(
    llm=model,
    graph=neo4j_graph,
    llm_validation=True,
    cypher_statement=cypher_result
)

execute_info = await validate_cypher(state=state)
```

校验包括：

### 语法预检

```python
graph.query(f"EXPLAIN {cypher_statement}")
```

`EXPLAIN` 只检查语法和执行计划，不真正执行查询。

### 禁止写操作

```python
WRITE_CLAUSES = {
    "CREATE", "DELETE", "DETACH DELETE", "SET", "REMOVE", "FOREACH", "MERGE"
}
```

这是防止模型生成会修改数据库的语句。

### 关系方向修正

```python
CypherQueryCorrector(corrector_schema)
```

Neo4j 关系有方向，方向错了可能查不到数据。这里借 LangChain 的 corrector 修正。

### LLM 语义校验

```python
validate_cypher_chain = validation_prompt_template | llm.with_structured_output(ValidateCypherOutput)
```

模型检查：

- 节点标签是否存在。
- 属性名是否存在。
- 是否足以回答问题。
- 属性值是否映射到数据库。

### 执行

```python
records = graph.query(cypher_statement)
```

结果包装成：

```python
CypherOutputState(
    task=...,
    statement=cypher_statement,
    records=records,
    errors=...,
    steps=...
)
```

## 11. 什么时候走 GraphRAG

GraphRAG 工具定义：

```python
class microsoft_graphrag_query(BaseModel):
    """如果用户问的问题是关于产品的故障、售后、保修、维修、退换货以及评价等，则使用这个工具"""
    query: str
```

适合：

- 故障处理
- 保修政策
- 售后说明
- 使用手册
- 非结构化文档问答

执行节点在 `customer_tools/node.py`。

初始化 GraphRAG：

```python
self.project_dir = project_dir or settings.GRAPHRAG_PROJECT_DIR
self.data_dir_name = data_dir_name or settings.GRAPHRAG_DATA_DIR
self.query_type = query_type or settings.GRAPHRAG_QUERY_TYPE
```

加载数据：

```python
self.entities = await load_table_from_storage("entities", self.storage)
self.text_units = await load_table_from_storage("text_units", self.storage)
self.communities = await load_table_from_storage("communities", self.storage)
self.community_reports = await load_table_from_storage("community_reports", self.storage)
self.relationships = await load_table_from_storage("relationships", self.storage)
```

这说明 GraphRAG 查询依赖离线构建好的索引产物。

## 12. GraphRAG 四种查询方式

`query_graphrag` 支持：

```python
if self.query_type.lower() == "local":
    response, context = await api.local_search(...)
elif self.query_type.lower() == "global":
    response, context = await api.global_search(...)
elif self.query_type.lower() == "drift":
    response, context = await api.drift_search(...)
elif self.query_type.lower() == "basic":
    response, context = await api.basic_search(...)
```

理解方式：

| 查询类型 | 适合问题 | 依赖 |
|---|---|---|
| basic | 简单片段匹配 | text_units |
| local | 围绕实体的局部问题 | entities、relationships、text_units |
| global | 全局总结、概览类问题 | communities、community_reports |
| drift | 多轮上下文下动态转移焦点 | entities、communities、relationships |

项目配置默认：

```python
GRAPHRAG_QUERY_TYPE: str = "local"
```

所以默认更偏向实体局部检索。

## 13. Summarize：为什么查询后还要摘要

无论是 Cypher 还是 GraphRAG，工具节点返回的都是结构化结果。用户不能直接看原始 records。

看 `summarize/node.py`：

```python
for cypher in state.get("cyphers", list()):
    if isinstance(cypher, dict) and cypher.get("records") is not None:
        results.append(cypher.get("records"))
    elif hasattr(cypher, "records") and cypher.records is not None:
        results.append(cypher.records)
```

然后：

```python
summary = await generate_summary.ainvoke(
    {
        "question": state.get("question"),
        "results": results,
    }
)
```

Prompt 要求：

```text
根据上述事实信息，以亲切的电商客服口吻回答用户问题
当事实不为空时，只使用这些信息构建回答
```

所以 `summarize` 的作用：

- 把多个工具结果合并。
- 转成客服自然语言。
- 约束模型只基于事实回答。

## 14. Final Answer：最终返回和历史记录

看 `final_answer/node.py`：

```python
answer = state.get("summary", " ")

history_record = {
    "question": state.get("question", ""),
    "answer": answer,
    "cyphers": [
        {
            "task": ...,
            "records": ...,
        }
        for c in state.get("cyphers", list())
    ],
}
```

最终返回：

```python
return {
    "answer": answer,
    "steps": ["final_answer"],
    "history": [history_record],
}
```

它没有再调用模型，只是把 `summary` 作为最终答案，同时保存历史记录。

## 15. 用一个问题串完整链路

问题：

```text
某款智能门锁库存还有多少？如果坏了能不能退？
```

完整流程：

```text
Router
  -> graphrag-query

create_research_plan
  -> 创建 multi_tool_workflow

guardrails
  -> 判断属于智能家居售后/商品范围
  -> planner

planner
  -> 任务1：某款智能门锁库存还有多少？
  -> 任务2：某款智能门锁坏了能不能退？

tool_selection(任务1)
  -> predefined_cypher 或 cypher_query
  -> Neo4j 查询 Product.UnitsInStock

tool_selection(任务2)
  -> microsoft_graphrag_query
  -> GraphRAG 查售后政策/退换货说明

summarize
  -> 合并库存结果和售后政策

final_answer
  -> 返回客服风格答案
```

## 16. 当前实现里必须注意的问题

1. `tool_selection/node.py` 里 `go_to_text2cypher` 被引用，但当前文件中没有定义。如果模型没有选择任何工具并进入该分支，会报错。
2. `cypher_tools/utils.py` 中纠错链调用：

   ```python
   corrected_cypher_update = correct_cypher_chain.ainvoke(...)
   corrected_cypher = corrected_cypher_update
   ```

   这里少了 `await`，`corrected_cypher` 可能变成 coroutine，而不是字符串。

3. `customer_tools/node.py` 中 GraphRAG 查询失败时，`search_result` 可能为空，但后面使用 `search_result["response"]`，有潜在 KeyError。
4. `check_hallucinations` 在主图中没有接入，所以当前不是完整“幻觉拦截链”。
5. 子图每次 `create_research_plan` 都创建 `multi_tool_workflow`，如果调用频繁，可能有重复构建成本。

## 17. 本阶段自测问题

1. Planner 为什么不能和 Tool Selection 合成一个节点？
2. 预定义 Cypher 和 Text2Cypher 分别适合什么问题？
3. GraphRAG 为什么需要离线索引？
4. `Annotated[List[...], add]` 在多任务结果汇总里起什么作用？
5. 为什么查询结果不能直接返回用户，而要经过 `summarize`？

## 18. 本阶段方案的不足

这个阶段是项目的核心，但代码里仍有一些半成品痕迹：幻觉检测未接入、文件分支未完成、工具选择失败分支存在未定义变量、Text2Cypher 纠错少 `await`。所以学习时应该把它当成“多 Agent 架构样板”来理解，同时对工程完整性保持审慎，不要把简历描述中的所有指标都默认视为当前代码已经完整实现。

