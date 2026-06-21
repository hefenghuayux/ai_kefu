from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

from .permissions import ToolPolicy


@dataclass(frozen=True)
class ForkedAgentStep:
    content: str
    tool_calls: int = 0
    denied_tool_calls: int = 0
    should_continue: bool = False


ForkedAgentRunner = Callable[[int, "ForkedAgentRequest"], Awaitable[ForkedAgentStep] | ForkedAgentStep]


@dataclass(frozen=True)
class ForkedAgentRequest:
    prompt_messages: list[dict[str, str]]
    query_source: str
    fork_label: str
    tool_policy: ToolPolicy
    skip_transcript: bool = True
    max_turns: int = 5
    runner: ForkedAgentRunner | None = None


@dataclass(frozen=True)
class ForkedAgentResult:
    status: str
    content: str
    tool_calls: int
    denied_tool_calls: int
    elapsed_ms: int
    error_type: str | None = None


async def run_forked_agent(
    request: ForkedAgentRequest,
) -> ForkedAgentResult:
    started_at = time.perf_counter()
    if request.max_turns <= 0:
        return ForkedAgentResult(
            status="failed",
            content="",
            tool_calls=0,
            denied_tool_calls=0,
            elapsed_ms=_elapsed_ms(started_at),
            error_type="InvalidMaxTurns",
        )

    try:
        if request.runner is None:
            content = _default_single_turn_content(request.prompt_messages)
            return ForkedAgentResult(
                status="completed",
                content=content,
                tool_calls=0,
                denied_tool_calls=0,
                elapsed_ms=_elapsed_ms(started_at),
            )

        content_parts: list[str] = []
        tool_calls = 0
        denied_tool_calls = 0
        stopped_by_max_turns = False
        for turn_index in range(request.max_turns):
            raw_step = request.runner(turn_index, request)
            step = await raw_step if inspect.isawaitable(raw_step) else raw_step
            content_parts.append(step.content)
            tool_calls += step.tool_calls
            denied_tool_calls += step.denied_tool_calls
            if not step.should_continue:
                break
        else:
            stopped_by_max_turns = True

        return ForkedAgentResult(
            status="max_turns_exceeded" if stopped_by_max_turns else "completed",
            content="\n".join(part for part in content_parts if part),
            tool_calls=tool_calls,
            denied_tool_calls=denied_tool_calls,
            elapsed_ms=_elapsed_ms(started_at),
        )
    except Exception as exc:
        return ForkedAgentResult(
            status="failed",
            content="",
            tool_calls=0,
            denied_tool_calls=0,
            elapsed_ms=_elapsed_ms(started_at),
            error_type=exc.__class__.__name__,
        )


def _default_single_turn_content(prompt_messages: list[dict[str, str]]) -> str:
    for message in reversed(prompt_messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return prompt_messages[-1].get("content", "") if prompt_messages else ""


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)
