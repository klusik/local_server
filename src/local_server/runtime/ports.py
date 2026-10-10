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
