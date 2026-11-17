"""The React shell is public; it never grants access to protected API data."""
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

import httpx

from server import app as server


class ReactHostingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.object(server, "browser_auth_enabled", True))
        self.enterContext(patch.object(server, "requires_api_token", True))
        self.enterContext(patch.object(server.config, "api_token", "synthetic-test-only"))
        self.enterContext(patch.object(server, "request_limiter", server.SlidingWindowLimiter()))
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_react_pages_are_public_and_not_cached(self):
        for path in ("/", "/library", "/documents", "/settings"):
            with self.subTest(path=path):
                result = await self.client.get(path)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.headers.get("cache-control"), "no-store")
                self.assertNotIn("www-authenticate", result.headers)

    async def test_storage_failure_keeps_shell_public_but_health_fails_explicitly(self):
        with patch.object(server, "get_engine", side_effect=server.StorageUnavailable("Kho chưa sẵn sàng")):
            shell = await self.client.get("/")
            health = await self.client.get("/api/health")
        self.assertEqual(shell.status_code, 200)
        self.assertEqual(health.status_code, 503)

    async def test_startup_does_not_require_storage_or_tts_provider(self):
        with tempfile.TemporaryDirectory() as root:
            with (
                patch.object(server, "SERVER_META", Path(root) / "server.json"),
                patch.object(server, "ensure_dirs"),
                patch.object(server, "get_engine", side_effect=AssertionError("eager engine")),
                patch.object(server, "get_voice_manager", side_effect=AssertionError("eager TTS")),
                patch.object(server.uvicorn, "run") as run,
            ):
                server.main()
                run.assert_called_once()

    async def test_assets_can_load_without_admin_authority(self):
        result = await self.client.get("/assets/nonexistent-build-file.js")
        self.assertEqual(result.status_code, 404)
        self.assertNotIn("www-authenticate", result.headers)

    async def test_public_admin_shell_does_not_open_data_apis(self):
        for path in (
            "/api/documents", "/api/admin/storage",
            "/api/documents/unknown/text", "/documents.html",
        ):
            with self.subTest(path=path):
                result = await self.client.get(path)
                self.assertEqual(result.status_code, 401)

    async def test_unknown_routes_and_source_files_remain_protected(self):
        for path in ("/core/settings.py", "/run.py", "/api/assets/file.js"):
            with self.subTest(path=path):
                result = await self.client.get(path)
                self.assertEqual(result.status_code, 401)

    async def test_public_asset_prefix_cannot_read_outside_ui(self):
        result = await self.client.get("/assets/..%2F..%2Fcore%2Fsettings.py")
        self.assertIn(result.status_code, (401, 404))
        self.assertNotIn("HV_API_TOKEN", result.text)
