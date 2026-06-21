import unittest

from app.lg_agent.context_manager import (
    CONTEXT_SYSTEM_PREFIX,
    format_context_bundle,
    merge_memory_context_into_prompt,
    should_update_session_note,
    validate_session_note,
)


def _valid_session_note():
    return {
        "current_state": "用户正在确认智能门锁库存。",
        "customer_need": "用户想购买有现货的智能门锁。",
        "confirmed_facts": [{"fact": "用户关注智能门锁。", "source": "user"}],
        "tool_evidence": [
            {
                "summary": "库存查询显示有货。",
                "tool_name": "multi_tool_workflow",
                "request_id": "rid-1",
                "raw_ref": "request_id=rid-1",
            }
        ],
        "failed_paths": [],
        "user_preferences": ["希望回答简洁。"],
        "next_action": "继续确认预算和安装需求。",
        "worklog": ["已完成库存查询。"],
    }


class ContextManagerTest(unittest.TestCase):
    def test_should_update_session_note_by_message_threshold(self):
        should_update, reason = should_update_session_note(
            messages_since_session_note=6,
            recent_messages=[],
            session_note=None,
            user_query="还有货吗？",
            final_answer="有货。",
            evidence_items=[],
        )

        self.assertTrue(should_update)
        self.assertEqual(reason, "message_threshold")

    def test_should_update_session_note_by_tool_evidence_threshold(self):
        should_update, reason = should_update_session_note(
            messages_since_session_note=1,
            recent_messages=[],
            session_note=None,
            user_query="查一下库存。",
            final_answer="查询结果如下。",
            evidence_items=[{"result_digest": "a"}, {"result_digest": "b"}],
        )

        self.assertTrue(should_update)
        self.assertEqual(reason, "tool_evidence_threshold")

    def test_should_update_session_note_skips_below_threshold(self):
        should_update, reason = should_update_session_note(
            messages_since_session_note=1,
            recent_messages=[],
            session_note=None,
            user_query="你好",
            final_answer="你好，有什么可以帮您？",
            evidence_items=[],
        )

        self.assertFalse(should_update)
        self.assertEqual(reason, "below_threshold")

    def test_validate_session_note_accepts_valid_schema(self):
        note = validate_session_note(_valid_session_note())

        self.assertEqual(note["current_state"], "用户正在确认智能门锁库存。")

    def test_validate_session_note_rejects_missing_key(self):
        note = _valid_session_note()
        note.pop("next_action")

        with self.assertRaisesRegex(ValueError, "missing keys"):
            validate_session_note(note)

    def test_validate_session_note_rejects_tool_evidence_without_raw_ref(self):
        note = _valid_session_note()
        note["tool_evidence"][0].pop("raw_ref")

        with self.assertRaisesRegex(ValueError, "raw_ref"):
            validate_session_note(note)

    def test_format_context_bundle_includes_session_note_and_request_id(self):
        context_text = format_context_bundle(
            {
                "session_note": {"content_json": _valid_session_note()},
                "recent_messages": [{"role": "user", "content": "查库存"}],
                "tool_evidence": [
                    {
                        "content": "库存查询显示有货。",
                        "request_id": "rid-1",
                    }
                ],
            }
        )

        self.assertIn("Session Note", context_text)
        self.assertIn("当前状态", context_text)
        self.assertIn("request_id=rid-1", context_text)

    def test_merge_memory_context_keeps_base_prompt_when_memory_empty(self):
        base_prompt = f"{CONTEXT_SYSTEM_PREFIX}\n最近对话摘录：\n- user：查库存"

        merged = merge_memory_context_into_prompt(
            base_prompt_context=base_prompt,
            session_memory_context="",
            relevant_memory_context="",
        )

        self.assertEqual(merged, base_prompt)

    def test_merge_memory_context_places_memory_after_prefix(self):
        base_prompt = f"{CONTEXT_SYSTEM_PREFIX}\nSession Note：\n- 当前状态：查库存"

        merged = merge_memory_context_into_prompt(
            base_prompt_context=base_prompt,
            session_memory_context="<session_memory>会话摘要</session_memory>",
            relevant_memory_context="<memory>回答要简洁</memory>",
        )

        self.assertTrue(merged.startswith(CONTEXT_SYSTEM_PREFIX))
        self.assertLess(merged.index("<session_memory>"), merged.index("Session Note"))
        self.assertLess(merged.index("Session Note"), merged.index("<memory>"))


if __name__ == "__main__":
    unittest.main()
