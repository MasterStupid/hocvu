"""Authentication is launcher-independent; invalid credentials consume quota."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import httpx
from starlette.requests import Request

from server import app as server
from server.security import SlidingWindowLimiter, client_address, parse_trusted_proxies


class LimiterTests(unittest.TestCase):
    def test_sliding_window_and_retry_after(self):
        limiter = SlidingWindowLimiter()
        self.assertEqual(limiter.consume("a", 2, now=0), 0)
        self.assertEqual(limiter.consume("a", 2, now=30), 0)
        self.assertEqual(limiter.consume("a", 2, now=54.2), 6)
        self.assertEqual(limiter.consume("a", 2, now=60), 0)
        self.assertEqual(limiter.consume("a", 2, now=60.1), 30)

    def test_expired_ips_are_removed_including_under_rejected_traffic(self):
        limiter = SlidingWindowLimiter(max_clients=2)
        limiter.consume("old", 1, now=0)
        limiter.consume("new", 1, now=10)
        self.assertGreater(limiter.consume("old", 1, now=20), 0)
        self.assertEqual(limiter.consume("third", 1, now=60), 0)
        self.assertNotIn("old", limiter._buckets)
        self.assertEqual(set(limiter._buckets), {"new", "third"})

    def test_capacity_cannot_evict_active_clients_and_reset_their_limit(self):
        limiter = SlidingWindowLimiter(max_clients=2)
        limiter.consume("a", 1, now=0)
        limiter.consume("b", 1, now=1)
        for index in range(100):
            self.assertGreater(limiter.consume(f"flood-{index}", 1, now=2), 0)
        self.assertEqual(len(limiter._buckets), 2)
        self.assertGreater(limiter.consume("a", 1, now=3), 0)
        self.assertEqual(limiter.consume("replacement", 1, now=61), 0)
        self.assertEqual(len(limiter._buckets), 1)

    def test_concurrent_calls_cannot_exceed_quota(self):
        limiter = SlidingWindowLimiter()
        with ThreadPoolExecutor(max_workers=16) as executor:
            results = list(executor.map(lambda _: limiter.consume("same-ip", 10, now=1), range(100)))
        self.assertEqual(results.count(0), 10)
        self.assertEqual(len(limiter._buckets["same-ip"]), 10)


class ProxyIdentityTests(unittest.TestCase):
    def request(self, peer, forwarded=None):
        headers = [] if forwarded is None else [(b"x-forwarded-for", forwarded.encode())]
        return Request({"type": "http", "client": (peer, 123), "headers": headers})

    def test_untrusted_peer_cannot_spoof_forwarded_addresses(self):
        proxies = parse_trusted_proxies("127.0.0.1,10.0.0.0/24")
        request = self.request("198.51.100.8", "203.0.113.7, 10.0.0.2")
        self.assertEqual(client_address(request, proxies), "198.51.100.8")

    def test_trusted_proxy_identifies_different_clients(self):
        proxies = parse_trusted_proxies("10.0.0.0/24")
        for ip in ("198.51.100.7", "198.51.100.8"):
            self.assertEqual(client_address(self.request("10.0.0.2", ip), proxies), ip)

    def test_chain_is_walked_right_to_left_and_ignores_forged_prefix(self):
        proxies = parse_trusted_proxies("10.0.0.0/24,127.0.0.1")
        request = self.request("127.0.0.1", "203.0.113.99,198.51.100.7,10.0.0.2")
        self.assertEqual(client_address(request, proxies), "198.51.100.7")

    def test_invalid_or_oversized_forwarded_header_fails_closed_to_peer(self):
        proxies = parse_trusted_proxies("127.0.0.1")
        for header in ("", "not-an-ip", "198.51.100.7:123", "1.2.3.4," * 34, "a" * 5000):
            with self.subTest(header_length=len(header)):
                self.assertEqual(client_address(self.request("127.0.0.1", header), proxies), "127.0.0.1")

    def test_ipv6_clients_and_disabled_proxy_trust(self):
        proxies = parse_trusted_proxies("::1,fd00::/8")
        request = self.request("::1", "2001:db8::123,fd00::2")
        self.assertEqual(client_address(request, proxies), "2001:db8::123")
        self.assertEqual(client_address(request, ()), "::1")

    def test_bad_proxy_configuration_is_rejected(self):
        for value in ("*", "0.0.0.0/0", "::/0", "https://proxy", "proxy.example", "10.0.0.1:80"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError, "HV_TRUSTED_PROXIES"):
                    parse_trusted_proxies(value)


class AuthThrottlingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        patches = [
            patch.object(server.config, "api_token", "synthetic-security-token"),
            patch.object(server.config, "rate_limit_per_minute", 2),
            patch.object(server, "requires_api_token", True),
            patch.object(server, "browser_auth_enabled", True),
            patch.object(server, "request_limiter", SlidingWindowLimiter()),
            patch.object(server, "trusted_proxies", parse_trusted_proxies("10.0.0.0/24")),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app, client=("10.0.0.2", 123)),
            base_url="http://test",
        )
        self.addAsyncCleanup(self.client.aclose)

    async def test_basic_brute_force_is_limited_on_pages_and_api(self):
        for path in ("/", "/api/documents"):
            with self.subTest(path=path):
                with patch.object(server, "request_limiter", SlidingWindowLimiter()):
                    for _ in range(2):
                        self.assertEqual((await self.client.get(path, auth=("hocvu", "wrong"))).status_code, 401)
                    response = await self.client.get(path, auth=("hocvu", "wrong-again"))
                    self.assertEqual(response.status_code, 429)
                    self.assertGreater(int(response.headers["retry-after"]), 0)

    async def test_header_token_brute_force_is_limited_without_browser_auth(self):
        with patch.object(server, "browser_auth_enabled", False):
            for _ in range(2):
                self.assertEqual((await self.client.get("/api/documents", headers={"X-HocVu-Token": "wrong"})).status_code, 401)
            response = await self.client.get("/api/documents", headers={"X-HocVu-Token": "also-wrong"})
            self.assertEqual(response.status_code, 429)

    async def test_invalid_and_valid_credentials_share_the_same_quota(self):
        for _ in range(2):
            await self.client.get("/api/suggestions", auth=("hocvu", "wrong"))
        response = await self.client.get("/api/suggestions", auth=("hocvu", "synthetic-security-token"))
        self.assertEqual(response.status_code, 429)

    async def test_health_stays_public_even_when_client_is_throttled(self):
        for _ in range(3):
            await self.client.get("/")
        with patch.object(server, "get_engine") as engine:
            engine.return_value.list_documents.return_value = []
            engine.return_value.searcher.provider = "bm25"
            engine.return_value.searcher.semantic_error = None
            response = await self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)

    async def test_clients_behind_trusted_proxy_do_not_share_a_quota(self):
        for _ in range(3):
            await self.client.get("/", headers={"X-Forwarded-For": "198.51.100.1"})
        response = await self.client.get("/", headers={"X-Forwarded-For": "198.51.100.2"})
        self.assertEqual(response.status_code, 401)
        blocked = await self.client.get("/", headers={"X-Forwarded-For": "198.51.100.1"})
        self.assertEqual(blocked.status_code, 429)

    async def test_forged_forwarded_prefix_cannot_reset_a_real_clients_quota(self):
        for fake_ip in ("203.0.113.1", "203.0.113.2", "203.0.113.3"):
            response = await self.client.get(
                "/", headers={"X-Forwarded-For": f"{fake_ip},198.51.100.1"},
            )
        self.assertEqual(response.status_code, 429)

    async def test_direct_client_cannot_rotate_spoofed_headers_to_evade_limit(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app, client=("198.51.100.9", 123)),
            base_url="http://test",
        ) as client:
            for ip in ("203.0.113.1", "203.0.113.2", "203.0.113.3"):
                response = await client.get("/", headers={"X-Forwarded-For": ip})
            self.assertEqual(response.status_code, 429)


class LauncherIndependentAuthTests(unittest.TestCase):
    def test_fresh_asgi_import_requires_auth_without_calling_main(self):
        code = """
import asyncio, json, os, sys
os.environ["HV_API_TOKEN"] = sys.argv[1]
os.environ["HV_BROWSER_AUTH"] = "0"
from unittest.mock import patch
import httpx
from server import app as server
async def check():
    with patch.object(server, "get_engine") as engine:
        engine.return_value.suggestion_topics.return_value = []
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as client:
            missing = await client.get("/api/suggestions")
            wrong = await client.get("/api/suggestions", headers={"X-HocVu-Token": "wrong"})
            valid = await client.get("/api/suggestions", headers={"X-HocVu-Token": sys.argv[1]})
    print(json.dumps([server.requires_api_token, missing.status_code, wrong.status_code, valid.status_code]))
asyncio.run(check())
"""
        for token, expected in (("synthetic-asgi-only", [True, 401, 401, 200]), ("", [True, 401, 401, 401])):
            with self.subTest(configured=bool(token)):
                result = subprocess.run(
                    [sys.executable, "-c", code, token], cwd=Path(__file__).resolve().parents[1],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)

    def test_launcher_cannot_disable_auth_by_binding_to_loopback(self):
        for host in ("127.0.0.1", "0.0.0.0"):
            with self.subTest(host=host):
                with (
                    patch.object(server.config, "api_token", ""),
                    patch.object(server, "requires_api_token", True),
                    patch.object(server.uvicorn, "run") as run,
                ):
                    with self.assertRaisesRegex(RuntimeError, "HV_API_TOKEN"):
                        server.main(host=host)
                    self.assertTrue(server.requires_api_token)
                    run.assert_not_called()
