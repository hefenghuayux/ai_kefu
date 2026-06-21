from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from .memory_types import MemoryType


class MemoryScope(StrEnum):
    CUSTOMER = "customer"
    BUSINESS = "business"


@dataclass(frozen=True)
class MemoryIdentity:
    customer_id: str
    tenant_id: str
    conversation_id: str | None
    user_id: int | None


@dataclass(frozen=True)
class MemoryFrontmatter:
    type: MemoryType
    description: str
    created_at: str
    updated_at: str
    confidence: float
    source_conversation_id: str | None = None
    source_request_id: str | None = None
    source_type: str | None = None
    source_ref: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    expires_at: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemoryHeader:
    relative_path: str
    absolute_path: Path
    mtime_ms: float
    description: str | None
    type: MemoryType | None
    scope: MemoryScope
    source_type: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    parse_error: str | None = None


@dataclass(frozen=True)
class MemoryScanResult:
    headers: list[MemoryHeader]
    scanned_file_count: int
    skipped_file_count: int
    skipped_reasons: list[str]
    memory_dirs: tuple[Path, ...]


@dataclass(frozen=True)
class SelectedMemory:
    header: MemoryHeader
    content: str
    truncated: bool


@dataclass
class MemoryTrace:
    enabled: bool = False
    recall_enabled: bool = False
    selected_memory_count: int = 0
    selected_memory_paths: list[str] = field(default_factory=list)
    session_memory_loaded: bool = False
    transcript_status: str | None = None
    extract_status: str | None = None
    auto_dream_status: str | None = None
    skipped_reasons: list[str] = field(default_factory=list)


class TranscriptRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


@dataclass(frozen=True)
class TranscriptToolEvidence:
    tool_name: str
    request_id: str
    raw_ref: str | None
    result_digest: str
    result_count: int | None = None
    elapsed_ms: int | None = None


@dataclass(frozen=True)
class TranscriptEvent:
    event_id: str
    timestamp: str
    request_id: str
    conversation_id: str
    user_id: int
    tenant_id: str
    role: TranscriptRole
    content: str
    content_digest: str
    tool_calls: tuple[str, ...] = ()
    tool_evidence: tuple[TranscriptToolEvidence, ...] = ()
    source: str = "main_agent"


@dataclass(frozen=True)
class ExtractCursor:
    conversation_id: str
    last_event_id: str | None
    last_line_index: int
    updated_at: str
