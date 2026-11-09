"""Keep the Docker dependency list aligned with the hosted API runtime."""
import importlib
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def requirements(filename):
    result = {}
    for line in (ROOT / filename).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            name = re.split(r"[<>=!~;\[\s]", line, maxsplit=1)[0].lower()
            result[name] = line
    return result


class ProductionDependencyTests(unittest.TestCase):
    def test_production_includes_required_api_document_and_voice_dependencies(self):
        production = requirements("requirements.production.txt")
        development = requirements("requirements.txt")
        for name in (
            "fastapi", "uvicorn", "python-multipart", "edge-tts",
            "pypdf", "pillow", "pytesseract", "pymupdf", "psycopg", "replit-object-storage",
        ):
            with self.subTest(package=name):
                self.assertIn(name, production)
                self.assertEqual(production[name], development[name])
        # Hosted BM25 does not need heavyweight semantic packages.
        self.assertNotIn("sentence-transformers", production)
        self.assertNotIn("torch", production)

    def test_runtime_modules_import_and_upload_routes_register(self):
        for module in (
            "fastapi", "uvicorn", "python_multipart", "edge_tts",
            "pypdf", "PIL", "pytesseract", "fitz", "psycopg", "replit.object_storage",
        ):
            with self.subTest(module=module):
                importlib.import_module(module)
        # FastAPI validates multipart support when File/Form routes register.
        from server.app import app
        paths = {route.path for route in app.routes}
        self.assertIn("/api/documents/upload", paths)
        self.assertIn("/api/tts", paths)

    def test_docker_installs_production_manifest_and_disables_optional_embeddings(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.production.txt ./requirements.production.txt", dockerfile)
        self.assertRegex(dockerfile, r"RUN pip install[^\n]*-r requirements\.production\.txt")
        self.assertIn("HV_SEMANTIC=0", dockerfile)
