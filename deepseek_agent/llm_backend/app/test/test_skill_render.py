import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.skill_system.config import SkillSystemConfig
from app.skill_system.render import render_skill_markdown
from app.skill_system.schemas import (
    SkillContextMode,
    SkillDraft,
    SkillFrontmatter,
    SkillScope,
    SkillStatus,
    SkillStep,
)


def _frontmatter(status=SkillStatus.DRAFT):
    return SkillFrontmatter(
        name="smart-lock-after-sales",
        description="智能门锁售后判断流程",
        when_to_use="当用户咨询智能门锁售后判断时使用",
        allowed_tools=("knowledge_query", "order_query"),
        argument_hint=None,
        arguments=("customer_issue",),
        context=SkillContextMode.INLINE,
        status=status,
        scope=SkillScope.BUSINESS,
        tenant_id="default",
        customer_id=None,
        created_at="2026-06-22T10:00:00+00:00",
        updated_at="2026-06-22T10:00:00+00:00",
        source_conversation_id="conv-1",
        source_request_id=None,
    )


def _draft(**overrides):
    data = {
        "frontmatter": _frontmatter(),
        "title": "Smart Lock After Sales",
        "inputs": ("customer_issue",),
        "goal": "判断用户诉求并给出可执行售后下一步。",
        "steps": (
            SkillStep(
                title="识别问题类型",
                action="根据用户描述判断是否属于安装、质量或使用问题。",
                success_criteria="问题类型被归类，且不固化具体订单事实。",
            ),
        ),
        "constraints": ("涉及订单或售后进度时必须实时查询。",),
        "source_notes": ("Generated from conversation conv-1.",),
    }
    data.update(overrides)
    return SkillDraft(**data)


class SkillRenderTest(unittest.TestCase):
    def test_render_complete_skill_markdown(self):
        markdown = render_skill_markdown(_draft())

        self.assertIn("---\n", markdown)
        self.assertIn("status: draft", markdown)
        self.assertIn("# Smart Lock After Sales", markdown)
        self.assertIn("## Inputs", markdown)
        self.assertIn("## Goal", markdown)
        self.assertIn("## Steps", markdown)
        self.assertIn("### 1. 识别问题类型", markdown)
        self.assertIn("**Action**:", markdown)
        self.assertIn("**Success criteria**:", markdown)
        self.assertIn("## Constraints", markdown)
        self.assertIn("## Source", markdown)

    def test_each_step_requires_success_criteria(self):
        draft = _draft(
            steps=(
                SkillStep(
                    title="坏步骤",
                    action="执行动作",
                    success_criteria="",
                ),
            )
        )

        with self.assertRaises(ValueError):
            render_skill_markdown(draft)

    def test_body_too_long_raises(self):
        draft = _draft(goal="x" * 200)

        with self.assertRaises(ValueError):
            render_skill_markdown(
                draft,
                config=SkillSystemConfig(max_body_chars=80),
            )

    def test_non_draft_status_rejected(self):
        draft = _draft(frontmatter=_frontmatter(status=SkillStatus.ACTIVE))

        with self.assertRaises(ValueError):
            render_skill_markdown(draft)

    def test_realtime_fact_samples_are_rejected(self):
        cases = (
            {"constraints": ("订单号: ABC123456 已确认。",)},
            {"constraints": ("手机号 13800138000 不要写入。",)},
            {"constraints": ("支付状态: 已支付。",)},
        )
        for override in cases:
            with self.subTest(override=override):
                with self.assertRaises(ValueError):
                    render_skill_markdown(_draft(**override))


if __name__ == "__main__":
    unittest.main()
