"""Loopback port diagnostics; a probe does not reserve a port."""

from __future__ import annotations

import socket


def port_available(port: int) -> bool:
    """Check whether an IPv4 loopback TCP port can currently be bound."""
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("Invalid TCP port")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        try:
            listener.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


class PortReservation:
    """Hold a loopback port until immediately before a server binds it.

    Nginx/PHP cannot inherit these sockets. Health probes and child polling
    therefore also guard the unavoidable release/bind interval.
    """

    def __init__(self, port: int = 0) -> None:
        if isinstance(port, bool) or not isinstance(port, int) or (port != 0 and not 1024 <= port <= 65535):
            raise ValueError("Runtime ports must be unprivileged")
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind(("127.0.0.1", port))
            self.port = self.socket.getsockname()[1]
            if self.port < 1024:
                raise OSError("No unprivileged port available")
        except BaseException:
            self.socket.close()
            raise

    def close(self) -> None:
        """Release the socket, never signal a process occupying another port."""
        self.socket.close()
