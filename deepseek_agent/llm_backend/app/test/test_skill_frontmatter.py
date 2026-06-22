import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.skill_system.frontmatter import (
    dump_skill_frontmatter_markdown,
    parse_skill_frontmatter,
    parse_skill_markdown,
    read_skill_frontmatter_prefix,
)
from app.skill_system.schemas import (
    SkillContextMode,
    SkillFrontmatter,
    SkillScope,
    SkillStatus,
)


def _raw_frontmatter():
    return {
        "name": "smart-lock-after-sales",
        "description": "智能门锁售后判断流程",
        "when_to_use": "当用户咨询智能门锁售后处理时使用",
        "allowed-tools": ["knowledge_query", "order_query"],
        "argument-hint": "<customer_issue>",
        "arguments": ["customer_issue"],
        "context": "inline",
        "status": "draft",
        "scope": "business",
        "tenant_id": "default",
        "customer_id": None,
        "created_at": "2026-06-22T10:00:00+00:00",
        "updated_at": "2026-06-22T10:00:00+00:00",
        "source_conversation_id": "conv-1",
        "source_request_id": None,
        "generated_by": "skillify_mvp",
    }


class SkillFrontmatterTest(unittest.TestCase):
    def test_valid_frontmatter_parses(self):
        frontmatter = parse_skill_frontmatter(_raw_frontmatter())

        self.assertEqual(frontmatter.name, "smart-lock-after-sales")
        self.assertEqual(frontmatter.description, "智能门锁售后判断流程")
        self.assertEqual(frontmatter.allowed_tools, ("knowledge_query", "order_query"))
        self.assertEqual(frontmatter.context, SkillContextMode.INLINE)
        self.assertEqual(frontmatter.status, SkillStatus.DRAFT)
        self.assertEqual(frontmatter.scope, SkillScope.BUSINESS)

    def test_required_fields_are_validated(self):
        for field in ("name", "description", "when_to_use"):
            with self.subTest(field=field):
                raw = _raw_frontmatter()
                raw.pop(field)
                with self.assertRaises(ValueError):
                    parse_skill_frontmatter(raw)

    def test_invalid_name_status_context_and_scope_raise(self):
        cases = {
            "name": "Bad_Name",
            "status": "published",
            "context": "background",
            "scope": "global",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                raw = _raw_frontmatter()
                raw[field] = value
                with self.assertRaises(ValueError):
                    parse_skill_frontmatter(raw)

    def test_denied_and_unknown_allowed_tools_raise(self):
        for tool in ("shell", "mysql_write", "payment", "unknown_tool"):
            with self.subTest(tool=tool):
                raw = _raw_frontmatter()
                raw["allowed-tools"] = [tool]
                with self.assertRaises(ValueError):
                    parse_skill_frontmatter(raw)

    def test_utf8_markdown_round_trip(self):
        frontmatter = SkillFrontmatter(
            name="smart-lock-after-sales",
            description="智能门锁售后判断流程",
            when_to_use="当用户咨询智能门锁售后处理时使用",
            allowed_tools=("knowledge_query",),
            argument_hint=None,
            arguments=("customer_issue",),
            context=SkillContextMode.INLINE,
            status=SkillStatus.DRAFT,
            scope=SkillScope.BUSINESS,
            tenant_id="default",
            customer_id=None,
            created_at="2026-06-22T10:00:00+00:00",
            updated_at="2026-06-22T10:00:00+00:00",
            source_conversation_id="conv-1",
            source_request_id=None,
        )
        content = dump_skill_frontmatter_markdown(frontmatter, "正文：需要实时查询。")
        parsed = parse_skill_markdown(content)

        self.assertTrue(parsed.has_frontmatter)
        self.assertEqual(parsed.frontmatter["description"], "智能门锁售后判断流程")
        self.assertIn("正文", parsed.body)

    def test_read_frontmatter_prefix_uses_utf8_and_limit(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "SKILL.md"
            path.write_text("一\n二\n三\n", encoding="utf-8")

            self.assertEqual(read_skill_frontmatter_prefix(path, 2), "一\n二\n")


if __name__ == "__main__":
    unittest.main()
