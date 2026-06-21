import asyncio
import json

from app.memory_system.schemas import TranscriptEvent, TranscriptRole, TranscriptToolEvidence
from app.memory_system.transcripts import (
    TranscriptFormatError,
    append_transcript_event,
    append_turn_transcript,
    read_transcript_events,
    read_transcript_since_cursor,
    update_extract_cursor,
)


def _event(role: TranscriptRole = TranscriptRole.USER, source: str = "main_agent"):
    return TranscriptEvent(
        event_id="evt_test",
        timestamp="2026-06-21T10:00:00+08:00",
        request_id="req-1",
        conversation_id="conv-1",
        user_id=1,
        tenant_id="default",
        role=role,
        content="你好",
        content_digest="digest",
        source=source,
    )


def test_append_transcript_event_writes_one_json_line(tmp_path):
    path = tmp_path / "conv.jsonl"

    asyncio.run(append_transcript_event(path, _event()))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["content"] == "你好"


def test_append_turn_transcript_writes_user_then_assistant(tmp_path):
    path = tmp_path / "conv.jsonl"

    events = asyncio.run(
        append_turn_transcript(
            transcript_path=path,
            request_id="req-1",
            conversation_id="conv-1",
            user_id=1,
            tenant_id="default",
            user_query="查库存",
            final_answer="有货",
            tool_evidence=[
                {
                    "tool_name": "multi_tool_workflow",
                    "request_id": "req-1",
                    "raw_ref": "request_id=req-1",
                    "result_digest": "库存有货",
                    "result_count": 1,
                    "elapsed_ms": 20,
                }
            ],
        )
    )

    assert [event.role for event in events] == [
        TranscriptRole.USER,
        TranscriptRole.ASSISTANT,
    ]
    loaded = asyncio.run(read_transcript_events(path))
    assert [event.role for event in loaded] == [
        TranscriptRole.USER,
        TranscriptRole.ASSISTANT,
    ]
    assert loaded[1].tool_evidence[0].result_digest == "库存有货"


def test_append_rejects_background_source_by_default(tmp_path):
    path = tmp_path / "conv.jsonl"

    try:
        asyncio.run(append_transcript_event(path, _event(source="extract_memories")))
    except ValueError as exc:
        assert "background source" in str(exc)
    else:
        raise AssertionError("expected background source to raise")


def test_read_transcript_events_reads_utf8_chinese(tmp_path):
    path = tmp_path / "conv.jsonl"
    asyncio.run(append_transcript_event(path, _event()))

    events = asyncio.run(read_transcript_events(path))

    assert events[0].content == "你好"


def test_read_transcript_since_cursor_returns_only_new_events(tmp_path):
    transcript_path = tmp_path / "conv.jsonl"
    cursor_path = tmp_path / "state" / "extract_cursor.json"
    events = asyncio.run(
        append_turn_transcript(
            transcript_path=transcript_path,
            request_id="req-1",
            conversation_id="conv-1",
            user_id=1,
            tenant_id="default",
            user_query="查库存",
            final_answer="有货",
            tool_evidence=[],
        )
    )
    asyncio.run(
        update_extract_cursor(
            cursor_path=cursor_path,
            conversation_id="conv-1",
            last_event=events[0],
            last_line_index=0,
        )
    )

    new_events, cursor = asyncio.run(
        read_transcript_since_cursor(
            transcript_path=transcript_path,
            cursor_path=cursor_path,
            conversation_id="conv-1",
            max_events=10,
        )
    )

    assert cursor.last_line_index == 0
    assert len(new_events) == 1
    assert new_events[0].role == TranscriptRole.ASSISTANT


def test_update_extract_cursor_advances_after_success(tmp_path):
    cursor_path = tmp_path / "state" / "extract_cursor.json"
    event = _event()

    asyncio.run(
        update_extract_cursor(
            cursor_path=cursor_path,
            conversation_id="conv-1",
            last_event=event,
            last_line_index=3,
        )
    )

    state = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert state["conversations"]["conv-1"]["last_event_id"] == "evt_test"
    assert state["conversations"]["conv-1"]["last_line_index"] == 3


def test_bad_json_line_raises_format_error(tmp_path):
    path = tmp_path / "conv.jsonl"
    path.write_text("{bad json}\n", encoding="utf-8")

    try:
        asyncio.run(read_transcript_events(path))
    except TranscriptFormatError as exc:
        assert "bad transcript json" in str(exc)
    else:
        raise AssertionError("expected bad json to raise")


def test_append_event_accepts_structured_tool_evidence_when_allowed(tmp_path):
    path = tmp_path / "conv.jsonl"
    event = TranscriptEvent(
        event_id="evt_tool",
        timestamp="2026-06-21T10:00:00+08:00",
        request_id="req-1",
        conversation_id="conv-1",
        user_id=1,
        tenant_id="default",
        role=TranscriptRole.ASSISTANT,
        content="有货",
        content_digest="digest",
        tool_evidence=(
            TranscriptToolEvidence(
                tool_name="multi_tool_workflow",
                request_id="req-1",
                raw_ref="request_id=req-1",
                result_digest="库存有货",
            ),
        ),
    )

    asyncio.run(append_transcript_event(path, event))
    loaded = asyncio.run(read_transcript_events(path))

    assert loaded[0].tool_evidence[0].tool_name == "multi_tool_workflow"
