"""OS-released ownership locks; lock files contain no trusted process IDs."""

import sys
from pathlib import Path
from typing import BinaryIO


class OwnershipLock:
    """Hold an exclusive byte lock until release or process death."""

    def __init__(self, filename: Path) -> None:
        """Acquire an OS-released lock for one private resource.

        Args:
            filename (Path): Private file path for persistence or ownership locking.
        """
        self.stream: BinaryIO | None = None
        filename.parent.mkdir(parents=True, exist_ok=True)
        stream = filename.open("a+b")
        try:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            if sys.platform == "win32":
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
