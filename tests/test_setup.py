from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ProjectSetupTests(unittest.TestCase):
    def test_assignment_file_exists_and_is_not_empty(self) -> None:
        assignment = PROJECT_ROOT / "assignment.md"
        self.assertTrue(assignment.is_file(), "assignment.md must exist")
        self.assertGreater(len(assignment.read_text(encoding="utf-8").strip()), 0)

    def test_group_metadata_exists(self) -> None:
        group_config = PROJECT_ROOT / ".group" / "group.json"
        self.assertTrue(group_config.is_file(), ".group/group.json must exist")


if __name__ == "__main__":
    unittest.main()
