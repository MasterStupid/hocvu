from pathlib import Path
import subprocess
import unittest


class DocumentDateUiTests(unittest.TestCase):
    def test_date_editor_browser_flow(self):
        result = subprocess.run(
            ["node", "--test", "tests/test_document_date_ui.cjs"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
