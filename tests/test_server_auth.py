import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from server import app as server
from core import engine as engine_module, settings
from core.settings import AppConfig


class IsolatedServerEngineTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        paths = {
            "DATA": self.root, "RAW": self.root / "raw", "IDX": self.root / "index",
            "AUD": self.root / "audio", "DOCS": self.root / "documents",
            "MODELS": self.root / "models", "SESSION_DB": self.root / "sessions.db",
            "INDEX_JSON": self.root / "index" / "index.json",
            "SERVER_META": self.root / "server.json",
        }
        paths.update(
            CORPUS_JSON=paths["RAW"] / "corpus.json",
            CORPUS_MD=paths["RAW"] / "corpus.md",
            QA_JSON=paths["RAW"] / "qa_testset.json",
            EVAL_JSON=self.root / "eval_result.json",
            EVAL_CSV=self.root / "eval_result.csv",
        )
        self.enterContext(patch.dict(os.environ, {"HV_SEMANTIC": "0"}))
        self.enterContext(patch.multiple(settings, **paths))
        self.enterContext(patch.multiple(engine_module, **{
            key: paths[key] for key in ("AUD", "DOCS", "SESSION_DB", "INDEX_JSON")
        }))
        self.enterContext(patch.multiple(server, **{
            key: paths[key] for key in ("AUD", "INDEX_JSON", "SERVER_META")
        }))
        self.enterContext(patch.object(server, "engine", None))
        self.enterContext(patch.object(server, "config", AppConfig(
            semantic_enabled=False, api_token="test-access-only",
        )))
        # Fail rather than downloading a real model if a test regresses.
        self.enterContext(patch(
            "core.searcher.SemanticEncoder",
            side_effect=AssertionError("Authentication tests must stay offline"),
        ))


class BrowserAuthenticationTests(IsolatedServerEngineTests):
    def test_engine_uses_only_temporary_state_without_models(self):
        engine = server.get_engine()
        self.assertFalse(engine.config.semantic_enabled)
        self.assertEqual(engine.searcher.provider, "bm25")
        self.assertEqual(engine.session.db_path, self.root / "sessions.db")
        self.assertTrue((self.root / "index" / "index.json").is_file())
        self.assertFalse(list((self.root / "models").iterdir()))

    async def asyncSetUp(self):
        # Synthetic test credential only; never use a workspace secret in tests.
        self.patches = [
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
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
        for path in ["/", "/documents.html", "/main.js", "/api-errors.js", "/api/documents", "/docs"]:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertIn("Basic", response.headers["www-authenticate"])

    async def test_browser_login_serves_pages_and_api(self):
        for path in ["/", "/documents.html", "/main.js", "/api-errors.js", "/api/suggestions"]:
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
            headers={"Origin": "http://test", "X-HocVu-Owner": "a" * 64},
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


class NetlifyProxyOriginTests(IsolatedServerEngineTests):
    """Netlify forwards the browser's site Origin to the separate API host."""

    async def asyncSetUp(self):
        self.patches = [
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server.config, "api_token", "test-access-only"),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", False),
            patch.object(
                server, "trusted_origins",
                server.parse_trusted_origins("https://hocvu-site.netlify.app"),
            ),
        ]
        for item in self.patches:
            item.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="https://hocvu-api.onrender.com",
        )
        self.proxy_headers = {
            "X-HocVu-Token": "test-access-only",
            "X-Forwarded-Proto": "https",
        }

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()

    async def test_trusted_netlify_site_can_ask_and_upload(self):
        headers = {
            **self.proxy_headers,
            "Origin": "https://hocvu-site.netlify.app",
            "Sec-Fetch-Site": "same-origin",
        }
        ask = await self.client.post(
            "/api/ask", headers=headers,
            json={"question": "Điều kiện bảo lưu kết quả học tập là gì?"},
        )
        self.assertEqual(ask.status_code, 200)
        with patch.object(server, "get_engine") as get_engine:
            get_engine.return_value.add_document.return_value = {"id": "test-upload"}
            upload = await self.client.post(
                "/api/documents/upload", headers=headers,
                files={"file": ("regulation.docx", b"synthetic document")},
            )
            self.assertEqual(upload.status_code, 201)

    async def test_attacker_cannot_use_netlify_proxy_token(self):
        for extra in [
            {"Origin": "https://attacker.example"},
            {"Origin": "https://hocvu-site.netlify.app.attacker.example"},
            {"Origin": "https://hocvu-site.netlify.app", "Sec-Fetch-Site": "cross-site"},
        ]:
            with self.subTest(headers=extra):
                with patch.object(server, "get_engine") as get_engine:
                    response = await self.client.post(
                        "/api/documents/upload",
                        headers={**self.proxy_headers, **extra},
                        files={"file": ("poison.docx", b"malicious regulation")},
                    )
                    self.assertEqual(response.status_code, 403)
                    get_engine.assert_not_called()

    def test_invalid_trusted_origin_configuration_fails_clearly(self):
        for value in ["*.netlify.app", "https://*.netlify.app", "https://site.netlify.app/path", "hocvu.netlify.app"]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "HV_TRUSTED_ORIGINS"):
                    server.parse_trusted_origins(value)

    def test_trusted_origins_are_normalized(self):
        self.assertEqual(
            server.parse_trusted_origins(" https://Site.Netlify.app/ , http://localhost:8888 "),
            frozenset({"https://site.netlify.app", "http://localhost:8888"}),
        )
