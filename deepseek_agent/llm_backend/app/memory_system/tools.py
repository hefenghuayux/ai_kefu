from __future__ import annotations

import re
from pathlib import Path

from app.core.logger import get_logger, log_event

from .permissions import (
    PermissionDenied,
    ToolPolicy,
    assert_read_allowed,
    assert_write_allowed,
    decide_tool_permission,
)


logger = get_logger("memory_system")


async def read_file(path: Path, policy: ToolPolicy) -> str:
    decision = decide_tool_permission(tool_name="read_file", policy=policy, target_path=path)
    if not decision.allowed:
        _log_denied("read_file", path, decision.reason)
        raise PermissionDenied(decision.reason)
    safe_path = assert_read_allowed(path, policy)
    return safe_path.read_text(encoding="utf-8")


async def grep(pattern: str, root: Path, policy: ToolPolicy) -> list[str]:
    if ".." in Path(pattern).parts:
        raise PermissionDenied("grep pattern cannot contain path traversal")
    safe_root = assert_read_allowed(root, policy)
    regex = re.compile(pattern)
    matches: list[str] = []
    for path in safe_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            safe_path = assert_read_allowed(path, policy)
            for line_number, line in enumerate(
                safe_path.read_text(encoding="utf-8").splitlines(),
                start=1,
            ):
                if regex.search(line):
                    matches.append(f"{safe_path.relative_to(safe_root).as_posix()}:{line_number}:{line}")
        except (UnicodeDecodeError, PermissionDenied):
            continue
    return matches


async def glob(pattern: str, root: Path, policy: ToolPolicy) -> list[str]:
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise PermissionDenied("glob pattern must be relative and stay within root")
    safe_root = assert_read_allowed(root, policy)
    results: list[str] = []
    for path in safe_root.glob(pattern):
        safe_path = assert_read_allowed(path, policy)
        results.append(safe_path.relative_to(safe_root).as_posix())
    return sorted(results)


async def write_file(path: Path, content: str, policy: ToolPolicy) -> None:
    decision = decide_tool_permission(tool_name="write_file", policy=policy, target_path=path)
    if not decision.allowed:
        _log_denied("write_file", path, decision.reason)
        raise PermissionDenied(decision.reason)
    safe_path = assert_write_allowed(path, policy)
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_text(content, encoding="utf-8")


async def edit_file(path: Path, old: str, new: str, policy: ToolPolicy) -> None:
    decision = decide_tool_permission(tool_name="edit_file", policy=policy, target_path=path)
    if not decision.allowed:
        _log_denied("edit_file", path, decision.reason)
        raise PermissionDenied(decision.reason)
    safe_path = assert_write_allowed(path, policy)
    content = safe_path.read_text(encoding="utf-8")
    if old not in content:
        raise ValueError("old content not found for edit_file")
    safe_path.write_text(content.replace(old, new, 1), encoding="utf-8")


def _log_denied(tool_name: str, path: Path, reason: str) -> None:
    log_event(
        logger,
        "WARNING",
        "memory_tool_denied",
        tool=tool_name,
        path=str(path),
        reason=reason,
    )
