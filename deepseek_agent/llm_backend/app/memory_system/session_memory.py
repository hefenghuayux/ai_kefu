from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import MemorySystemConfig
from .paths import assert_under_memory_root


SESSION_MEMORY_SECTIONS = (
    "# Session Title",
    "# Current State",
    "# Customer Need",
    "# Confirmed Facts",
    "# Tool Evidence",
    "# Failed Paths",
    "# User Preferences",
    "# Next Action",
    "# Worklog",
)


@dataclass(frozen=True)
class SessionMemoryConfig:
    minimum_message_tokens_to_init: int = 10000
    minimum_tokens_between_update: int = 5000
    tool_calls_between_updates: int = 3


@dataclass(frozen=True)
class SessionMemoryState:
    summary_path: Path
    exists: bool
    content: str | None
    last_updated_at: str | None


@dataclass(frozen=True)
class SessionMemoryUpdateDecision:
    should_update: bool
    reason: str
    token_estimate: int
    tool_call_count: int


@dataclass(frozen=True)
class SessionMemoryUpdateResult:
    status: str
    reason: str | None
    summary_path: str | None
    updated: bool
    error_type: str | None = None


SessionSummaryGenerator = Callable[..., Awaitable[str] | str]


async def load_session_memory(summary_path: Path) -> SessionMemoryState:
    if not summary_path.exists():
        return SessionMemoryState(
            summary_path=summary_path,
            exists=False,
            content=None,
            last_updated_at=None,
        )
    stat = summary_path.stat()
    return SessionMemoryState(
        summary_path=summary_path,
        exists=True,
        content=summary_path.read_text(encoding="utf-8"),
        last_updated_at=datetime.fromtimestamp(
            stat.st_mtime, tz=timezone.utc
        ).isoformat(),
    )


def should_update_session_memory(
    *,
    current_summary: str | None,
    recent_messages: list[dict[str, Any]],
    tool_evidence: list[dict[str, Any]],
    token_estimate: int,
    config: SessionMemoryConfig,
) -> SessionMemoryUpdateDecision:
    tool_call_count = len(tool_evidence)
    if current_summary is None and token_estimate >= config.minimum_message_tokens_to_init:
        return SessionMemoryUpdateDecision(True, "init_token_threshold", token_estimate, tool_call_count)
    if current_summary is not None and token_estimate >= config.minimum_tokens_between_update:
        return SessionMemoryUpdateDecision(True, "update_token_threshold", token_estimate, tool_call_count)
    if tool_call_count >= config.tool_calls_between_updates:
        return SessionMemoryUpdateDecision(True, "tool_call_threshold", token_estimate, tool_call_count)
    return SessionMemoryUpdateDecision(False, "below_threshold", token_estimate, tool_call_count)


def build_session_memory_prompt(
    *,
    current_summary: str | None,
    recent_messages: list[dict[str, Any]],
    user_query: str,
    final_answer: str,
    tool_evidence: list[dict[str, Any]],
) -> list[dict[str, str]]:
    payload = {
        "current_summary": current_summary or "",
        "recent_messages": recent_messages,
        "current_turn": {
            "user_query": user_query,
            "final_answer": final_answer,
            "tool_evidence": tool_evidence,
        },
        "required_sections": list(SESSION_MEMORY_SECTIONS),
    }
    system_prompt = (
        "你是智能客服系统的后台 SessionMemory 更新器。"
        "只输出 Markdown；必须保留所有固定 section；不要新增 section。"
        "不要把订单、库存、价格、物流、售后进度等实时事实写成长期事实。"
        "工具证据必须保留 request_id 或 raw_ref。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]


async def update_session_memory(
    *,
    summary_path: Path | None,
    context_bundle: dict[str, Any],
    user_query: str,
    final_answer: str,
    tool_evidence: list[dict[str, Any]],
    config: MemorySystemConfig,
    session_config: SessionMemoryConfig | None = None,
    generator: SessionSummaryGenerator | None = None,
) -> SessionMemoryUpdateResult:
    if not config.enabled:
        return SessionMemoryUpdateResult("skipped", "memory_disabled", None, False)
    if not config.session_memory_enabled:
        return SessionMemoryUpdateResult("skipped", "session_memory_disabled", None, False)
    if summary_path is None:
        return SessionMemoryUpdateResult("skipped", "missing_summary_path", None, False)

    try:
        safe_path = assert_under_memory_root(summary_path, config.memory_root)
        state = await load_session_memory(safe_path)
        recent_messages = list(context_bundle.get("recent_messages") or [])
        token_estimate = estimate_session_tokens(
            state.content,
            recent_messages,
            user_query,
            final_answer,
            tool_evidence,
        )
        decision = should_update_session_memory(
            current_summary=state.content,
            recent_messages=recent_messages,
            tool_evidence=tool_evidence,
            token_estimate=token_estimate,
            config=session_config or SessionMemoryConfig(),
        )
        if not decision.should_update:
            return SessionMemoryUpdateResult(
                "skipped",
                decision.reason,
                str(safe_path),
                False,
            )

        prompt_messages = build_session_memory_prompt(
            current_summary=state.content,
            recent_messages=recent_messages,
            user_query=user_query,
            final_answer=final_answer,
            tool_evidence=tool_evidence,
        )
        if generator is None:
            summary = build_deterministic_session_summary(
                recent_messages=recent_messages,
                user_query=user_query,
                final_answer=final_answer,
                tool_evidence=tool_evidence,
            )
        else:
            generated = generator(
                prompt_messages=prompt_messages,
                current_summary=state.content,
                recent_messages=recent_messages,
                user_query=user_query,
                final_answer=final_answer,
                tool_evidence=tool_evidence,
            )
            summary = await generated if inspect.isawaitable(generated) else generated

        validate_session_summary(summary)
        safe_path.parent.mkdir(parents=True, exist_ok=True)
        safe_path.write_text(summary, encoding="utf-8")
        return SessionMemoryUpdateResult("updated", decision.reason, str(safe_path), True)
    except Exception as exc:
        return SessionMemoryUpdateResult(
            "failed",
            str(exc),
            str(summary_path),
            False,
            error_type=exc.__class__.__name__,
        )


def validate_session_summary(markdown: str) -> None:
    if not isinstance(markdown, str) or not markdown.strip():
        raise ValueError("session summary must be non-empty markdown")
    missing = [section for section in SESSION_MEMORY_SECTIONS if section not in markdown]
    if missing:
        raise ValueError(f"session summary missing sections: {missing}")


def estimate_session_tokens(*values: Any) -> int:
    text = json.dumps(values, ensure_ascii=False, default=str)
    return max(1, len(text) // 2)


def build_deterministic_session_summary(
    *,
    recent_messages: list[dict[str, Any]],
    user_query: str,
    final_answer: str,
    tool_evidence: list[dict[str, Any]],
) -> str:
    recent_lines = [
        f"- {item.get('role', 'unknown')}: {str(item.get('content', ''))[:300]}"
        for item in recent_messages[-4:]
    ]
    evidence_lines = []
    for evidence in tool_evidence[:5]:
        digest = evidence.get("result_digest") or evidence.get("content") or ""
        ref = evidence.get("raw_ref") or (
            f"request_id={evidence.get('request_id')}" if evidence.get("request_id") else ""
        )
        evidence_lines.append(
            f"- {evidence.get('tool_name', 'unknown_tool')}: {digest} {ref}".strip()
        )
    return "\n".join(
        [
            "# Session Title",
            "_A short and distinctive title for the session._",
            "客服咨询会话",
            "",
            "# Current State",
            "_What is actively being worked on right now? Pending tasks and immediate next steps._",
            f"用户刚询问：{user_query}",
            f"助手刚回答：{final_answer}",
            "",
            "# Customer Need",
            "_The user's current business need, constraints, and unresolved questions._",
            user_query,
            "",
            "# Confirmed Facts",
            "_Facts explicitly confirmed by user or tools. Include source when useful._",
            "\n".join(recent_lines) if recent_lines else "- 暂无",
            "",
            "# Tool Evidence",
            "_Important tool calls and results. Preserve request_id or raw reference._",
            "\n".join(evidence_lines) if evidence_lines else "- 暂无",
            "",
            "# Failed Paths",
            "_Failed queries, wrong assumptions, or approaches that should not be repeated._",
            "- 暂无",
            "",
            "# User Preferences",
            "_Preferences expressed in this session. Only promote to long-term memory when durable._",
            "- 暂无",
            "",
            "# Next Action",
            "_The most useful next move if the conversation continues._",
            "继续围绕用户当前问题提供帮助；涉及订单、库存、价格、物流或售后进度时查询业务系统。",
            "",
            "# Worklog",
            "_Terse step-by-step record of what has been attempted or completed._",
            "- 已记录当前轮用户问题和助手回答。",
        ]
    )
