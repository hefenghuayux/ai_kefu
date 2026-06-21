from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .memory_types import MemoryType, require_memory_type
from .schemas import MemoryFrontmatter


TRUSTED_BUSINESS_RULE_SOURCE_TYPES = {
    "operator_confirmed",
    "official_doc",
    "tool_verified",
    "policy_import",
    "manual_review",
}

_BUSINESS_RULE_REQUIRED_KEYS = (
    "effective_from",
    "effective_to",
    "verified_by",
    "verified_at",
)


@dataclass(frozen=True)
class ParsedMarkdownMemory:
    frontmatter: dict[str, Any]
    body: str
    has_frontmatter: bool


def parse_frontmatter_markdown(content: str) -> ParsedMarkdownMemory:
    lines = content.splitlines(keepends=True)
    if not lines:
        return ParsedMarkdownMemory(frontmatter={}, body="", has_frontmatter=False)
    if lines[0].strip() != "---":
        return ParsedMarkdownMemory(frontmatter={}, body=content, has_frontmatter=False)

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise ValueError("unterminated frontmatter")

    raw_frontmatter = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :])
    return ParsedMarkdownMemory(
        frontmatter=_parse_yaml_subset(raw_frontmatter),
        body=body,
        has_frontmatter=True,
    )


def parse_memory_frontmatter(raw: dict[str, Any]) -> MemoryFrontmatter:
    memory_type = require_memory_type(raw.get("type"))
    description = _require_non_empty_str(raw, "description")
    created_at = _require_non_empty_str(raw, "created_at")
    updated_at = _require_non_empty_str(raw, "updated_at")
    confidence = _require_confidence(raw.get("confidence"))
    tags = _parse_tags(raw.get("tags"))

    if memory_type == MemoryType.BUSINESS_RULE:
        _validate_business_rule_source(raw)

    return MemoryFrontmatter(
        type=memory_type,
        description=description,
        created_at=created_at,
        updated_at=updated_at,
        confidence=confidence,
        source_conversation_id=_optional_str(raw.get("source_conversation_id")),
        source_request_id=_optional_str(raw.get("source_request_id")),
        source_type=_optional_str(raw.get("source_type")),
        source_ref=_optional_str(raw.get("source_ref")),
        effective_from=_optional_str(raw.get("effective_from")),
        effective_to=_optional_str(raw.get("effective_to")),
        verified_by=_optional_str(raw.get("verified_by")),
        verified_at=_optional_str(raw.get("verified_at")),
        expires_at=_optional_str(raw.get("expires_at")),
        tags=tags,
    )


def dump_frontmatter_markdown(frontmatter: MemoryFrontmatter, body: str) -> str:
    data: dict[str, Any] = {
        "type": frontmatter.type.value,
        "description": frontmatter.description,
        "created_at": frontmatter.created_at,
        "updated_at": frontmatter.updated_at,
        "confidence": frontmatter.confidence,
        "source_conversation_id": frontmatter.source_conversation_id,
        "source_request_id": frontmatter.source_request_id,
        "source_type": frontmatter.source_type,
        "source_ref": frontmatter.source_ref,
        "effective_from": frontmatter.effective_from,
        "effective_to": frontmatter.effective_to,
        "verified_by": frontmatter.verified_by,
        "verified_at": frontmatter.verified_at,
        "expires_at": frontmatter.expires_at,
        "tags": list(frontmatter.tags),
    }

    lines = ["---\n"]
    for key, value in data.items():
        if key == "tags":
            lines.append("tags:\n")
            for tag in value:
                lines.append(f"  - {_format_scalar(tag)}\n")
            continue
        lines.append(f"{key}: {_format_scalar(value)}\n")
    lines.append("---\n")
    lines.append(body)
    return "".join(lines)


def read_frontmatter_prefix(path: Path, max_lines: int) -> str:
    if max_lines <= 0:
        raise ValueError("max_lines must be positive")
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as file_obj:
        for _ in range(max_lines):
            line = file_obj.readline()
            if line == "":
                break
            lines.append(line)
    return "".join(lines)


def _parse_yaml_subset(raw: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list_key: str | None = None
    for line_number, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_list_key and line.startswith((" ", "\t")) and stripped.startswith("- "):
            item = stripped[2:].strip()
            result[current_list_key].append(_parse_scalar(item))
            continue
        current_list_key = None
        if ":" not in line:
            raise ValueError(f"invalid frontmatter line {line_number}: {line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key:
            raise ValueError(f"empty frontmatter key on line {line_number}")
        value = value.strip()
        if value == "":
            result[key] = []
            current_list_key = key
        else:
            result[key] = _parse_scalar(value)
    return result


def _parse_scalar(value: str) -> Any:
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if any(char in text for char in [":", "#", "\n", '"']) or text.strip() != text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def _require_non_empty_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"frontmatter field {key} must be a non-empty string")
    return value.strip()


def _require_confidence(value: Any) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError("frontmatter field confidence must be a number")
    confidence = float(value)
    if confidence < 0 or confidence > 1:
        raise ValueError("frontmatter field confidence must be between 0 and 1")
    return confidence


def _parse_tags(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if value == ():
        return ()
    if not isinstance(value, list):
        raise ValueError("frontmatter field tags must be a list of strings")
    tags = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("frontmatter field tags must be a list of non-empty strings")
        tags.append(item.strip())
    return tuple(tags)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"frontmatter optional field must be string or null: {value!r}")
    return value


def _validate_business_rule_source(raw: dict[str, Any]) -> None:
    source_type = raw.get("source_type")
    if source_type == "customer_statement":
        raise ValueError("business_rule cannot use source_type=customer_statement")
    if source_type not in TRUSTED_BUSINESS_RULE_SOURCE_TYPES:
        raise ValueError(
            "business_rule requires trusted source_type: "
            + ", ".join(sorted(TRUSTED_BUSINESS_RULE_SOURCE_TYPES))
        )
    for key in _BUSINESS_RULE_REQUIRED_KEYS:
        if key not in raw:
            raise ValueError(f"business_rule requires frontmatter field {key}")
    if raw.get("effective_from") is None:
        raise ValueError("business_rule requires non-empty effective_from")
    if not raw.get("verified_by"):
        raise ValueError("business_rule requires non-empty verified_by")
    if not raw.get("verified_at"):
        raise ValueError("business_rule requires non-empty verified_at")
