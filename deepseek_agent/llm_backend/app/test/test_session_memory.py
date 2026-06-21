import asyncio
from pathlib import Path

from app.memory_system.config import MemorySystemConfig
from app.memory_system.session_memory import (
    SessionMemoryConfig,
    build_deterministic_session_summary,
    load_session_memory,
    should_update_session_memory,
    update_session_memory,
    validate_session_summary,
)


def _config(root: Path, **kwargs) -> MemorySystemConfig:
    defaults = {
        "enabled": True,
        "session_memory_enabled": True,
        "memory_root": root,
    }
    defaults.update(kwargs)
    return MemorySystemConfig(**defaults)


def test_load_session_memory_missing(tmp_path):
    state = asyncio.run(load_session_memory(tmp_path / "summary.md"))

    assert state.exists is False
    assert state.content is None


def test_validate_session_summary_requires_all_sections():
    try:
        validate_session_summary("# Session Title\n")
    except ValueError as exc:
        assert "missing sections" in str(exc)
    else:
        raise AssertionError("expected missing sections to raise")


def test_should_init_after_token_threshold():
    decision = should_update_session_memory(
        current_summary=None,
        recent_messages=[],
        tool_evidence=[],
        token_estimate=10,
        config=SessionMemoryConfig(minimum_message_tokens_to_init=10),
    )

    assert decision.should_update is True
    assert decision.reason == "init_token_threshold"


def test_should_update_after_tool_threshold():
    decision = should_update_session_memory(
        current_summary="existing",
        recent_messages=[],
        tool_evidence=[{"a": 1}, {"b": 2}],
        token_estimate=1,
        config=SessionMemoryConfig(tool_calls_between_updates=2),
    )

    assert decision.should_update is True
    assert decision.reason == "tool_call_threshold"


def test_should_skip_below_threshold():
    decision = should_update_session_memory(
        current_summary="existing",
        recent_messages=[],
        tool_evidence=[],
        token_estimate=1,
        config=SessionMemoryConfig(minimum_tokens_between_update=100),
    )

    assert decision.should_update is False
    assert decision.reason == "below_threshold"


def test_update_session_memory_writes_summary(tmp_path):
    config = _config(tmp_path / "memory")
    summary_path = config.memory_root / "sessions" / "conv-1" / "summary.md"

    result = asyncio.run(
        update_session_memory(
            summary_path=summary_path,
            context_bundle={"recent_messages": [{"role": "user", "content": "查库存"}]},
            user_query="查库存",
            final_answer="有货",
            tool_evidence=[{"tool_name": "multi_tool_workflow", "result_digest": "库存有货", "request_id": "rid"}],
            config=config,
            session_config=SessionMemoryConfig(
                minimum_message_tokens_to_init=1,
                minimum_tokens_between_update=1,
                tool_calls_between_updates=1,
            ),
        )
    )

    assert result.status == "updated"
    assert summary_path.exists()
    validate_session_summary(summary_path.read_text(encoding="utf-8"))


def test_update_session_memory_rejects_missing_sections(tmp_path):
    config = _config(tmp_path / "memory")
    summary_path = config.memory_root / "sessions" / "conv-1" / "summary.md"

    result = asyncio.run(
        update_session_memory(
            summary_path=summary_path,
            context_bundle={},
            user_query="查库存",
            final_answer="有货",
            tool_evidence=[],
            config=config,
            session_config=SessionMemoryConfig(minimum_message_tokens_to_init=1),
            generator=lambda **kwargs: "# Session Title\n",
        )
    )

    assert result.status == "failed"
    assert result.error_type == "ValueError"


def test_build_deterministic_session_summary_is_valid():
    summary = build_deterministic_session_summary(
        recent_messages=[],
        user_query="查库存",
        final_answer="有货",
        tool_evidence=[],
    )

    validate_session_summary(summary)
