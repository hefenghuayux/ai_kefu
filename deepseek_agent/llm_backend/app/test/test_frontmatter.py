from app.memory_system.frontmatter import (
    dump_frontmatter_markdown,
    parse_frontmatter_markdown,
    parse_memory_frontmatter,
    read_frontmatter_prefix,
)
from app.memory_system.memory_types import MemoryType
from app.memory_system.schemas import MemoryFrontmatter


def _feedback_frontmatter():
    return {
        "type": "feedback",
        "description": "客户希望库存回答简洁",
        "created_at": "2026-06-21T10:00:00+08:00",
        "updated_at": "2026-06-21T10:00:00+08:00",
        "confidence": 0.9,
        "source_type": "customer_statement",
        "tags": ["inventory", "answer_style"],
    }


def test_parse_frontmatter_markdown_reads_utf8_body():
    content = """---
type: feedback
description: 客户希望库存回答简洁
created_at: 2026-06-21T10:00:00+08:00
updated_at: 2026-06-21T10:00:00+08:00
confidence: 0.9
tags:
  - inventory
  - answer_style
---

客户在库存咨询中希望回答简洁。
"""
    parsed = parse_frontmatter_markdown(content)

    assert parsed.has_frontmatter is True
    assert parsed.frontmatter["type"] == "feedback"
    assert parsed.frontmatter["tags"] == ["inventory", "answer_style"]
    assert "库存咨询" in parsed.body


def test_parse_frontmatter_markdown_without_frontmatter():
    parsed = parse_frontmatter_markdown("just body")

    assert parsed.has_frontmatter is False
    assert parsed.frontmatter == {}
    assert parsed.body == "just body"


def test_parse_memory_frontmatter_validates_common_fields():
    frontmatter = parse_memory_frontmatter(_feedback_frontmatter())

    assert frontmatter.type == MemoryType.FEEDBACK
    assert frontmatter.confidence == 0.9
    assert frontmatter.tags == ("inventory", "answer_style")


def test_parse_memory_frontmatter_rejects_invalid_confidence():
    raw = _feedback_frontmatter()
    raw["confidence"] = 2

    try:
        parse_memory_frontmatter(raw)
    except ValueError as exc:
        assert "confidence" in str(exc)
    else:
        raise AssertionError("expected invalid confidence to raise")


def test_business_rule_rejects_customer_statement():
    raw = _feedback_frontmatter()
    raw.update(
        {
            "type": "business_rule",
            "source_type": "customer_statement",
            "effective_from": "2026-06-21",
            "effective_to": None,
            "verified_by": "operator:1",
            "verified_at": "2026-06-21T10:00:00+08:00",
        }
    )

    try:
        parse_memory_frontmatter(raw)
    except ValueError as exc:
        assert "customer_statement" in str(exc)
    else:
        raise AssertionError("expected customer_statement business_rule to raise")


def test_business_rule_requires_verification_metadata():
    raw = _feedback_frontmatter()
    raw.update({"type": "business_rule", "source_type": "operator_confirmed"})

    try:
        parse_memory_frontmatter(raw)
    except ValueError as exc:
        assert "effective_from" in str(exc)
    else:
        raise AssertionError("expected missing verification metadata to raise")


def test_business_rule_accepts_trusted_source():
    raw = _feedback_frontmatter()
    raw.update(
        {
            "type": "business_rule",
            "source_type": "operator_confirmed",
            "effective_from": "2026-06-21",
            "effective_to": None,
            "verified_by": "operator:1",
            "verified_at": "2026-06-21T10:00:00+08:00",
        }
    )

    frontmatter = parse_memory_frontmatter(raw)

    assert frontmatter.type == MemoryType.BUSINESS_RULE
    assert frontmatter.source_type == "operator_confirmed"


def test_dump_frontmatter_markdown_round_trips_basic_fields():
    frontmatter = MemoryFrontmatter(
        type=MemoryType.FEEDBACK,
        description="客户希望库存回答简洁",
        created_at="2026-06-21T10:00:00+08:00",
        updated_at="2026-06-21T10:00:00+08:00",
        confidence=0.9,
        tags=("inventory",),
    )

    content = dump_frontmatter_markdown(frontmatter, "正文")
    parsed = parse_frontmatter_markdown(content)

    assert content.startswith("---\n")
    assert parsed.frontmatter["description"] == "客户希望库存回答简洁"
    assert parsed.body == "正文"


def test_read_frontmatter_prefix_uses_utf8_and_line_limit(tmp_path):
    path = tmp_path / "memory.md"
    path.write_text("一\n二\n三\n", encoding="utf-8")

    assert read_frontmatter_prefix(path, 2) == "一\n二\n"
