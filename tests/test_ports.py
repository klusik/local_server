"""Loopback-only port diagnostic tests."""

import socket
import unittest

from local_server.runtime.ports import port_available


class PortTests(unittest.TestCase):
    """Port checks should report an already bound local listener."""

    def test_occupied_port(self) -> None:
        """A bound local listener reserves its TCP port from a second binder."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
            self.assertFalse(port_available(port))

    def test_invalid_port(self) -> None:
        """Port zero and invalid types are rejected."""
        for invalid in (0, -1, 65536, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                port_available(invalid)


if __name__ == "__main__":
    unittest.main()
