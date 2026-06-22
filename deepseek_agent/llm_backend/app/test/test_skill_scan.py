import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.skill_system.config import SkillSystemConfig
from app.skill_system.schemas import SkillStatus
from app.skill_system.skill_scan import scan_skill_files


def _write_skill(path: Path, name: str, status: str = "draft", extra_body: str = ""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
name: {name}
description: 智能门锁售后判断流程
when_to_use: 当用户咨询智能门锁售后判断时使用
allowed-tools:
  - knowledge_query
context: inline
status: {status}
scope: business
tenant_id: default
customer_id: null
created_at: "2026-06-22T10:00:00+00:00"
updated_at: "2026-06-22T10:00:00+00:00"
source_conversation_id: conv-1
source_request_id: null
generated_by: skillify_mvp
---

{extra_body}
""",
        encoding="utf-8",
    )


class SkillScanTest(unittest.TestCase):
    def test_scan_only_skill_md_and_ignores_plain_markdown(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(
                root / "business" / "default" / "skills" / "a" / "SKILL.md",
                "smart-lock-after-sales",
            )
            (root / "business" / "default" / "skills" / "note.md").parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            (root / "business" / "default" / "skills" / "note.md").write_text(
                "---\nname: ignored\n---\n",
                encoding="utf-8",
            )

            result = scan_skill_files(root, config=SkillSystemConfig(skill_root=root))

            self.assertEqual(result.scanned_file_count, 1)
            self.assertEqual(result.headers[0].name, "smart-lock-after-sales")

    def test_scan_keeps_all_statuses(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for status in ("draft", "active", "deprecated"):
                _write_skill(
                    root / "business" / "default" / "skills" / status / "SKILL.md",
                    f"{status}-skill",
                    status=status,
                )

            result = scan_skill_files(root, config=SkillSystemConfig(skill_root=root))

            self.assertEqual(
                {header.status for header in result.headers},
                {SkillStatus.DRAFT, SkillStatus.ACTIVE, SkillStatus.DEPRECATED},
            )

    def test_bad_file_records_parse_error_without_crashing(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(
                root / "business" / "default" / "skills" / "ok" / "SKILL.md",
                "valid-skill",
            )
            bad = root / "business" / "default" / "skills" / "bad" / "SKILL.md"
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_text("---\nname: Bad_Name\n---\n", encoding="utf-8")

            result = scan_skill_files(root, config=SkillSystemConfig(skill_root=root))

            self.assertEqual(result.scanned_file_count, 2)
            errors = [header for header in result.headers if header.parse_errors]
            self.assertEqual(len(errors), 1)
            self.assertIn("frontmatter_parse_error", errors[0].parse_errors[0])

    def test_bad_encoding_is_skipped(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bad = root / "business" / "default" / "skills" / "bad" / "SKILL.md"
            bad.parent.mkdir(parents=True, exist_ok=True)
            bad.write_bytes(b"\xff\xfe\x00\x00")

            result = scan_skill_files(root, config=SkillSystemConfig(skill_root=root))

            self.assertEqual(result.skipped_file_count, 1)
            self.assertEqual(result.headers, [])
            self.assertIn("UnicodeDecodeError", result.skipped_reasons[0])

    def test_scan_reads_frontmatter_prefix_only(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_skill(
                root / "business" / "default" / "skills" / "a" / "SKILL.md",
                "prefix-only-skill",
                extra_body="\n".join("body line" for _ in range(200)),
            )

            result = scan_skill_files(
                root,
                config=SkillSystemConfig(skill_root=root, frontmatter_max_lines=40),
            )

            self.assertEqual(result.headers[0].name, "prefix-only-skill")
            self.assertEqual(result.headers[0].parse_errors, ())


if __name__ == "__main__":
    unittest.main()
