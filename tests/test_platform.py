"""Platform label normalization tests."""

import unittest
from unittest.mock import patch

from local_server.core.platform import PlatformTarget


class PlatformTests(unittest.TestCase):
    """Architecture labels should agree with curated manifest entries."""

    def test_windows_x86_64(self) -> None:
        """Windows AMD64 maps to one stable catalog identifier."""
        with (
            patch("local_server.core.platform.sys.platform", "win32"),
            patch("local_server.core.platform.platform.machine", return_value="AMD64"),
        ):
            self.assertEqual(
                PlatformTarget.detect(), PlatformTarget("windows", "x86_64")
            )

    def test_macos_arm64(self) -> None:
        """Apple Silicon maps to macos/arm64."""
        with (
            patch("local_server.core.platform.sys.platform", "darwin"),
            patch("local_server.core.platform.platform.machine", return_value="arm64"),
        ):
            self.assertEqual(PlatformTarget.detect(), PlatformTarget("macos", "arm64"))

    def test_linux_not_yet_supported(self) -> None:
        """Linux is intentionally outside the current runtime support matrix."""
        with patch("local_server.core.platform.sys.platform", "linux"):
            with self.assertRaises(NotImplementedError):
                PlatformTarget.detect()


if __name__ == "__main__":
    unittest.main()
