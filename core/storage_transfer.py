"""Private, verified backups and explicit, empty-target-only storage imports."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import uuid
import zipfile

from psycopg.types.json import Jsonb

from .blob_storage import BlobStorage, safe_relative_path
from .documents import DocumentRepository
from .persistent_db import StorageUnavailable, connect_database
from .persistent_documents import DocumentState, repository_files
from .settings import ROOT


TURN_COLUMNS = (
    "id", "session_id", "question", "answer", "intent", "article_id", "rid",
    "context_question", "context_root", "refused", "references_json", "card_json",
    "confidence", "refusal_reason",
)
HISTORY_TABLES = ("turns", "session_owners", "closed_sessions")


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def _sqlite_history(path):
    history = {table: [] for table in HISTORY_TABLES}
    if not path.exists():
        return history
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for table in HISTORY_TABLES:
            if table in tables:
                order = "id" if table == "turns" else "session_id"
                history[table] = [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}")]
    # Legacy columns are absent, not invented evidence or inferred ownership.
    for row in history["turns"]:
        for column in TURN_COLUMNS:
            row.setdefault(column, "" if column in {"context_root", "context_question"} else None)
    return history


def _postgres_history():
    from psycopg.rows import dict_row
    with connect_database() as connection:
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        history = {}
        with connection.cursor(row_factory=dict_row) as cursor:
            for table in HISTORY_TABLES:
                order = "id" if table == "turns" else "session_id"
                cursor.execute(f"SELECT * FROM hv_{table} ORDER BY {order}")
                history[table] = cursor.fetchall()
    return history


def _finish_backup(repository, history, directory, sqlite_snapshot=None, output_dir=None):
    entries = repository.list()
    files = {name: repository.root / name for name in repository_files(repository, entries)}
    for name, path in files.items():
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(repository.root.resolve()):
            raise StorageUnavailable("Bản sao lưu thiếu tệp hoặc chứa đường dẫn không hợp lệ; chưa chuyển dữ liệu.")
    hashes = {name: _digest(path) for name, path in files.items()}
    source = {"manifest": entries, "history": history, "files": hashes}
    info = {
        "format": "hocvu-backup-v1",
        "source_digest": hashlib.sha256(_json(source).encode()).hexdigest(),
        "files": hashes,
    }
    output_dir = Path(output_dir) if output_dir else ROOT / "generated-artifacts" / "backups"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output_dir / f"hocvu-{stamp}-{uuid.uuid4().hex[:8]}.zip"
    temporary = Path(directory) / "backup.zip"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup-info.json", _json(info))
        archive.writestr("documents/manifest.json", _json(entries))
        archive.writestr("history.json", _json(history))
        if sqlite_snapshot and sqlite_snapshot.exists():
            archive.write(sqlite_snapshot, "sessions.db")
        for name, path in files.items():
            archive.write(path, "documents/" + name)
    # Detect a concurrent local document change rather than publishing a mixed
    # backup. SQLite itself was snapshotted with its WAL-aware backup API.
    if repository.list() != entries or any(_digest(path) != hashes[name] for name, path in files.items()):
        raise StorageUnavailable("Tài liệu thay đổi khi sao lưu. Hãy tạm dừng tải lên/xóa và thử lại.")
    descriptor = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(descriptor, "wb") as target, temporary.open("rb") as source:
        shutil.copyfileobj(source, target)
    return {
        "path": str(destination), "documents": len(entries),
        "turns": len(history["turns"]), "owners": len(history["session_owners"]),
        "closed_sessions": len(history["closed_sessions"]), "source_digest": info["source_digest"],
    }


def backup_local(data_root, *, output_dir=None):
    data_root = Path(data_root)
    repository = DocumentRepository(data_root / "documents", create_dirs=False)
    with tempfile.TemporaryDirectory(prefix="hocvu-backup-") as directory:
        snapshot = Path(directory) / "sessions.db"
        source = data_root / "sessions.db"
        if source.exists():
            uri = source.resolve().as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True, timeout=5)) as live:
                with closing(sqlite3.connect(snapshot)) as target:
                    live.backup(target)
        return _finish_backup(repository, _sqlite_history(snapshot), directory, snapshot, output_dir)


def backup_persistent(repository, *, output_dir=None):
    with repository.state.writer():
        repository.refresh()
        with tempfile.TemporaryDirectory(prefix="hocvu-backup-") as directory:
            result = _finish_backup(repository, _postgres_history(), directory, output_dir=output_dir)
        result["backup_key"] = repository.blobs.backup(Path(result["path"]))
        return result


def _read_backup(path, directory):
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > 50000 or any(item.file_size > 128 * 1024 * 1024 for item in archive.infolist()):
            raise StorageUnavailable("Bản sao lưu vượt giới hạn an toàn.")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise StorageUnavailable("Bản sao lưu có tên tệp trùng nhau.")
        for name in names:
            safe_relative_path(name)
        info = json.loads(archive.read("backup-info.json"))
        if info.get("format") != "hocvu-backup-v1":
            raise StorageUnavailable("Định dạng bản sao lưu không được hỗ trợ.")
        entries = json.loads(archive.read("documents/manifest.json"))
        history = json.loads(archive.read("history.json"))
        if not isinstance(entries, list) or set(history) != set(HISTORY_TABLES):
            raise StorageUnavailable("Danh mục hoặc lịch sử sao lưu không hợp lệ.")
        repository = DocumentRepository(Path(directory) / "documents")
        files = repository_files(repository, entries)
        if set(files) != set(info["files"]):
            raise StorageUnavailable("Danh mục không khớp danh sách tệp sao lưu.")
        for name in files:
            path = repository.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open("documents/" + name) as source, path.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            if _digest(path) != info["files"][name]:
                raise StorageUnavailable("Bản sao lưu không khớp mã kiểm tra.")
        source = {"manifest": entries, "history": history, "files": info["files"]}
        if hashlib.sha256(_json(source).encode()).hexdigest() != info["source_digest"]:
            raise StorageUnavailable("Thông tin bản sao lưu bị thay đổi.")
        return entries, history, info, repository


def import_backup(path, *, apply=False, confirmed=False, blobs=None, state=None):
    """Import data only; production schema is exclusively managed by Publish.

    The operator runs this in development. The first Publish can initialize
    production from the verified development data through Replit's own UI.
    """
    if os.environ.get("REPLIT_DEPLOYMENT") == "1":
        raise StorageUnavailable("Chuyển dữ liệu chỉ chạy trong development; dùng luồng Publish cho production.")
    if apply and not confirmed:
        raise StorageUnavailable("Cần --confirm sau khi kiểm tra nguồn và bản sao lưu.")
    path = Path(path)
    state = state or DocumentState()
    with tempfile.TemporaryDirectory(prefix="hocvu-import-") as directory:
        entries, history, info, repository = _read_backup(path, directory)
        report = {
            "documents": len(entries), "turns": len(history["turns"]),
            "owners": len(history["session_owners"]), "closed_sessions": len(history["closed_sessions"]),
            "applied": False, "already_imported": False,
        }
        with state.writer():
            with connect_database() as connection:
                previous = connection.execute(
                    "SELECT backup_key FROM hv_storage_imports WHERE source_digest = %s",
                    (info["source_digest"],),
                ).fetchone()
                if previous:
                    return {**report, "already_imported": True, "backup_key": previous[0]}
                exists = connection.execute("""
                    SELECT EXISTS(SELECT 1 FROM hv_document_state)
                        OR EXISTS(SELECT 1 FROM hv_turns)
                        OR EXISTS(SELECT 1 FROM hv_session_owners)
                        OR EXISTS(SELECT 1 FROM hv_closed_sessions)
                """).fetchone()[0]
                if exists:
                    raise StorageUnavailable("Đích đã có dữ liệu. Không ghi đè hoặc trộn lịch sử/quyền sở hữu.")
            if not apply:
                return report
            blobs = blobs or BlobStorage()
            blobs.check()
            backup_key = blobs.backup(path)
            objects = {
                name: blobs.put((repository.root / name).read_bytes())
                for name in repository_files(repository, entries)
            }
            with connect_database() as connection:
                # Recheck under table locks after object uploads. A concurrent
                # history writer must not turn an empty-target import into a merge.
                connection.execute("""
                    LOCK TABLE hv_document_state, hv_turns, hv_session_owners,
                        hv_closed_sessions, hv_storage_imports IN EXCLUSIVE MODE
                """)
                occupied = connection.execute("""
                    SELECT EXISTS(SELECT 1 FROM hv_document_state)
                        OR EXISTS(SELECT 1 FROM hv_turns)
                        OR EXISTS(SELECT 1 FROM hv_session_owners)
                        OR EXISTS(SELECT 1 FROM hv_closed_sessions)
                """).fetchone()[0]
                if occupied:
                    raise StorageUnavailable("Đích vừa có dữ liệu mới. Hủy nhập, không ghi đè hoặc trộn lịch sử.")
                for row in history["turns"]:
                    connection.execute(
                        f"INSERT INTO hv_turns ({','.join(TURN_COLUMNS)}) VALUES ({','.join(['%s'] * len(TURN_COLUMNS))})",
                        tuple(row[column] for column in TURN_COLUMNS),
                    )
                for row in history["session_owners"]:
                    connection.execute(
                        "INSERT INTO hv_session_owners (session_id, owner, updated_at) VALUES (%s, %s, %s)",
                        (row["session_id"], row["owner"], row["updated_at"]),
                    )
                for row in history["closed_sessions"]:
                    connection.execute("INSERT INTO hv_closed_sessions (session_id) VALUES (%s)", (row["session_id"],))
                connection.execute("""
                    SELECT setval(pg_get_serial_sequence('hv_turns', 'id'),
                        COALESCE((SELECT MAX(id) FROM hv_turns), 1),
                        EXISTS(SELECT 1 FROM hv_turns))
                """)
                connection.execute(
                    "INSERT INTO hv_document_state (id, revision, manifest, objects) VALUES (1, 1, %s, %s)",
                    (Jsonb(entries), Jsonb(objects)),
                )
                connection.execute(
                    "INSERT INTO hv_storage_imports (source_digest, backup_key) VALUES (%s, %s)",
                    (info["source_digest"], backup_key),
                )
            return {**report, "applied": True, "backup_key": backup_key}
