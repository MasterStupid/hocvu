"""Exercise the real UI scripts without network, media devices or extra packages."""
from pathlib import Path
import shutil
import subprocess
import unittest


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for UI regression tests")
class UiInteractionTests(unittest.TestCase):
    def run_script(self, filename):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", "--test", str(root / "tests" / filename)],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_audio_playback_lifecycle(self):
        self.run_script("test_ui_audio.cjs")

    def test_document_upload_batches(self):
        self.run_script("test_ui_documents.cjs")

    def test_shared_theme_and_typing_styles(self):
        self.run_script("test_ui_theme_styles.cjs")

    def test_scoped_conversation_picker(self):
        self.run_script("test_ui_conversations.cjs")
