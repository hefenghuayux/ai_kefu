import asyncio
from pathlib import Path

from app.memory_system.config import MemorySystemConfig
from app.memory_system.find_relevant_memories import (
    filter_selected_memory_paths,
    find_relevant_memories,
    read_selected_memory,
    select_relevant_memories_deterministic,
)
from app.memory_system.memory_scan import scan_memory_roots
from app.memory_system.paths import build_memory_identity, resolve_memory_paths
from app.memory_system.render import MEMORY_REALTIME_FACT_WARNING, render_memory_context


def _config(root: Path, **kwargs) -> MemorySystemConfig:
    defaults = {
        "enabled": True,
        "recall_enabled": True,
        "memory_root": root,
        "max_selected_memories": 5,
        "max_memory_body_chars": 200,
    }
    defaults.update(kwargs)
    return MemorySystemConfig(**defaults)


def _paths(config: MemorySystemConfig):
    identity = build_memory_identity(
        user_id=1, conversation_id="conv-1", tenant_id=None, config=config
    )
    return resolve_memory_paths(identity=identity, config=config)


def _write_memory(path: Path, description: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
type: feedback
description: {description}
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.9
---
{body}
""",
        encoding="utf-8",
    )


def test_recall_returns_empty_when_disabled(tmp_path):
    config = _config(tmp_path / "memory", enabled=False)
    result = asyncio.run(
        find_relevant_memories(query="查库存", paths=_paths(config), config=config)
    )

    assert result.selected == []
    assert result.reason == "memory_disabled"


def test_deterministic_selector_selects_by_description(tmp_path):
    config = _config(tmp_path / "memory")
    paths = _paths(config)
    _write_memory(
        paths.customer_memory_dir / "feedback" / "inventory.md",
        "客户希望库存回答简洁，不解释字段",
        "body",
    )
    scan = asyncio.run(scan_memory_roots(paths, config=config))

    selected = select_relevant_memories_deterministic(
        query="帮我查库存，别解释字段",
        headers=scan.headers,
        max_selected=5,
    )

    assert selected == ["feedback/inventory.md"]


def test_selector_filters_invalid_paths():
    selected, skipped = filter_selected_memory_paths(
        [
            "feedback/a.md",
            "../secret.md",
            "C:/secret.md",
            "feedback/a.md",
            "missing.md",
        ],
        valid_paths={"feedback/a.md"},
        max_selected=5,
    )

    assert selected == ["feedback/a.md"]
    assert any("path_traversal" in item for item in skipped)
    assert any("absolute_path" in item for item in skipped)
    assert any("duplicate" in item for item in skipped)
    assert any("not_in_manifest" in item for item in skipped)


def test_recall_reads_selected_memory_body(tmp_path):
    config = _config(tmp_path / "memory")
    paths = _paths(config)
    _write_memory(
        paths.customer_memory_dir / "feedback" / "inventory.md",
        "客户希望库存回答简洁",
        "这是正文",
    )

    result = asyncio.run(
        find_relevant_memories(query="库存回答", paths=paths, config=config)
    )

    assert result.selected_paths == ["feedback/inventory.md"]
    assert result.selected[0].content == "这是正文\n"


def test_recall_truncates_large_memory(tmp_path):
    config = _config(tmp_path / "memory", max_memory_body_chars=5)
    paths = _paths(config)
    _write_memory(paths.customer_memory_dir / "feedback" / "a.md", "库存回答", "abcdefg")
    scan = asyncio.run(scan_memory_roots(paths, config=config))

    memory = asyncio.run(
        read_selected_memory(scan.headers[0], memory_root=paths.root, max_chars=5)
    )

    assert memory.content == "abcde"
    assert memory.truncated is True


def test_render_memory_context_warns_not_realtime_fact(tmp_path):
    config = _config(tmp_path / "memory")
    paths = _paths(config)
    _write_memory(paths.customer_memory_dir / "feedback" / "a.md", "库存回答", "正文")
    result = asyncio.run(
        find_relevant_memories(query="库存回答", paths=paths, config=config)
    )

    rendered = render_memory_context(session_summary="当前会话摘要", relevant_memories=result.selected)

    assert MEMORY_REALTIME_FACT_WARNING in rendered
    assert '<memory path="feedback/a.md"' in rendered
    assert "<session_memory>" in rendered


def test_render_memory_context_does_not_include_empty_section():
    assert render_memory_context(session_summary=None, relevant_memories=[]) == ""
