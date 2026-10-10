# Platform and component compatibility

This is an architectural support matrix, not a claim that binaries have
already been downloaded or tested. The starting package catalog is empty.

| Runtime concern | Windows x86-64 | macOS Intel | macOS Apple Silicon |
| --- | --- | --- | --- |
| Python 3.11+ Tk UI | Designed | Designed | Designed |
| Project profile manager | Implemented | Implemented | Implemented |
| Package installer engine | Implemented, awaiting catalog | Implemented, awaiting catalog | Implemented, awaiting catalog |
| Nginx | Upstream Windows builds are available; integration pending | Reviewed build required | Reviewed build required |
| Apache HTTPD | Reviewed third-party/build-from-source distribution required | Reviewed build required | Reviewed build required |
| PHP | Windows ZIP and php-cgi planned | Relocatable php-fpm build required | Relocatable php-fpm build required |
| MySQL Community | Private ZIP archive planned | Private tar archive planned | Private tar archive planned |
| Automated stack start | Not implemented | Not implemented | Not implemented |
| Hot PHP switching | Not implemented | Not implemented | Not implemented |

Windows ARM64 requires explicit artifact verification or a validated compatibility
strategy. No implicit x86-to-ARM binary assumption is built into the catalog.

## Why per-platform providers matter

- [Official Nginx on Windows documentation](https://nginx.org/en/docs/windows.html)
  describes a Windows beta intended primarily for development and testing.
- [Apache Windows documentation](https://httpd.apache.org/docs/current/platform/windows.html)
  explains that Apache itself publishes source rather than official Windows
  binary releases.
- [PHP FPM documentation](https://www.php.net/manual/en/install.fpm.php)
  documents Unix-style FastCGI process management and its security constraints.
- [Official PHP installation guide](https://www.php.net/manual/en/install.php)
  separates Unix/macOS and Windows binary installation workflows.
- [Official MySQL downloads](https://dev.mysql.com/downloads/mysql/)
  include platform-specific archive distributions.

One machine may have several distinct PHP versions installed at once, but
serving them concurrently requires separate FastCGI processes, distinct
loopback ports or sockets, and project-specific configurations. A successful
profile edit alone is not a live runtime switch.

## Licensing and redistribution

Apache, Nginx, PHP and MySQL have distinct licenses and binary distribution
rules. Review each approved source and bundled dependency before packaging.
The initial project repository contains none of their binaries.
