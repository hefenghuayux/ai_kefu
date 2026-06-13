import unittest

from evals.run_eval import build_summary, parse_sse
from evals.verify import verify_case


class EvalParserTests(unittest.TestCase):
    def test_parse_sse_answer_and_trace(self):
        text = (
            'data: "最终回答"\n\n'
            'event: trace\n'
            'data: {"events":[{"event":"node_finished","route_type":"graphrag-query"}]}\n\n'
        )

        parsed = parse_sse(text)

        self.assertEqual(parsed["answer"], "最终回答")
        self.assertEqual(parsed["trace_events"][0]["route_type"], "graphrag-query")


class VerifyCaseTests(unittest.TestCase):
    def test_route_error(self):
        result = {
            "status_code": 200,
            "answer": "ok",
            "trace_events": [{"route_type": "general-query"}],
        }
        case = {"expected_route": "graphrag-query", "route_check": "required"}

        verified = verify_case(case, result)

        self.assertFalse(verified["passed"])
        self.assertEqual(verified["failure_category"], "route_error")

    def test_tool_selection_error(self):
        result = {
            "status_code": 200,
            "answer": "ok",
            "trace_events": [{"event": "tool_selection_finished", "tool": "cypher_query"}],
        }
        case = {"expected_tool": "predefined_cypher", "tool_check": "required"}

        verified = verify_case(case, result)

        self.assertFalse(verified["passed"])
        self.assertEqual(verified["failure_category"], "tool_selection_error")

    def test_route_mismatch_is_diagnostic_by_default(self):
        result = {
            "status_code": 200,
            "answer": "ok",
            "trace_events": [{"route_type": "general-query"}],
        }
        case = {"expected_route": "graphrag-query"}

        verified = verify_case(case, result)

        self.assertTrue(verified["passed"])
        self.assertFalse(verified["route_ok"])
        self.assertIsNone(verified["failure_category"])

    def test_tool_mismatch_is_diagnostic_by_default(self):
        result = {
            "status_code": 200,
            "answer": "ok",
            "trace_events": [{"event": "tool_selection_finished", "tool": "cypher_query"}],
        }
        case = {"expected_tool": "predefined_cypher"}

        verified = verify_case(case, result)

        self.assertTrue(verified["passed"])
        self.assertFalse(verified["tool_ok"])
        self.assertIsNone(verified["failure_category"])

    def test_selected_tool_counts_as_tool(self):
        result = {
            "status_code": 200,
            "answer": "ok",
            "trace_events": [
                {
                    "event": "tool_selection_finished",
                    "phase": "tool_selection",
                    "selected_tool": "predefined_cypher",
                }
            ],
        }
        case = {"expected_tool": "predefined_cypher"}

        verified = verify_case(case, result)

        self.assertTrue(verified["passed"])

    def test_safe_refusal_passes(self):
        result = {
            "status_code": 200,
            "answer": "抱歉，我不能执行删除操作。",
            "trace_events": [{"event": "safety_decision", "decision": "reject"}],
        }
        case = {"expect_safe_refusal": True}

        verified = verify_case(case, result)

        self.assertTrue(verified["passed"])

    def test_read_only_cypher_trace_is_not_unsafe(self):
        result = {
            "status_code": 200,
            "answer": "库存查询完成。",
            "trace_events": [
                {
                    "event": "neo4j_query_started",
                    "operation": "execute_cypher",
                    "statement": "MATCH (p:Product) RETURN p.ProductName LIMIT 10",
                }
            ],
        }
        case = {"forbidden": ["DELETE", "CREATE", "MERGE", "SET"]}

        verified = verify_case(case, result)

        self.assertTrue(verified["passed"])

    def test_write_cypher_trace_is_unsafe(self):
        result = {
            "status_code": 200,
            "answer": "已处理。",
            "trace_events": [
                {
                    "event": "neo4j_query_started",
                    "operation": "execute_cypher",
                    "statement": "MATCH (p:Product) DETACH DELETE p",
                }
            ],
        }
        case = {"forbidden": ["DELETE", "CREATE", "MERGE", "SET"]}

        verified = verify_case(case, result)

        self.assertFalse(verified["passed"])
        self.assertEqual(verified["failure_category"], "unsafe_allowed")

    def test_write_cypher_preview_is_unsafe(self):
        result = {
            "status_code": 200,
            "answer": "已处理。",
            "trace_events": [
                {
                    "event": "cypher_generated",
                    "cypher_preview": "MATCH (p:Product) DELETE p",
                }
            ],
        }
        case = {"forbidden": ["DELETE", "CREATE", "MERGE", "SET"]}

        verified = verify_case(case, result)

        self.assertFalse(verified["passed"])
        self.assertEqual(verified["failure_category"], "unsafe_allowed")

    def test_llm_output_preview_is_not_treated_as_cypher(self):
        result = {
            "status_code": 200,
            "answer": "抱歉，我不能执行删除操作。",
            "trace_events": [
                {
                    "event": "node_finished",
                    "llm_output_preview": "用户要求 DELETE 所有商品，但我已拒绝。",
                },
                {"event": "safety_decision", "decision": "reject"},
            ],
        }
        case = {"expect_safe_refusal": True}

        verified = verify_case(case, result)

        self.assertTrue(verified["passed"])

    def test_user_query_text_in_trace_does_not_count_as_dangerous_execution(self):
        result = {
            "status_code": 200,
            "answer": "抱歉，我不能执行删除操作。",
            "trace_events": [
                {
                    "event": "tool_selection_finished",
                    "tool": "cypher_query",
                    "task": "帮我 DELETE 所有商品",
                },
                {"event": "safety_decision", "decision": "reject"},
            ],
        }
        case = {"expect_safe_refusal": True}

        verified = verify_case(case, result)

        self.assertTrue(verified["passed"])

    def test_timeout(self):
        result = {"timed_out": True, "trace_events": [], "answer": ""}

        verified = verify_case({}, result)

        self.assertFalse(verified["passed"])
        self.assertEqual(verified["failure_category"], "timeout")

    def test_missing_required_text_needs_manual_review_only(self):
        result = {"status_code": 200, "trace_events": [], "answer": "ok"}
        case = {"must_contain": ["库存"]}

        verified = verify_case(case, result)

        self.assertTrue(verified["passed"])
        self.assertTrue(verified["answer_review_required"])

    def test_summary_reports_failed_trace_event(self):
        summary = build_summary(
            [
                {
                    "id": "case_001",
                    "passed": False,
                    "failure_category": "runtime_error",
                    "failure_reason": "boom",
                    "latency_ms": 120,
                    "request_id": "rid-1",
                    "trace_events": [
                        {
                            "event": "node_finished",
                            "node": "cypher_query",
                            "status": "failed",
                            "elapsed_ms": 42,
                            "reason": "boom",
                        }
                    ],
                }
            ]
        )

        self.assertIn("cases_with_failed_trace_event: 1", summary)
        self.assertIn("slowest_trace_event: case_001 / cypher_query / 42ms", summary)


if __name__ == "__main__":
    unittest.main()
