import json
import asyncio
from datetime import datetime
from typing import Any, Optional

from langchain_deepseek import ChatDeepSeek
from langchain_ollama import ChatOllama
from sqlalchemy import desc, func, select, update

from app.core.config import ServiceType, settings
from app.core.database import AsyncSessionLocal
from app.core.logger import get_logger, log_event
from app.models.conversation_context import ConversationContextItem
from app.models.message import Message
from app.models.user_memory import UserMemoryItem


logger = get_logger(service="context_manager")

CONTEXT_SYSTEM_PREFIX = """以下是本轮对话可复用的上下文摘要。请优先遵守用户当前问题；引用工具证据时只基于明确证据，不要把摘要当作新的数据库查询结果。"""

CONTEXT_ITEM_LIMITS = {
    "session_note": 1,
    "current_goal": 1,
    "confirmed_fact": 8,
    "tool_evidence": 5,
    "failed_path": 3,
}
USER_MEMORY_LIMIT = 3
RECENT_MESSAGE_LIMIT = 8
PROMPT_RECENT_MESSAGE_LIMIT = 4
MAX_CONTENT_LEN = 800
SESSION_NOTE_MESSAGE_THRESHOLD = 6
SESSION_NOTE_TOOL_EVIDENCE_THRESHOLD = 2
SESSION_NOTE_TOKEN_THRESHOLD = 3500
SESSION_NOTE_SCHEMA_KEYS = {
    "current_state",
    "customer_need",
    "confirmed_facts",
    "tool_evidence",
    "failed_paths",
    "user_preferences",
    "next_action",
    "worklog",
}


def _safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _json_loads(text: Optional[str]) -> Optional[dict[str, Any]]:
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _clip(text: str, limit: int = MAX_CONTENT_LEN) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def _conversation_int(conversation_id: Optional[str | int]) -> Optional[int]:
    if conversation_id is None:
        return None
    value = str(conversation_id)
    return int(value) if value.isdigit() else None


def _message_to_dict(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "role": "user" if message.sender == "user" else "assistant",
        "content": message.content,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


async def _load_recent_messages(conversation_id: Optional[int]) -> list[dict[str, Any]]:
    if conversation_id is None:
        return []
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(RECENT_MESSAGE_LIMIT)
        )
        result = await db.execute(stmt)
        messages = list(result.scalars().all())
    return [_message_to_dict(message) for message in reversed(messages)]


async def _load_context_items(
    user_id: int,
    conversation_id: Optional[int],
    item_type: str,
    limit: int,
) -> list[dict[str, Any]]:
    if conversation_id is None:
        return []
    async with AsyncSessionLocal() as db:
        stmt = (
            select(ConversationContextItem)
            .where(
                ConversationContextItem.user_id == user_id,
                ConversationContextItem.conversation_id == conversation_id,
                ConversationContextItem.item_type == item_type,
                ConversationContextItem.status == "active",
            )
            .order_by(desc(ConversationContextItem.confidence), desc(ConversationContextItem.updated_at))
            .limit(limit)
        )
        result = await db.execute(stmt)
        items = result.scalars().all()
    return [
        {
            "id": item.id,
            "type": item.item_type,
            "content": item.content,
            "request_id": item.request_id,
            "tool_name": item.tool_name,
            "raw_ref": item.raw_ref,
            "confidence": item.confidence,
            "content_json": _json_loads(item.content_json),
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
        for item in items
    ]


async def _load_user_memories(user_id: int) -> list[dict[str, Any]]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(UserMemoryItem)
            .where(UserMemoryItem.user_id == user_id, UserMemoryItem.status == "active")
            .order_by(desc(UserMemoryItem.confidence), desc(UserMemoryItem.updated_at))
            .limit(USER_MEMORY_LIMIT)
        )
        result = await db.execute(stmt)
        items = result.scalars().all()
    return [
        {
            "id": item.id,
            "type": item.memory_type,
            "content": item.content,
            "confidence": item.confidence,
        }
        for item in items
    ]


def format_context_bundle(context_bundle: dict[str, Any]) -> str:
    lines = []
    session_note = context_bundle.get("session_note") or {}
    note_json = session_note.get("content_json") or {}
    if note_json:
        lines.append("Session Note：")
        current_state = note_json.get("current_state")
        customer_need = note_json.get("customer_need")
        next_action = note_json.get("next_action")
        if current_state:
            lines.append(f"- 当前状态：{_clip(current_state, 300)}")
        if customer_need:
            lines.append(f"- 用户需求：{_clip(customer_need, 300)}")
        if next_action:
            lines.append(f"- 下一步：{_clip(next_action, 300)}")

    current_goal = context_bundle.get("current_goal")
    if current_goal:
        lines.append(f"当前咨询目标：{current_goal}")

    sections = [
        ("recent_messages", "最近对话摘录"),
        ("confirmed_facts", "已确认事实"),
        ("tool_evidence", "工具证据摘要"),
        ("failed_paths", "已知失败路径"),
        ("user_preferences", "用户偏好"),
    ]
    for key, title in sections:
        items = context_bundle.get(key) or []
        if not items:
            continue
        lines.append(f"{title}：")
        for item in items:
            content = item.get("content") or item.get("digest") or ""
            if key == "recent_messages":
                content = f"{item.get('role', 'unknown')}：{content}"
            suffix = ""
            if item.get("request_id"):
                suffix = f"（request_id={item['request_id']}）"
            lines.append(f"- {_clip(content, 300)}{suffix}")
    if not lines:
        return ""
    return "\n".join([CONTEXT_SYSTEM_PREFIX] + lines)


async def load_context_bundle(
    user_id: int,
    conversation_id: Optional[str | int],
    query: str,
) -> dict[str, Any]:
    conversation_int = _conversation_int(conversation_id)
    recent_messages = await _load_recent_messages(conversation_int)
    context: dict[str, Any] = {
        "conversation_id": conversation_int,
        "current_query": query,
        "recent_messages": recent_messages[-PROMPT_RECENT_MESSAGE_LIMIT:],
        "session_note": None,
        "current_goal": None,
        "confirmed_facts": [],
        "tool_evidence": [],
        "failed_paths": [],
        "user_preferences": await _load_user_memories(user_id),
    }

    for item_type, limit in CONTEXT_ITEM_LIMITS.items():
        items = await _load_context_items(user_id, conversation_int, item_type, limit)
        if item_type == "session_note":
            context["session_note"] = items[0] if items else None
        elif item_type == "current_goal":
            context["current_goal"] = items[0]["content"] if items else None
        elif item_type == "confirmed_fact":
            context["confirmed_facts"] = items
        elif item_type == "tool_evidence":
            context["tool_evidence"] = items
        elif item_type == "failed_path":
            context["failed_paths"] = items
    context["prompt_context"] = format_context_bundle(context)
    context["history_records"] = [
        {
            "question": item["content"],
            "answer": item["content"],
            "cyphers": [],
        }
        for item in context["tool_evidence"][:3]
    ]

    log_event(
        logger,
        "INFO",
        "context_bundle_loaded",
        user_id=user_id,
        conversation_id=conversation_int,
        recent_message_count=len(recent_messages),
        has_session_note=context["session_note"] is not None,
        confirmed_fact_count=len(context["confirmed_facts"]),
        tool_evidence_count=len(context["tool_evidence"]),
        failed_path_count=len(context["failed_paths"]),
        user_preference_count=len(context["user_preferences"]),
    )
    return context


async def _save_context_item(
    user_id: int,
    conversation_id: Optional[int],
    item_type: str,
    content: str,
    request_id: Optional[str] = None,
    tool_name: Optional[str] = None,
    raw_ref: Optional[str] = None,
    content_json: Optional[dict[str, Any]] = None,
    confidence: float = 0.8,
) -> None:
    if conversation_id is None or not content:
        return
    async with AsyncSessionLocal() as db:
        if item_type in {"session_note", "current_goal"}:
            stmt = (
                update(ConversationContextItem)
                .where(
                    ConversationContextItem.user_id == user_id,
                    ConversationContextItem.conversation_id == conversation_id,
                    ConversationContextItem.item_type == item_type,
                    ConversationContextItem.status == "active",
                )
                .values(status="obsolete")
            )
            await db.execute(stmt)
        item = ConversationContextItem(
            user_id=user_id,
            conversation_id=conversation_id,
            item_type=item_type,
            content=_clip(content, 1200),
            content_json=_safe_json(content_json) if content_json is not None else None,
            request_id=request_id,
            tool_name=tool_name,
            raw_ref=raw_ref,
            confidence=confidence,
            status="active",
        )
        db.add(item)
        await db.commit()


async def _save_user_memory(
    user_id: int,
    conversation_id: Optional[int],
    memory_type: str,
    content: str,
    confidence: float = 0.85,
) -> None:
    if not content:
        return
    async with AsyncSessionLocal() as db:
        item = UserMemoryItem(
            user_id=user_id,
            memory_type=memory_type,
            content=_clip(content, 600),
            source_conversation_id=conversation_id,
            confidence=confidence,
            status="active",
        )
        db.add(item)
        await db.commit()


def summarize_tool_evidence(response: dict[str, Any], request_id: str) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for cypher in response.get("cyphers", []) or []:
        task = cypher.task if hasattr(cypher, "task") else cypher.get("task", "")
        records = cypher.records if hasattr(cypher, "records") else cypher.get("records", {})
        record_text = _clip(str(records), 600)
        if not task and not record_text:
            continue
        evidence.append(
            {
                "tool_name": "multi_tool_workflow",
                "query_text": task or response.get("question", ""),
                "result_digest": f"{task} -> {record_text}",
                "raw_ref": f"request_id={request_id}",
            }
        )
    return evidence


async def save_tool_evidence_items(
    user_id: int,
    conversation_id: Optional[str | int],
    request_id: str,
    evidence_items: list[dict[str, Any]],
) -> None:
    conversation_int = _conversation_int(conversation_id)
    for evidence in evidence_items[: CONTEXT_ITEM_LIMITS["tool_evidence"]]:
        await _save_context_item(
            user_id=user_id,
            conversation_id=conversation_int,
            item_type="tool_evidence",
            content=evidence.get("result_digest", ""),
            request_id=request_id,
            tool_name=evidence.get("tool_name"),
            raw_ref=evidence.get("raw_ref"),
            content_json=evidence,
            confidence=0.85,
        )
    if evidence_items:
        log_event(
            logger,
            "INFO",
            "tool_evidence_saved",
            user_id=user_id,
            conversation_id=conversation_int,
            request_id=request_id,
            evidence_count=len(evidence_items),
        )


async def _load_latest_context_item(
    user_id: int,
    conversation_id: int,
    item_type: str,
) -> Optional[ConversationContextItem]:
    async with AsyncSessionLocal() as db:
        stmt = (
            select(ConversationContextItem)
            .where(
                ConversationContextItem.user_id == user_id,
                ConversationContextItem.conversation_id == conversation_id,
                ConversationContextItem.item_type == item_type,
                ConversationContextItem.status == "active",
            )
            .order_by(desc(ConversationContextItem.updated_at), desc(ConversationContextItem.id))
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalars().first()


async def _count_messages_since(
    conversation_id: int,
    since: Optional[datetime],
) -> int:
    async with AsyncSessionLocal() as db:
        stmt = select(func.count(Message.id)).where(Message.conversation_id == conversation_id)
        if since is not None:
            stmt = stmt.where(Message.created_at > since)
        result = await db.execute(stmt)
        return int(result.scalar() or 0)


def _estimate_tokens(*values: Any) -> int:
    text = _safe_json(values)
    return max(1, len(text) // 2)


def _has_stage_end_signal(text: str) -> bool:
    signals = [
        "已完成",
        "已经完成",
        "查询结果",
        "推荐",
        "下一步",
        "可以下单",
        "需要您确认",
        "请确认",
    ]
    return any(signal in text for signal in signals)


def _has_failed_tool_signal(evidence_items: list[dict[str, Any]], final_answer: str) -> bool:
    failed_words = ["无结果", "未查到", "没有查到", "查询失败", "无法查询", "没有找到", "empty", "error"]
    evidence_text = _safe_json(evidence_items)
    target = f"{evidence_text}\n{final_answer}"
    return bool(evidence_items) and any(word in target for word in failed_words)


def should_update_session_note(
    *,
    messages_since_session_note: int,
    recent_messages: list[dict[str, Any]],
    session_note: Optional[dict[str, Any]],
    user_query: str,
    final_answer: str,
    evidence_items: list[dict[str, Any]],
) -> tuple[bool, str]:
    token_estimate = _estimate_tokens(recent_messages, session_note, user_query, final_answer)
    if messages_since_session_note >= SESSION_NOTE_MESSAGE_THRESHOLD:
        return True, "message_threshold"
    if len(evidence_items) >= SESSION_NOTE_TOOL_EVIDENCE_THRESHOLD:
        return True, "tool_evidence_threshold"
    if token_estimate >= SESSION_NOTE_TOKEN_THRESHOLD:
        return True, "token_threshold"
    if _has_stage_end_signal(final_answer):
        return True, "stage_end_signal"
    if _has_failed_tool_signal(evidence_items, final_answer):
        return True, "failed_tool_signal"
    return False, "below_threshold"


def build_session_note_prompt(
    *,
    recent_messages: list[dict[str, Any]],
    previous_session_note: Optional[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    user_query: str,
    final_answer: str,
) -> list[dict[str, str]]:
    schema = {
        "current_state": "当前咨询状态",
        "customer_need": "用户真实需求和约束",
        "confirmed_facts": [{"fact": "事实", "source": "user|tool|assistant", "request_id": "可选"}],
        "tool_evidence": [
            {
                "summary": "工具证据摘要",
                "tool_name": "工具名",
                "request_id": "必须保留",
                "raw_ref": "必须保留",
            }
        ],
        "failed_paths": [{"summary": "失败路径", "request_id": "可选"}],
        "user_preferences": ["仅保存用户明确表达的长期偏好"],
        "next_action": "下一轮最应该继续做什么",
        "worklog": ["关键进展，不记录寒暄"],
    }
    payload = {
        "previous_session_note": previous_session_note or {},
        "recent_messages": recent_messages,
        "current_turn": {
            "user_query": user_query,
            "final_answer": final_answer,
            "tool_evidence": evidence_items,
        },
        "required_schema": schema,
    }
    system_prompt = (
        "你是智能客服系统的后台 session note 更新器。"
        "只输出一个 JSON object，不要输出 Markdown、解释或代码块。"
        "必须使用固定字段；不能编造工具结果；工具证据必须保留 request_id 和 raw_ref。"
        "如果没有某类信息，字符串填空字符串，列表填空列表。"
    )
    user_prompt = (
        "请根据以下上下文生成更新后的 session note JSON。\n"
        f"{json.dumps(payload, ensure_ascii=False, default=str)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


async def generate_session_note_with_llm(messages: list[dict[str, str]]) -> str:
    if settings.AGENT_SERVICE == ServiceType.DEEPSEEK:
        model = ChatDeepSeek(
            api_key=settings.DEEPSEEK_API_KEY,
            model_name=settings.DEEPSEEK_MODEL,
            temperature=0,
            tags=["session_note"],
        )
    else:
        model = ChatOllama(
            model=settings.OLLAMA_AGENT_MODEL,
            base_url=settings.OLLAMA_BASE_URL,
            temperature=0,
            tags=["session_note"],
        )
    response = await model.ainvoke(messages)
    return str(response.content)


def validate_session_note(raw_note: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_note, str):
        try:
            note = json.loads(_strip_json_fence(raw_note))
        except json.JSONDecodeError as exc:
            raise ValueError(f"session note is not valid JSON: {exc}") from exc
    else:
        note = raw_note

    if not isinstance(note, dict):
        raise ValueError("session note must be a JSON object")

    missing_keys = SESSION_NOTE_SCHEMA_KEYS - set(note)
    if missing_keys:
        raise ValueError(f"session note missing keys: {sorted(missing_keys)}")

    for key in ["current_state", "customer_need", "next_action"]:
        if not isinstance(note[key], str):
            raise ValueError(f"session note field {key} must be string")

    for key in ["confirmed_facts", "tool_evidence", "failed_paths", "user_preferences", "worklog"]:
        if not isinstance(note[key], list):
            raise ValueError(f"session note field {key} must be list")

    for fact in note["confirmed_facts"]:
        if not isinstance(fact, dict) or not isinstance(fact.get("fact"), str):
            raise ValueError("confirmed_facts item must contain string fact")
        if fact.get("source") not in {"user", "tool", "assistant", None, ""}:
            raise ValueError("confirmed_facts source must be user/tool/assistant")

    for evidence in note["tool_evidence"]:
        if not isinstance(evidence, dict):
            raise ValueError("tool_evidence item must be object")
        for key in ["summary", "tool_name", "request_id", "raw_ref"]:
            if not isinstance(evidence.get(key), str) or not evidence.get(key):
                raise ValueError(f"tool_evidence item must contain non-empty {key}")

    for failed_path in note["failed_paths"]:
        if not isinstance(failed_path, dict) or not isinstance(failed_path.get("summary"), str):
            raise ValueError("failed_paths item must contain string summary")

    for preference in note["user_preferences"]:
        if not isinstance(preference, str):
            raise ValueError("user_preferences items must be strings")

    for worklog in note["worklog"]:
        if not isinstance(worklog, str):
            raise ValueError("worklog items must be strings")

    return note


def _session_note_content(note: dict[str, Any]) -> str:
    sections = [
        ("当前状态", note.get("current_state", "")),
        ("用户需求", note.get("customer_need", "")),
        ("下一步", note.get("next_action", "")),
    ]
    parts = [f"{title}：{value}" for title, value in sections if value]
    return _clip("；".join(parts), 1200)


async def save_session_note(
    user_id: int,
    conversation_id: Optional[str | int],
    request_id: str,
    session_note: dict[str, Any],
) -> None:
    conversation_int = _conversation_int(conversation_id)
    if conversation_int is None:
        return

    content = _session_note_content(session_note)
    await _save_context_item(
        user_id=user_id,
        conversation_id=conversation_int,
        item_type="session_note",
        content=content,
        request_id=request_id,
        raw_ref=f"request_id={request_id}",
        content_json=session_note,
        confidence=0.9,
    )

    goal_parts = [
        session_note.get("current_state", ""),
        f"下一步：{session_note.get('next_action')}" if session_note.get("next_action") else "",
    ]
    current_goal = _clip("；".join(part for part in goal_parts if part), 500)
    if current_goal:
        await _save_context_item(
            user_id=user_id,
            conversation_id=conversation_int,
            item_type="current_goal",
            content=current_goal,
            request_id=request_id,
            raw_ref=f"request_id={request_id}",
            confidence=0.8,
        )

    for fact in session_note.get("confirmed_facts", [])[: CONTEXT_ITEM_LIMITS["confirmed_fact"]]:
        request_ref = fact.get("request_id") or request_id
        await _save_context_item(
            user_id=user_id,
            conversation_id=conversation_int,
            item_type="confirmed_fact",
            content=fact["fact"],
            request_id=request_ref,
            raw_ref=f"request_id={request_ref}" if request_ref else None,
            content_json=fact,
            confidence=0.8,
        )

    for failed_path in session_note.get("failed_paths", [])[: CONTEXT_ITEM_LIMITS["failed_path"]]:
        request_ref = failed_path.get("request_id") or request_id
        await _save_context_item(
            user_id=user_id,
            conversation_id=conversation_int,
            item_type="failed_path",
            content=failed_path["summary"],
            request_id=request_ref,
            raw_ref=f"request_id={request_ref}" if request_ref else None,
            content_json=failed_path,
            confidence=0.8,
        )

    for preference in session_note.get("user_preferences", [])[:USER_MEMORY_LIMIT]:
        await _save_user_memory(
            user_id=user_id,
            conversation_id=conversation_int,
            memory_type="preference",
            content=preference,
        )

    log_event(
        logger,
        "INFO",
        "session_note_saved",
        user_id=user_id,
        conversation_id=conversation_int,
        request_id=request_id,
        confirmed_fact_count=len(session_note.get("confirmed_facts", [])),
        failed_path_count=len(session_note.get("failed_paths", [])),
        user_preference_count=len(session_note.get("user_preferences", [])),
    )


async def _run_session_note_update(
    *,
    user_id: int,
    conversation_id: Optional[str | int],
    request_id: str,
    user_query: str,
    final_answer: str,
    evidence_items: list[dict[str, Any]],
    context_bundle: dict[str, Any],
) -> dict[str, Any]:
    conversation_int = _conversation_int(conversation_id)
    if conversation_int is None:
        log_event(
            logger,
            "INFO",
            "session_note_update_skipped",
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            reason="conversation_id is not a MySQL integer id",
        )
        return {
            "status": "skipped",
            "reason": "conversation_id is not a MySQL integer id",
        }

    latest_session_note = await _load_latest_context_item(user_id, conversation_int, "session_note")
    messages_since_note = await _count_messages_since(
        conversation_int,
        latest_session_note.updated_at if latest_session_note else None,
    )
    recent_messages = await _load_recent_messages(conversation_int)
    previous_session_note = (
        _json_loads(latest_session_note.content_json)
        if latest_session_note
        else (context_bundle.get("session_note") or {}).get("content_json")
    )

    should_update, reason = should_update_session_note(
        messages_since_session_note=messages_since_note,
        recent_messages=recent_messages,
        session_note=previous_session_note,
        user_query=user_query,
        final_answer=final_answer,
        evidence_items=evidence_items,
    )
    if not should_update:
        log_event(
            logger,
            "INFO",
            "session_note_update_skipped",
            user_id=user_id,
            conversation_id=conversation_int,
            request_id=request_id,
            reason=reason,
            messages_since_session_note=messages_since_note,
            evidence_count=len(evidence_items),
        )
        return {
            "status": "skipped",
            "reason": reason,
            "messages_since_session_note": messages_since_note,
            "evidence_count": len(evidence_items),
        }

    log_event(
        logger,
        "INFO",
        "session_note_update_started",
        user_id=user_id,
        conversation_id=conversation_int,
        request_id=request_id,
        reason=reason,
        messages_since_session_note=messages_since_note,
        evidence_count=len(evidence_items),
    )
    prompt_messages = build_session_note_prompt(
        recent_messages=recent_messages,
        previous_session_note=previous_session_note,
        evidence_items=evidence_items,
        user_query=user_query,
        final_answer=final_answer,
    )
    raw_note = await generate_session_note_with_llm(prompt_messages)
    session_note = validate_session_note(raw_note)
    await save_session_note(
        user_id=user_id,
        conversation_id=conversation_int,
        request_id=request_id,
        session_note=session_note,
    )
    log_event(
        logger,
        "INFO",
        "session_note_update_finished",
        user_id=user_id,
        conversation_id=conversation_int,
        request_id=request_id,
        reason=reason,
    )
    return {
        "status": "updated",
        "reason": reason,
        "messages_since_session_note": messages_since_note,
        "evidence_count": len(evidence_items),
        "session_note": session_note,
    }


async def update_session_note_for_trace(
    *,
    user_id: int,
    conversation_id: Optional[str | int],
    request_id: str,
    user_query: str,
    final_answer: str,
    evidence_items: Optional[list[dict[str, Any]]] = None,
    context_bundle: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    try:
        return await _run_session_note_update(
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            user_query=user_query,
            final_answer=final_answer,
            evidence_items=evidence_items or [],
            context_bundle=context_bundle or {},
        )
    except Exception as exc:
        log_event(
            logger,
            "ERROR",
            "session_note_update_failed",
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            error_type=exc.__class__.__name__,
            reason=str(exc),
            exception=True,
        )
        return {
            "status": "failed",
            "error_type": exc.__class__.__name__,
            "reason": str(exc),
        }


def maybe_schedule_session_note_update(
    *,
    user_id: int,
    conversation_id: Optional[str | int],
    request_id: str,
    user_query: str,
    final_answer: str,
    evidence_items: Optional[list[dict[str, Any]]] = None,
    context_bundle: Optional[dict[str, Any]] = None,
) -> Optional[asyncio.Task]:
    async def _guarded_update() -> None:
        await update_session_note_for_trace(
            user_id=user_id,
            conversation_id=conversation_id,
            request_id=request_id,
            user_query=user_query,
            final_answer=final_answer,
            evidence_items=evidence_items or [],
            context_bundle=context_bundle or {},
        )

    return asyncio.create_task(_guarded_update())
