"""The React shell is public; it never grants access to protected API data."""
import unittest
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
