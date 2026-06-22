from __future__ import annotations

import re
from pathlib import Path

from .config import SkillSystemConfig
from .schemas import SkillIdentity, SkillPaths, SkillScope


_SKILL_NAME_RE = re.compile(r"^[a-z0-9-]{3,64}$")
_IDENTITY_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


def validate_skill_name(name: str) -> str:
    if not isinstance(name, str) or not _SKILL_NAME_RE.fullmatch(name):
        raise ValueError(f"invalid skill name: {name!r}")
    return name


def _validate_identity_segment(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
        or not _IDENTITY_SEGMENT_RE.fullmatch(normalized)
    ):
        raise ValueError(f"invalid {field_name}: {value!r}")
    return normalized


def build_skill_identity(
    *,
    scope: SkillScope | str,
    tenant_id: str | None,
    customer_id: str | None,
) -> SkillIdentity:
    skill_scope = SkillScope(scope)
    normalized_tenant = _validate_identity_segment(tenant_id or "default", "tenant_id")
    normalized_customer = (
        _validate_identity_segment(customer_id, "customer_id")
        if isinstance(customer_id, str)
        else None
    )
    if skill_scope == SkillScope.CUSTOMER and not normalized_customer:
        raise ValueError("customer_id is required when scope=customer")
    return SkillIdentity(
        scope=skill_scope,
        tenant_id=normalized_tenant,
        customer_id=normalized_customer,
    )


def resolve_skill_paths(
    identity: SkillIdentity,
    config: SkillSystemConfig,
    skill_name: str | None = None,
) -> SkillPaths:
    root = config.skill_root
    if identity.scope == SkillScope.BUSINESS:
        scope_dir = root / "business" / identity.tenant_id / "skills"
    else:
        if not identity.customer_id:
            raise ValueError("customer_id is required when scope=customer")
        scope_dir = root / "customers" / identity.customer_id / "skills"

    skill_dir = None
    skill_file_path = None
    if skill_name is not None:
        normalized_name = validate_skill_name(skill_name)
        skill_dir = scope_dir / normalized_name
        skill_file_path = skill_dir / "SKILL.md"

    return SkillPaths(
        root=root,
        scope_dir=scope_dir,
        skill_dir=skill_dir,
        skill_file_path=skill_file_path,
    )


def assert_under_skill_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PermissionError(f"path outside skill root: {resolved}") from exc
    return resolved


def ensure_skill_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
