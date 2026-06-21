from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable, Literal, Sequence

from .config import MemorySystemConfig
from .frontmatter import (
    TRUSTED_BUSINESS_RULE_SOURCE_TYPES,
    dump_frontmatter_markdown,
)
from .memory_scan import format_memory_manifest, scan_memory_roots
from .memory_types import MemoryType, require_memory_type
from .paths import MemoryPaths, assert_under_memory_root, memory_file_path, normalize_memory_filename
from .schemas import MemoryFrontmatter, MemoryIdentity, MemoryScope, TranscriptEvent, TranscriptRole
from .transcripts import read_transcript_since_cursor, update_extract_cursor


ExtractAction = Literal["create", "update"]


@dataclass(frozen=True)
class ExtractMemoryCandidate:
    memory_type: MemoryType
    scope: MemoryScope
    title: str
    filename: str
    description: str
    body: str
    confidence: float
    source_type: str
    source_conversation_id: str
    source_request_id: str
    effective_from: str | None = None
    effective_to: str | None = None
    verified_by: str | None = None
    verified_at: str | None = None
    action: ExtractAction = "create"
    existing_path: str | None = None


@dataclass(frozen=True)
class ExtractMemoriesResult:
    status: str
    reason: str | None
    processed_event_count: int
    written_paths: list[str]
    updated_paths: list[str]
    rejected_count: int
    cursor_advanced: bool
    error_type: str | None = None


MemoryExtractor = Callable[..., Awaitable[Sequence[ExtractMemoryCandidate | dict[str, Any]]] | Sequence[ExtractMemoryCandidate | dict[str, Any]]]


async def maybe_extract_memories(
    *,
    paths: MemoryPaths,
    identity: MemoryIdentity,
    config: MemorySystemConfig,
    request_id: str,
    extractor: MemoryExtractor | None = None,
    max_events: int = 50,
) -> ExtractMemoriesResult:
    if not config.enabled:
        return _extract_result("skipped", "memory_disabled")
    if not config.extract_memories_enabled:
        return _extract_result("skipped", "extract_memories_disabled")
    if paths.transcript_path is None:
        return _extract_result("skipped", "missing_transcript_path")
    if identity.conversation_id is None:
        return _extract_result("skipped", "missing_conversation_id")

    events, cursor = await read_transcript_since_cursor(
        transcript_path=paths.transcript_path,
        cursor_path=paths.extract_cursor_path,
        conversation_id=identity.conversation_id,
        max_events=max_events,
    )
    if not events:
        return _extract_result("skipped", "no_new_transcript_events")

    scan_result = await scan_memory_roots(paths, config=config)
    manifest = format_memory_manifest(scan_result.headers)
    prompt_messages = build_extract_prompt(
        events=events,
        manifest=manifest,
        current_date=datetime.now(timezone.utc).date().isoformat(),
    )

    if extractor is None:
        raw_candidates = extract_candidates_deterministic(
            events=events,
            identity=identity,
            request_id=request_id,
        )
    else:
        extracted = extractor(
            prompt_messages=prompt_messages,
            events=events,
            manifest=manifest,
            identity=identity,
            request_id=request_id,
        )
        raw_candidates = await extracted if inspect.isawaitable(extracted) else extracted

    written_paths: list[str] = []
    updated_paths: list[str] = []
    rejected_count = 0
    existing_paths = {header.relative_path for header in scan_result.headers}

    for raw_candidate in raw_candidates:
        try:
            candidate = (
                raw_candidate
                if isinstance(raw_candidate, ExtractMemoryCandidate)
                else parse_extract_candidate(raw_candidate)
            )
            candidate = prefer_update_for_duplicate(candidate, existing_paths)
            path = await write_memory_candidate(
                candidate=candidate,
                paths=paths,
                config=config,
            )
            display_path = _display_path(path, paths.root)
            if candidate.action == "update":
                updated_paths.append(display_path)
            else:
                written_paths.append(display_path)
        except (KeyError, TypeError, ValueError, PermissionError, OSError) as exc:
            rejected_count += 1

    last_line_index = cursor.last_line_index + len(events)
    await update_extract_cursor(
        cursor_path=paths.extract_cursor_path,
        conversation_id=identity.conversation_id,
        last_event=events[-1],
        last_line_index=last_line_index,
    )
    return ExtractMemoriesResult(
        status="processed",
        reason=None,
        processed_event_count=len(events),
        written_paths=written_paths,
        updated_paths=updated_paths,
        rejected_count=rejected_count,
        cursor_advanced=True,
    )


def build_extract_prompt(
    *,
    events: list[TranscriptEvent],
    manifest: str,
    current_date: str,
) -> list[dict[str, str]]:
    payload = {
        "current_date": current_date,
        "manifest": manifest,
        "events": [
            {
                "event_id": event.event_id,
                "request_id": event.request_id,
                "role": event.role.value,
                "content": event.content,
                "tool_evidence": [item.__dict__ for item in event.tool_evidence],
            }
            for event in events
        ],
        "schema": {
            "candidates": [
                {
                    "memory_type": "customer|feedback|business_rule|reference",
                    "scope": "customer|business",
                    "title": "short title",
                    "filename": "safe-name.md",
                    "description": "one sentence",
                    "body": "markdown body",
                    "confidence": 0.0,
                    "source_type": "customer_statement|operator_confirmed|official_doc|tool_verified|policy_import|manual_review",
                    "source_conversation_id": "conversation id",
                    "source_request_id": "request id",
                    "action": "create|update",
                    "existing_path": "relative/path.md or null",
                }
            ]
        },
    }
    system_prompt = (
        "你是智能客服系统的长期记忆抽取器。只输出 JSON。"
        "只能根据 transcript 新增事件抽取；不要调查源码、git、API 实现；不要调用业务系统重新查。"
        "普通客户表达不能生成 business_rule；business_rule 必须有可信 source_type 和验证字段。"
        "订单、库存、价格、物流、售后进度等实时事实不能写长期 memory。"
        "优先更新 manifest 中已有 memory，不要重复创建。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
    ]


def parse_extract_candidate(raw: dict[str, Any]) -> ExtractMemoryCandidate:
    memory_type = require_memory_type(raw.get("memory_type", raw.get("type")))
    action = str(raw.get("action", "create"))
    if action not in {"create", "update"}:
        raise ValueError(f"invalid extract action: {action}")
    return ExtractMemoryCandidate(
        memory_type=memory_type,
        scope=MemoryScope(str(raw["scope"])),
        title=_require_non_empty_str(raw, "title"),
        filename=_require_non_empty_str(raw, "filename"),
        description=_require_non_empty_str(raw, "description"),
        body=_require_non_empty_str(raw, "body"),
        confidence=float(raw["confidence"]),
        source_type=_require_non_empty_str(raw, "source_type"),
        source_conversation_id=_require_non_empty_str(raw, "source_conversation_id"),
        source_request_id=_require_non_empty_str(raw, "source_request_id"),
        effective_from=_optional_str(raw.get("effective_from")),
        effective_to=_optional_str(raw.get("effective_to")),
        verified_by=_optional_str(raw.get("verified_by")),
        verified_at=_optional_str(raw.get("verified_at")),
        action=action,  # type: ignore[arg-type]
        existing_path=_optional_str(raw.get("existing_path")),
    )


def validate_extract_candidate(candidate: ExtractMemoryCandidate) -> None:
    normalize_memory_filename(candidate.filename)
    if candidate.action == "update":
        existing_path = _validate_relative_path(candidate.existing_path)
        if not existing_path.startswith(f"{candidate.memory_type.value}/"):
            raise ValueError("existing_path must match candidate memory_type directory")
    if candidate.confidence < 0 or candidate.confidence > 1:
        raise ValueError("candidate confidence must be between 0 and 1")
    if candidate.scope == MemoryScope.CUSTOMER and candidate.memory_type == MemoryType.BUSINESS_RULE:
        raise ValueError("customer scope cannot contain business_rule")
    if candidate.scope == MemoryScope.BUSINESS and candidate.memory_type == MemoryType.CUSTOMER:
        raise ValueError("business scope cannot contain customer memory")
    if _contains_realtime_fact(candidate.description) or _contains_realtime_fact(candidate.body):
        raise ValueError("candidate contains realtime fact that must come from business system")
    if candidate.memory_type == MemoryType.BUSINESS_RULE:
        if candidate.source_type == "customer_statement":
            raise ValueError("business_rule cannot use source_type=customer_statement")
        if candidate.source_type not in TRUSTED_BUSINESS_RULE_SOURCE_TYPES:
            raise ValueError("business_rule requires trusted source_type")
        if not candidate.effective_from:
            raise ValueError("business_rule requires effective_from")
        if not candidate.verified_by:
            raise ValueError("business_rule requires verified_by")
        if not candidate.verified_at:
            raise ValueError("business_rule requires verified_at")


async def write_memory_candidate(
    *,
    candidate: ExtractMemoryCandidate,
    paths: MemoryPaths,
    config: MemorySystemConfig,
) -> Path:
    validate_extract_candidate(candidate)
    target_path = _target_path_for_candidate(candidate, paths)
    safe_path = assert_under_memory_root(target_path, config.memory_root)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    frontmatter = MemoryFrontmatter(
        type=candidate.memory_type,
        description=candidate.description,
        created_at=now,
        updated_at=now,
        confidence=candidate.confidence,
        source_conversation_id=candidate.source_conversation_id,
        source_request_id=candidate.source_request_id,
        source_type=candidate.source_type,
        effective_from=candidate.effective_from,
        effective_to=candidate.effective_to,
        verified_by=candidate.verified_by,
        verified_at=candidate.verified_at,
    )
    safe_path.write_text(
        dump_frontmatter_markdown(frontmatter, candidate.body),
        encoding="utf-8",
    )
    return safe_path


def prefer_update_for_duplicate(
    candidate: ExtractMemoryCandidate,
    existing_paths: set[str],
) -> ExtractMemoryCandidate:
    if candidate.action != "create":
        return candidate
    relative_path = _candidate_relative_path(candidate)
    if relative_path in existing_paths:
        return replace(candidate, action="update", existing_path=relative_path)
    return candidate


def extract_candidates_deterministic(
    *,
    events: list[TranscriptEvent],
    identity: MemoryIdentity,
    request_id: str,
) -> list[ExtractMemoryCandidate]:
    candidates: list[ExtractMemoryCandidate] = []
    for event in events:
        if event.role != TranscriptRole.USER:
            continue
        text = event.content
        if _looks_like_feedback(text):
            candidates.append(
                ExtractMemoryCandidate(
                    memory_type=MemoryType.FEEDBACK,
                    scope=MemoryScope.CUSTOMER,
                    title="customer-feedback",
                    filename="customer-feedback.md",
                    description=_clip(f"客户反馈：{text}", 120),
                    body=f"客户在会话中表达了可复用反馈：{text}",
                    confidence=0.7,
                    source_type="customer_statement",
                    source_conversation_id=identity.conversation_id or "",
                    source_request_id=event.request_id or request_id,
                )
            )
    return candidates


def _target_path_for_candidate(
    candidate: ExtractMemoryCandidate,
    paths: MemoryPaths,
) -> Path:
    base_dir = (
        paths.customer_memory_dir
        if candidate.scope == MemoryScope.CUSTOMER
        else paths.business_memory_dir
    )
    if candidate.action == "update":
        relative_path = _validate_relative_path(candidate.existing_path)
        return base_dir / relative_path
    return memory_file_path(
        base_memory_dir=base_dir,
        memory_type=candidate.memory_type,
        filename=candidate.filename,
    )


def _candidate_relative_path(candidate: ExtractMemoryCandidate) -> str:
    filename = normalize_memory_filename(candidate.filename)
    return f"{candidate.memory_type.value}/{filename}"


def _validate_relative_path(raw_path: str | None) -> str:
    if not raw_path:
        raise ValueError("existing_path is required for update")
    path = raw_path.replace("\\", "/")
    if Path(path).is_absolute() or path.startswith("/"):
        raise ValueError("existing_path must be relative")
    pure_path = PurePosixPath(path)
    if ".." in pure_path.parts:
        raise ValueError("existing_path cannot contain path traversal")
    return path


def _contains_realtime_fact(text: str) -> bool:
    patterns = (
        "order_status",
        "inventory_count",
        "shipment_status",
        "after_sales_progress",
        "订单状态",
        "库存数量",
        "实时库存",
        "当前库存",
        "物流状态",
        "售后进度",
        "待发货",
        "已发货",
        "库存有货",
        "库存不足",
    )
    lowered = text.lower()
    if re.search(r"价格[为是:：]\s*\d+", text):
        return True
    return any(pattern in lowered or pattern in text for pattern in patterns)


def _looks_like_feedback(text: str) -> bool:
    return any(word in text for word in ("以后", "下次", "希望", "不要", "别")) and any(
        word in text for word in ("回答", "解释", "客服", "库存", "物流")
    )


def _require_non_empty_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"candidate field {key} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"candidate optional field must be string or null: {value!r}")
    return value


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _extract_result(
    status: str,
    reason: str | None,
    *,
    error_type: str | None = None,
) -> ExtractMemoriesResult:
    return ExtractMemoriesResult(
        status=status,
        reason=reason,
        processed_event_count=0,
        written_paths=[],
        updated_paths=[],
        rejected_count=0,
        cursor_advanced=False,
        error_type=error_type,
    )


def _clip(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[:limit] + "..."
