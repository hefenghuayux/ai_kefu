import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.skill_system.config import DEFAULT_SKILL_ROOT, SkillSystemConfig, load_skill_config
from app.skill_system.paths import (
    assert_under_skill_root,
    build_skill_identity,
    ensure_skill_directory,
    resolve_skill_paths,
)
from app.skill_system.schemas import SkillScope


class SkillPathsTest(unittest.TestCase):
    def test_default_skill_root_is_runtime_skills(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_KEFU_SKILL_ROOT", None)
            config = load_skill_config()

        self.assertEqual(config.skill_root, DEFAULT_SKILL_ROOT)
        self.assertEqual(config.skill_root.name, "skills")
        self.assertEqual(config.skill_root.parent.name, "runtime")

    def test_business_and_customer_paths(self):
        root = Path("C:/tmp/ai-kefu-skills")
        config = SkillSystemConfig(skill_root=root)

        business = resolve_skill_paths(
            build_skill_identity(
                scope=SkillScope.BUSINESS,
                tenant_id="default",
                customer_id=None,
            ),
            config,
            "smart-lock-after-sales",
        )
        customer = resolve_skill_paths(
            build_skill_identity(
                scope=SkillScope.CUSTOMER,
                tenant_id="default",
                customer_id="42",
            ),
            config,
            "customer-refund-check",
        )

        self.assertEqual(
            business.skill_file_path,
            root / "business" / "default" / "skills" / "smart-lock-after-sales" / "SKILL.md",
        )
        self.assertEqual(
            customer.skill_file_path,
            root / "customers" / "42" / "skills" / "customer-refund-check" / "SKILL.md",
        )

    def test_customer_scope_requires_customer_id(self):
        with self.assertRaises(ValueError):
            build_skill_identity(
                scope=SkillScope.CUSTOMER,
                tenant_id="default",
                customer_id=None,
            )

    def test_rejects_path_traversal_segments(self):
        for tenant_id in ("..", "../tenant", "tenant/name", "tenant\\name"):
            with self.subTest(tenant_id=tenant_id):
                with self.assertRaises(ValueError):
                    build_skill_identity(
                        scope=SkillScope.BUSINESS,
                        tenant_id=tenant_id,
                        customer_id=None,
                    )

        for skill_name in ("../x", "BadName", "ab", "name_with_underscore"):
            with self.subTest(skill_name=skill_name):
                with self.assertRaises(ValueError):
                    resolve_skill_paths(
                        build_skill_identity(
                            scope=SkillScope.BUSINESS,
                            tenant_id="default",
                            customer_id=None,
                        ),
                        SkillSystemConfig(skill_root=Path("C:/tmp/skills")),
                        skill_name,
                    )

    def test_assert_under_skill_root_rejects_escape_and_similar_prefix(self):
        with self.subTest("parent escape"):
            root = Path("C:/tmp/skills-root")
            outside = root / ".." / "skills-root-other" / "x.md"
            with self.assertRaises(PermissionError):
                assert_under_skill_root(outside, root)

        with self.subTest("similar prefix"):
            root = Path("C:/tmp/skills")
            outside = Path("C:/tmp/skills-other/SKILL.md")
            with self.assertRaises(PermissionError):
                assert_under_skill_root(outside, root)

    def test_ensure_skill_directory_creates_path(self):
        with self.subTest("creates"):
            import tempfile

            with tempfile.TemporaryDirectory() as temp_dir:
                path = Path(temp_dir) / "runtime" / "skills"
                ensure_skill_directory(path)
                self.assertTrue(path.is_dir())


if __name__ == "__main__":
    unittest.main()
