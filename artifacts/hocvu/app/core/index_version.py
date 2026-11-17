"""Fingerprint the source and settings that determine indexed chunks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .settings import AppConfig, DOCS


# nlp.py supplies the sentence boundaries used by the splitter.
INDEX_SOURCE_FILES = tuple(
    Path(__file__).with_name(name) for name in ("corpus.py", "splitter.py", "nlp.py")
)


def index_fingerprint(
    config: AppConfig, documents_root: Path | None = None, *,
    document_entries: list[dict] | None = None,
) -> str:
    """Hash code/settings and the actual uploaded-document manifest snapshot."""
    digest = hashlib.sha256()
    for source in INDEX_SOURCE_FILES:
        content = source.read_bytes()
        digest.update(source.name.encode("utf-8"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    digest.update(json.dumps({
        "seed": config.seed,
        "max_chunk_chars": config.max_chunk_chars,
        "overlap_sents": config.overlap_sents,
    }, sort_keys=True).encode("utf-8"))
    if document_entries is None:
        from .documents import DocumentRepository
        document_entries = DocumentRepository(
            DOCS if documents_root is None else documents_root,
        ).list()
    digest.update(json.dumps(
        document_entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    return digest.hexdigest()
