import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable

from neo4j import GraphDatabase


SCRIPT_DIR = Path(__file__).resolve().parent
LLM_BACKEND_DIR = SCRIPT_DIR.parent
DEFAULT_GRAPHRAG_INPUT = LLM_BACKEND_DIR / "app" / "graphrag" / "data" / "input"


def load_kg(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def copy_docs(docs_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    if docs_path.is_file():
        shutil.copy2(docs_path, target_dir / docs_path.name)
        return
    for markdown_file in docs_path.glob("*.md"):
        shutil.copy2(markdown_file, target_dir / markdown_file.name)


def reset_commerce_graph(session) -> None:
    session.run("MATCH (n:Shop) DETACH DELETE n")
    session.run("MATCH (n:Voucher) DETACH DELETE n")
    session.run("MATCH (n:Activity) DETACH DELETE n")
    session.run("MATCH (n:Policy) DETACH DELETE n")


def merge_nodes(session, label: str, key: str, rows: Iterable[Dict[str, Any]]) -> None:
    query = f"""
    UNWIND $rows AS row
    MERGE (n:{label} {{{key}: row.{key}}})
    SET n += row
    """
    session.run(query, rows=list(rows))


def merge_relationships(session, relationships: Iterable[Dict[str, Any]]) -> None:
    for rel in relationships:
        rel_type = rel["type"]
        from_label = rel["fromLabel"]
        to_label = rel["toLabel"]
        from_key = id_key(from_label)
        to_key = id_key(to_label)
        query = f"""
        MATCH (from:{from_label} {{{from_key}: $from_id}})
        MATCH (to:{to_label} {{{to_key}: $to_id}})
        MERGE (from)-[:{rel_type}]->(to)
        """
        session.run(query, from_id=rel["fromId"], to_id=rel["toId"])


def id_key(label: str) -> str:
    keys = {
        "Shop": "shopId",
        "Voucher": "voucherId",
        "Activity": "activityId",
        "Policy": "policyId",
    }
    return keys[label]


def sync_neo4j(args, kg: Dict[str, Any]) -> None:
    driver = GraphDatabase.driver(args.neo4j_url, auth=(args.neo4j_user, args.neo4j_password))
    try:
        with driver.session(database=args.neo4j_database) as session:
            reset_commerce_graph(session)
            merge_nodes(session, "Shop", "shopId", kg.get("shops", []))
            merge_nodes(session, "Voucher", "voucherId", kg.get("vouchers", []))
            merge_nodes(session, "Activity", "activityId", kg.get("activities", []))
            merge_nodes(session, "Policy", "policyId", kg.get("policies", []))
            merge_relationships(session, kg.get("relationships", []))
    finally:
        driver.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="同步单商铺电商知识到 ai_kefu 的 Neo4j 和 GraphRAG 输入目录")
    parser.add_argument("--kg", required=True, help="commerce_kg.json 路径")
    parser.add_argument("--docs", required=True, help="commerce_docs 目录或单个 Markdown 文件路径")
    parser.add_argument("--graphrag-input-dir", default=str(DEFAULT_GRAPHRAG_INPUT), help="GraphRAG input 目录")
    parser.add_argument("--neo4j-url", default="bolt://127.0.0.1:7687")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default="password")
    parser.add_argument("--neo4j-database", default="neo4j")
    parser.add_argument("--skip-neo4j", action="store_true", help="只复制 GraphRAG 文档，不写 Neo4j")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    kg_path = Path(args.kg)
    docs_path = Path(args.docs)
    target_dir = Path(args.graphrag_input_dir)

    if not kg_path.exists():
        raise FileNotFoundError(f"kg 文件不存在: {kg_path}")
    if not docs_path.exists():
        raise FileNotFoundError(f"docs 路径不存在: {docs_path}")

    kg = load_kg(kg_path)
    if not args.skip_neo4j:
        sync_neo4j(args, kg)
        print("Neo4j commerce knowledge synced")
    copy_docs(docs_path, target_dir)
    print(f"GraphRAG docs copied to {target_dir}")


if __name__ == "__main__":
    main()
