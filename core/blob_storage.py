"""Private immutable files in Replit App Storage; disk is only a verified cache."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from pathlib import Path, PurePosixPath

from .persistent_db import StorageUnavailable


def safe_relative_path(name: str) -> str:
    path = PurePosixPath(name)
    if not name or "\\" in name or path.is_absolute() or ".." in path.parts or str(path) != name:
        raise StorageUnavailable("Đường dẫn trong bản lưu không hợp lệ.")
    return name


class BlobStorage:
    def __init__(self, client=None, prefix=None):
        self.prefix = prefix or os.environ.get("HV_STORAGE_PREFIX", "hocvu/v1")
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9/_-]{0,120}", self.prefix) or ".." in self.prefix:
            raise StorageUnavailable("HV_STORAGE_PREFIX không hợp lệ.")
        if client is None:
            from replit.object_storage import Client
            client = Client(bucket_id=os.environ.get("HV_STORAGE_BUCKET_ID") or None)
        self.client = client

    def check(self):
        try:
            self.client.exists(f"{self.prefix}/.access-check")
        except Exception:
            raise StorageUnavailable(
                "Chưa truy cập được App Storage. Hãy tạo/chọn bucket mặc định; không lưu thay thế trên ổ đĩa."
            ) from None

    def put(self, data: bytes) -> dict:
        digest = hashlib.sha256(data).hexdigest()
        key = f"{self.prefix}/files/{digest}"
        try:
            if not self.client.exists(key):
                self.client.upload_from_bytes(key, data)
            # Verify the acknowledged bytes, including an existing immutable key.
            actual = self.client.download_as_bytes(key)
        except Exception:
            raise StorageUnavailable("Không ghi/xác minh được tệp trên App Storage.") from None
        if hashlib.sha256(actual).hexdigest() != digest:
            raise StorageUnavailable("Tệp trên App Storage không khớp mã kiểm tra.")
        return {"key": key, "sha256": digest, "size": len(data)}

    def read(self, descriptor: dict) -> bytes:
        key = descriptor.get("key", "")
        if not re.fullmatch(re.escape(self.prefix) + r"/files/[a-f0-9]{64}", key):
            raise StorageUnavailable("Mã đối tượng lưu trữ không hợp lệ.")
        try:
            data = self.client.download_as_bytes(key)
        except Exception:
            raise StorageUnavailable("Không tải được tệp từ App Storage.") from None
        if len(data) != descriptor.get("size") or hashlib.sha256(data).hexdigest() != descriptor.get("sha256"):
            raise StorageUnavailable("Tệp lưu trữ bị thiếu hoặc không khớp mã kiểm tra.")
        return data

    def materialize(self, root: Path, name: str, descriptor: dict):
        safe_relative_path(name)
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise StorageUnavailable("Đường dẫn cache vượt ngoài thư mục dữ liệu.")
        if path.is_file() and not path.is_symlink():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest == descriptor["sha256"]:
                return
        data = self.read(descriptor)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_bytes(data)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)

    def backup(self, path: Path) -> str:
        key = f"{self.prefix}/backups/{uuid.uuid4().hex}/{path.name}"
        try:
            self.client.upload_from_filename(key, str(path))
            if hashlib.sha256(self.client.download_as_bytes(key)).digest() != hashlib.sha256(path.read_bytes()).digest():
                raise StorageUnavailable("Bản sao lưu không khớp mã kiểm tra.")
        except StorageUnavailable:
            raise
        except Exception:
            raise StorageUnavailable("Chưa lưu được bản sao lưu riêng tư trên App Storage.") from None
        return key
