"""OS-released ownership locks; lock files contain no trusted process IDs."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class OwnershipLock:
    """Hold an exclusive byte lock until release or process death."""

    def __init__(self, filename: Path) -> None:
        self.stream: BinaryIO | None = None
        filename.parent.mkdir(parents=True, exist_ok=True)
        stream = filename.open("a+b")
        try:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            stream.close()
            raise
        self.stream = stream

    def close(self) -> None:
        """Release ownership without deleting the shared lock inode."""
        if self.stream is not None:
            self.stream.close()
            self.stream = None
