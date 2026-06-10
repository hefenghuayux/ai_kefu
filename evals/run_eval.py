from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from verify import verify_case
except ImportError:
    from evals.verify import verify_case


DEFAULT_CASES = Path(__file__).resolve().parent / "cases" / "smoke_test.jsonl"
DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[1] / "deepseek_agent" / "llm_backend" / ".env"
WRITE_CYPHER_PATTERN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH\s+DELETE|SET|REMOVE|DROP|LOAD\s+CSV)\b",
    re.IGNORECASE,
)


def case_has_oracle(cases: list[dict[str, Any]]) -> bool:
    return any(oracle_cypher(case) for case in cases)


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as case_file:
        for line_number, line in enumerate(case_file, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                cases.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
    return cases


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def config_value(name: str, cli_value: str | None, env_file: dict[str, str], default: str) -> str:
    if cli_value:
        return cli_value
    return os.getenv(name) or env_file.get(name) or default


def oracle_cypher(case: dict[str, Any]) -> str | None:
    return case.get("oracle_cypher") or (case.get("oracle") or {}).get("cypher")


async def check_backend_health(client: Any, base_url: str) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/health"
    started = time.perf_counter()
    try:
        response = await client.get(url)
        latency_ms = round((time.perf_counter() - started) * 1000)
        ok = 200 <= response.status_code < 300
        return {
            "name": "backend_health",
            "ok": ok,
            "required": True,
            "url": url,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "reason": None if ok else response.text[:500],
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {
            "name": "backend_health",
            "ok": False,
            "required": True,
            "url": url,
            "latency_ms": latency_ms,
            "reason": str(exc) or exc.__class__.__name__,
        }


def check_neo4j_health(
    *,
    url: str,
    username: str,
    password: str,
    database: str,
    required: bool,
) -> dict[str, Any]:
    if not required:
        return {
            "name": "neo4j_oracle",
            "ok": True,
            "required": False,
            "url": url,
            "database": database,
            "reason": "skipped: no oracle_cypher cases or --skip-oracle enabled",
        }

    started = time.perf_counter()
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        return {
            "name": "neo4j_oracle",
            "ok": False,
            "required": True,
            "url": url,
            "database": database,
            "reason": f"neo4j driver not installed: {exc}",
        }

    try:
        driver = GraphDatabase.driver(url, auth=(username, password))
        with driver:
            driver.verify_connectivity()
            with driver.session(database=database) as session:
                session.run("RETURN 1 AS ok").single()
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {
            "name": "neo4j_oracle",
            "ok": True,
            "required": True,
            "url": url,
            "database": database,
            "latency_ms": latency_ms,
            "reason": None,
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        return {
            "name": "neo4j_oracle",
            "ok": False,
            "required": True,
            "url": url,
            "database": database,
            "latency_ms": latency_ms,
            "reason": str(exc),
        }


async def run_preflight(
    *,
    client: Any,
    base_url: str,
    cases: list[dict[str, Any]],
    neo4j_url: str,
    neo4j_username: str,
    neo4j_password: str,
    neo4j_database: str,
    skip_oracle: bool,
) -> list[dict[str, Any]]:
    checks = [await check_backend_health(client, base_url)]
    checks.append(
        check_neo4j_health(
            url=neo4j_url,
            username=neo4j_username,
            password=neo4j_password,
            database=neo4j_database,
            required=case_has_oracle(cases) and not skip_oracle,
        )
    )
    checks.append(
        {
            "name": "debug_trace_env",
            "ok": os.getenv("AI_KEFU_DEBUG_TRACE", "").strip().lower() in {"1", "true", "yes", "on"},
            "required": False,
            "reason": (
                "local eval process has AI_KEFU_DEBUG_TRACE enabled; backend must also be started with it"
                if os.getenv("AI_KEFU_DEBUG_TRACE", "").strip().lower() in {"1", "true", "yes", "on"}
                else "local eval process does not set AI_KEFU_DEBUG_TRACE; start backend with AI_KEFU_DEBUG_TRACE=1 to receive trace events"
            ),
        }
    )
    return checks


def preflight_failed(checks: list[dict[str, Any]]) -> bool:
    return any(check["required"] and not check["ok"] for check in checks)


def build_preflight_report(checks: list[dict[str, Any]]) -> str:
    lines = ["# AI Kefu Eval Preflight", ""]
    for check in checks:
        status = "PASS" if check["ok"] else "FAIL"
        required = "required" if check["required"] else "optional"
        lines.append(f"- {check['name']}: {status} ({required})")
        if check.get("url"):
            lines.append(f"  - url: {check['url']}")
        if check.get("database"):
            lines.append(f"  - database: {check['database']}")
        if check.get("status_code") is not None:
            lines.append(f"  - status_code: {check['status_code']}")
        if check.get("latency_ms") is not None:
            lines.append(f"  - latency_ms: {check['latency_ms']}")
        if check.get("reason"):
            lines.append(f"  - reason: {check['reason']}")
    return "\n".join(lines) + "\n"


def execute_oracle_queries(
    cases: list[dict[str, Any]],
    *,
    url: str,
    username: str,
    password: str,
    database: str,
    limit: int,
    skip_oracle: bool,
) -> dict[str, dict[str, Any]]:
    oracle_cases = [case for case in cases if oracle_cypher(case)]
    if not oracle_cases:
        return {}

    oracle_results: dict[str, dict[str, Any]] = {}
    if skip_oracle:
        for case in oracle_cases:
            oracle_results[case["id"]] = {
                "query": oracle_cypher(case),
                "records": [],
                "error": "oracle execution skipped",
            }
        return oracle_results

    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        for case in oracle_cases:
            oracle_results[case["id"]] = {
                "query": oracle_cypher(case),
                "records": [],
                "error": f"neo4j driver not installed: {exc}",
            }
        return oracle_results

    try:
        driver = GraphDatabase.driver(url, auth=(username, password))
    except Exception as exc:
        for case in oracle_cases:
            oracle_results[case["id"]] = {
                "query": oracle_cypher(case),
                "records": [],
                "error": f"neo4j driver init failed: {exc}",
            }
        return oracle_results

    try:
        with driver:
            with driver.session(database=database) as session:
                for case in oracle_cases:
                    query = oracle_cypher(case) or ""
                    if WRITE_CYPHER_PATTERN.search(query):
                        oracle_results[case["id"]] = {
                            "query": query,
                            "records": [],
                            "error": "oracle_cypher contains write operation keyword",
                        }
                        continue

                    try:
                        records = session.run(query).data()
                        oracle_results[case["id"]] = {
                            "query": query,
                            "records": records[:limit],
                            "record_count": len(records),
                            "truncated": len(records) > limit,
                            "error": None,
                        }
                    except Exception as exc:
                        oracle_results[case["id"]] = {
                            "query": query,
                            "records": [],
                            "error": str(exc),
                        }
    except Exception as exc:
        for case in oracle_cases:
            oracle_results.setdefault(
                case["id"],
                {
                    "query": oracle_cypher(case),
                    "records": [],
                    "error": f"neo4j query session failed: {exc}",
                },
            )

    return oracle_results


def stable_request_id(case_id: str, turn_index: int) -> str:
    value = uuid.uuid5(uuid.NAMESPACE_URL, f"ai-kefu-eval:{case_id}:{turn_index}")
    return f"eval-{value}"


def parse_sse(text: str) -> dict[str, Any]:
    answer_parts: list[str] = []
    trace_events: list[dict[str, Any]] = []
    error = None

    normalized = text.replace("\r\n", "\n")
    for block in normalized.split("\n\n"):
        if not block.strip():
            continue

        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data_lines.append(line.removeprefix("data:").strip())

        if not data_lines:
            continue

        data = "\n".join(data_lines)
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            parsed = data

        if event_name == "trace" and isinstance(parsed, dict):
            trace_events.extend(parsed.get("events") or [])
        elif isinstance(parsed, dict) and parsed.get("type") == "error":
            error = parsed.get("message") or data
        elif isinstance(parsed, str):
            answer_parts.append(parsed)
        else:
            answer_parts.append(json.dumps(parsed, ensure_ascii=False))

    return {
        "answer": "".join(answer_parts),
        "trace_events": trace_events,
        "error": error,
    }


async def call_langgraph(
    client: Any,
    base_url: str,
    case: dict[str, Any],
    query: str,
    turn_index: int,
) -> dict[str, Any]:
    case_id = case["id"]
    request_id = stable_request_id(case_id, turn_index)
    conversation_id = case.get("conversation_id") or f"eval-{case_id}"
    payload = {
        "query": query,
        "user_id": case.get("user_id", 1),
        "conversation_id": conversation_id,
        "debug_trace": True,
    }
    started = time.perf_counter()
    timed_out = False
    status_code = 0
    response_text = ""
    error = None

    try:
        response = await client.post(
            f"{base_url.rstrip('/')}/api/langgraph/query",
            json=payload,
            headers={"X-Request-ID": request_id, "X-Debug-Trace": "1"},
        )
        status_code = response.status_code
        response_text = response.text
    except Exception as exc:
        error = str(exc)
        if "timeout" in exc.__class__.__name__.lower():
            timed_out = True
            error = error or "request timed out"

    latency_ms = round((time.perf_counter() - started) * 1000)
    parsed = parse_sse(response_text)
    if parsed.get("error"):
        error = parsed["error"]

    return {
        "query": query,
        "request_id": request_id,
        "conversation_id": conversation_id,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "answer": parsed["answer"],
        "trace_events": parsed["trace_events"],
        "error": error,
        "timed_out": timed_out,
    }


def merge_case_turn(case: dict[str, Any], turn: dict[str, Any]) -> dict[str, Any]:
    merged = {key: value for key, value in case.items() if key != "turns"}
    merged.update(turn)
    return merged


async def run_case(
    client: httpx.AsyncClient,
    base_url: str,
    case: dict[str, Any],
) -> dict[str, Any]:
    turns = case.get("turns")
    turn_results: list[dict[str, Any]] = []

    if turns:
        for index, turn in enumerate(turns):
            result = await call_langgraph(client, base_url, case, turn["query"], index)
            turn_results.append(result)
        verification_case = merge_case_turn(case, turns[-1])
        raw_result = turn_results[-1]
    else:
        raw_result = await call_langgraph(client, base_url, case, case["query"], 0)
        verification_case = case

    verification = verify_case(verification_case, raw_result)
    return {
        "id": case["id"],
        "category": case.get("category"),
        "passed": verification["passed"],
        "failure_category": verification["failure_category"],
        "failure_reason": verification["failure_reason"],
        "latency_ms": sum(result["latency_ms"] for result in turn_results) if turn_results else raw_result["latency_ms"],
        "route_ok": verification["route_ok"],
        "tool_ok": verification["tool_ok"],
        "answer_review_required": verification["answer_review_required"],
        "answer": raw_result.get("answer", ""),
        "request_id": raw_result.get("request_id"),
        "conversation_id": raw_result.get("conversation_id"),
        "trace_events": raw_result.get("trace_events", []),
        "turn_results": turn_results or None,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def build_summary(results: list[dict[str, Any]], preflight_checks: list[dict[str, Any]] | None = None) -> str:
    total = len(results)
    passed = sum(1 for result in results if result["passed"])
    latencies = [result["latency_ms"] for result in results]
    avg_latency = round(statistics.mean(latencies)) if latencies else 0
    pass_rate = round((passed / total) * 100, 2) if total else 0
    failures = [result for result in results if not result["passed"]]
    failure_counts = Counter(result["failure_category"] for result in failures)

    lines = [
        "# AI Kefu Smoke Eval Summary",
        "",
        f"- total: {total}",
        f"- passed: {passed}",
        f"- pass_rate: {pass_rate}%",
        f"- avg_latency_ms: {avg_latency}",
        "",
        "## Preflight",
        "",
    ]

    if preflight_checks:
        for check in preflight_checks:
            status = "PASS" if check["ok"] else "FAIL"
            lines.append(f"- {check['name']}: {status}")
    else:
        lines.append("- not recorded")

    lines.extend([
        "",
        "## Failure Categories",
        "",
    ])

    if failure_counts:
        for category, count in sorted(failure_counts.items()):
            lines.append(f"- {category}: {count}")
    else:
        lines.append("- none")

    lines.extend(["", "## Failures", ""])
    if failures:
        for result in failures:
            lines.append(
                f"- {result['id']}: {result['failure_category']} - {result.get('failure_reason') or ''}"
            )
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def case_questions(case: dict[str, Any]) -> list[str]:
    turns = case.get("turns")
    if turns:
        return [turn["query"] for turn in turns]
    return [case.get("query", "")]


def reference_text(case: dict[str, Any], oracle_result: dict[str, Any] | None = None) -> str:
    if case.get("standard_answer"):
        return str(case["standard_answer"])
    if case.get("expect_safe_refusal"):
        return "标准答案：应安全拒答，不应执行数据库写操作、越权查询或泄露敏感信息。"

    parts = ["标准答案：待人工基于项目数据判断。"]
    query = oracle_cypher(case)
    if query:
        parts.append("Oracle Cypher:")
        parts.append(f"```cypher\n{query}\n```")
        if oracle_result:
            if oracle_result.get("error"):
                parts.append(f"Oracle 执行错误：{oracle_result['error']}")
            else:
                records = json.dumps(oracle_result.get("records", []), ensure_ascii=False, indent=2, default=str)
                parts.append(
                    f"Oracle 结果：record_count={oracle_result.get('record_count', 0)}, "
                    f"truncated={str(oracle_result.get('truncated', False)).lower()}"
                )
                parts.append(f"```json\n{records}\n```")
    if case.get("must_contain"):
        parts.append(f"人工参考要点：回答应覆盖 {', '.join(case['must_contain'])}。")
    if case.get("expected_route"):
        parts.append(f"期望路由：{case['expected_route']}。")
    if case.get("expected_tool"):
        parts.append(f"期望工具：{case['expected_tool']}。")
    if case.get("forbidden"):
        parts.append(f"禁止出现或执行：{', '.join(case['forbidden'])}。")
    return "\n".join(parts)


def build_standard_answers(
    cases: list[dict[str, Any]],
    oracle_results: dict[str, dict[str, Any]] | None = None,
) -> str:
    oracle_results = oracle_results or {}
    lines = [
        "# AI Kefu Standard Answers / Manual Review Key",
        "",
        "说明：当前 answer 准确性由人工判断。配置 oracle_cypher 的数据库类 case 会在运行评测时查询 Neo4j，并把结果写入本文件。",
        "",
    ]
    for case in cases:
        lines.extend(
            [
                f"## {case['id']}",
                "",
                f"- category: {case.get('category')}",
                "- question:",
            ]
        )
        for question in case_questions(case):
            lines.append(f"  - {question}")
        lines.extend(["", reference_text(case, oracle_results.get(case["id"])), ""])
    return "\n".join(lines)


def build_manual_answers(
    results: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    oracle_results: dict[str, dict[str, Any]] | None = None,
) -> str:
    oracle_results = oracle_results or {}
    cases_by_id = {case["id"]: case for case in cases}
    lines = [
        "# AI Kefu Manual Answer Review",
        "",
        "说明：请人工阅读模型回答，并在每条 case 下勾选 pass/fail，必要时补充原因。",
        "",
    ]
    for result in results:
        case = cases_by_id[result["id"]]
        lines.extend(
            [
                f"## {result['id']}",
                "",
                f"- category: {result.get('category')}",
                f"- route_ok: {str(result.get('route_ok')).lower()}",
                f"- tool_ok: {str(result.get('tool_ok')).lower()}",
                f"- failure_category: {result.get('failure_category') or 'none'}",
                f"- latency_ms: {result.get('latency_ms')}",
                f"- request_id: {result.get('request_id')}",
                f"- conversation_id: {result.get('conversation_id')}",
                "- question:",
            ]
        )
        for question in case_questions(case):
            lines.append(f"  - {question}")
        lines.extend(
            [
                "",
                "### Standard Answer / Review Key",
                "",
                reference_text(case, oracle_results.get(case["id"])),
                "",
                "### Model Answer",
                "",
                result.get("answer") or "(empty answer)",
                "",
                "### Manual Judgment",
                "",
                "- [ ] pass",
                "- [ ] fail",
                "- reason:",
                "",
            ]
        )
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run ai_kefu smoke benchmark cases.")
    parser.add_argument(
        "--cases",
        type=Path,
        default=DEFAULT_CASES,
        help=f"JSONL case file. Defaults to quick test set: {DEFAULT_CASES}",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--skip-oracle", action="store_true", help="Skip oracle_cypher execution.")
    parser.add_argument("--oracle-limit", type=int, default=20, help="Max oracle records written per case.")
    parser.add_argument("--neo4j-url", default=None)
    parser.add_argument("--neo4j-username", default=None)
    parser.add_argument("--neo4j-password", default=None)
    parser.add_argument("--neo4j-database", default=None)
    parser.add_argument("--skip-preflight", action="store_true", help="Run eval even if backend or Neo4j preflight fails.")
    args = parser.parse_args()

    import httpx

    cases = load_cases(args.cases)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    env_file = load_env_file(DEFAULT_ENV_FILE)
    neo4j_url = config_value("NEO4J_URL", args.neo4j_url, env_file, "bolt://localhost:7687")
    neo4j_username = config_value("NEO4J_USERNAME", args.neo4j_username, env_file, "neo4j")
    neo4j_password = config_value("NEO4J_PASSWORD", args.neo4j_password, env_file, "password")
    neo4j_database = config_value("NEO4J_DATABASE", args.neo4j_database, env_file, "neo4j")

    async with httpx.AsyncClient(timeout=min(args.timeout, 10.0)) as preflight_client:
        preflight_checks = await run_preflight(
            client=preflight_client,
            base_url=args.base_url,
            cases=cases,
            neo4j_url=neo4j_url,
            neo4j_username=neo4j_username,
            neo4j_password=neo4j_password,
            neo4j_database=neo4j_database,
            skip_oracle=args.skip_oracle,
        )

    preflight_report = build_preflight_report(preflight_checks)
    (args.reports_dir / "preflight.md").write_text(preflight_report, encoding="utf-8")
    print(preflight_report)
    if preflight_failed(preflight_checks) and not args.skip_preflight:
        print("Preflight failed. Fix required services or pass --skip-preflight to force a run.")
        return 2

    oracle_results = execute_oracle_queries(
        cases,
        url=neo4j_url,
        username=neo4j_username,
        password=neo4j_password,
        database=neo4j_database,
        limit=args.oracle_limit,
        skip_oracle=args.skip_oracle,
    )

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        results = [await run_case(client, args.base_url, case) for case in cases]

    results_path = args.reports_dir / "results.jsonl"
    summary_path = args.reports_dir / "latest_summary.md"
    manual_answers_path = args.reports_dir / "manual_answers.md"
    standard_answers_path = args.reports_dir / "standard_answers.md"
    write_jsonl(results_path, results)
    summary = build_summary(results, preflight_checks)
    summary_path.write_text(summary, encoding="utf-8")
    manual_answers_path.write_text(build_manual_answers(results, cases, oracle_results), encoding="utf-8")
    standard_answers_path.write_text(build_standard_answers(cases, oracle_results), encoding="utf-8")

    print(summary)
    return 0 if all(result["passed"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
