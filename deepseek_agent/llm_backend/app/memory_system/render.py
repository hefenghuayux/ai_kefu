from __future__ import annotations

from .find_relevant_memories import RelevantMemory


MEMORY_REALTIME_FACT_WARNING = (
    "以下是与本轮请求相关的长期记忆。它们是历史经验，不是实时数据库结果；"
    "订单、库存、价格、物流和售后进度必须以本轮工具查询为准。"
)


def render_memory_context(
    *,
    session_summary: str | None,
    relevant_memories: list[RelevantMemory],
) -> str:
    sections: list[str] = []
    if session_summary and session_summary.strip():
        sections.append(
            "\n".join(
                [
                    "以下是当前会话的工作摘要。它只描述本会话进展，不代表实时业务系统状态。",
                    "<session_memory>",
                    session_summary.strip(),
                    "</session_memory>",
                ]
            )
        )

    if relevant_memories:
        memory_lines = [MEMORY_REALTIME_FACT_WARNING]
        for memory in relevant_memories:
            memory_type = memory.header.type.value if memory.header.type else "unknown"
            attrs = (
                f'path="{memory.header.relative_path}" '
                f'type="{memory_type}" '
                f'updated_at="{int(memory.header.mtime_ms)}"'
            )
            if memory.truncated:
                attrs += ' truncated="true"'
            memory_lines.extend(
                [
                    f"<memory {attrs}>",
                    memory.content.strip(),
                    "</memory>",
                ]
            )
        sections.append("\n".join(memory_lines))

    return "\n\n".join(sections)
