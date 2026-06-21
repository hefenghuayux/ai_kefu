import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.memory_system.auto_dream import (
    AutoDreamConfig,
    AutoDreamLocked,
    acquire_auto_dream_lock,
    run_auto_dream,
    should_run_auto_dream,
    update_memory_index,
)
from app.memory_system.config import MemorySystemConfig
from app.memory_system.memory_scan import scan_memory_roots
from app.memory_system.paths import build_memory_identity, resolve_memory_paths


def _config(root: Path, **kwargs) -> MemorySystemConfig:
    defaults = {
        "enabled": True,
        "auto_dream_enabled": True,
        "memory_root": root,
    }
    defaults.update(kwargs)
    return MemorySystemConfig(**defaults)


def _paths(config: MemorySystemConfig):
    identity = build_memory_identity(
        user_id=1, conversation_id="conv-1", tenant_id=None, config=config
    )
    return resolve_memory_paths(identity=identity, config=config)


def _write_transcripts(transcript_root: Path, count: int) -> None:
    transcript_root.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (transcript_root / f"conv-{index}.jsonl").write_text(
            '{"event_id":"evt","content":"hello"}\n',
            encoding="utf-8",
        )


def _write_feedback(path: Path, description: str = "客户希望库存回答简洁") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
type: feedback
description: {description}
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.9
---
secret body should not enter index
""",
        encoding="utf-8",
    )


def _write_business_rule(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """---
type: business_rule
description: 智能门锁安装后 7 天内质量问题支持换货
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.95
source_type: operator_confirmed
effective_from: "2026-06-21"
effective_to: null
verified_by: "operator:123"
verified_at: "2026-06-21T10:00:00+08:00"
---
规则正文
""",
        encoding="utf-8",
    )


def test_auto_dream_skips_before_min_hours(tmp_path):
    state_path = tmp_path / "state" / "auto_dream_state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            {
                "last_consolidated_at": datetime.now(timezone.utc).isoformat(),
                "processed_session_ids": [],
            }
        ),
        encoding="utf-8",
    )
    transcript_root = tmp_path / "transcripts"
    _write_transcripts(transcript_root, 10)

    decision = should_run_auto_dream(
        state_path=state_path,
        transcript_root=transcript_root,
        config=AutoDreamConfig(min_hours=24, min_sessions=1),
    )

    assert decision.should_run is False
    assert decision.reason == "min_hours_not_reached"


def test_auto_dream_skips_before_min_sessions(tmp_path):
    transcript_root = tmp_path / "transcripts"
    _write_transcripts(transcript_root, 2)

    decision = should_run_auto_dream(
        state_path=tmp_path / "state" / "auto_dream_state.json",
        transcript_root=transcript_root,
        config=AutoDreamConfig(min_hours=0, min_sessions=5),
    )

    assert decision.should_run is False
    assert decision.reason == "min_sessions_not_reached"


def test_auto_dream_force_runs(tmp_path):
    config = _config(tmp_path / "memory")
    paths = _paths(config)
    _write_transcripts(paths.root / "transcripts", 1)
    _write_feedback(paths.customer_memory_dir / "feedback" / "inventory.md")

    result = asyncio.run(
        run_auto_dream(
            paths=paths,
            config=config,
            auto_config=AutoDreamConfig(min_hours=999, min_sessions=999),
            force=True,
        )
    )

    assert result.status == "completed"
    assert result.index_updated is True
    assert (paths.customer_memory_dir / "MEMORY.md").exists()
    assert paths.auto_dream_state_path.exists()


def test_auto_dream_lock_prevents_concurrent_run(tmp_path):
    lock_path = tmp_path / "state" / "auto_dream.lock"
    lock_path.parent.mkdir(parents=True)
    lock_path.write_text("locked", encoding="utf-8")

    try:
        async def _try_lock():
            async with acquire_auto_dream_lock(lock_path, stale_after_seconds=99999):
                pass

        asyncio.run(_try_lock())
    except AutoDreamLocked as exc:
        assert "lock exists" in str(exc)
    else:
        raise AssertionError("expected lock to prevent concurrent run")


def test_update_memory_index_excludes_body(tmp_path):
    config = _config(tmp_path / "memory")
    paths = _paths(config)
    _write_feedback(paths.customer_memory_dir / "feedback" / "inventory.md")
    scan = asyncio.run(scan_memory_roots(paths, config=config))

    asyncio.run(update_memory_index(paths.customer_memory_dir, scan.headers))

    index = (paths.customer_memory_dir / "MEMORY.md").read_text(encoding="utf-8")
    assert "secret body" not in index
    assert "feedback/inventory.md" in index
    assert str(paths.root) not in index


def test_business_rule_metadata_preserved(tmp_path):
    config = _config(tmp_path / "memory")
    paths = _paths(config)
    rule_path = paths.business_memory_dir / "business_rule" / "after_sales.md"
    _write_business_rule(rule_path)
    _write_transcripts(paths.root / "transcripts", 1)

    result = asyncio.run(
        run_auto_dream(paths=paths, config=config, force=True)
    )

    content = rule_path.read_text(encoding="utf-8")
    assert result.status == "completed"
    assert "source_type: operator_confirmed" in content
    assert "verified_by: \"operator:123\"" in content
