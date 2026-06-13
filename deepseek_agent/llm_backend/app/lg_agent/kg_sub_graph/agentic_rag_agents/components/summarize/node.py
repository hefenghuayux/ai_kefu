"""
This code is based on content found in the LangGraph documentation: https://python.langchain.com/docs/tutorials/graph/#advanced-implementation-with-langgraph
"""

from typing import Any, Callable, Coroutine, Dict

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser

from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.state import OverallState
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.summarize.prompts import create_summarization_prompt_template
from app.core.logger import get_logger, log_event
import time

generate_summary_prompt = create_summarization_prompt_template()
logger = get_logger(service="summarize_node")


def create_summarization_node(
    llm: BaseChatModel,
) -> Callable[[OverallState], Coroutine[Any, Any, dict[str, Any]]]:
    """
    Create a Summarization node for a LangGraph workflow.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM do perform processing.

    Returns
    -------
    Callable[[OverallState], OutputState]
        The LangGraph node.
    """

    generate_summary = generate_summary_prompt | llm | StrOutputParser()

    async def summarize(state: OverallState) -> Dict[str, Any]:
        """
        Summarize results of the performed Cypher queries.
        """
        started = time.perf_counter()
        results = []
        
        # 使用直接属性访问而不是get方法
        for cypher in state.get("cyphers", list()):
            # 检查是否是字典类型，使用get方法
            if isinstance(cypher, dict) and cypher.get("records") is not None:
                results.append(cypher.get("records"))
            # 检查是否是Pydantic模型，使用直接属性访问
            elif hasattr(cypher, "records") and cypher.records is not None:
                results.append(cypher.records)
                
        if results:
            try:
                summary = await generate_summary.ainvoke(
                    {
                        "question": state.get("question"),
                        "results": results,
                    }
                )
            except Exception as e:
                log_event(
                    logger,
                    "ERROR",
                    "node_finished",
                    phase="summarize",
                    node="summarize",
                    status="failed",
                    elapsed_ms=round((time.perf_counter() - started) * 1000),
                    input_query_len=len(state.get("question", "") or ""),
                    result_count=len(results),
                    error_type=e.__class__.__name__,
                    reason=str(e),
                    exception=True,
                )
                raise

        else:
            summary = "No data to summarize."

        log_event(
            logger,
            "INFO",
            "node_finished",
            phase="summarize",
            node="summarize",
            status="success",
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            input_query_len=len(state.get("question", "") or ""),
            result_count=len(results),
            result_summary_len=len(summary),
            output_len=len(summary),
            llm_output_len=len(summary),
            llm_output_preview=summary[:500],
        )
        return {"summary": summary, "steps": ["summarize"]}

    return summarize
