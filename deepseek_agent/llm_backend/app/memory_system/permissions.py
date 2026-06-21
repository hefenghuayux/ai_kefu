from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PermissionDenied(PermissionError):
    pass


@dataclass(frozen=True)
class ToolDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class ToolPolicy:
    memory_root: Path
    allowed_read_roots: tuple[Path, ...]
    allowed_write_root: Path
    allow_shell: bool = False
    allow_business_tools: bool = False


def create_auto_mem_tool_policy(
    *,
    memory_root: Path,
    transcript_root: Path,
) -> ToolPolicy:
    return ToolPolicy(
        memory_root=memory_root,
        allowed_read_roots=(memory_root, transcript_root),
        allowed_write_root=memory_root,
        allow_shell=False,
        allow_business_tools=False,
    )


def assert_path_allowed(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PermissionDenied(f"path outside allowed root: {resolved}") from exc
    return resolved


def assert_read_allowed(path: Path, policy: ToolPolicy) -> Path:
    if is_sensitive_path(path):
        raise PermissionDenied(f"sensitive path is not readable: {path}")
    last_error: PermissionDenied | None = None
    for root in policy.allowed_read_roots:
        try:
            return assert_path_allowed(path, root)
        except PermissionDenied as exc:
            last_error = exc
    raise PermissionDenied(f"path outside allowed read roots: {path}") from last_error


def assert_write_allowed(path: Path, policy: ToolPolicy) -> Path:
    if is_sensitive_path(path):
        raise PermissionDenied(f"sensitive path is not writable: {path}")
    return assert_path_allowed(path, policy.allowed_write_root)


def decide_tool_permission(
    *,
    tool_name: str,
    policy: ToolPolicy,
    target_path: Path | None = None,
) -> ToolDecision:
    if tool_name in {"shell", "run_shell", "powershell", "cmd"}:
        return ToolDecision(policy.allow_shell, "shell_allowed" if policy.allow_shell else "shell_denied")
    if tool_name.startswith("business_") or tool_name in {
        "mysql_write",
        "order_update",
        "payment",
        "inventory_update",
    }:
        return ToolDecision(
            policy.allow_business_tools,
            "business_tool_allowed" if policy.allow_business_tools else "business_tool_denied",
        )
    if target_path is None:
        return ToolDecision(True, "no_path_required")
    try:
        if tool_name in {"write_file", "edit_file"}:
            assert_write_allowed(target_path, policy)
        else:
            assert_read_allowed(target_path, policy)
    except PermissionDenied as exc:
        return ToolDecision(False, str(exc))
    return ToolDecision(True, "allowed")


def is_sensitive_path(path: Path) -> bool:
    parts = {part.lower() for part in path.parts}
    name = path.name.lower()
    if name in {".env", ".env.local", ".env.production"}:
        return True
    if name.endswith((".pem", ".key", ".pfx", ".p12")):
        return True
    if "mysql-win" in parts and "data" in parts:
        return True
    if "secrets" in parts:
        return True
    return False
