"""Reserved PHP FastCGI adapter boundary for simultaneous PHP versions.

The Windows php-cgi path, private configuration and diagnostics are implemented;
the macOS php-fpm boundary and hot switching remain future work.
"""

from __future__ import annotations

import os
import socket
import struct
from pathlib import Path
from .processes import ManagedProcess, ProcessSupervisor


def _ini_path(path: Path) -> str:
    value = path.resolve().as_posix()
    if any(char in value for char in '\"\r\n\x00'):
        raise ValueError("Path contains unsupported PHP configuration characters")
    # PHP interpolates ${ENV} in INI values.
    if "$" in value:
        raise ValueError("PHP paths cannot contain environment substitutions")
    return '"' + value + '"'


def render_php_ini(config_dir: Path, package_dir: Path) -> str:
    """Isolate CGI settings, errors, sessions and temporary uploads."""
    return (
        "[PHP]\ncgi.force_redirect=0\ncgi.fix_pathinfo=0\nfastcgi.impersonate=0\n"
        "expose_php=0\ndisplay_errors=0\nlog_errors=1\n"
        f"error_log={_ini_path(config_dir / 'php-error.log')}\n"
        f"extension_dir={_ini_path(package_dir / 'ext')}\n"
        f"sys_temp_dir={_ini_path(config_dir / 'php-temp')}\n"
        f"upload_tmp_dir={_ini_path(config_dir / 'php-temp')}\n"
        f"session.save_path={_ini_path(config_dir / 'sessions')}\n"
        "date.timezone=UTC\n"
    )


def php_environment() -> dict[str, str]:
    """Prevent inherited PHP ini/CGI overrides without modifying global PATH."""
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith(("PHP", "FCGI", "CGI", "REDIRECT_"))
           and key.upper() != "PHPRC"}
    env.update(PHP_INI_SCAN_DIR="", PHP_FCGI_MAX_REQUESTS="0")
    return env


def _record(kind: int, content: bytes) -> bytes:
    return struct.pack("!BBHHBB", 1, kind, 1, len(content), 0, 0) + content


def _read_exact(stream: socket.socket, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.recv(size - len(data))
        if not chunk:
            raise OSError("FastCGI worker closed the diagnostic request")
        data.extend(chunk)
    return bytes(data)


def probe_fastcgi(port: int, script: Path, expected: bytes) -> None:
    """Execute only the private diagnostic script over loopback FastCGI."""
    params = {"SCRIPT_FILENAME": str(script.resolve()), "SCRIPT_NAME": "/probe.php",
              "REQUEST_METHOD": "GET", "REQUEST_URI": "/probe.php", "QUERY_STRING": "",
              "SERVER_PROTOCOL": "HTTP/1.1", "GATEWAY_INTERFACE": "CGI/1.1",
              "SERVER_NAME": "localhost", "SERVER_ADDR": "127.0.0.1",
              "REMOTE_ADDR": "127.0.0.1", "SERVER_PORT": "80", "CONTENT_LENGTH": "0"}
    encoded = bytearray()
    for name, value in params.items():
        key, data = name.encode(), value.encode("utf-8")
        for length in (len(key), len(data)):
            encoded.extend(bytes([length]) if length < 128 else struct.pack("!I", length | 0x80000000))
        encoded.extend(key + data)
    with socket.create_connection(("127.0.0.1", port), timeout=0.5) as stream:
        stream.sendall(_record(1, struct.pack("!HB5x", 1, 0)) +
                       _record(4, bytes(encoded)) + _record(4, b"") + _record(5, b""))
        output = bytearray()
        for _ in range(100):
            version, kind, request, length, padding, _ = struct.unpack("!BBHHBB", _read_exact(stream, 8))
            if version != 1 or request != 1:
                raise OSError("Invalid FastCGI diagnostic response")
            content = _read_exact(stream, length)
            _read_exact(stream, padding)
            if kind == 6:
                output.extend(content)
            if len(output) > 65536:
                raise OSError("Oversized FastCGI diagnostic response")
            if kind == 3:
                if len(content) != 8 or content[:5] != b"\0" * 5:
                    raise OSError("PHP diagnostic request failed")
                if output.partition(b"\r\n\r\n")[2] != expected:
                    raise OSError("PHP diagnostic output/version mismatch")
                return
        raise OSError("Incomplete FastCGI diagnostic response")


class PhpFastCgiAdapter:
    """Pending per-project php-cgi (Windows) / php-fpm (macOS) orchestration.

    Windows startup now uses the contained supervisor below; macOS is pending.
    """

    def start(self, supervisor: ProcessSupervisor, executable: Path, config_dir: Path,
              port: int, name: str) -> ManagedProcess:
        """Require a real verified binary and configured project-specific port."""
        if executable.name.lower() != "php-cgi.exe":
            raise ValueError("Windows FastCGI requires php-cgi.exe")
        if isinstance(port, bool) or not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ValueError("FastCGI requires an unprivileged loopback port")
        return supervisor.start(name, [str(executable), "-c", str(config_dir / "php.ini"),
                                      "-b", f"127.0.0.1:{port}"], cwd=config_dir,
                                env=php_environment(), contain=True)
