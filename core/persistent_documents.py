"""PostgreSQL owns the manifest; App Storage owns files; local files are disposable."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import tempfile

from psycopg.types.json import Jsonb

from .blob_storage import BlobStorage, safe_relative_path
from .documents import DocumentRepository
from .persistent_db import StorageUnavailable, connect_database


class DocumentState:
    def snapshot(self, *, initialized=True):
        with connect_database() as connection:
            row = connection.execute("SELECT revision, manifest, objects FROM hv_document_state WHERE id = 1").fetchone()
        if row is None:
            if initialized:
                raise StorageUnavailable("Chưa chuyển dữ liệu. Chạy migrate-storage trước khi bật HV_STORAGE_BACKEND=replit.")
            return 0, [], {}
        return row

    def revision(self):
        with connect_database() as connection:
            row = connection.execute("SELECT revision FROM hv_document_state WHERE id = 1").fetchone()
        if row is None:
            raise StorageUnavailable("Chưa chuyển dữ liệu sang kho bền vững.")
        return row[0]

    @contextmanager
    def writer(self):
        # Session-level lock: serialize cache staging + remote commits without
        # keeping a PostgreSQL transaction open around extraction/model work.
        connection = connect_database()
        connection.autocommit = True
        try:
            connection.execute("SET lock_timeout = '10s'")
            connection.execute("SELECT pg_advisory_lock(hashtextextended('hocvu-documents', 0))")
            yield
        finally:
            # Closing releases the advisory lock even after cancellation/error.
            connection.close()

    def commit(self, revision, entries, objects):
        with connect_database() as connection:
            result = connection.execute("""
                INSERT INTO hv_document_state (id, revision, manifest, objects)
                VALUES (1, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET revision = EXCLUDED.revision, manifest = EXCLUDED.manifest, objects = EXCLUDED.objects
                WHERE hv_document_state.revision = %s
            """, (revision + 1, Jsonb(entries), Jsonb(objects), revision))
            if result.rowcount != 1:
                raise StorageUnavailable("Kho tài liệu đã thay đổi; chưa ghi đè dữ liệu. Hãy tải lại.")
        return revision + 1


def repository_files(repository, entries):
    names = []
    for item in entries:
        item_id = safe_relative_path(item["id"])
        stored = safe_relative_path(item["stored_name"])
        if "/" in item_id or "/" in stored:
            raise StorageUnavailable("Tên tệp trong danh mục không hợp lệ.")
        names.extend((stored, f"extracted/{item_id}.txt"))
    return names


class PersistentDocumentRepository(DocumentRepository):
    durable = True

    def __init__(self, root: Path, *, blobs=None, state=None):
        super().__init__(root)
        self.blobs = blobs or BlobStorage()
        self.state = state or DocumentState()
        self.revision = None
        self._entries = []
        self._objects = {}

    def refresh(self):
        revision, entries, objects = self.state.snapshot()
        self.blobs.check()
        for name in repository_files(self, entries):
            if name not in objects:
                raise StorageUnavailable("Danh mục lưu trữ thiếu tệp gốc hoặc văn bản trích xuất.")
            self.blobs.materialize(self.root, name, objects[name])
        # Never merge an old local manifest back into authoritative storage.
        DocumentRepository._write_manifest(self, entries)
        self.revision, self._entries, self._objects = revision, entries, objects

    def _publish(self):
        entries = self.list()
        objects = {}
        for name in repository_files(self, entries):
            path = self.root / name
            if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
                raise StorageUnavailable("Tệp dữ liệu không hợp lệ.")
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            previous = self._objects.get(name)
            objects[name] = previous if previous and previous["sha256"] == digest else self.blobs.put(data)
        if entries != self._entries or objects != self._objects:
            self.revision = self.state.commit(self.revision, entries, objects)
            self._entries, self._objects = entries, objects
        # Old immutable blobs stay private for backups/other DB environments.
        # Logical deletion removes references, never a shared backup's objects.

    @contextmanager
    def writing(self):
        with self.state.writer():
            self.refresh()
            with self._manifest_transaction():
                yield
                self._publish()

    @contextmanager
    def adding_many(self, uploads):
        with self.state.writer():
            self.refresh()
            with super().adding_many(uploads) as items:
                yield items
                self._publish()

    @contextmanager
    def removing_many(self, item_ids):
        with self.state.writer():
            self.refresh()
            with super().removing_many(item_ids) as result:
                yield result
                self._publish()

    @contextmanager
    def change_date(self, item_id, document_date):
        with self.state.writer():
            self.refresh()
            with super().change_date(item_id, document_date) as result:
                yield result
                self._publish()


@contextmanager
def rollback_index(repository, index_path):
    """A failed remote commit must also undo an already-written local index."""
    if not getattr(repository, "durable", False):
        yield
        return
    index_path = Path(index_path)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=index_path.parent, prefix=".cloud-index-") as directory:
        snapshots = {}
        for path in (index_path, index_path.with_suffix(index_path.suffix + ".bak")):
            if path.exists():
                snapshot = Path(directory) / path.name
                snapshot.write_bytes(path.read_bytes())
                snapshots[path] = snapshot
            else:
                snapshots[path] = None
        try:
            yield
        except BaseException:
            for path, snapshot in snapshots.items():
                if snapshot:
                    snapshot.replace(path)
                else:
                    path.unlink(missing_ok=True)
            raise
