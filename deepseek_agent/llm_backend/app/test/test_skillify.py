import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.skill_system.config import SkillSystemConfig
from app.skill_system.frontmatter import parse_skill_markdown, parse_skill_frontmatter
from app.skill_system.schemas import SkillStatus, SkillifyInput, SkillifyResult
from app.skill_system.skillify import (
    SkillDraftParseError,
    SkillDraftValidationError,
    SkillifyInputError,
    generate_skill_draft,
    generate_skill_from_conversation,
    save_skill_draft,
)


class FakeLLM:
    def __init__(self, response):
        self.response = response
        self.messages = None

    def generate(self, messages):
        self.messages = messages
        return self.response


def _llm_payload(**overrides):
    payload = {
        "name": "smart-lock-after-sales",
        "description": "智能门锁售后判断流程",
        "when_to_use": "当用户咨询智能门锁售后判断时使用",
        "allowed_tools": ["knowledge_query", "order_query"],
        "argument_hint": "<customer_issue>",
        "arguments": ["customer_issue"],
        "context": "inline",
        "title": "Smart Lock After Sales",
        "inputs": ["customer_issue"],
        "goal": "判断用户诉求并给出可执行售后下一步。",
        "steps": [
            {
                "title": "识别问题类型",
                "action": "根据用户描述判断是否属于安装、质量或使用问题。",
                "success_criteria": "问题类型被归类，且需要实时事实时会查询工具。",
            }
        ],
        "constraints": ["涉及订单、物流或售后进度时必须实时查询。"],
        "source_notes": ["Generated from conversation conv-1."],
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False)


class SkillifyTest(unittest.TestCase):
    def test_fake_llm_generates_valid_skill_draft(self):
        llm = FakeLLM(_llm_payload())
        config = SkillSystemConfig(skill_root=Path("C:/tmp/runtime/skills"))

        result = asyncio.run(
            generate_skill_draft(
                SkillifyInput(
                    description="沉淀智能门锁售后流程",
                    conversation_id="conv-1",
                    tenant_id="default",
                    session_summary="用户咨询智能门锁售后。",
                    transcript_events=({"role": "user", "content": "门锁坏了"},),
                ),
                llm=llm,
                config=config,
            )
        )

        self.assertIn("status: draft", result.markdown)
        self.assertEqual(result.draft.frontmatter.name, "smart-lock-after-sales")
        self.assertEqual(
            result.skill_file_path,
            config.skill_root
            / "business"
            / "default"
            / "skills"
            / "smart-lock-after-sales"
            / "SKILL.md",
        )

    def test_llm_returning_non_json_raises(self):
        with self.assertRaises(SkillDraftParseError):
            asyncio.run(
                generate_skill_draft(
                    SkillifyInput(description="desc", conversation_id="conv-1"),
                    llm=FakeLLM("not json"),
                    config=SkillSystemConfig(skill_root=Path("C:/tmp/runtime/skills")),
                )
            )

    def test_llm_returning_illegal_tool_raises(self):
        with self.assertRaises(SkillDraftValidationError):
            asyncio.run(
                generate_skill_draft(
                    SkillifyInput(description="desc", conversation_id="conv-1"),
                    llm=FakeLLM(_llm_payload(allowed_tools=["shell"])),
                    config=SkillSystemConfig(skill_root=Path("C:/tmp/runtime/skills")),
                )
            )

    def test_existing_skill_manifest_enters_prompt(self):
        llm = FakeLLM(_llm_payload())
        asyncio.run(
            generate_skill_draft(
                SkillifyInput(
                    description="desc",
                    conversation_id="conv-1",
                    existing_skill_manifest="- [draft/business] old-skill",
                ),
                llm=llm,
                config=SkillSystemConfig(skill_root=Path("C:/tmp/runtime/skills")),
            )
        )

        self.assertIn("- [draft/business] old-skill", llm.messages[0]["content"])
        self.assertIn('"name": "skill-name"', llm.messages[0]["content"])

    def test_save_skill_draft_rejects_existing_by_default(self):
        with TemporaryDirectory() as temp_dir:
            result = asyncio.run(
                generate_skill_draft(
                    SkillifyInput(description="desc", conversation_id="conv-1"),
                    llm=FakeLLM(_llm_payload()),
                    config=SkillSystemConfig(skill_root=Path(temp_dir)),
                )
            )
            save_skill_draft(result)

            with self.assertRaises(FileExistsError):
                save_skill_draft(result)

    def test_overwrite_only_allows_draft(self):
        with TemporaryDirectory() as temp_dir:
            config = SkillSystemConfig(skill_root=Path(temp_dir))
            result = asyncio.run(
                generate_skill_draft(
                    SkillifyInput(description="desc", conversation_id="conv-1"),
                    llm=FakeLLM(_llm_payload()),
                    config=config,
                )
            )
            save_skill_draft(result)
            save_skill_draft(result, overwrite=True)
            parsed = parse_skill_markdown(result.skill_file_path.read_text(encoding="utf-8"))
            frontmatter = parse_skill_frontmatter(parsed.frontmatter)
            self.assertEqual(frontmatter.status, SkillStatus.DRAFT)

            active_content = result.markdown.replace("status: draft", "status: active")
            result.skill_file_path.write_text(active_content, encoding="utf-8", newline="\n")
            with self.assertRaises(FileExistsError):
                save_skill_draft(result, overwrite=True)

    def test_transcript_missing_raises_clear_error(self):
        with TemporaryDirectory() as temp_dir:
            with patch.dict(
                os.environ,
                {
                    "AI_KEFU_MEMORY_ROOT": temp_dir,
                    "AI_KEFU_SKILL_ROOT": str(Path(temp_dir) / "skills"),
                },
                clear=False,
            ):
                with self.assertRaises(SkillifyInputError) as caught:
                    asyncio.run(
                        generate_skill_from_conversation(
                            conversation_id="missing",
                            user_id=1,
                            tenant_id="default",
                            description="desc",
                            llm=FakeLLM(_llm_payload()),
                        )
                    )

        self.assertIn("transcript not found", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
