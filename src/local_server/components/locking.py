"""OS-released lock serializes package mutation and interrupted-work cleanup."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from local_server.core.paths import reject_links


def rename_directory(source: Path, target: Path) -> None:
    """Retry transient Windows sharing/access failures without replacing a target."""
    for attempt in range(6):
        try:
            os.rename(source, target)
            return
        except PermissionError:
            if os.name != "nt" or target.exists() or attempt == 5:
                raise
            time.sleep(0.05 * (attempt + 1))


@contextmanager
def package_lock(root: Path) -> Iterator[None]:
    """Fail promptly if another application instance manages this package root."""
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".manager.lock"
    reject_links(root, lock)
    with lock.open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Packages are being managed by another Local Server instance. Retry when it finishes.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
