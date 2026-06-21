from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import MemorySystemConfig
from .memory_types import MemoryType, memory_type_directory
from .schemas import MemoryIdentity


@dataclass(frozen=True)
class MemoryPaths:
    root: Path
    customer_memory_dir: Path
    business_memory_dir: Path
    session_summary_path: Path | None
    transcript_path: Path | None
    state_dir: Path
    extract_cursor_path: Path
    auto_dream_lock_path: Path
    auto_dream_state_path: Path
    surfaced_memories_path: Path


_SAFE_FILENAME_RE = re.compile(r"^[a-z0-9_-]+\.md$")
_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def build_memory_identity(
    *,
    user_id: int,
    conversation_id: str | int | None,
    tenant_id: str | None,
    config: MemorySystemConfig,
) -> MemoryIdentity:
    return MemoryIdentity(
        customer_id=str(user_id),
        tenant_id=(tenant_id or config.default_tenant_id).strip() or config.default_tenant_id,
        conversation_id=str(conversation_id) if conversation_id is not None else None,
        user_id=user_id,
    )


def resolve_memory_paths(
    *,
    identity: MemoryIdentity,
    config: MemorySystemConfig,
) -> MemoryPaths:
    root = config.memory_root
    session_summary_path = None
    transcript_path = None
    if identity.conversation_id:
        session_summary_path = root / "sessions" / identity.conversation_id / "summary.md"
        transcript_path = root / "transcripts" / f"{identity.conversation_id}.jsonl"

    state_dir = root / "state"
    return MemoryPaths(
        root=root,
        customer_memory_dir=root / "customers" / identity.customer_id / "memory",
        business_memory_dir=root / "business" / identity.tenant_id / "memory",
        session_summary_path=session_summary_path,
        transcript_path=transcript_path,
        state_dir=state_dir,
        extract_cursor_path=state_dir / "extract_cursor.json",
        auto_dream_lock_path=state_dir / "auto_dream.lock",
        auto_dream_state_path=state_dir / "auto_dream_state.json",
        surfaced_memories_path=state_dir / "surfaced_memories.json",
    )


def assert_under_memory_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PermissionError(f"path outside memory root: {resolved}") from exc
    return resolved


def ensure_memory_directories(paths: MemoryPaths) -> None:
    assert_under_memory_root(paths.root, paths.root)

    customer_dirs = [
        paths.customer_memory_dir / "customer",
        paths.customer_memory_dir / "feedback",
        paths.customer_memory_dir / "reference",
    ]
    business_dirs = [
        paths.business_memory_dir / "business_rule",
        paths.business_memory_dir / "feedback",
        paths.business_memory_dir / "reference",
    ]
    directories = [
        paths.customer_memory_dir,
        *customer_dirs,
        paths.business_memory_dir,
        *business_dirs,
        paths.state_dir,
        paths.root / "transcripts",
    ]
    if paths.session_summary_path is not None:
        directories.append(paths.session_summary_path.parent)

    for directory in directories:
        assert_under_memory_root(directory, paths.root)
        directory.mkdir(parents=True, exist_ok=True)

    for index_path in (paths.customer_memory_dir / "MEMORY.md", paths.business_memory_dir / "MEMORY.md"):
        assert_under_memory_root(index_path, paths.root)
        if not index_path.exists():
            index_path.write_text("", encoding="utf-8")


def memory_file_path(
    *,
    base_memory_dir: Path,
    memory_type: MemoryType,
    filename: str,
) -> Path:
    normalized = normalize_memory_filename(filename)
    return base_memory_dir / memory_type_directory(memory_type) / normalized


def normalize_memory_filename(title: str) -> str:
    raw = title.strip().lower()
    if not raw:
        raise ValueError("memory filename cannot be empty")
    if "/" in raw or "\\" in raw or ".." in raw:
        raise ValueError(f"invalid memory filename: {title!r}")
    if not raw.endswith(".md"):
        raw = f"{raw}.md"
    slug_base = raw[:-3]
    slug_base = _SLUG_RE.sub("-", slug_base).strip("-_")
    if not slug_base:
        raise ValueError(f"invalid memory filename: {title!r}")
    normalized = f"{slug_base}.md"
    if not _SAFE_FILENAME_RE.match(normalized):
        raise ValueError(f"invalid memory filename: {title!r}")
    return normalized
