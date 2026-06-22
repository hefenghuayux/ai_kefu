from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any


class SkillScope(StrEnum):
    BUSINESS = "business"
    CUSTOMER = "customer"


class SkillStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"


class SkillContextMode(StrEnum):
    INLINE = "inline"
    FORK = "fork"


ALLOWED_SKILL_TOOLS = {
    "knowledge_query",
    "order_query",
    "inventory_query",
    "logistics_query",
    "after_sales_query",
    "customer_profile_read",
    "memory_read",
    "transcript_read",
}

DENIED_SKILL_TOOLS = {
    "shell",
    "bash",
    "cmd",
    "powershell",
    "mysql_write",
    "inventory_update",
    "payment",
}


@dataclass(frozen=True)
class SkillIdentity:
    scope: SkillScope
    tenant_id: str
    customer_id: str | None = None


@dataclass(frozen=True)
class SkillPaths:
    root: Path
    scope_dir: Path
    skill_dir: Path | None = None
    skill_file_path: Path | None = None


@dataclass(frozen=True)
class SkillFrontmatter:
    name: str
    description: str
    when_to_use: str
    allowed_tools: tuple[str, ...]
    argument_hint: str | None
    arguments: tuple[str, ...]
    context: SkillContextMode
    status: SkillStatus
    scope: SkillScope
    tenant_id: str
    customer_id: str | None
    created_at: str
    updated_at: str
    source_conversation_id: str | None
    source_request_id: str | None
    generated_by: str = "skillify_mvp"


@dataclass(frozen=True)
class SkillStep:
    title: str
    action: str
    success_criteria: str
    artifacts: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    human_checkpoint: str | None = None


@dataclass(frozen=True)
class SkillDraft:
    frontmatter: SkillFrontmatter
    title: str
    inputs: tuple[str, ...]
    goal: str
    steps: tuple[SkillStep, ...]
    constraints: tuple[str, ...]
    source_notes: tuple[str, ...]


@dataclass(frozen=True)
class SkillifyInput:
    description: str
    conversation_id: str
    user_id: int | None = None
    tenant_id: str = "default"
    customer_id: str | None = None
    scope: SkillScope = SkillScope.BUSINESS
    session_summary: str | None = None
    transcript_events: tuple[dict[str, Any], ...] = ()
    existing_skill_manifest: str = ""
    source_request_id: str | None = None


@dataclass(frozen=True)
class SkillifyResult:
    draft: SkillDraft
    markdown: str
    skill_file_path: Path
    prompt: str
    raw_response: str


@dataclass(frozen=True)
class SkillHeader:
    name: str | None
    description: str | None
    when_to_use: str | None
    scope: SkillScope | None
    status: SkillStatus | None
    relative_path: str
    absolute_path: Path
    updated_at: str | None
    parse_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillScanResult:
    headers: list[SkillHeader]
    scanned_file_count: int
    skipped_file_count: int
    skipped_reasons: list[str]
    skill_root: Path
