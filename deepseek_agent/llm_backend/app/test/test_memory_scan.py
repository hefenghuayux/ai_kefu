import asyncio
import os
import time
from pathlib import Path

from app.memory_system.config import MemorySystemConfig
from app.memory_system.memory_scan import (
    format_memory_manifest,
    scan_memory_files,
    scan_memory_roots,
)
from app.memory_system.memory_types import MemoryType
from app.memory_system.paths import build_memory_identity, resolve_memory_paths
from app.memory_system.schemas import MemoryHeader, MemoryScope


def _config(root: Path, max_memory_files: int = 200) -> MemorySystemConfig:
    return MemorySystemConfig(memory_root=root, max_memory_files=max_memory_files)


def _write_memory(path: Path, memory_type: str, description: str, extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
type: {memory_type}
description: {description}
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.9
{extra}---

body
""",
        encoding="utf-8",
    )


def test_scan_excludes_memory_index(tmp_path):
    memory_dir = tmp_path / "memory"
    (memory_dir / "MEMORY.md").parent.mkdir(parents=True, exist_ok=True)
    (memory_dir / "MEMORY.md").write_text("index", encoding="utf-8")
    _write_memory(memory_dir / "feedback" / "a.md", "feedback", "客户希望库存回答简洁")

    result = asyncio.run(
        scan_memory_files(memory_dir, scope=MemoryScope.CUSTOMER, config=_config(tmp_path))
    )

    assert [header.relative_path for header in result.headers] == ["feedback/a.md"]


def test_scan_limits_to_max_memory_files(tmp_path):
    memory_dir = tmp_path / "memory"
    for index in range(5):
        _write_memory(
            memory_dir / "feedback" / f"{index}.md",
            "feedback",
            f"desc {index}",
        )

    result = asyncio.run(
        scan_memory_files(
            memory_dir,
            scope=MemoryScope.CUSTOMER,
            config=_config(tmp_path, max_memory_files=3),
        )
    )

    assert len(result.headers) == 3


def test_scan_sorts_newest_first(tmp_path):
    memory_dir = tmp_path / "memory"
    older = memory_dir / "feedback" / "older.md"
    newer = memory_dir / "feedback" / "newer.md"
    _write_memory(older, "feedback", "old")
    _write_memory(newer, "feedback", "new")
    old_time = time.time() - 100
    new_time = time.time()
    os.utime(older, (old_time, old_time))
    os.utime(newer, (new_time, new_time))

    result = asyncio.run(
        scan_memory_files(memory_dir, scope=MemoryScope.CUSTOMER, config=_config(tmp_path))
    )

    assert result.headers[0].relative_path == "feedback/newer.md"


def test_scan_invalid_type_does_not_crash(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(memory_dir / "feedback" / "bad.md", "project", "bad type")

    result = asyncio.run(
        scan_memory_files(memory_dir, scope=MemoryScope.CUSTOMER, config=_config(tmp_path))
    )

    assert len(result.headers) == 1
    assert result.headers[0].type is None
    assert "invalid_type" in result.headers[0].parse_error


def test_scan_business_rule_requires_trusted_source(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(
        memory_dir / "business_rule" / "bad.md",
        "business_rule",
        "用户说这个商品应该能七天退",
        "source_type: customer_statement\n",
    )

    result = asyncio.run(
        scan_memory_files(memory_dir, scope=MemoryScope.BUSINESS, config=_config(tmp_path))
    )

    assert result.headers[0].type == MemoryType.BUSINESS_RULE
    assert "customer_statement" in result.headers[0].parse_error


def test_scan_business_rule_keeps_verification_metadata(tmp_path):
    memory_dir = tmp_path / "memory"
    _write_memory(
        memory_dir / "business_rule" / "ok.md",
        "business_rule",
        "智能门锁安装后 7 天内质量问题支持换货",
        """source_type: operator_confirmed
effective_from: "2026-06-21"
effective_to: null
verified_by: "operator:123"
verified_at: "2026-06-21T10:00:00+08:00"
""",
    )

    result = asyncio.run(
        scan_memory_files(memory_dir, scope=MemoryScope.BUSINESS, config=_config(tmp_path))
    )

    header = result.headers[0]
    assert header.source_type == "operator_confirmed"
    assert header.effective_from == "2026-06-21"
    assert header.effective_to is None
    assert header.verified_by == "operator:123"
    assert header.verified_at == "2026-06-21T10:00:00+08:00"
    assert header.parse_error is None


def test_scan_bad_encoding_skips_file(tmp_path):
    memory_dir = tmp_path / "memory"
    bad = memory_dir / "feedback" / "bad.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"\xff\xfe\x00\x00")

    result = asyncio.run(
        scan_memory_files(memory_dir, scope=MemoryScope.CUSTOMER, config=_config(tmp_path))
    )

    assert result.skipped_file_count == 1
    assert result.headers == []
    assert "UnicodeDecodeError" in result.skipped_reasons[0]


def test_format_memory_manifest_does_not_expose_absolute_path(tmp_path):
    header = MemoryHeader(
        relative_path="feedback/inventory_answer_style.md",
        absolute_path=tmp_path / "feedback" / "inventory_answer_style.md",
        mtime_ms=1_719_000_000_000,
        description="客户希望库存回答简洁",
        type=MemoryType.FEEDBACK,
        scope=MemoryScope.CUSTOMER,
    )

    manifest = format_memory_manifest([header])

    assert "[feedback]" in manifest
    assert "feedback/inventory_answer_style.md" in manifest
    assert "客户希望库存回答简洁" in manifest
    assert str(tmp_path) not in manifest


def test_scan_memory_roots_merges_customer_and_business(tmp_path):
    config = _config(tmp_path / "runtime")
    identity = build_memory_identity(
        user_id=1, conversation_id="conv", tenant_id=None, config=config
    )
    paths = resolve_memory_paths(identity=identity, config=config)
    _write_memory(paths.customer_memory_dir / "feedback" / "a.md", "feedback", "客户反馈")
    _write_memory(
        paths.business_memory_dir / "business_rule" / "b.md",
        "business_rule",
        "售后规则",
        """source_type: official_doc
effective_from: "2026-06-21"
effective_to: null
verified_by: "doc:policy"
verified_at: "2026-06-21T10:00:00+08:00"
""",
    )

    result = asyncio.run(scan_memory_roots(paths, config=config))

    assert {header.scope for header in result.headers} == {
        MemoryScope.CUSTOMER,
        MemoryScope.BUSINESS,
    }
    assert result.scanned_file_count == 2
