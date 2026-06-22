from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEEPSEEK_AGENT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILL_ROOT = DEEPSEEK_AGENT_ROOT / "runtime" / "skills"


@dataclass(frozen=True)
class SkillSystemConfig:
    skill_root: Path = DEFAULT_SKILL_ROOT
    frontmatter_max_lines: int = 40
    max_body_chars: int = 12000
    max_transcript_events: int = 40


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


def _read_skill_root() -> Path:
    raw = os.getenv("AI_KEFU_SKILL_ROOT")
    if raw is None or not raw.strip():
        return DEFAULT_SKILL_ROOT
    path = Path(raw.strip())
    if not path.is_absolute():
        path = DEEPSEEK_AGENT_ROOT / path
    return path


def load_skill_config() -> SkillSystemConfig:
    return SkillSystemConfig(
        skill_root=_read_skill_root(),
        frontmatter_max_lines=_read_positive_int_env(
            "AI_KEFU_SKILL_FRONTMATTER_MAX_LINES", 40
        ),
        max_body_chars=_read_positive_int_env("AI_KEFU_SKILL_MAX_BODY_CHARS", 12000),
        max_transcript_events=_read_positive_int_env(
            "AI_KEFU_SKILL_MAX_TRANSCRIPT_EVENTS", 40
        ),
    )
