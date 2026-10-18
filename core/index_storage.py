"""Crash-safe local index commits shared by server and CLI writers."""
from __future__ import annotations

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def index_write_lock(destination: Path):
    # Never unlink this file: waiters must always lock the same inode.
    with destination.with_name(destination.name + ".lock").open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.write(b"\0")
            lock.flush()
            while True:
                lock.seek(0)
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def atomic_write(destination: Path, content: bytes) -> None:
    """Publish only fully flushed files, on the destination filesystem."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        # Persist each rename before the next commit step (backup, then index).
        if os.name != "nt":
            descriptor = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
