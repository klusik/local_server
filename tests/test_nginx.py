"""Localhost-only generated Nginx config tests."""

from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from local_server.core.models import ProjectProfile
from local_server.runtime.nginx import render_nginx_config


class NginxConfigTests(unittest.TestCase):
    """Generated web-server configuration must be isolated by default."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = ProjectProfile.create("One", self.root, http_port=8083)

    def test_localhost_and_no_php_leak(self) -> None:
        """Without a FastCGI worker, PHP source must not be publicly served."""
        config = render_nginx_config(self.profile, self.root)
        self.assertIn("listen 127.0.0.1:8083;", config)
        self.assertIn("daemon off;", config)
        self.assertIn("return 404;", config)
        self.assertIn("server_tokens off;", config)

    def test_fastcgi_upstream(self) -> None:
        """A configured PHP port produces an explicit loopback FastCGI target."""
        config = render_nginx_config(
            self.profile, self.root, php_upstream_port=9000
        )
        self.assertIn("fastcgi_pass 127.0.0.1:9000;", config)
        self.assertIn("fastcgi_param SCRIPT_FILENAME", config)

    def test_reject_shared_http_fastcgi_port(self) -> None:
        """Web and PHP workers cannot bind the same TCP port."""
        with self.assertRaises(ValueError):
            render_nginx_config(self.profile, self.root, php_upstream_port=8083)

    def test_reject_wrong_backend(self) -> None:
        """Apache profiles cannot silently receive Nginx configuration."""
        with self.assertRaises(ValueError):
            render_nginx_config(
                replace(self.profile, server="apache"), self.root
            )


if __name__ == "__main__":
    unittest.main()
