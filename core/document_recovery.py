"""Offline, explicitly confirmed recovery of legacy invalid document dates.

Build and verify in a temporary directory before publishing either metadata or
index. No original files, extracted text, or unrelated metadata are rewritten.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from .documents import DocumentError, DocumentRepository
from .engine import build_index
from .index_storage import atomic_write, index_write_lock
from .models import Chunk
from .searcher import HybridSearcher
from .settings import AppConfig
from .splitter import split_regulation


def require_stopped_server(server_meta: Path) -> None:
    """Fail closed when the bundled server is still using its in-memory index."""
    if not server_meta.exists():
        return
    try:
        pid = json.loads(server_meta.read_text(encoding="utf-8"))["pid"]
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError()
        os.kill(pid, 0)
    except ProcessLookupError:
        return  # Stale marker from a server that is no longer running.
    except (OSError, ValueError, KeyError, TypeError):
        raise DocumentError("Không xác minh được máy chủ đã dừng. Kiểm tra server.json trước khi phục hồi.") from None
    raise DocumentError("Hãy dừng máy chủ và mọi tiến trình ghi dữ liệu trước khi phục hồi; khởi động lại sau khi xong.")


def _read_optional(path: Path) -> bytes | None:
    return path.read_bytes() if path.exists() else None


def _verify_dates(config: AppConfig, chunks, selected: list[dict]) -> list[dict]:
    """Exercise real retrieval on each document, without logging its query."""
    results = []
    for item in selected:
        document_chunks = [chunk for chunk in chunks if chunk.rid == item["rid"]]
        if not document_chunks or any(chunk.valid_from != item["document_date"] for chunk in document_chunks):
            raise DocumentError("Chỉ mục mới thiếu tài liệu đã chọn hoặc có ngày chưa được sửa.")
        searcher = HybridSearcher(replace(config, semantic_enabled=False))
        searcher.build(document_chunks)
        # A title can consist entirely of stopwords; try clause text as well.
        queries = [document_chunks[0].reg_title, document_chunks[0].text]
        effective = date.fromisoformat(item["document_date"])
        previous = (effective - timedelta(days=1)).isoformat() if effective > date.min else None
        following = (effective + timedelta(days=1)).isoformat() if effective < date.max else None
        at_date = any(searcher.search(query, len(document_chunks), effective.isoformat()) for query in queries)
        before_date = any(searcher.search(query, len(document_chunks), previous) for query in queries) if previous else False
        after_date = any(searcher.search(query, len(document_chunks), following) for query in queries) if following else at_date
        if before_date or not at_date or not after_date:
            raise DocumentError("Tìm kiếm không đạt kiểm tra trước/đúng/sau ngày áp dụng. Chưa lưu thay đổi.")
        results.append({
            **item, "before_effective_date": previous,
            "visible_before": False if previous else None,
            "visible_on": True, "after_effective_date": following,
            "visible_after": True if following else None,
        })
    return results


def recover_document_dates(
    config: AppConfig, repository: DocumentRepository, index_path: Path, plan: dict,
    *, apply: bool = False, confirmed: bool = False, server_meta: Path,
) -> dict:
    """A dry run only validates the selection. Apply requires offline confirmation."""
    manifest_before = _read_optional(repository.manifest)
    entries, selected = repository.prepare_date_repairs(plan)
    result = {"mode": "dry_run", "selected_count": len(selected), "selected": selected}
    if not apply:
        return result
    if not confirmed:
        raise DocumentError("Cần --confirm để xác nhận ngày đúng do quản trị viên cung cấp.")
    require_stopped_server(server_meta)
    for item in selected:
        entry = next(entry for entry in entries if entry["id"] == item["id"])
        if not (repository.root / entry["stored_name"]).is_file():
            raise DocumentError("Thiếu tệp gốc của tài liệu đã chọn; chưa thay đổi dữ liệu.")

    original_entries = json.loads(manifest_before) if manifest_before is not None else []
    # No extraction upgrade writes: even old extraction_version and extra fields
    # must survive unchanged, including those of unselected documents.
    try:
        before_regulations = repository.regulations(entries=original_entries, refresh_extraction=False)
    except Exception:
        raise DocumentError("Không đọc được tệp gốc hoặc văn bản trích xuất. Chưa lưu thay đổi.") from None
    corrected_dates = {item["rid"]: item["document_date"] for item in selected}
    after_regulations = [
        replace(regulation, valid_from=corrected_dates[regulation.rid])
        if regulation.rid in corrected_dates else regulation
        for regulation in before_regulations
    ]
    before_chunks = [
        chunk for regulation in before_regulations
        for chunk in split_regulation(regulation, config.max_chunk_chars, config.overlap_sents)
    ]
    selected_rids = {item["rid"] for item in selected}
    if len(selected_rids) != len(selected) or any(
        sum(entry["rid"] == item["rid"] for entry in entries) != 1 for item in selected
    ):
        raise DocumentError("Mã quy định bị trùng; không thể xác minh phục hồi an toàn.")

    index_before = _read_optional(index_path)
    # BM25 verifies date filtering offline; the normal loader can enable
    # semantic retrieval later from the very same chunks and fingerprint.
    offline_config = replace(config, semantic_enabled=False)
    previous_index = None
    previous_index_status = "missing"
    if index_before is not None:
        try:
            # Read the actual primary snapshot, not a reconstructed index or
            # fallback backup. Keep a good backup if the primary is corrupt.
            previous_data = json.loads(index_before)
            previous_index = HybridSearcher(offline_config)
            previous_index.build([Chunk.from_dict(item) for item in previous_data["chunks"]])
            previous_index_status = "loaded"
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            previous_index = None
            previous_index_status = "unreadable"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".date-recovery-", dir=index_path.parent) as directory:
        staged_index = Path(directory) / "index.json"
        build_index(
            offline_config, index_path=staged_index,
            uploaded_regulations=after_regulations, document_entries=entries,
        )
        staged = HybridSearcher.load(str(staged_index), offline_config)
        checks = _verify_dates(offline_config, staged.chunks, selected)
        expected = {}
        for chunk in before_chunks:
            value = chunk.to_dict()
            if chunk.rid in corrected_dates:
                value["valid_from"] = corrected_dates[chunk.rid]
            expected[chunk.rid, chunk.cid] = value
        uploaded_rids = {entry["rid"] for entry in entries}
        actual = {(chunk.rid, chunk.cid): chunk.to_dict()
                  for chunk in staged.chunks if chunk.rid in uploaded_rids}
        if expected != actual:
            raise DocumentError("Chỉ mục tài liệu có thay đổi ngoài ngày được xác nhận. Chưa lưu thay đổi.")
        for check in checks:
            check["visible_before_repair"] = any(
                hit.chunk.rid == check["rid"]
                for hit in previous_index.search(
                    next(reg.title for reg in before_regulations if reg.rid == check["rid"]),
                    len(previous_index.chunks), check["document_date"],
                )
            ) if previous_index is not None else None

        manifest_after = json.dumps(entries, ensure_ascii=False, indent=2).encode("utf-8")
        index_after = staged_index.read_bytes()
        # The server must be stopped (also for directly launched ASGI servers).
        # Detect intervening CLI edits instead of overwriting their work.
        with index_write_lock(index_path):
            require_stopped_server(server_meta)
            if _read_optional(repository.manifest) != manifest_before or _read_optional(index_path) != index_before:
                raise DocumentError("Dữ liệu đã thay đổi trong lúc kiểm tra. Hãy rà soát và xác nhận lại.")
            backups = {
                repository.manifest_backup: _read_optional(repository.manifest_backup),
                index_path.with_suffix(".json.bak"): _read_optional(index_path.with_suffix(".json.bak")),
            }
            originals = {repository.manifest: manifest_before, index_path: index_before, **backups}
            try:
                if manifest_before is not None:
                    atomic_write(repository.manifest_backup, manifest_before)
                if index_before is not None and previous_index_status == "loaded":
                    atomic_write(index_path.with_suffix(".json.bak"), index_before)
                atomic_write(repository.manifest, manifest_after)
                atomic_write(index_path, index_after)
            except OSError:
                try:
                    for path, content in originals.items():
                        if content is None:
                            path.unlink(missing_ok=True)
                        else:
                            atomic_write(path, content)
                except OSError:
                    raise DocumentError("Không thể hoàn tác lỗi ghi. Giữ máy chủ dừng và khôi phục bản sao lưu trước khi chạy lại.") from None
                raise DocumentError("Không thể lưu phục hồi; đã hoàn tác metadata và chỉ mục.") from None
    return {
        "mode": "applied", "selected_count": len(selected), "verification": checks,
        "previous_index_status": previous_index_status, "restart_required": True,
    }
