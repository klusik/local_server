# Package catalog format and review

The bundled manifest is located at:

`src/local_server/components/package_catalog.json`

```json
{
  "schema_version": 1,
  "packages": []
}
```

This is intentionally empty: no unverifiable CDN URL, checksum, upstream
binary, platform coverage or redistribution authorization is guessed.

Each curated record follows this shape (illustrative placeholders only,
**not a package that can be installed**):

```json
{
  "component": "nginx",
  "version": "REVIEWED_VERSION",
  "os": "windows",
  "arch": "x86_64",
  "url": "https://TRUSTED_DISTRIBUTOR/REVIEWED_ARCHIVE.zip",
  "sha256": "REPLACE_WITH_64_HEXADECIMAL_SHA256",
  "archive": "zip",
  "entrypoint": "nginx.exe",
  "strip_components": 1
}
```

Do not paste this placeholder into the active catalog. The validator
requires real version/digest syntax, and installation requires an exact match.

Fields:

| Field | Meaning |
| --- | --- |
| `component` | One of `nginx`, `apache`, `php`, `mysql` |
| `version` | Exact package version, never floating `latest` |
| `os` | `windows` or `macos` |
| `arch` | `x86_64` or `arm64` |
| `url` | Explicit HTTPS archive URL |
| `sha256` | Independent 64-digit hex SHA-256 checksum |
| `archive` | `zip` or `tar.gz` |
| `entrypoint` | Safe relative executable path after extraction |
| `strip_components` | Number of leading archive path segments to remove |

No OS installer, source tarball that still requires compilation, PKG, MSI,
DMG or external installer script can be handed directly to the archive-based
installer. Such packaging requires an explicitly implemented adapter.

Before shipping a record, verify the signed/hash-authenticated source, archive
layout, executable dependencies (VC runtimes, OpenSSL, ICU, etc.), platform
architecture, license notices, relocation support and a clean-machine smoke test.
Never put credentials, tokens or private download endpoints in this file.

Useful official entry points:

- Nginx: https://nginx.org/en/download.html
- Apache HTTP Server: https://httpd.apache.org/download.cgi
- PHP: https://www.php.net/downloads.php
- Windows PHP binaries: https://windows.php.net/download/
- MySQL Community: https://dev.mysql.com/downloads/mysql/

**Important caveat:** Apache's own project does not ship official Windows
binaries. Review any third-party Windows build separately. macOS binary support
and relocatability must be established rather than assumed. PHP-FPM supports
unix-like systems; Windows FastCGI integration uses a different executable.

An installer implementation and archive unit tests are present already.
A component download UI, official catalog entries, required dependencies,
installation progress and cancellation remain future work.
