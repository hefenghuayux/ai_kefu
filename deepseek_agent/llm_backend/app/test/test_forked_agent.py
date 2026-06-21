import asyncio

from app.memory_system.forked_agent import (
    ForkedAgentRequest,
    ForkedAgentStep,
    run_forked_agent,
)
from app.memory_system.permissions import create_auto_mem_tool_policy


def _request(tmp_path, **kwargs):
    memory_root = tmp_path / "memory"
    transcript_root = tmp_path / "transcripts"
    memory_root.mkdir()
    transcript_root.mkdir()
    defaults = {
        "prompt_messages": [{"role": "user", "content": "hello"}],
        "query_source": "session_memory",
        "fork_label": "test",
        "tool_policy": create_auto_mem_tool_policy(
            memory_root=memory_root,
            transcript_root=transcript_root,
        ),
    }
    defaults.update(kwargs)
    return ForkedAgentRequest(**defaults)


def test_run_forked_agent_respects_skip_transcript_default(tmp_path):
    request = _request(tmp_path)

    result = asyncio.run(run_forked_agent(request))

    assert request.skip_transcript is True
    assert result.status == "completed"
    assert result.content == "hello"
    assert result.tool_calls == 0


def test_run_forked_agent_stops_at_max_turns(tmp_path):
    def runner(turn_index, request):
        return ForkedAgentStep(
            content=f"turn-{turn_index}",
            tool_calls=1,
            denied_tool_calls=1,
            should_continue=True,
        )

    request = _request(tmp_path, max_turns=3, runner=runner)

    result = asyncio.run(run_forked_agent(request))

    assert result.status == "max_turns_exceeded"
    assert result.tool_calls == 3
    assert result.denied_tool_calls == 3
    assert result.content == "turn-0\nturn-1\nturn-2"


def test_run_forked_agent_completes_when_runner_stops(tmp_path):
    def runner(turn_index, request):
        return ForkedAgentStep(content="done", tool_calls=1, should_continue=False)

    result = asyncio.run(run_forked_agent(_request(tmp_path, runner=runner)))

    assert result.status == "completed"
    assert result.content == "done"
    assert result.tool_calls == 1


def test_run_forked_agent_rejects_invalid_max_turns(tmp_path):
    result = asyncio.run(run_forked_agent(_request(tmp_path, max_turns=0)))

    assert result.status == "failed"
    assert result.error_type == "InvalidMaxTurns"
