from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEEPSEEK_AGENT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MEMORY_ROOT = DEEPSEEK_AGENT_ROOT / "runtime" / "memory"


@dataclass(frozen=True)
class MemorySystemConfig:
    enabled: bool = False
    memory_root: Path = DEFAULT_MEMORY_ROOT
    recall_enabled: bool = False
    transcript_enabled: bool = False
    session_memory_enabled: bool = False
    extract_memories_enabled: bool = False
    auto_dream_enabled: bool = False
    debug_trace_enabled: bool = True
    default_tenant_id: str = "default"
    max_memory_files: int = 200
    frontmatter_max_lines: int = 30
    max_selected_memories: int = 5
    max_memory_body_chars: int = 6000


_BOOL_TRUE = {"1", "true", "yes", "on"}
_BOOL_FALSE = {"0", "false", "no", "off"}


def _read_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in _BOOL_TRUE:
        return True
    if normalized in _BOOL_FALSE:
        return False
    raise ValueError(f"invalid boolean env {name}: {raw!r}")


def _read_positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"invalid integer env {name}: {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"env {name} must be positive: {raw!r}")
    return value


def _read_memory_root() -> Path:
    raw = os.getenv("AI_KEFU_MEMORY_ROOT")
    if raw is None or not raw.strip():
        return DEFAULT_MEMORY_ROOT
    path = Path(raw.strip())
    if not path.is_absolute():
        path = DEEPSEEK_AGENT_ROOT / path
    return path


def load_memory_config() -> MemorySystemConfig:
    return MemorySystemConfig(
        enabled=_read_bool_env("AI_KEFU_MEMORY_ENABLED", False),
        memory_root=_read_memory_root(),
        recall_enabled=_read_bool_env("AI_KEFU_MEMORY_RECALL_ENABLED", False),
        transcript_enabled=_read_bool_env("AI_KEFU_MEMORY_TRANSCRIPT_ENABLED", False),
        session_memory_enabled=_read_bool_env("AI_KEFU_SESSION_MEMORY_ENABLED", False),
        extract_memories_enabled=_read_bool_env(
            "AI_KEFU_EXTRACT_MEMORIES_ENABLED", False
        ),
        auto_dream_enabled=_read_bool_env("AI_KEFU_AUTO_DREAM_ENABLED", False),
        debug_trace_enabled=_read_bool_env(
            "AI_KEFU_MEMORY_DEBUG_TRACE_ENABLED", True
        ),
        default_tenant_id=os.getenv(
            "AI_KEFU_MEMORY_DEFAULT_TENANT_ID", "default"
        ).strip()
        or "default",
        max_memory_files=_read_positive_int_env("AI_KEFU_MEMORY_MAX_FILES", 200),
        frontmatter_max_lines=_read_positive_int_env(
            "AI_KEFU_MEMORY_FRONTMATTER_MAX_LINES", 30
        ),
        max_selected_memories=_read_positive_int_env(
            "AI_KEFU_MEMORY_MAX_SELECTED", 5
        ),
        max_memory_body_chars=_read_positive_int_env(
            "AI_KEFU_MEMORY_MAX_BODY_CHARS", 6000
        ),
    )
