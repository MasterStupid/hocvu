"""Explicit backend selection; a cloud outage must never create local-only data."""
import os
from contextlib import nullcontext


def storage_backend():
    value = os.environ.get("HV_STORAGE_BACKEND", "local").strip().lower()
    if value not in {"local", "replit"}:
        raise ValueError("HV_STORAGE_BACKEND phải là local hoặc replit.")
    if value == "local" and os.environ.get("REPLIT_DEPLOYMENT") == "1":
        raise RuntimeError("Bản publish yêu cầu HV_STORAGE_BACKEND=replit để tránh mất dữ liệu.")
    return value


def document_repository(root):
    if storage_backend() == "replit":
        from .persistent_documents import PersistentDocumentRepository
        return PersistentDocumentRepository(root)
    from .documents import DocumentRepository
    return DocumentRepository(root)


def session_store(path):
    if storage_backend() == "replit":
        from .postgres_session import PostgresSessionStore
        return PostgresSessionStore()
    from .session import SessionStore
    return SessionStore(path)


def writing(repository):
    return repository.writing() if getattr(repository, "durable", False) else nullcontext()
