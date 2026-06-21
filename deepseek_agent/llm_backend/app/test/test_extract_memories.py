import asyncio
from pathlib import Path

from app.memory_system.config import MemorySystemConfig
from app.memory_system.extract_memories import (
    ExtractMemoryCandidate,
    maybe_extract_memories,
    parse_extract_candidate,
    prefer_update_for_duplicate,
    validate_extract_candidate,
    write_memory_candidate,
)
from app.memory_system.memory_types import MemoryType
from app.memory_system.paths import build_memory_identity, resolve_memory_paths
from app.memory_system.schemas import MemoryScope
from app.memory_system.transcripts import append_turn_transcript


def _config(root: Path, **kwargs) -> MemorySystemConfig:
    defaults = {
        "enabled": True,
        "extract_memories_enabled": True,
        "memory_root": root,
    }
    defaults.update(kwargs)
    return MemorySystemConfig(**defaults)


def _identity(config: MemorySystemConfig):
    return build_memory_identity(
        user_id=1, conversation_id="conv-1", tenant_id=None, config=config
    )


def _paths(config: MemorySystemConfig):
    return resolve_memory_paths(identity=_identity(config), config=config)


def _candidate(**kwargs) -> ExtractMemoryCandidate:
    defaults = {
        "memory_type": MemoryType.FEEDBACK,
        "scope": MemoryScope.CUSTOMER,
        "title": "inventory-answer-style",
        "filename": "inventory-answer-style.md",
        "description": "客户希望库存回答简洁",
        "body": "客户希望后续库存回答简洁，不重复解释字段。",
        "confidence": 0.8,
        "source_type": "customer_statement",
        "source_conversation_id": "conv-1",
        "source_request_id": "req-1",
    }
    defaults.update(kwargs)
    return ExtractMemoryCandidate(**defaults)


def test_extract_skips_when_disabled(tmp_path):
    config = _config(tmp_path / "memory", enabled=False)
    result = asyncio.run(
        maybe_extract_memories(
            paths=_paths(config),
            identity=_identity(config),
            config=config,
            request_id="req-1",
        )
    )

    assert result.status == "skipped"
    assert result.reason == "memory_disabled"


def test_extract_reads_only_cursor_after_events(tmp_path):
    config = _config(tmp_path / "memory")
    identity = _identity(config)
    paths = _paths(config)
    events = asyncio.run(
        append_turn_transcript(
            transcript_path=paths.transcript_path,
            request_id="req-1",
            conversation_id="conv-1",
            user_id=1,
            tenant_id="default",
            user_query="你好",
            final_answer="你好",
            tool_evidence=[],
        )
    )
    from app.memory_system.transcripts import update_extract_cursor

    asyncio.run(
        update_extract_cursor(
            cursor_path=paths.extract_cursor_path,
            conversation_id="conv-1",
            last_event=events[-1],
            last_line_index=1,
        )
    )
    asyncio.run(
        append_turn_transcript(
            transcript_path=paths.transcript_path,
            request_id="req-2",
            conversation_id="conv-1",
            user_id=1,
            tenant_id="default",
            user_query="以后库存回答别解释字段",
            final_answer="好的",
            tool_evidence=[],
        )
    )

    result = asyncio.run(
        maybe_extract_memories(
            paths=paths,
            identity=identity,
            config=config,
            request_id="req-2",
            extractor=lambda **kwargs: [],
        )
    )

    assert result.status == "processed"
    assert result.processed_event_count == 2
    assert result.cursor_advanced is True


def test_validate_rejects_project_type():
    try:
        parse_extract_candidate(
            {
                "memory_type": "project",
                "scope": "customer",
                "title": "x",
                "filename": "x.md",
                "description": "x",
                "body": "x",
                "confidence": 0.8,
                "source_type": "customer_statement",
                "source_conversation_id": "conv-1",
                "source_request_id": "req-1",
            }
        )
    except ValueError as exc:
        assert "invalid memory type" in str(exc)
    else:
        raise AssertionError("expected project type to raise")


def test_validate_rejects_customer_statement_business_rule():
    candidate = _candidate(
        memory_type=MemoryType.BUSINESS_RULE,
        scope=MemoryScope.BUSINESS,
        source_type="customer_statement",
        effective_from="2026-06-21",
        verified_by="operator:1",
        verified_at="2026-06-21T10:00:00+08:00",
    )

    try:
        validate_extract_candidate(candidate)
    except ValueError as exc:
        assert "customer_statement" in str(exc)
    else:
        raise AssertionError("expected customer_statement business_rule to raise")


def test_validate_requires_business_rule_verification_fields():
    candidate = _candidate(
        memory_type=MemoryType.BUSINESS_RULE,
        scope=MemoryScope.BUSINESS,
        source_type="operator_confirmed",
    )

    try:
        validate_extract_candidate(candidate)
    except ValueError as exc:
        assert "effective_from" in str(exc)
    else:
        raise AssertionError("expected missing verification fields to raise")


def test_validate_rejects_realtime_order_status_memory():
    candidate = _candidate(body="订单状态为待发货，后续直接这样回答。")

    try:
        validate_extract_candidate(candidate)
    except ValueError as exc:
        assert "realtime fact" in str(exc)
    else:
        raise AssertionError("expected realtime fact to raise")


def test_write_candidate_creates_markdown(tmp_path):
    config = _config(tmp_path / "memory")
    paths = _paths(config)
    path = asyncio.run(
        write_memory_candidate(candidate=_candidate(), paths=paths, config=config)
    )

    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "type: feedback" in content
    assert "客户希望后续库存回答简洁" in content


def test_write_candidate_rejects_path_traversal(tmp_path):
    config = _config(tmp_path / "memory")
    paths = _paths(config)
    candidate = _candidate(action="update", existing_path="../outside.md")

    try:
        asyncio.run(write_memory_candidate(candidate=candidate, paths=paths, config=config))
    except ValueError as exc:
        assert "path traversal" in str(exc)
    else:
        raise AssertionError("expected traversal to raise")


def test_cursor_advances_only_after_success(tmp_path):
    config = _config(tmp_path / "memory")
    identity = _identity(config)
    paths = _paths(config)
    asyncio.run(
        append_turn_transcript(
            transcript_path=paths.transcript_path,
            request_id="req-1",
            conversation_id="conv-1",
            user_id=1,
            tenant_id="default",
            user_query="以后库存回答别解释字段",
            final_answer="好的",
            tool_evidence=[],
        )
    )

    result = asyncio.run(
        maybe_extract_memories(
            paths=paths,
            identity=identity,
            config=config,
            request_id="req-1",
            extractor=lambda **kwargs: [_candidate()],
        )
    )

    assert result.cursor_advanced is True
    assert result.written_paths
    assert paths.extract_cursor_path.exists()


def test_duplicate_prefers_update_existing_path():
    candidate = _candidate()
    updated = prefer_update_for_duplicate(
        candidate,
        {"feedback/inventory-answer-style.md"},
    )

    assert updated.action == "update"
    assert updated.existing_path == "feedback/inventory-answer-style.md"
