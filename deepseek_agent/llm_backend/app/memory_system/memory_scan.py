from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from app.core.logger import get_logger, log_event

from .config import MemorySystemConfig
from .frontmatter import parse_frontmatter_markdown, parse_memory_frontmatter, read_frontmatter_prefix
from .memory_types import MemoryType, parse_memory_type
from .paths import MemoryPaths
from .schemas import MemoryHeader, MemoryScanResult, MemoryScope


logger = get_logger("memory_system")

_ALLOWED_TYPES_BY_SCOPE = {
    MemoryScope.CUSTOMER: {
        MemoryType.CUSTOMER,
        MemoryType.FEEDBACK,
        MemoryType.REFERENCE,
    },
    MemoryScope.BUSINESS: {
        MemoryType.BUSINESS_RULE,
        MemoryType.FEEDBACK,
        MemoryType.REFERENCE,
    },
}


async def scan_memory_files(
    memory_dir: Path,
    *,
    scope: MemoryScope,
    config: MemorySystemConfig,
) -> MemoryScanResult:
    started_at = time.perf_counter()
    log_event(
        logger,
        "INFO",
        "memory_scan_started",
        memory_dir=str(memory_dir),
        scope=scope.value,
    )

    if not memory_dir.exists():
        return MemoryScanResult(
            headers=[],
            scanned_file_count=0,
            skipped_file_count=0,
            skipped_reasons=[],
            memory_dirs=(memory_dir,),
        )
    if not memory_dir.is_dir():
        reason = f"not_a_directory:{memory_dir}"
        return MemoryScanResult(
            headers=[],
            scanned_file_count=0,
            skipped_file_count=1,
            skipped_reasons=[reason],
            memory_dirs=(memory_dir,),
        )

    headers: list[MemoryHeader] = []
    skipped_reasons: list[str] = []
    scanned_file_count = 0
    skipped_file_count = 0

    try:
        candidates = sorted(
            (
                path
                for path in memory_dir.rglob("*.md")
                if path.name != "MEMORY.md" and path.is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError as exc:
        reason = f"scan_failed:{type(exc).__name__}:{memory_dir}"
        log_event(
            logger,
            "WARNING",
            "memory_scan_file_skipped",
            memory_dir=str(memory_dir),
            scope=scope.value,
            reason=reason,
            exception=exc,
        )
        return MemoryScanResult(
            headers=[],
            scanned_file_count=0,
            skipped_file_count=1,
            skipped_reasons=[reason],
            memory_dirs=(memory_dir,),
        )

    for file_path in candidates:
        try:
            mtime_ms = file_path.stat().st_mtime * 1000
            prefix = read_frontmatter_prefix(file_path, config.frontmatter_max_lines)
            headers.append(
                parse_memory_header(
                    file_path=file_path,
                    base_dir=memory_dir,
                    scope=scope,
                    prefix_content=prefix,
                    mtime_ms=mtime_ms,
                )
            )
            scanned_file_count += 1
        except (OSError, UnicodeDecodeError) as exc:
            skipped_file_count += 1
            reason = f"{type(exc).__name__}:{_relative_or_name(file_path, memory_dir)}"
            skipped_reasons.append(reason)
            log_event(
                logger,
                "WARNING",
                "memory_scan_file_skipped",
                memory_dir=str(memory_dir),
                scope=scope.value,
                reason=reason,
                exception=exc,
            )

    headers.sort(key=lambda header: header.mtime_ms, reverse=True)
    headers = headers[: config.max_memory_files]
    elapsed_ms = int((time.perf_counter() - started_at) * 1000)
    log_event(
        logger,
        "INFO",
        "memory_scan_finished",
        memory_dir=str(memory_dir),
        scope=scope.value,
        scanned_file_count=scanned_file_count,
        header_count=len(headers),
        skipped_file_count=skipped_file_count,
        elapsed_ms=elapsed_ms,
    )
    return MemoryScanResult(
        headers=headers,
        scanned_file_count=scanned_file_count,
        skipped_file_count=skipped_file_count,
        skipped_reasons=skipped_reasons,
        memory_dirs=(memory_dir,),
    )


async def scan_memory_roots(
    paths: MemoryPaths,
    *,
    config: MemorySystemConfig,
) -> MemoryScanResult:
    customer = await scan_memory_files(
        paths.customer_memory_dir, scope=MemoryScope.CUSTOMER, config=config
    )
    business = await scan_memory_files(
        paths.business_memory_dir, scope=MemoryScope.BUSINESS, config=config
    )
    headers = [*customer.headers, *business.headers]
    headers.sort(key=lambda header: header.mtime_ms, reverse=True)
    headers = headers[: config.max_memory_files]
    return MemoryScanResult(
        headers=headers,
        scanned_file_count=customer.scanned_file_count + business.scanned_file_count,
        skipped_file_count=customer.skipped_file_count + business.skipped_file_count,
        skipped_reasons=[*customer.skipped_reasons, *business.skipped_reasons],
        memory_dirs=(*customer.memory_dirs, *business.memory_dirs),
    )


def parse_memory_header(
    *,
    file_path: Path,
    base_dir: Path,
    scope: MemoryScope,
    prefix_content: str,
    mtime_ms: float,
) -> MemoryHeader:
    errors: list[str] = []
    parsed = None
    raw_frontmatter: dict[str, object] = {}

    try:
        parsed = parse_frontmatter_markdown(prefix_content)
        raw_frontmatter = parsed.frontmatter
        if not parsed.has_frontmatter:
            errors.append("missing_frontmatter")
    except ValueError as exc:
        errors.append(f"frontmatter_parse_error:{exc}")

    raw_type = raw_frontmatter.get("type")
    memory_type = parse_memory_type(raw_type)
    if raw_type is None:
        errors.append("missing_type")
    elif memory_type is None:
        errors.append(f"invalid_type:{raw_type}")

    description = raw_frontmatter.get("description")
    if description is not None and not isinstance(description, str):
        errors.append("invalid_description")
        description = None
    elif isinstance(description, str) and not description.strip():
        errors.append("invalid_description")
        description = None

    if memory_type and memory_type not in _ALLOWED_TYPES_BY_SCOPE[scope]:
        errors.append(f"scope_type_mismatch:{scope.value}:{memory_type.value}")

    if memory_type == MemoryType.BUSINESS_RULE:
        try:
            parse_memory_frontmatter(raw_frontmatter)
        except ValueError as exc:
            errors.append(f"business_rule_validation_error:{exc}")

    return MemoryHeader(
        relative_path=_relative_or_name(file_path, base_dir),
        absolute_path=file_path,
        mtime_ms=mtime_ms,
        description=description.strip() if isinstance(description, str) else None,
        type=memory_type,
        scope=scope,
        source_type=_string_or_none(raw_frontmatter.get("source_type")),
        effective_from=_string_or_none(raw_frontmatter.get("effective_from")),
        effective_to=_string_or_none(raw_frontmatter.get("effective_to")),
        verified_by=_string_or_none(raw_frontmatter.get("verified_by")),
        verified_at=_string_or_none(raw_frontmatter.get("verified_at")),
        parse_error=";".join(errors) if errors else None,
    )


def format_memory_manifest(headers: Sequence[MemoryHeader]) -> str:
    lines: list[str] = []
    for header in headers:
        memory_type = header.type.value if header.type else "unknown"
        timestamp = datetime.fromtimestamp(
            header.mtime_ms / 1000, tz=timezone.utc
        ).isoformat()
        line = f"- [{memory_type}] {header.relative_path} ({timestamp})"
        if header.description:
            line += f": {header.description}"
        lines.append(line)
    return "\n".join(lines)


def filter_headers_by_type(
    headers: Sequence[MemoryHeader],
    allowed_types: set[MemoryType],
) -> list[MemoryHeader]:
    return [header for header in headers if header.type in allowed_types]


def _relative_or_name(file_path: Path, base_dir: Path) -> str:
    try:
        return file_path.relative_to(base_dir).as_posix()
    except ValueError:
        return file_path.name


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)
