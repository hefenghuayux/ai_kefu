from __future__ import annotations

from pathlib import Path

from .config import SkillSystemConfig
from .frontmatter import (
    parse_skill_frontmatter,
    parse_skill_markdown,
    read_skill_frontmatter_prefix,
)
from .schemas import SkillHeader, SkillScanResult


def scan_skill_files(
    skill_root: Path,
    *,
    config: SkillSystemConfig,
) -> SkillScanResult:
    if not skill_root.exists():
        return SkillScanResult(
            headers=[],
            scanned_file_count=0,
            skipped_file_count=0,
            skipped_reasons=[],
            skill_root=skill_root,
        )
    if not skill_root.is_dir():
        return SkillScanResult(
            headers=[],
            scanned_file_count=0,
            skipped_file_count=1,
            skipped_reasons=[f"not_a_directory:{skill_root}"],
            skill_root=skill_root,
        )

    headers: list[SkillHeader] = []
    skipped_reasons: list[str] = []
    skipped_file_count = 0
    candidates = sorted(
        (path for path in skill_root.rglob("SKILL.md") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for file_path in candidates:
        try:
            prefix = read_skill_frontmatter_prefix(
                file_path, config.frontmatter_max_lines
            )
            headers.append(_parse_skill_header(file_path, skill_root, prefix))
        except (OSError, UnicodeDecodeError) as exc:
            skipped_file_count += 1
            reason = f"{type(exc).__name__}:{_relative_or_name(file_path, skill_root)}"
            skipped_reasons.append(reason)

    return SkillScanResult(
        headers=headers,
        scanned_file_count=len(headers),
        skipped_file_count=skipped_file_count,
        skipped_reasons=skipped_reasons,
        skill_root=skill_root,
    )


def format_skill_manifest(headers: list[SkillHeader]) -> str:
    lines: list[str] = []
    for header in headers:
        name = header.name or "unknown"
        status = header.status.value if header.status else "unknown"
        scope = header.scope.value if header.scope else "unknown"
        line = f"- [{status}/{scope}] {name} @ {header.relative_path}"
        if header.description:
            line += f": {header.description}"
        if header.when_to_use:
            line += f" | when_to_use: {header.when_to_use}"
        if header.parse_errors:
            line += f" | parse_errors: {';'.join(header.parse_errors)}"
        lines.append(line)
    return "\n".join(lines)


def _parse_skill_header(
    file_path: Path,
    skill_root: Path,
    prefix_content: str,
) -> SkillHeader:
    errors: list[str] = []
    raw_frontmatter = {}
    frontmatter = None
    try:
        parsed = parse_skill_markdown(prefix_content)
        raw_frontmatter = parsed.frontmatter
        if not parsed.has_frontmatter:
            errors.append("missing_frontmatter")
        else:
            frontmatter = parse_skill_frontmatter(raw_frontmatter)
    except ValueError as exc:
        errors.append(f"frontmatter_parse_error:{exc}")

    return SkillHeader(
        name=frontmatter.name if frontmatter else _string_or_none(raw_frontmatter.get("name")),
        description=(
            frontmatter.description
            if frontmatter
            else _string_or_none(raw_frontmatter.get("description"))
        ),
        when_to_use=(
            frontmatter.when_to_use
            if frontmatter
            else _string_or_none(raw_frontmatter.get("when_to_use"))
        ),
        scope=frontmatter.scope if frontmatter else None,
        status=frontmatter.status if frontmatter else None,
        relative_path=_relative_or_name(file_path, skill_root),
        absolute_path=file_path,
        updated_at=frontmatter.updated_at if frontmatter else None,
        parse_errors=tuple(errors),
    )


def _relative_or_name(file_path: Path, base_dir: Path) -> str:
    try:
        return file_path.relative_to(base_dir).as_posix()
    except ValueError:
        return file_path.name


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
