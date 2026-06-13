from typing import Any, Callable, Coroutine, Dict, List

from langchain_neo4j import Neo4jGraph
from langchain_core.language_models import BaseChatModel

from app.lg_agent.kg_sub_graph.agentic_rag_agents.constants import NO_CYPHER_RESULTS
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.state import PredefinedCypherInputState
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.text2cypher.state import CypherOutputState
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.predefined_cypher.utils import create_vector_query_matcher
from app.lg_agent.kg_sub_graph.agentic_rag_agents.components.predefined_cypher.descriptions import QUERY_DESCRIPTIONS
from app.core.logger import get_logger, log_event
import time


logger = get_logger(service="predefined_cypher")


def create_predefined_cypher_node(
    graph: Neo4jGraph, predefined_cypher_dict: Dict[str, str]
) -> Callable[
    [PredefinedCypherInputState],
    Coroutine[Any, Any, Dict[str, List[CypherOutputState] | List[str]]],
]:
    """
    Create a predefined Cypher execution node for a LangGraph workflow.

    Parameters
    ----------
    graph : Neo4jGraph
        The Neo4j graph wrapper.
    predefined_cypher_dict : Dict[str, str]
        A Python dictionary with Cypher query names as keys and parameterized Cypher queries as values.

    Returns
    -------
    Callable[[PredefinedCypherInputState], Dict[str, List[CypherOutputState] | List[str]]]
        The LangGraph node named `predefined_cypher`.
    """
    async def predefined_cypher(
        state: PredefinedCypherInputState,
    ) -> Dict[str, List[CypherOutputState] | List[str]]:
        """
        Executes a predefined Cypher statement with found parameters.
        """
        started = time.perf_counter()
        errors = list()

        statement_name = state.get("query_name", "")
        task = state.get("task", "")
        params = state.get(
            "query_parameters", dict()
        )  
        log_event(
            logger,
            "INFO",
            "node_started",
            phase="tool_execution",
            node="predefined_cypher",
            tool="predefined_cypher",
            status="started",
            input_query_len=len(task),
            task_len=len(task),
            query_name=statement_name,
        )
        print("statement_name", statement_name)
        print("params", params)
        
        # 将parameters中的每个值转换为字符串
        parameters = params.get("parameters", {})
        for key, value in parameters.items():
            parameters[key] = str(value)
        
        statement = predefined_cypher_dict.get(params.get("query"))
        print("statement", statement)
        if statement is not None:
            query_started = time.perf_counter()
            log_event(
                logger,
                "INFO",
                "neo4j_query_started",
                phase="tool_execution",
                node="predefined_cypher",
                tool="predefined_cypher",
                status="started",
                operation="execute_predefined_cypher",
                query_name=params.get("query") or statement_name,
                cypher_len=len(statement),
                cypher_preview=statement[:500],
            )
            try:
                records = graph.query(query=statement, params=parameters)
                log_event(
                    logger,
                    "INFO",
                    "neo4j_query_finished",
                    phase="tool_execution",
                    node="predefined_cypher",
                    tool="predefined_cypher",
                    status="success",
                    operation="execute_predefined_cypher",
                    query_name=params.get("query") or statement_name,
                    elapsed_ms=round((time.perf_counter() - query_started) * 1000),
                    result_count=len(records or []),
                    rows=len(records or []),
                )
            except Exception as e:
                log_event(
                    logger,
                    "ERROR",
                    "neo4j_query_finished",
                    phase="tool_execution",
                    node="predefined_cypher",
                    tool="predefined_cypher",
                    status="failed",
                    operation="execute_predefined_cypher",
                    query_name=params.get("query") or statement_name,
                    elapsed_ms=round((time.perf_counter() - query_started) * 1000),
                    error_type=e.__class__.__name__,
                    reason=str(e),
                    exception=True,
                )
                raise
            print(f"records: {records}")
            
        else:
            errors.append(
                f"Unable to find the specified Cypher statement: {statement_name}"
            )
            records = list()
            log_event(
                logger,
                "WARNING",
                "neo4j_query_finished",
                phase="tool_execution",
                node="predefined_cypher",
                tool="predefined_cypher",
                status="failed",
                operation="execute_predefined_cypher",
                query_name=statement_name,
                elapsed_ms=round((time.perf_counter() - started) * 1000),
                result_count=0,
                rows=0,
                reason=errors[-1],
            )

        log_event(
            logger,
            "INFO",
            "node_finished",
            phase="tool_execution",
            node="predefined_cypher",
            tool="predefined_cypher",
            status="success" if not errors else "failed",
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            input_query_len=len(task),
            task_len=len(task),
            query_name=params.get("query") or statement_name,
            cypher_len=len(statement or ""),
            cypher_preview=(statement or "")[:500],
            result_count=len(records or []),
            rows=len(records or []),
            result_summary_len=len(str(records or [])),
        )

        return {
            "cyphers": [
                CypherOutputState(
                    **{
                        "task": state.get("task", ""),
                        "statement": statement or "",
                        "parameters": params,
                        "errors": errors,
                        "records": records or NO_CYPHER_RESULTS,
                        "steps": ["execute_predefined_cypher"],
                    }
                )
            ],
            "steps": ["execute_predefined_cypher"],
        }

    return predefined_cypher
