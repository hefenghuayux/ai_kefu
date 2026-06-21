from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import (
    ExtractCursor,
    TranscriptEvent,
    TranscriptRole,
    TranscriptToolEvidence,
)


class TranscriptFormatError(ValueError):
    pass


async def append_transcript_event(
    path: Path,
    event: TranscriptEvent,
    *,
    allow_background_source: bool = False,
) -> None:
    if event.source != "main_agent" and not allow_background_source:
        raise ValueError(f"background source cannot write main transcript: {event.source}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _event_to_dict(event)
    with path.open("a", encoding="utf-8", newline="\n") as file_obj:
        file_obj.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        file_obj.write("\n")


async def append_turn_transcript(
    *,
    transcript_path: Path,
    request_id: str,
    conversation_id: str,
    user_id: int,
    tenant_id: str,
    user_query: str,
    final_answer: str,
    tool_evidence: list[dict[str, Any] | TranscriptToolEvidence],
) -> list[TranscriptEvent]:
    timestamp = _now_iso()
    user_event = TranscriptEvent(
        event_id=_new_event_id(),
        timestamp=timestamp,
        request_id=request_id,
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        role=TranscriptRole.USER,
        content=user_query,
        content_digest=_digest(user_query),
    )
    assistant_event = TranscriptEvent(
        event_id=_new_event_id(),
        timestamp=_now_iso(),
        request_id=request_id,
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        role=TranscriptRole.ASSISTANT,
        content=final_answer,
        content_digest=_digest(final_answer),
        tool_evidence=tuple(_coerce_tool_evidence(item) for item in tool_evidence),
    )
    await append_transcript_event(transcript_path, user_event)
    await append_transcript_event(transcript_path, assistant_event)
    return [user_event, assistant_event]


async def read_transcript_events(
    path: Path,
    *,
    start_line: int = 0,
    max_events: int | None = None,
) -> list[TranscriptEvent]:
    if start_line < 0:
        raise ValueError("start_line must be >= 0")
    if max_events is not None and max_events <= 0:
        raise ValueError("max_events must be positive")
    if not path.exists():
        return []

    events: list[TranscriptEvent] = []
    with path.open("r", encoding="utf-8") as file_obj:
        for line_index, line in enumerate(file_obj):
            if line_index < start_line:
                continue
            if max_events is not None and len(events) >= max_events:
                break
            stripped = line.strip()
            if not stripped:
                raise TranscriptFormatError(f"empty transcript line: {line_index}")
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise TranscriptFormatError(
                    f"bad transcript json on line {line_index}"
                ) from exc
            events.append(_event_from_dict(raw, line_index=line_index))
    return events


async def read_transcript_since_cursor(
    *,
    transcript_path: Path,
    cursor_path: Path,
    conversation_id: str,
    max_events: int,
) -> tuple[list[TranscriptEvent], ExtractCursor]:
    cursor = _read_cursor(cursor_path, conversation_id)
    events = await read_transcript_events(
        transcript_path,
        start_line=cursor.last_line_index + 1,
        max_events=max_events,
    )
    return events, cursor


async def update_extract_cursor(
    *,
    cursor_path: Path,
    conversation_id: str,
    last_event: TranscriptEvent,
    last_line_index: int,
) -> None:
    if last_line_index < 0:
        raise ValueError("last_line_index must be >= 0")
    state = _read_cursor_state(cursor_path)
    conversations = state.setdefault("conversations", {})
    conversations[conversation_id] = {
        "last_event_id": last_event.event_id,
        "last_line_index": last_line_index,
        "updated_at": _now_iso(),
    }
    cursor_path.parent.mkdir(parents=True, exist_ok=True)
    with cursor_path.open("w", encoding="utf-8") as file_obj:
        json.dump(state, file_obj, ensure_ascii=False, indent=2)
        file_obj.write("\n")


def _coerce_tool_evidence(
    item: dict[str, Any] | TranscriptToolEvidence,
) -> TranscriptToolEvidence:
    if isinstance(item, TranscriptToolEvidence):
        return item
    return TranscriptToolEvidence(
        tool_name=str(item["tool_name"]),
        request_id=str(item["request_id"]),
        raw_ref=item.get("raw_ref"),
        result_digest=str(item["result_digest"]),
        result_count=item.get("result_count"),
        elapsed_ms=item.get("elapsed_ms"),
    )


def _event_to_dict(event: TranscriptEvent) -> dict[str, Any]:
    payload = asdict(event)
    payload["role"] = event.role.value
    return payload


def _event_from_dict(raw: dict[str, Any], *, line_index: int) -> TranscriptEvent:
    try:
        tool_evidence = tuple(
            TranscriptToolEvidence(**item) for item in raw.get("tool_evidence", [])
        )
        return TranscriptEvent(
            event_id=str(raw["event_id"]),
            timestamp=str(raw["timestamp"]),
            request_id=str(raw["request_id"]),
            conversation_id=str(raw["conversation_id"]),
            user_id=int(raw["user_id"]),
            tenant_id=str(raw["tenant_id"]),
            role=TranscriptRole(str(raw["role"])),
            content=str(raw["content"]),
            content_digest=str(raw["content_digest"]),
            tool_calls=tuple(raw.get("tool_calls", ())),
            tool_evidence=tool_evidence,
            source=str(raw.get("source", "main_agent")),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise TranscriptFormatError(f"bad transcript schema on line {line_index}") from exc


def _read_cursor(cursor_path: Path, conversation_id: str) -> ExtractCursor:
    state = _read_cursor_state(cursor_path)
    raw = state.get("conversations", {}).get(conversation_id)
    if not raw:
        return ExtractCursor(
            conversation_id=conversation_id,
            last_event_id=None,
            last_line_index=-1,
            updated_at=_now_iso(),
        )
    return ExtractCursor(
        conversation_id=conversation_id,
        last_event_id=raw.get("last_event_id"),
        last_line_index=int(raw["last_line_index"]),
        updated_at=str(raw["updated_at"]),
    )


def _read_cursor_state(cursor_path: Path) -> dict[str, Any]:
    if not cursor_path.exists():
        return {"conversations": {}}
    with cursor_path.open("r", encoding="utf-8") as file_obj:
        try:
            state = json.load(file_obj)
        except json.JSONDecodeError as exc:
            raise TranscriptFormatError("bad extract cursor json") from exc
    if not isinstance(state, dict):
        raise TranscriptFormatError("extract cursor must be a json object")
    if "conversations" not in state:
        state["conversations"] = {}
    if not isinstance(state["conversations"], dict):
        raise TranscriptFormatError("extract cursor conversations must be an object")
    return state


def _new_event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
