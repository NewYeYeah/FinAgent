from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path


class DocumentationGovernanceTest(unittest.TestCase):
    def test_repository_documentation_governance(self) -> None:
        root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [sys.executable, str(root / "scripts" / "check_docs.py")],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=(completed.stdout + "\n" + completed.stderr).strip(),
        )


if __name__ == "__main__":
    unittest.main()
