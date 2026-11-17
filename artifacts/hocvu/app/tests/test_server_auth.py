import base64
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock

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
            key: paths[key] for key in ("DOCS", "SESSION_DB", "INDEX_JSON")
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

    async def test_management_pages_and_api_require_login(self):
        for path in ["/documents.html", "/documents.js", "/document-date-editor.js", "/api/documents", "/docs", "/api/unknown"]:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 401)
                self.assertIn("Basic", response.headers["www-authenticate"])

    async def test_chat_pages_assets_and_catalog_are_public(self):
        for path in ["/", "/index.html", "/main.js", "/theme.js", "/styles.css", "/api-errors.js", "/api/catalog", "/api/suggestions"]:
            with self.subTest(path=path):
                response = await self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("www-authenticate", response.headers)
        with patch.object(server, "get_engine") as engine:
            engine.return_value.list_documents.return_value = [{
                "rid": "public-id", "title": "Quy chế", "version": "2026",
                "filename": "internal.docx", "extracted_path": "/private/extracted.txt",
            }]
            response = await self.client.get("/api/catalog")
            self.assertEqual(response.json(), [{
                "rid": "public-id", "title": "Quy chế", "version": "2026",
            }])

    async def test_public_question_and_own_history_need_no_admin_password(self):
        headers = {"Origin": "http://test", "X-HocVu-Owner": "b" * 64}
        response = await self.client.post(
            "/api/ask", headers=headers,
            json={"question": "Điều kiện bảo lưu kết quả học tập là gì?", "session_id": "public-chat"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()["refused"])
        for path, params in [
            ("/api/conversations", {}),
            ("/api/history", {"session_id": "public-chat"}),
            ("/api/history/status", {"session_id": "public-chat"}),
        ]:
            self.assertEqual((await self.client.get(path, params=params, headers=headers)).status_code, 200)
        other = await self.client.get(
            "/api/history", params={"session_id": "public-chat"},
            headers={"X-HocVu-Owner": "c" * 64},
        )
        self.assertEqual(other.status_code, 404)
        deleted = await self.client.delete(
            "/api/history", params={"session_id": "public-chat"}, headers=headers,
        )
        self.assertEqual(deleted.status_code, 200)

    async def test_chat_capability_does_not_grant_document_administration(self):
        for method, path, kwargs in [
            ("GET", "/documents.html", {}),
            ("GET", "/api/documents", {}),
            ("GET", "/api/documents/example/text", {}),
            ("POST", "/api/documents/upload", {"files": {"file": ("test.pdf", b"%PDF-test")}}),
            ("POST", "/api/documents/upload-batch", {}),
            ("POST", "/api/documents/delete-batch", {"json": {"ids": ["example"]}}),
            ("DELETE", "/api/documents/example", {}),
            ("PATCH", "/api/documents/example/date", {"json": {"document_date": "2026-10-20"}}),
            ("POST", "/api/documents/reindex", {}),
            ("GET", "/api/admin/storage", {}),
            ("POST", "/api/admin/storage/backup", {}),
            ("GET", "/api/admin/storage/backups/hocvu-20261020T000000Z-1234abcd.zip", {}),
        ]:
            with self.subTest(path=path), patch.object(server, "get_engine") as engine:
                response = await self.client.request(
                    method, path,
                    headers={"Origin": "http://test", "X-HocVu-Owner": "b" * 64},
                    **kwargs,
                )
                self.assertEqual(response.status_code, 401)
                engine.assert_not_called()

    async def test_public_chat_still_rejects_cross_site_changes(self):
        with patch.object(server, "get_engine") as engine:
            response = await self.client.post(
                "/api/ask", headers={"Origin": "https://attacker.example", "X-HocVu-Owner": "b" * 64},
                json={"question": "Điều kiện bảo lưu?"},
            )
            self.assertEqual(response.status_code, 403)
            engine.assert_not_called()

    async def test_public_voice_endpoints_do_not_request_admin_login(self):
        with patch.object(server, "get_voice_manager") as get_voice:
            get_voice.return_value.synthesize = AsyncMock(return_value=b"synthetic-mp3")
            get_voice.return_value.generate_audio_file = AsyncMock(return_value=("/api/audio/test.mp3", None))
            get = await self.client.get("/api/tts", params={"text": "Xin chào"})
            self.assertEqual(get.status_code, 200)
            post = await self.client.post(
                "/api/tts", headers={"Origin": "http://test"}, json={"text": "Xin chào"},
            )
            self.assertEqual(post.status_code, 200)
            audio_dir = self.root / "audio"
            audio_dir.mkdir(exist_ok=True)
            (audio_dir / "test.mp3").write_bytes(b"synthetic-mp3")
            audio = await self.client.get(post.json()["audio_url"])
            self.assertEqual(audio.status_code, 200)
            self.assertEqual(audio.content, b"synthetic-mp3")

    async def test_admin_can_still_delete_reindex_and_edit_dates(self):
        for method, path, engine_method, kwargs in [
            ("DELETE", "/api/documents/example", "remove_document", {}),
            ("POST", "/api/documents/reindex", "rebuild_index", {}),
            ("PATCH", "/api/documents/example/date", "update_document_date",
             {"json": {"document_date": "2026-10-20"}}),
        ]:
            with self.subTest(path=path), patch.object(server, "get_engine") as engine:
                getattr(engine.return_value, engine_method).return_value = {}
                response = await self.client.request(
                    method, path, auth=("hocvu", "test-access-only"),
                    headers={"Origin": "http://test"}, **kwargs,
                )
                self.assertEqual(response.status_code, 200, response.text)
                getattr(engine.return_value, engine_method).assert_called_once()

    async def test_backup_requires_admin_and_returns_no_private_storage_paths(self):
        result = {
            "filename": "hocvu-20261020T000000Z-1234abcd.zip",
            "documents": 1, "turns": 3, "persistent_copy": True,
        }
        with patch.object(server, "get_engine") as engine:
            engine.return_value.backup_storage.return_value = result
            response = await self.client.post(
                "/api/admin/storage/backup", auth=("hocvu", "test-access-only"),
                headers={"Origin": "http://test"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), result)
            engine.return_value.backup_storage.assert_called_once()
        backup_root = self.root / "generated-artifacts" / "backups"
        backup_root.mkdir(parents=True)
        (backup_root / result["filename"]).write_bytes(b"private-backup")
        with patch.object(server, "ROOT", self.root):
            downloaded = await self.client.get(
                "/api/admin/storage/backups/" + result["filename"],
                auth=("hocvu", "test-access-only"),
            )
            self.assertEqual(downloaded.status_code, 200)
            self.assertEqual(downloaded.content, b"private-backup")
            self.assertEqual(downloaded.headers["cache-control"], "no-store")

    async def test_browser_login_serves_pages_and_api(self):
        for path in ["/", "/documents.html", "/main.js", "/documents.js", "/theme.js", "/styles.css", "/api-errors.js", "/api/suggestions"]:
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
            response = await self.client.get("/documents.html", headers={"Authorization": authorization})
            self.assertEqual(response.status_code, 401)

    async def test_empty_secret_does_not_authenticate(self):
        with patch.object(server.config, "api_token", ""):
            response = await self.client.get("/documents.html", auth=("hocvu", ""))
            self.assertEqual(response.status_code, 401)

    async def test_health_is_public(self):
        response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    async def test_legacy_local_mode_remains_unchanged(self):
        with patch.object(server, "browser_auth_enabled", False):
            self.assertEqual((await self.client.get("/")).status_code, 200)
            self.assertEqual((await self.client.get("/api/documents")).status_code, 401)


class TrustedOriginProtectionTests(IsolatedServerEngineTests):
    """Keep exact-origin authorization covered independently of hosting vendors."""

    async def asyncSetUp(self):
        self.patches = [
            patch.object(server, "request_limiter", server.SlidingWindowLimiter()),
            patch.object(server.config, "api_token", "test-access-only"),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", False),
            patch.object(
                server, "trusted_origins",
                server.parse_trusted_origins("https://frontend.example.test"),
            ),
        ]
        for item in self.patches:
            item.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="https://api.example.test",
        )
        self.proxy_headers = {
            "X-HocVu-Token": "test-access-only",
            "X-Forwarded-Proto": "https",
        }

    async def asyncTearDown(self):
        await self.client.aclose()
        for item in reversed(self.patches):
            item.stop()

    async def test_explicitly_trusted_origin_can_ask_and_upload(self):
        headers = {
            **self.proxy_headers,
            "Origin": "https://frontend.example.test",
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

    async def test_valid_token_does_not_bypass_origin_checks(self):
        for extra in [
            {"Origin": "https://attacker.example"},
            {"Origin": "https://frontend.example.test.attacker.example"},
            {"Origin": "https://frontend.example.test", "Sec-Fetch-Site": "cross-site"},
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
        for value in ["*.example.test", "https://*.example.test", "https://frontend.example.test/path", "frontend.example.test"]:
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "HV_TRUSTED_ORIGINS"):
                    server.parse_trusted_origins(value)

    def test_trusted_origins_are_normalized(self):
        self.assertEqual(
            server.parse_trusted_origins(" https://Frontend.Example.Test/ , http://localhost:8888 "),
            frozenset({"https://frontend.example.test", "http://localhost:8888"}),
        )

    def test_single_origin_setup_needs_no_trusted_external_frontend(self):
        self.assertEqual(server.parse_trusted_origins(""), frozenset())
