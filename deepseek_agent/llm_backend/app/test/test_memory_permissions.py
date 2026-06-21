import asyncio
from pathlib import Path

from app.memory_system.permissions import (
    PermissionDenied,
    assert_path_allowed,
    create_auto_mem_tool_policy,
    decide_tool_permission,
)
from app.memory_system.tools import edit_file, glob, grep, read_file, write_file


def _policy(tmp_path: Path):
    memory_root = tmp_path / "memory"
    transcript_root = tmp_path / "transcripts"
    memory_root.mkdir()
    transcript_root.mkdir()
    return create_auto_mem_tool_policy(
        memory_root=memory_root,
        transcript_root=transcript_root,
    )


def test_assert_path_allowed_accepts_memory_root_child(tmp_path):
    root = tmp_path / "memory"
    child = root / "customer" / "a.md"

    assert assert_path_allowed(child, root) == child.resolve()


def test_assert_path_allowed_rejects_sibling_prefix(tmp_path):
    root = tmp_path / "memory"
    sibling = tmp_path / "memory-other" / "a.md"

    try:
        assert_path_allowed(sibling, root)
    except PermissionDenied as exc:
        assert "outside allowed root" in str(exc)
    else:
        raise AssertionError("expected sibling prefix path to be denied")


def test_assert_path_allowed_rejects_dotdot(tmp_path):
    root = tmp_path / "memory"
    outside = root / ".." / "outside.md"

    try:
        assert_path_allowed(outside, root)
    except PermissionDenied as exc:
        assert "outside allowed root" in str(exc)
    else:
        raise AssertionError("expected dotdot path to be denied")


def test_write_file_denied_outside_memory_root(tmp_path):
    policy = _policy(tmp_path)
    outside = tmp_path / "outside.md"

    try:
        asyncio.run(write_file(outside, "x", policy))
    except PermissionDenied as exc:
        assert "outside allowed root" in str(exc)
    else:
        raise AssertionError("expected outside write to be denied")


def test_read_file_denied_sensitive_env(tmp_path):
    policy = _policy(tmp_path)
    env_path = policy.memory_root / ".env"
    env_path.write_text("SECRET=1", encoding="utf-8")

    try:
        asyncio.run(read_file(env_path, policy))
    except PermissionDenied as exc:
        assert "sensitive path" in str(exc)
    else:
        raise AssertionError("expected .env read to be denied")


def test_tool_denied_logs_reason_for_business_tool(tmp_path):
    policy = _policy(tmp_path)

    decision = decide_tool_permission(tool_name="order_update", policy=policy)

    assert decision.allowed is False
    assert decision.reason == "business_tool_denied"


def test_write_and_edit_file_inside_memory_root(tmp_path):
    policy = _policy(tmp_path)
    target = policy.memory_root / "feedback" / "a.md"

    asyncio.run(write_file(target, "hello", policy))
    asyncio.run(edit_file(target, "hello", "你好", policy))

    assert target.read_text(encoding="utf-8") == "你好"


def test_edit_file_missing_old_raises(tmp_path):
    policy = _policy(tmp_path)
    target = policy.memory_root / "a.md"
    target.write_text("hello", encoding="utf-8")

    try:
        asyncio.run(edit_file(target, "missing", "new", policy))
    except ValueError as exc:
        assert "old content not found" in str(exc)
    else:
        raise AssertionError("expected missing old content to raise")


def test_grep_and_glob_are_limited_to_read_roots(tmp_path):
    policy = _policy(tmp_path)
    target = policy.memory_root / "feedback" / "a.md"
    target.parent.mkdir(parents=True)
    target.write_text("客户希望库存回答简洁", encoding="utf-8")

    matches = asyncio.run(grep("库存", policy.memory_root, policy))
    files = asyncio.run(glob("feedback/*.md", policy.memory_root, policy))

    assert matches == ["feedback/a.md:1:客户希望库存回答简洁"]
    assert files == ["feedback/a.md"]
