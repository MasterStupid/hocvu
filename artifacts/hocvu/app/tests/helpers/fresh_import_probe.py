"""Child process for the fresh-import setup checks.

Runs the real ASGI application against the storage named by its environment
and prints what an unauthenticated visitor and an administrator would receive.
Only the App Storage transport is replaced, by an in-memory object store.
"""
import asyncio
import json
import os
import sys
from unittest.mock import patch

import httpx

from tests.persistence_helpers import MemoryObjects


async def probe(options):
    from core.settings import DATA
    from server import app as server

    token = os.environ["HV_API_TOKEN"]
    if options.get("initialize_empty"):
        from core.persistent_documents import DocumentState
        DocumentState().initialize_empty(confirmed=True)
    result = {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test",
    ) as client:
        for name, path, headers in (
            ("shell", "/", {}),
            ("health", "/api/health", {}),
            ("documents_anonymous", "/api/documents", {}),
            ("documents_wrong_token", "/api/documents", {"X-HocVu-Token": token + "x"}),
            ("documents_admin", "/api/documents", {"X-HocVu-Token": token}),
            *((("asset", options["asset"], {}),) if options.get("asset") else ()),
        ):
            response = await client.get(path, headers=headers)
            try:
                body = response.json()
            except ValueError:
                body = response.text[:4000]
            result[name] = {"status": response.status_code, "body": body}
    result["auth"] = {"browser": server.browser_auth_enabled, "api_token": server.requires_api_token}
    result["local_history_file"] = (DATA / "sessions.db").exists()
    # Empty cache folders are harmless; a stored file would be a silent fallback.
    result["local_documents"] = sorted(
        str(item.relative_to(DATA)) for item in (DATA / "documents").rglob("*") if item.is_file()
    ) if (DATA / "documents").exists() else []
    return result


def main():
    options = json.loads(sys.argv[1])
    with patch("replit.object_storage.Client", side_effect=lambda bucket_id: MemoryObjects()):
        result = asyncio.run(probe(options))
    print("PROBE " + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
