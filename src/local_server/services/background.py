"""Small Tk-independent queue for serialized profile disk operations."""

from __future__ import annotations

import queue
import threading
from typing import Any, Callable


class BackgroundIO:
    """Run one operation at a time and deliver callbacks to the polling thread."""

    def __init__(self) -> None:
        self.results: queue.SimpleQueue[tuple[Callable[[Any], None], Any, Exception | None]] = queue.SimpleQueue()
        self.thread: threading.Thread | None = None

    @property
    def busy(self) -> bool:
        """Report whether an operation or an undelivered result is pending."""
        return bool(self.thread and self.thread.is_alive()) or not self.results.empty()

    def submit(self, operation: Callable[[], Any], success: Callable[[Any], None]) -> None:
        """Run IO in a worker; callbacks are invoked only by the caller's poller."""
        if self.busy:
            raise RuntimeError("A profile operation is already in progress")

        def run() -> None:
            try:
                result = operation()
            except Exception as exc:
                self.results.put((success, None, exc))
            else:
                self.results.put((success, result, None))

        self.thread = threading.Thread(target=run, name="profile-storage", daemon=False)
        self.thread.start()
