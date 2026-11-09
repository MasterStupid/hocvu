"""Run dependency-free JavaScript API-error regressions in the standard suite."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

import httpx

from core.documents import DocumentError
from server import app as server


class FrontendErrorTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for browser JavaScript tests")
    def test_shared_browser_error_parser(self):
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            ["node", "--test", str(root / "tests" / "test_ui_api_errors.cjs")],
            cwd=root, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class FrontendApiContractTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is needed for browser JavaScript tests")
    async def test_actual_fastapi_error_bodies_reach_the_browser_parser(self):
        business_errors = [
            "Tài liệu này đã tồn tại.",
            "PDF được mã hóa nên chưa thể lập chỉ mục.",
            "Hãy bật OCR để đọc tệp ảnh.",
            "Văn bản trích xuất chưa đủ 20 ký tự.",
            "Không tìm thấy Tesseract OCR trên máy chủ.",
            "Kích thước tệp vượt quá 25 MB.",
        ]
        payloads = []
        with (
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "requires_api_token", False),
            patch.object(server, "get_engine") as get_engine,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app), base_url="http://test"
            ) as client:
                for message in business_errors:
                    get_engine.return_value.add_document.side_effect = DocumentError(message)
                    response = await client.post(
                        "/api/documents/upload",
                        files={"file": ("test.pdf", b"synthetic test fixture")},
                    )
                    self.assertEqual(response.status_code, 400)
                    payloads.append(response.json())
                question_error = await client.post("/api/ask", json={"question": "x" * 4001})
                self.assertEqual(question_error.status_code, 422)
                payloads.append(question_error.json())
                missing_file = await client.post("/api/documents/upload", data={"ocr": "false"})
                self.assertEqual(missing_file.status_code, 422)
                payloads.append(missing_file.json())
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                "node", "-e",
                "const {errorMessage}=require('./ui/api-errors.js');"
                "const data=JSON.parse(require('node:fs').readFileSync(0,'utf8'));"
                "console.log(JSON.stringify(data.map(x=>errorMessage(x,'fallback'))));",
            ],
            cwd=root, input=json.dumps(payloads), capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), business_errors + [
            "Câu hỏi không được vượt quá 4000 ký tự.",
            "Tệp tải lên là bắt buộc.",
        ])
