from __future__ import annotations

import argparse
import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from .config import MemorySystemConfig, load_memory_config
from .forked_agent import ForkedAgentRequest, ForkedAgentRunner, run_forked_agent
from .memory_scan import format_memory_manifest, scan_memory_roots
from .paths import MemoryPaths, build_memory_identity, resolve_memory_paths
from .permissions import create_auto_mem_tool_policy
from .schemas import MemoryHeader


@dataclass(frozen=True)
class AutoDreamConfig:
    min_hours: int = 24
    min_sessions: int = 5
    lock_stale_seconds: int = 7200
    transcript_summary_chars: int = 1200


@dataclass(frozen=True)
class AutoDreamDecision:
    should_run: bool
    reason: str
    session_ids: list[str]


@dataclass(frozen=True)
class AutoDreamResult:
    status: str
    reason: str | None
    session_count: int
    updated_paths: list[str]
    deleted_paths: list[str]
    index_updated: bool
    error_type: str | None = None


class AutoDreamLocked(RuntimeError):
    pass


def should_run_auto_dream(
    *,
    state_path: Path,
    transcript_root: Path,
    config: AutoDreamConfig,
    force: bool = False,
) -> AutoDreamDecision:
    state = _read_auto_dream_state(state_path)
    session_ids = _list_transcript_session_ids(transcript_root)
    processed_session_ids = set(state.get("processed_session_ids", []))
    new_session_ids = [session_id for session_id in session_ids if session_id not in processed_session_ids]

    if force:
        return AutoDreamDecision(True, "force", new_session_ids or session_ids)

    last_consolidated_at = _parse_datetime(state.get("last_consolidated_at"))
    if last_consolidated_at is not None:
        age = datetime.now(timezone.utc) - last_consolidated_at
        if age < timedelta(hours=config.min_hours):
            return AutoDreamDecision(False, "min_hours_not_reached", new_session_ids)

    if len(new_session_ids) < config.min_sessions:
        return AutoDreamDecision(False, "min_sessions_not_reached", new_session_ids)

    return AutoDreamDecision(True, "threshold_reached", new_session_ids)


@asynccontextmanager
async def acquire_auto_dream_lock(
    lock_path: Path,
    *,
    stale_after_seconds: int = 7200,
) -> AsyncIterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            lock_path.stat().st_mtime,
            tz=timezone.utc,
        )
        if age.total_seconds() < stale_after_seconds:
            raise AutoDreamLocked(f"auto_dream lock exists: {lock_path}")
        lock_path.unlink()
    try:
        with lock_path.open("x", encoding="utf-8") as file_obj:
            file_obj.write(datetime.now(timezone.utc).isoformat())
        yield
    finally:
        if lock_path.exists():
            lock_path.unlink()


async def run_auto_dream(
    *,
    paths: MemoryPaths,
    config: MemorySystemConfig,
    auto_config: AutoDreamConfig | None = None,
    force: bool = False,
    runner: ForkedAgentRunner | None = None,
) -> AutoDreamResult:
    if not config.enabled:
        return _auto_result("skipped", "memory_disabled")
    if not config.auto_dream_enabled:
        return _auto_result("skipped", "auto_dream_disabled")

    active_auto_config = auto_config or AutoDreamConfig()
    transcript_root = paths.root / "transcripts"
    decision = should_run_auto_dream(
        state_path=paths.auto_dream_state_path,
        transcript_root=transcript_root,
        config=active_auto_config,
        force=force,
    )
    if not decision.should_run:
        return AutoDreamResult(
            status="skipped",
            reason=decision.reason,
            session_count=len(decision.session_ids),
            updated_paths=[],
            deleted_paths=[],
            index_updated=False,
        )

    try:
        async with acquire_auto_dream_lock(
            paths.auto_dream_lock_path,
            stale_after_seconds=active_auto_config.lock_stale_seconds,
        ):
            scan_result = await scan_memory_roots(paths, config=config)
            transcript_summaries = read_recent_transcript_summaries(
                transcript_root=transcript_root,
                session_ids=decision.session_ids,
                max_chars=active_auto_config.transcript_summary_chars,
            )
            prompt_messages = build_consolidation_prompt(
                manifest=format_memory_manifest(scan_result.headers),
                transcript_summaries=transcript_summaries,
            )
            policy = create_auto_mem_tool_policy(
                memory_root=paths.root,
                transcript_root=transcript_root,
            )
            await run_forked_agent(
                ForkedAgentRequest(
                    prompt_messages=prompt_messages,
                    query_source="auto_dream",
                    fork_label="auto_dream",
                    tool_policy=policy,
                    skip_transcript=True,
                    max_turns=5,
                    runner=runner,
                )
            )
            updated_paths = await update_memory_indexes(paths, scan_result.headers)
            _write_auto_dream_state(
                paths.auto_dream_state_path,
                processed_session_ids=decision.session_ids,
            )
            return AutoDreamResult(
                status="completed",
                reason=decision.reason,
                session_count=len(decision.session_ids),
                updated_paths=updated_paths,
                deleted_paths=[],
                index_updated=bool(updated_paths),
            )
    except AutoDreamLocked as exc:
        return _auto_result("skipped", "locked", error_type=exc.__class__.__name__)
    except Exception as exc:
        return _auto_result("failed", str(exc), error_type=exc.__class__.__name__)


def build_consolidation_prompt(
    *,
    manifest: str,
    transcript_summaries: list[str],
) -> list[dict[str, str]]:
    system_prompt = (
        "你是智能客服 memory 系统的 AutoDream 整理器。"
        "只在 memory_root 内读写；不要调用业务系统；不要把普通客户表达升级为 business_rule。"
        "business_rule 必须保留可信来源字段。订单、库存、价格、物流、售后进度以实时工具为准。"
    )
    payload = {
        "phase_1_orient": "查看 memory manifest 和 MEMORY.md。",
        "phase_2_gather_recent_signal": "只读取相关 transcript 摘要，避免全量读取大文件。",
        "phase_3_consolidate": "合并重复 memory，修正矛盾和过期项，保留 business_rule 可信来源字段。",
        "phase_4_prune_and_index": "更新 MEMORY.md，删除 stale/superseded 指针。",
        "manifest": manifest,
        "recent_transcripts": transcript_summaries,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


async def update_memory_index(memory_dir: Path, headers: list[MemoryHeader]) -> None:
    memory_dir.mkdir(parents=True, exist_ok=True)
    matching_headers = [
        header
        for header in headers
        if header.parse_error is None
        and header.type is not None
        and _is_relative_to(header.absolute_path, memory_dir)
    ]
    matching_headers.sort(key=lambda header: header.relative_path)
    lines = [
        "# MEMORY",
        "",
        "This index is generated from Markdown memory frontmatter. It does not contain memory bodies.",
        "",
    ]
    for header in matching_headers:
        description = header.description or ""
        lines.append(f"- [{header.type.value}] {header.relative_path}: {description}".rstrip())
    content = "\n".join(lines).rstrip() + "\n"
    (memory_dir / "MEMORY.md").write_text(content, encoding="utf-8")


async def update_memory_indexes(paths: MemoryPaths, headers: list[MemoryHeader]) -> list[str]:
    updated_paths: list[str] = []
    for memory_dir in (paths.customer_memory_dir, paths.business_memory_dir):
        await update_memory_index(memory_dir, headers)
        updated_paths.append((memory_dir / "MEMORY.md").relative_to(paths.root).as_posix())
    return updated_paths


def read_recent_transcript_summaries(
    *,
    transcript_root: Path,
    session_ids: list[str],
    max_chars: int,
) -> list[str]:
    summaries: list[str] = []
    for session_id in session_ids:
        path = transcript_root / f"{session_id}.jsonl"
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        if len(content) > max_chars:
            content = content[-max_chars:]
        summaries.append(f"## transcript:{session_id}\n{content}")
    return summaries


def _read_auto_dream_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {}
    with state_path.open("r", encoding="utf-8") as file_obj:
        state = json.load(file_obj)
    if not isinstance(state, dict):
        raise ValueError("auto_dream_state must be a JSON object")
    return state


def _write_auto_dream_state(
    state_path: Path,
    *,
    processed_session_ids: list[str],
) -> None:
    previous = _read_auto_dream_state(state_path)
    all_processed = sorted(set(previous.get("processed_session_ids", [])) | set(processed_session_ids))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with state_path.open("w", encoding="utf-8") as file_obj:
        json.dump(
            {
                "last_consolidated_at": datetime.now(timezone.utc).isoformat(),
                "processed_session_ids": all_processed,
            },
            file_obj,
            ensure_ascii=False,
            indent=2,
        )
        file_obj.write("\n")


def _list_transcript_session_ids(transcript_root: Path) -> list[str]:
    if not transcript_root.exists():
        return []
    return sorted(path.stem for path in transcript_root.glob("*.jsonl") if path.is_file())


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _auto_result(
    status: str,
    reason: str | None,
    *,
    error_type: str | None = None,
) -> AutoDreamResult:
    return AutoDreamResult(
        status=status,
        reason=reason,
        session_count=0,
        updated_paths=[],
        deleted_paths=[],
        index_updated=False,
        error_type=error_type,
    )


async def _run_cli() -> AutoDreamResult:
    parser = argparse.ArgumentParser(description="Run ai_kefu memory AutoDream once.")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--user-id", type=int, default=0)
    parser.add_argument("--conversation-id", default="manual-auto-dream")
    parser.add_argument("--tenant-id", default=None)
    args = parser.parse_args()

    config = load_memory_config()
    identity = build_memory_identity(
        user_id=args.user_id,
        conversation_id=args.conversation_id,
        tenant_id=args.tenant_id,
        config=config,
    )
    paths = resolve_memory_paths(identity=identity, config=config)
    return await run_auto_dream(paths=paths, config=config, force=args.force)


if __name__ == "__main__":
    print(asyncio.run(_run_cli()))
