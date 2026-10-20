"""Regression tests for file access, input bounds, docs, and lazy startup."""
import os
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException
import httpx

from server import app as server


class ApiHardeningTests(unittest.IsolatedAsyncioTestCase):
    async def test_audio_rejects_traversal_non_audio_and_external_symlinks(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            audio = root / "audio"
            audio.mkdir()
            (root / "sessions.db").write_bytes(b"private sessions")
            (root / "index.json").write_bytes(b"private index")
            (root / "outside.mp3").write_bytes(b"private outside file")
            (audio / "private.mp3").symlink_to(root / "sessions.db")
            (audio / "index.json").write_bytes(b"not audio")
            (audio / "valid.mp3").write_bytes(b"synthetic audio")
            with patch.object(server, "AUD", audio):
                for filename in (
                    "../sessions.db", "../index.json", "../outside.mp3",
                    str(root / "outside.mp3"), "private.mp3", "index.json",
                    "..\\sessions.db", "missing.mp3", "bad\x00.mp3",
                ):
                    with self.subTest(filename=filename):
                        with self.assertRaises(HTTPException) as caught:
                            await server.get_audio_file(filename)
                        self.assertEqual(caught.exception.status_code, 404)
                response = await server.get_audio_file("valid.mp3")
                self.assertEqual(Path(response.path), audio / "valid.mp3")

    async def test_audio_http_route_never_exposes_private_files(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "requires_api_token", False),
        ):
            audio = Path(root) / "audio"
            audio.mkdir()
            (Path(root) / "sessions.db").write_bytes(b"private marker")
            (audio / "leak.mp3").symlink_to(Path(root) / "sessions.db")
            (audio / "valid.mp3").write_bytes(b"synthetic audio")
            with patch.object(server, "AUD", audio):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=server.app), base_url="http://test"
                ) as client:
                    for suffix in ("..%2fsessions.db", "%2e%2e%2fsessions.db", "leak.mp3", "sessions.db"):
                        result = await client.get("/api/audio/" + suffix)
                        self.assertEqual(result.status_code, 404)
                        self.assertNotIn(b"private marker", result.content)
                    result = await client.get("/api/audio/valid.mp3")
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(result.content, b"synthetic audio")

    async def test_question_length_is_validated_before_engine_access(self):
        with (
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "requires_api_token", False),
            patch.object(server, "get_engine") as get_engine,
        ):
            get_engine.return_value.ask.return_value.to_dict.return_value = {"answer": "test"}
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app), base_url="http://test"
            ) as client:
                invalid = await client.post("/api/ask", json={"question": "đ" * 4001})
                self.assertEqual(invalid.status_code, 422)
                get_engine.assert_not_called()
                valid = await client.post("/api/ask", json={"question": "đ" * 4000},
                                          headers={"X-HocVu-Owner": "a" * 64})
                self.assertEqual(valid.status_code, 200)
                self.assertEqual(get_engine.call_count, 2)  # ownership + ask

    async def test_percent_encoded_windows_traversal_pocs_are_rejected(self):
        # Synthetic fixtures only: never read the actual project's .env or DB.
        with (
            tempfile.TemporaryDirectory() as root,
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "requires_api_token", False),
        ):
            root = Path(root)
            audio = root / "data" / "audio"
            audio.mkdir(parents=True)
            for private in (
                root / "requirements.txt", root / ".env",
                root / "data" / "sessions.db", root / "data" / "index.json",
                root / "private.mp3",
            ):
                private.write_bytes(b"synthetic-private-marker")
            payloads = (
                r"..\..\requirements.txt", r"..\sessions.db", r"..\..\.env",
                r"..\index.json", r"..\..\private.mp3",
                r"C:\Windows\private.mp3", r"\\server\share\private.mp3",
            )
            with patch.object(server, "AUD", audio):
                # Check both decoded handler arguments and real HTTP URL decoding.
                for filename in payloads:
                    with self.subTest(decoded_filename=filename):
                        with self.assertRaises(HTTPException) as caught:
                            await server.get_audio_file(filename)
                        self.assertEqual(caught.exception.status_code, 404)
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=server.app), base_url="http://test"
                ) as client:
                    for payload in payloads:
                        for escaped in (
                            payload.replace("\\", "%5c"),
                            payload.replace("\\", "%5C"),
                            payload.replace("\\", "%255c"),
                        ):
                            with self.subTest(url=escaped):
                                with patch.object(server, "FileResponse") as serve_file:
                                    response = await client.get("/api/audio/" + escaped)
                                    self.assertEqual(response.status_code, 404)
                                    self.assertNotIn(b"synthetic-private-marker", response.content)
                                    serve_file.assert_not_called()

    async def test_docs_and_schema_endpoints_are_not_exposed_by_default(self):
        with (
            patch.object(server, "browser_auth_enabled", False),
            patch.object(server, "requires_api_token", False),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app), base_url="http://test"
            ) as client:
                for path in ("/docs", "/redoc", "/openapi.json"):
                    response = await client.get(path)
                    self.assertEqual(response.status_code, 404)


class StartupHardeningTests(unittest.TestCase):
    def test_api_docs_are_disabled_by_default_and_explicitly_opt_in(self):
        code = (
            "import json; from server.app import app; "
            "print(json.dumps([app.docs_url, app.redoc_url, app.openapi_url]))"
        )
        for flag in (None, "0", "1"):
            with self.subTest(flag=flag):
                env = os.environ.copy()
                env.pop("HV_API_DOCS", None)
                if flag is not None:
                    env["HV_API_DOCS"] = flag
                output = subprocess.check_output([sys.executable, "-c", code], env=env, text=True)
                expected = ["/docs", "/redoc", "/openapi.json"] if flag == "1" else [None] * 3
                self.assertEqual(json.loads(output), expected)

    def test_concurrent_first_requests_build_only_one_engine(self):
        workers = 8
        start = threading.Barrier(workers)
        entered = threading.Event()
        release = threading.Event()
        all_attempted = threading.Event()
        sentinel = object()

        class ObservedLock:
            def __init__(self):
                self.lock = threading.Lock()
                self.counter_lock = threading.Lock()
                self.count = 0

            def __enter__(self):
                with self.counter_lock:
                    self.count += 1
                    if self.count == workers:
                        all_attempted.set()
                self.lock.acquire()

            def __exit__(self, *args):
                self.lock.release()

        def load(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test did not release engine initialization")
            return sentinel

        def request():
            start.wait(timeout=5)
            return server.get_engine()

        with (
            patch.object(server, "engine", None),
            patch.object(server, "_engine_lock", ObservedLock()),
            patch.object(server, "ensure_dirs") as ensure_dirs,
            patch.object(server.HocVuEngine, "load_or_build", side_effect=load) as loader,
            ThreadPoolExecutor(max_workers=workers) as pool,
        ):
            futures = [pool.submit(request) for _ in range(workers)]
            try:
                self.assertTrue(entered.wait(5))
                self.assertTrue(all_attempted.wait(5))
            finally:
                release.set()
            self.assertTrue(all(future.result(timeout=5) is sentinel for future in futures))
            loader.assert_called_once()
            ensure_dirs.assert_called_once()
