"""Reserved PHP FastCGI adapter boundary for simultaneous PHP versions.

The Windows php-cgi path, private configuration and diagnostics are implemented;
the macOS php-fpm boundary and hot switching remain future work.
"""

import os
import socket
import struct
from pathlib import Path

from .processes import ManagedProcess, ProcessSupervisor


def _ini_path(path: Path) -> str:
    """Escape a private filesystem path for the PHP ini file.

    Args:
        path (Path): Filesystem path validated or escaped before use.

    Returns:
        str: Escaped private path suitable for a PHP ini value.
    """
    value = path.resolve().as_posix()
    if any(char in value for char in '"\r\n\x00'):
        raise ValueError("Path contains unsupported PHP configuration characters")
    # PHP interpolates ${ENV} in INI values.
    if "$" in value:
        raise ValueError("PHP paths cannot contain environment substitutions")
    return '"' + value + '"'


def render_php_ini(config_dir: Path, package_dir: Path, *, mysql: bool = False) -> str:
    """Isolate CGI settings, errors, sessions and temporary uploads.

    Args:
        config_dir (Path): Private directory for generated configuration files.
        package_dir (Path): Receipt-backed directory containing the selected package.
        mysql (bool): Project-scoped MySQL adapter under test.

    Returns:
        str: Private CGI ini content with isolated sessions, uploads and error logs.
    """
    return (
        "[PHP]\ncgi.force_redirect=0\ncgi.fix_pathinfo=0\nfastcgi.impersonate=0\n"
        "expose_php=0\ndisplay_errors=0\nlog_errors=1\n"
        f"error_log={_ini_path(config_dir / 'php-error.log')}\n"
        f"extension_dir={_ini_path(package_dir / 'ext')}\n"
        f"sys_temp_dir={_ini_path(config_dir / 'php-temp')}\n"
        f"upload_tmp_dir={_ini_path(config_dir / 'php-temp')}\n"
        f"session.save_path={_ini_path(config_dir / 'sessions')}\n"
        "date.timezone=UTC\n"
        + ("extension=mysqli\nextension=pdo_mysql\n" if mysql else "")
    )


def php_environment() -> dict[str, str]:
    """Prevent inherited PHP ini/CGI overrides without modifying global PATH.

    Returns:
        dict[str, str]: Child environment without inherited PHP ini and CGI overrides.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith(("PHP", "FCGI", "CGI", "REDIRECT_"))
        and key.upper() != "PHPRC"
    }
    env.update(PHP_INI_SCAN_DIR="", PHP_FCGI_MAX_REQUESTS="0")
    return env


def _record(kind: int, content: bytes) -> bytes:
    """Encode one FastCGI protocol record.

    Args:
        kind (int): FastCGI record type identifier.
        content (bytes): Serialized catalog content to validate and decode.

    Returns:
        bytes: Encoded FastCGI record header, payload and alignment padding.
    """
    return struct.pack("!BBHHBB", 1, kind, 1, len(content), 0, 0) + content


def _read_exact(stream: socket.socket, size: int) -> bytes:
    """Read the requested number of FastCGI response bytes or fail.

    Args:
        stream (socket.socket): Binary stream receiving the verified download.
        size (int): Number of bytes in this progress update.

    Returns:
        bytes: Exactly the requested bytes, or an exception if the peer closes early.
    """
    data = bytearray()
    while len(data) < size:
        chunk = stream.recv(size - len(data))
        if not chunk:
            raise OSError("FastCGI worker closed the diagnostic request")
        data.extend(chunk)
    return bytes(data)


def probe_fastcgi(port: int, script: Path, expected: bytes) -> None:
    """Execute only the private diagnostic script over loopback FastCGI.

    Args:
        port (int): Loopback TCP port; zero requests an ephemeral port where supported.
        script (Path): Private diagnostic script or literal SQL submitted to the owned
            client.
        expected (bytes): Exact bytes expected from the health probe.
    """
    params = {
        "SCRIPT_FILENAME": str(script.resolve()),
        "SCRIPT_NAME": "/probe.php",
        "REQUEST_METHOD": "GET",
        "REQUEST_URI": "/probe.php",
        "QUERY_STRING": "",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "GATEWAY_INTERFACE": "CGI/1.1",
        "SERVER_NAME": "localhost",
        "SERVER_ADDR": "127.0.0.1",
        "REMOTE_ADDR": "127.0.0.1",
        "SERVER_PORT": "80",
        "CONTENT_LENGTH": "0",
    }
    encoded = bytearray()
    for name, value in params.items():
        key, data = name.encode(), value.encode("utf-8")
        for length in (len(key), len(data)):
            encoded.extend(
                bytes([length])
                if length < 128
                else struct.pack("!I", length | 0x80000000)
            )
        encoded.extend(key + data)
    with socket.create_connection(("127.0.0.1", port), timeout=0.5) as stream:
        stream.sendall(
            _record(1, struct.pack("!HB5x", 1, 0))
            + _record(4, bytes(encoded))
            + _record(4, b"")
            + _record(5, b"")
        )
        output = bytearray()
        for _ in range(100):
            version, kind, request, length, padding, _ = struct.unpack(
                "!BBHHBB", _read_exact(stream, 8)
            )
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

    def start(
        self,
        supervisor: ProcessSupervisor,
        executable: Path,
        config_dir: Path,
        port: int,
        name: str,
    ) -> ManagedProcess:
        """Require a real verified binary and configured project-specific port.

        Args:
            supervisor (ProcessSupervisor): Owner of explicitly started child processes.
            executable (Path): Selected private server executable.
            config_dir (Path): Private directory for generated configuration files.
            port (int): Loopback TCP port; zero requests an ephemeral port where
                supported.
            name (str): Logical child-process name used for ownership and log lookup.

        Returns:
            ManagedProcess: Handle wrapper for the directly owned child process.
        """
        if executable.name.lower() != "php-cgi.exe":
            raise ValueError("Windows FastCGI requires php-cgi.exe")
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 1024 <= port <= 65535
        ):
            raise ValueError("FastCGI requires an unprivileged loopback port")
        return supervisor.start(
            name,
            [
                str(executable),
                "-c",
                str(config_dir / "php.ini"),
                "-b",
                f"127.0.0.1:{port}",
            ],
            cwd=config_dir,
            env=php_environment(),
            contain=True,
        )
