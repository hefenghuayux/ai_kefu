from __future__ import annotations

import argparse
import asyncio
import inspect
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.memory_system.config import load_memory_config
from app.memory_system.paths import build_memory_identity, resolve_memory_paths
from app.memory_system.session_memory import load_session_memory
from app.memory_system.transcripts import read_transcript_events
from app.services.llm_factory import LLMFactory

from .config import SkillSystemConfig, load_skill_config
from .frontmatter import parse_skill_markdown, parse_skill_frontmatter
from .paths import (
    assert_under_skill_root,
    build_skill_identity,
    ensure_skill_directory,
    resolve_skill_paths,
)
from .render import render_skill_markdown
from .schemas import (
    ALLOWED_SKILL_TOOLS,
    SkillContextMode,
    SkillDraft,
    SkillFrontmatter,
    SkillScope,
    SkillStatus,
    SkillStep,
    SkillifyInput,
    SkillifyResult,
)
from .skill_scan import format_skill_manifest, scan_skill_files


PROMPT_PATH = Path(__file__).with_name("prompts") / "skillify.md"


class SkillifyInputError(ValueError):
    pass


class SkillDraftParseError(ValueError):
    pass


class SkillDraftValidationError(ValueError):
    pass


async def generate_skill_draft(
    input: SkillifyInput,
    *,
    llm: Any = None,
    config: SkillSystemConfig | None = None,
) -> SkillifyResult:
    skill_config = config or load_skill_config()
    prompt = _build_prompt(input)
    service = llm or LLMFactory.create_reasoner_service()
    raw_response = await _call_llm(service, [{"role": "user", "content": prompt}])
    draft = _draft_from_llm_json(raw_response, input)
    markdown = render_skill_markdown(draft, config=skill_config)
    identity = build_skill_identity(
        scope=draft.frontmatter.scope,
        tenant_id=draft.frontmatter.tenant_id,
        customer_id=draft.frontmatter.customer_id,
    )
    skill_paths = resolve_skill_paths(identity, skill_config, draft.frontmatter.name)
    if skill_paths.skill_file_path is None:
        raise SkillDraftValidationError("resolved skill file path is missing")
    return SkillifyResult(
        draft=draft,
        markdown=markdown,
        skill_file_path=skill_paths.skill_file_path,
        prompt=prompt,
        raw_response=raw_response,
    )


async def generate_skill_from_conversation(
    *,
    conversation_id: str,
    user_id: int,
    tenant_id: str,
    scope: SkillScope = SkillScope.BUSINESS,
    description: str,
    customer_id: str | None = None,
    source_request_id: str | None = None,
    llm: Any = None,
    skill_config: SkillSystemConfig | None = None,
) -> SkillifyResult:
    memory_config = load_memory_config()
    memory_identity = build_memory_identity(
        user_id=user_id,
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        config=memory_config,
    )
    memory_paths = resolve_memory_paths(identity=memory_identity, config=memory_config)
    if memory_paths.transcript_path is None or not memory_paths.transcript_path.exists():
        raise SkillifyInputError(
            "transcript not found; enable AI_KEFU_MEMORY_TRANSCRIPT_ENABLED "
            "and run a conversation first"
        )

    session_summary = None
    if memory_paths.session_summary_path is not None:
        session_state = await load_session_memory(memory_paths.session_summary_path)
        session_summary = session_state.content

    effective_skill_config = skill_config or load_skill_config()
    events = await read_transcript_events(memory_paths.transcript_path)
    events = events[-effective_skill_config.max_transcript_events :]
    skill_scan = scan_skill_files(
        effective_skill_config.skill_root,
        config=effective_skill_config,
    )
    skill_input = SkillifyInput(
        description=description,
        conversation_id=conversation_id,
        user_id=user_id,
        tenant_id=tenant_id,
        customer_id=customer_id,
        scope=scope,
        session_summary=session_summary,
        transcript_events=tuple(_event_to_dict(event) for event in events),
        existing_skill_manifest=format_skill_manifest(skill_scan.headers),
        source_request_id=source_request_id,
    )
    return await generate_skill_draft(
        skill_input,
        llm=llm,
        config=effective_skill_config,
    )


def save_skill_draft(result: SkillifyResult, *, overwrite: bool = False) -> Path:
    skill_path = result.skill_file_path
    root = _infer_skill_root(skill_path)
    assert_under_skill_root(skill_path, root)
    if skill_path.exists():
        if not overwrite:
            raise FileExistsError(f"skill already exists: {skill_path}")
        existing = parse_skill_markdown(skill_path.read_text(encoding="utf-8"))
        existing_frontmatter = parse_skill_frontmatter(existing.frontmatter)
        if existing_frontmatter.status != SkillStatus.DRAFT:
            raise FileExistsError(f"only draft skills can be overwritten: {skill_path}")

    ensure_skill_directory(skill_path.parent)
    skill_path.write_text(result.markdown, encoding="utf-8", newline="\n")
    return skill_path


def _build_prompt(input: SkillifyInput) -> str:
    if not input.description.strip():
        raise SkillifyInputError("description is required")
    template = PROMPT_PATH.read_text(encoding="utf-8")
    transcript_json = json.dumps(
        list(input.transcript_events),
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    replacements = {
        "{description}": input.description,
        "{session_summary}": input.session_summary or "",
        "{transcript_events}": transcript_json,
        "{existing_skill_manifest}": input.existing_skill_manifest or "",
    }
    prompt = template
    for placeholder, value in replacements.items():
        prompt = prompt.replace(placeholder, value)
    return prompt


async def _call_llm(service: Any, messages: list[dict[str, str]]) -> str:
    response = service.generate(messages)
    if inspect.isawaitable(response):
        response = await response
    if not isinstance(response, str):
        raise SkillDraftParseError("llm response must be a string")
    return response


def _draft_from_llm_json(raw_response: str, input: SkillifyInput) -> SkillDraft:
    try:
        raw = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise SkillDraftParseError("llm response is not strict JSON") from exc
    if not isinstance(raw, dict):
        raise SkillDraftValidationError("skill draft JSON must be an object")

    now = _now_iso()
    name = _required_str(raw, "name")
    allowed_tools = tuple(_string_list(raw.get("allowed_tools"), "allowed_tools"))
    for tool in allowed_tools:
        if tool not in ALLOWED_SKILL_TOOLS:
            raise SkillDraftValidationError(f"unsupported skill tool: {tool}")

    context = SkillContextMode(_required_str(raw, "context"))
    frontmatter = SkillFrontmatter(
        name=name,
        description=_required_str(raw, "description"),
        when_to_use=_required_str(raw, "when_to_use"),
        allowed_tools=allowed_tools,
        argument_hint=_optional_str(raw.get("argument_hint")),
        arguments=tuple(_string_list(raw.get("arguments"), "arguments")),
        context=context,
        status=SkillStatus.DRAFT,
        scope=input.scope,
        tenant_id=input.tenant_id,
        customer_id=input.customer_id,
        created_at=now,
        updated_at=now,
        source_conversation_id=input.conversation_id,
        source_request_id=input.source_request_id,
        generated_by="skillify_mvp",
    )
    parse_skill_frontmatter(
        {
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
    )

    steps = tuple(_parse_step(item) for item in _required_list(raw, "steps"))
    return SkillDraft(
        frontmatter=frontmatter,
        title=_required_str(raw, "title"),
        inputs=tuple(_string_list(raw.get("inputs"), "inputs")),
        goal=_required_str(raw, "goal"),
        steps=steps,
        constraints=tuple(_string_list(raw.get("constraints"), "constraints")),
        source_notes=tuple(_string_list(raw.get("source_notes"), "source_notes")),
    )


def _parse_step(raw: Any) -> SkillStep:
    if not isinstance(raw, dict):
        raise SkillDraftValidationError("skill step must be an object")
    return SkillStep(
        title=_required_str(raw, "title"),
        action=_required_str(raw, "action"),
        success_criteria=_required_str(raw, "success_criteria"),
        artifacts=tuple(_string_list(raw.get("artifacts"), "artifacts")),
        rules=tuple(_string_list(raw.get("rules"), "rules")),
        human_checkpoint=_optional_str(raw.get("human_checkpoint")),
    )


def _required_str(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SkillDraftValidationError(f"missing required string field: {key}")
    return value.strip()


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise SkillDraftValidationError(f"optional field must be string or null: {value!r}")
    return value.strip() or None


def _required_list(raw: dict[str, Any], key: str) -> list[Any]:
    value = raw.get(key)
    if not isinstance(value, list) or not value:
        raise SkillDraftValidationError(f"missing required list field: {key}")
    return value


def _string_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise SkillDraftValidationError(f"field {field_name} must be a list")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SkillDraftValidationError(
                f"field {field_name} must contain non-empty strings"
            )
        result.append(item.strip())
    return result


def _event_to_dict(event: Any) -> dict[str, Any]:
    if is_dataclass(event):
        return _jsonable(asdict(event))
    if isinstance(event, dict):
        return _jsonable(event)
    raise SkillifyInputError(f"unsupported transcript event: {type(event).__name__}")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_skill_root(skill_path: Path) -> Path:
    parts = skill_path.parts
    if "runtime" in parts and "skills" in parts:
        index = parts.index("skills")
        return Path(*parts[: index + 1])
    return skill_path.parents[4]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate ai_kefu Skill draft")
    parser.add_argument("--conversation-id", required=True)
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--customer-id")
    parser.add_argument("--scope", choices=[item.value for item in SkillScope], default="business")
    parser.add_argument("--description", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--save", action="store_true")
    parser.add_argument("--overwrite-draft", action="store_true")
    return parser.parse_args()


async def _main_async() -> int:
    args = _parse_args()
    result = await generate_skill_from_conversation(
        conversation_id=args.conversation_id,
        user_id=args.user_id,
        tenant_id=args.tenant_id,
        customer_id=args.customer_id,
        scope=SkillScope(args.scope),
        description=args.description,
    )
    if args.save:
        saved_path = save_skill_draft(result, overwrite=args.overwrite_draft)
        print(f"saved: {saved_path}")
        print(f"name: {result.draft.frontmatter.name}")
        print(f"status: {result.draft.frontmatter.status.value}")
    else:
        print(result.markdown)
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_main_async()))


if __name__ == "__main__":
    main()
