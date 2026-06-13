from typing import Any, Callable, Coroutine

from ...components.state import OverallState
from app.core.logger import get_logger, log_event
import time


logger = get_logger(service="final_answer_node")


def create_final_answer_node() -> (
    Callable[[OverallState], Coroutine[Any, Any, dict[str, Any]]]
):
    """
    Create a final_answer node for a LangGraph workflow.

    Parameters
    ----------
    llm : BaseChatModel
        The LLM do perform processing.

    Returns
    -------
    Callable[[OverallState], OutputState]
        The LangGraph node.
    """

    async def final_answer(state: OverallState) -> dict[str, Any]:
        """
        Construct a final answer.
        """
        started = time.perf_counter()

        answer = state.get("summary", " ")
        cyphers = state.get("cyphers", list())

        history_record = {
            "question": state.get("question", ""),
            "answer": answer,
            "cyphers": [
                {
                    "task": c.task if hasattr(c, "task") else c.get("task", ""),
                    "records": c.records if hasattr(c, "records") else c.get("records", {}),
                }
                for c in state.get("cyphers", list())
            ],
        }

        log_event(
            logger,
            "INFO",
            "node_finished",
            phase="final_answer",
            node="final_answer",
            status="success",
            elapsed_ms=round((time.perf_counter() - started) * 1000),
            input_query_len=len(state.get("question", "") or ""),
            result_count=len(cyphers),
            output_len=len(answer),
            llm_output_len=len(answer),
            llm_output_preview=answer[:500],
        )

        return {
            "answer": answer,
            "steps": ["final_answer"],
            "history": [history_record],
        }

    return final_answer
