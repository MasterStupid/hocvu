import base64
import unittest
from unittest.mock import patch

import httpx

from server import app as server


class BrowserAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Synthetic test credential only; never use a workspace secret in tests.
        self.patches = [
            patch.object(server.config, "api_token", "test-access-only"),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", True),
        ]
        for item in self.patches:
            item.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()

    async def test_pages_and_api_require_login(self):
        for path in ["/", "/documents.html", "/main.js", "/api/documents", "/docs"]:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertIn("Basic", response.headers["www-authenticate"])

    async def test_browser_login_serves_pages_and_api(self):
        for path in ["/", "/documents.html", "/main.js", "/api/suggestions"]:
            with self.subTest(path=path):
                response = await self.client.get(
                    path, auth=("hocvu", "test-access-only")
                )
                self.assertEqual(response.status_code, 200)

    async def test_existing_header_clients_still_work(self):
        response = await self.client.get(
            "/api/documents", headers={"X-HocVu-Token": "test-access-only"}
        )
        self.assertEqual(response.status_code, 200)

    async def test_authenticated_question_returns_grounded_answer(self):
        response = await self.client.post(
            "/api/ask",
            auth=("hocvu", "test-access-only"),
            headers={"Origin": "http://test"},
            json={"question": "Điều kiện bảo lưu kết quả học tập là gì?"},
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertFalse(result["refused"])
        self.assertTrue(result["answer"])
        self.assertTrue(result["references"])

    async def test_cross_site_upload_cannot_change_corpus_after_login(self):
        for headers in [
            {"Origin": "https://attacker.example"},
            {"Origin": "null"},
            {"Sec-Fetch-Site": "cross-site"},
            {},
        ]:
            with self.subTest(headers=headers):
                with patch.object(server, "get_engine") as get_engine:
                    response = await self.client.post(
                        "/api/documents/upload",
                        auth=("hocvu", "test-access-only"),
                        headers=headers,
                        files={"file": ("poison.docx", b"malicious regulation")},
                    )
                    self.assertEqual(response.status_code, 403)
                    get_engine.assert_not_called()
                    self.assertNotIn("access-control-allow-origin", response.headers)

    async def test_cross_site_corpus_mutations_are_rejected(self):
        for method, path in [
            ("DELETE", "/api/documents/example"),
            ("POST", "/api/documents/reindex"),
        ]:
            with self.subTest(path=path):
                response = await self.client.request(
                    method, path, auth=("hocvu", "test-access-only"),
                    headers={"Origin": "https://attacker.example"},
                )
                self.assertEqual(response.status_code, 403)

    async def test_same_origin_upload_reaches_document_handler(self):
        with patch.object(server, "get_engine") as get_engine:
            get_engine.return_value.add_document.return_value = {"id": "test-upload"}
            response = await self.client.post(
                "/api/documents/upload",
                auth=("hocvu", "test-access-only"),
                headers={"Origin": "http://test"},
                files={"file": ("regulation.docx", b"synthetic document")},
            )
            self.assertEqual(response.status_code, 201)
            get_engine.return_value.add_document.assert_called_once()

    async def test_same_origin_upload_works_behind_https_proxy(self):
        with patch.object(server, "get_engine") as get_engine:
            get_engine.return_value.add_document.return_value = {"id": "test-upload"}
            response = await self.client.post(
                "/api/documents/upload",
                auth=("hocvu", "test-access-only"),
                headers={"Origin": "https://test", "X-Forwarded-Proto": "https"},
                files={"file": ("regulation.docx", b"synthetic document")},
            )
            self.assertEqual(response.status_code, 201)

    async def test_cross_origin_preflight_is_not_enabled(self):
        response = await self.client.options(
            "/api/documents/upload",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        self.assertNotIn("access-control-allow-origin", response.headers)

    async def test_wrong_and_malformed_credentials_are_rejected(self):
        for authorization in [
            "Basic !!!",
            "Bearer test-access-only",
            "Basic " + base64.b64encode(b"hocvu:wrong").decode(),
            "Basic " + base64.b64encode(b"other:test-access-only").decode(),
        ]:
            response = await self.client.get("/", headers={"Authorization": authorization})
            self.assertEqual(response.status_code, 401)

    async def test_empty_secret_does_not_authenticate(self):
        with patch.object(server.config, "api_token", ""):
            response = await self.client.get("/", auth=("hocvu", ""))
            self.assertEqual(response.status_code, 401)

    async def test_health_is_public(self):
        response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    async def test_legacy_local_mode_remains_unchanged(self):
        with patch.object(server, "browser_auth_enabled", False):
            self.assertEqual((await self.client.get("/")).status_code, 200)
            self.assertEqual((await self.client.get("/api/documents")).status_code, 401)
