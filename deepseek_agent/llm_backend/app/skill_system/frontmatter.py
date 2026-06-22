from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import validate_skill_name
from .schemas import (
    ALLOWED_SKILL_TOOLS,
    DENIED_SKILL_TOOLS,
    SkillContextMode,
    SkillFrontmatter,
    SkillScope,
    SkillStatus,
)


@dataclass(frozen=True)
class ParsedSkillMarkdown:
    frontmatter: dict[str, Any]
    body: str
    has_frontmatter: bool


def parse_skill_markdown(content: str) -> ParsedSkillMarkdown:
    lines = content.splitlines(keepends=True)
    if not lines:
        return ParsedSkillMarkdown(frontmatter={}, body="", has_frontmatter=False)
    if lines[0].strip() != "---":
        return ParsedSkillMarkdown(frontmatter={}, body=content, has_frontmatter=False)

    closing_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing_index = index
            break
    if closing_index is None:
        raise ValueError("unterminated skill frontmatter")

    raw_frontmatter = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :])
    return ParsedSkillMarkdown(
        frontmatter=_parse_yaml_subset(raw_frontmatter),
        body=body,
        has_frontmatter=True,
    )


def parse_skill_frontmatter(raw: dict[str, Any]) -> SkillFrontmatter:
    name = validate_skill_name(_require_non_empty_str(raw, "name"))
    description = _require_non_empty_str(raw, "description")
    when_to_use = _require_non_empty_str(raw, "when_to_use")
    allowed_tools = _parse_allowed_tools(raw.get("allowed-tools"))
    arguments = _parse_str_list(raw.get("arguments"), "arguments")
    context = SkillContextMode(_require_non_empty_str(raw, "context"))
    status = SkillStatus(_require_non_empty_str(raw, "status"))
    scope = SkillScope(_require_non_empty_str(raw, "scope"))
    tenant_id = _require_non_empty_str(raw, "tenant_id")
    customer_id = _optional_str(raw.get("customer_id"))
    if scope == SkillScope.CUSTOMER and not customer_id:
        raise ValueError("customer_id is required when scope=customer")
    return SkillFrontmatter(
        name=name,
        description=description,
        when_to_use=when_to_use,
        allowed_tools=allowed_tools,
        argument_hint=_optional_str(raw.get("argument-hint")),
        arguments=arguments,
        context=context,
        status=status,
        scope=scope,
        tenant_id=tenant_id,
        customer_id=customer_id,
        created_at=_require_non_empty_str(raw, "created_at"),
        updated_at=_require_non_empty_str(raw, "updated_at"),
        source_conversation_id=_optional_str(raw.get("source_conversation_id")),
        source_request_id=_optional_str(raw.get("source_request_id")),
        generated_by=_require_non_empty_str(raw, "generated_by"),
    )


def dump_skill_frontmatter_markdown(frontmatter: SkillFrontmatter, body: str) -> str:
    data: dict[str, Any] = {
        "name": frontmatter.name,
        "description": frontmatter.description,
        "when_to_use": frontmatter.when_to_use,
        "allowed-tools": list(frontmatter.allowed_tools),
        "argument-hint": frontmatter.argument_hint,
        "arguments": list(frontmatter.arguments),
        "context": frontmatter.context.value,
        "status": frontmatter.status.value,
        "scope": frontmatter.scope.value,
        "tenant_id": frontmatter.tenant_id,
        "customer_id": frontmatter.customer_id,
        "created_at": frontmatter.created_at,
        "updated_at": frontmatter.updated_at,
        "source_conversation_id": frontmatter.source_conversation_id,
        "source_request_id": frontmatter.source_request_id,
        "generated_by": frontmatter.generated_by,
    }

    lines = ["---\n"]
    for key, value in data.items():
        if key in {"allowed-tools", "arguments"}:
            lines.append(f"{key}:\n")
            for item in value:
                lines.append(f"  - {_format_scalar(item)}\n")
            continue
        lines.append(f"{key}: {_format_scalar(value)}\n")
    lines.append("---\n\n")
    lines.append(body.lstrip("\n"))
    return "".join(lines)


def read_skill_frontmatter_prefix(path: Path, max_lines: int) -> str:
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


def _parse_allowed_tools(value: Any) -> tuple[str, ...]:
    tools = _parse_str_list(value, "allowed-tools")
    for tool in tools:
        if tool in DENIED_SKILL_TOOLS:
            raise ValueError(f"denied skill tool: {tool}")
        if tool not in ALLOWED_SKILL_TOOLS:
            raise ValueError(f"unsupported skill tool: {tool}")
    return tools


def _parse_str_list(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"frontmatter field {field_name} must be a list of strings")
    items = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"frontmatter field {field_name} must be a list of non-empty strings"
            )
        items.append(item.strip())
    return tuple(items)


def _require_non_empty_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"frontmatter field {key} must be a non-empty string")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"frontmatter optional field must be string or null: {value!r}")
    return value.strip() or None


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
