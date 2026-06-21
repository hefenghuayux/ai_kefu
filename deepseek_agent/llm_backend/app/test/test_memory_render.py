from app.memory_system.render import render_memory_context


def test_render_memory_context_empty():
    assert render_memory_context(session_summary="", relevant_memories=[]) == ""
