from __future__ import annotations

import inspect
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable, Sequence

from .config import MemorySystemConfig
from .frontmatter import parse_frontmatter_markdown
from .memory_scan import scan_memory_roots
from .paths import MemoryPaths, assert_under_memory_root
from .schemas import MemoryHeader


@dataclass(frozen=True)
class RelevantMemory:
    header: MemoryHeader
    content: str
    truncated: bool


@dataclass(frozen=True)
class MemoryRecallResult:
    selected: list[RelevantMemory]
    manifest_count: int
    selected_paths: list[str]
    skipped_paths: list[str]
    selector: str
    elapsed_ms: int
    reason: str | None = None


MemorySelector = Callable[..., Awaitable[list[str]] | list[str]]


async def find_relevant_memories(
    *,
    query: str,
    paths: MemoryPaths,
    config: MemorySystemConfig,
    recent_tools: list[str] | None = None,
    already_surfaced: set[str] | None = None,
    selector: MemorySelector | None = None,
) -> MemoryRecallResult:
    started_at = time.perf_counter()
    if not config.enabled:
        return _empty_recall_result(started_at, selector="none", reason="memory_disabled")
    if not config.recall_enabled:
        return _empty_recall_result(started_at, selector="none", reason="recall_disabled")

    scan_result = await scan_memory_roots(paths, config=config)
    headers = [
        header
        for header in scan_result.headers
        if not already_surfaced or header.relative_path not in already_surfaced
    ]
    if not headers:
        return MemoryRecallResult(
            selected=[],
            manifest_count=0,
            selected_paths=[],
            skipped_paths=[],
            selector="deterministic" if selector is None else "custom",
            elapsed_ms=_elapsed_ms(started_at),
            reason="no_memory_headers",
        )

    header_by_path = {header.relative_path: header for header in headers}
    if selector is None:
        selected_paths = select_relevant_memories_deterministic(
            query=query,
            headers=headers,
            max_selected=config.max_selected_memories,
        )
        selector_name = "deterministic"
    else:
        raw_selected = selector(
            query=query,
            headers=headers,
            valid_paths=set(header_by_path),
            recent_tools=recent_tools or [],
            max_selected=config.max_selected_memories,
        )
        selected_paths = await raw_selected if inspect.isawaitable(raw_selected) else raw_selected
        selector_name = getattr(selector, "__name__", "custom")

    filtered_paths, skipped_paths = filter_selected_memory_paths(
        selected_paths,
        valid_paths=set(header_by_path),
        max_selected=config.max_selected_memories,
    )

    selected: list[RelevantMemory] = []
    for relative_path in filtered_paths:
        try:
            selected.append(
                await read_selected_memory(
                    header_by_path[relative_path],
                    memory_root=paths.root,
                    max_chars=config.max_memory_body_chars,
                )
            )
        except (OSError, UnicodeDecodeError, ValueError, PermissionError) as exc:
            skipped_paths.append(f"{relative_path}:{type(exc).__name__}")

    return MemoryRecallResult(
        selected=selected,
        manifest_count=len(headers),
        selected_paths=[item.header.relative_path for item in selected],
        skipped_paths=skipped_paths,
        selector=selector_name,
        elapsed_ms=_elapsed_ms(started_at),
        reason=None if selected else "no_selected_memories",
    )


def select_relevant_memories_deterministic(
    *,
    query: str,
    headers: Sequence[MemoryHeader],
    max_selected: int,
) -> list[str]:
    terms = _query_terms(query)
    scored: list[tuple[int, float, str]] = []
    for header in headers:
        target = f"{header.relative_path} {header.description or ''}".lower()
        score = sum(1 for term in terms if term and term in target)
        if score <= 0:
            continue
        scored.append((score, header.mtime_ms, header.relative_path))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [relative_path for _, _, relative_path in scored[:max_selected]]


async def select_relevant_memories_with_llm(
    *,
    query: str,
    manifest: str,
    valid_paths: set[str],
    recent_tools: list[str],
    llm_client: Any,
) -> list[str]:
    if llm_client is None:
        raise ValueError("llm_client is required for LLM memory selection")
    messages = [
        {
            "role": "system",
            "content": (
                "你是智能客服系统的长期记忆选择器。只输出 JSON。"
                "只选择明确有助于本轮请求的 memory，最多 5 条；不确定就返回空列表。"
                "memory 是历史经验，不是实时事实。订单、库存、价格、物流、售后进度必须以本轮工具查询为准。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "query": query,
                    "recent_tools": recent_tools,
                    "manifest": manifest,
                    "schema": {"selected_memories": ["relative/path.md"]},
                },
                ensure_ascii=False,
            ),
        },
    ]
    response = await llm_client.ainvoke(messages)
    raw = str(getattr(response, "content", response)).strip()
    data = json.loads(_strip_json_fence(raw))
    selected = data.get("selected_memories", [])
    if not isinstance(selected, list):
        raise ValueError("selected_memories must be a list")
    filtered, _ = filter_selected_memory_paths(
        [str(item) for item in selected],
        valid_paths=valid_paths,
        max_selected=5,
    )
    return filtered


def filter_selected_memory_paths(
    selected_paths: Sequence[str],
    *,
    valid_paths: set[str],
    max_selected: int,
) -> tuple[list[str], list[str]]:
    accepted: list[str] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for raw_path in selected_paths:
        path = str(raw_path).strip().replace("\\", "/")
        if not path:
            skipped.append("<empty>:empty_path")
            continue
        if Path(path).is_absolute() or path.startswith("/"):
            skipped.append(f"{path}:absolute_path")
            continue
        pure_path = PurePosixPath(path)
        if ".." in pure_path.parts:
            skipped.append(f"{path}:path_traversal")
            continue
        if path not in valid_paths:
            skipped.append(f"{path}:not_in_manifest")
            continue
        if path in seen:
            skipped.append(f"{path}:duplicate")
            continue
        accepted.append(path)
        seen.add(path)
        if len(accepted) >= max_selected:
            break
    return accepted, skipped


async def read_selected_memory(
    header: MemoryHeader,
    *,
    memory_root: Path,
    max_chars: int,
) -> RelevantMemory:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    path = assert_under_memory_root(header.absolute_path, memory_root)
    content = path.read_text(encoding="utf-8")
    try:
        parsed = parse_frontmatter_markdown(content)
        body = parsed.body if parsed.has_frontmatter else content
    except ValueError:
        body = content
    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars]
    return RelevantMemory(header=header, content=body, truncated=truncated)


def _empty_recall_result(
    started_at: float,
    *,
    selector: str,
    reason: str,
) -> MemoryRecallResult:
    return MemoryRecallResult(
        selected=[],
        manifest_count=0,
        selected_paths=[],
        skipped_paths=[],
        selector=selector,
        elapsed_ms=_elapsed_ms(started_at),
        reason=reason,
    )


def _query_terms(query: str) -> set[str]:
    lowered = query.lower()
    terms = set(re.findall(r"[a-z0-9_]+", lowered))
    cjk_chunks = re.findall(r"[\u4e00-\u9fff]+", lowered)
    for chunk in cjk_chunks:
        if len(chunk) <= 2:
            terms.add(chunk)
        else:
            terms.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
            terms.update(chunk[index : index + 3] for index in range(len(chunk) - 2))
    return {term for term in terms if len(term) >= 2}


def _strip_json_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)
