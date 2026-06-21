from pathlib import Path

from app.memory_system.config import MemorySystemConfig
from app.memory_system.memory_types import MemoryType
from app.memory_system.paths import (
    assert_under_memory_root,
    build_memory_identity,
    ensure_memory_directories,
    memory_file_path,
    normalize_memory_filename,
    resolve_memory_paths,
)


def _config(root: Path) -> MemorySystemConfig:
    return MemorySystemConfig(memory_root=root)


def test_resolve_memory_paths_uses_customer_and_business_roots(tmp_path):
    config = _config(tmp_path / "memory")
    identity = build_memory_identity(
        user_id=7, conversation_id="conv-1", tenant_id=None, config=config
    )
    paths = resolve_memory_paths(identity=identity, config=config)

    assert paths.customer_memory_dir == tmp_path / "memory" / "customers" / "7" / "memory"
    assert paths.business_memory_dir == tmp_path / "memory" / "business" / "default" / "memory"
    assert paths.session_summary_path == tmp_path / "memory" / "sessions" / "conv-1" / "summary.md"
    assert paths.transcript_path == tmp_path / "memory" / "transcripts" / "conv-1.jsonl"


def test_resolve_memory_paths_allows_missing_conversation(tmp_path):
    config = _config(tmp_path / "memory")
    identity = build_memory_identity(
        user_id=7, conversation_id=None, tenant_id="tenant-a", config=config
    )
    paths = resolve_memory_paths(identity=identity, config=config)

    assert paths.session_summary_path is None
    assert paths.transcript_path is None


def test_ensure_memory_directories_creates_runtime_layout(tmp_path):
    config = _config(tmp_path / "memory")
    identity = build_memory_identity(
        user_id=1, conversation_id="abc", tenant_id=None, config=config
    )
    paths = resolve_memory_paths(identity=identity, config=config)

    ensure_memory_directories(paths)

    assert (paths.customer_memory_dir / "MEMORY.md").exists()
    assert (paths.customer_memory_dir / "customer").is_dir()
    assert (paths.customer_memory_dir / "feedback").is_dir()
    assert (paths.customer_memory_dir / "reference").is_dir()
    assert (paths.business_memory_dir / "MEMORY.md").exists()
    assert (paths.business_memory_dir / "business_rule").is_dir()
    assert (paths.business_memory_dir / "feedback").is_dir()
    assert (paths.business_memory_dir / "reference").is_dir()
    assert paths.session_summary_path.parent.is_dir()
    assert paths.state_dir.is_dir()


def test_assert_under_memory_root_rejects_path_traversal(tmp_path):
    root = tmp_path / "memory"
    inside = root / "customers" / "1" / "memory" / "customer" / "a.md"
    outside = root / ".." / "outside.md"

    assert assert_under_memory_root(inside, root) == inside.resolve()
    try:
        assert_under_memory_root(outside, root)
    except PermissionError as exc:
        assert "outside memory root" in str(exc)
    else:
        raise AssertionError("expected outside path to raise")


def test_normalize_memory_filename_and_memory_file_path(tmp_path):
    assert normalize_memory_filename("VIP Style") == "vip-style.md"

    path = memory_file_path(
        base_memory_dir=tmp_path / "memory",
        memory_type=MemoryType.FEEDBACK,
        filename="Inventory Style",
    )
    assert path == tmp_path / "memory" / "feedback" / "inventory-style.md"


def test_normalize_memory_filename_rejects_empty_and_traversal():
    for raw in ("", "../x.md", "a/b.md", "中文"):
        try:
            normalize_memory_filename(raw)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid filename to raise: {raw!r}")
