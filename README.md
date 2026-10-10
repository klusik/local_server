# Local Server

Cross-platform desktop manager for isolated local web development environments.

> **Status: bootstrap / initial scaffold.** The application is being built in stages. The initial desktop UI manages project profiles and can preview an Nginx configuration. Automated component downloads, starting Apache/Nginx/PHP/MySQL and zero-downtime PHP switching are **not** implemented yet.

## Goals

- Python 3.11+ and Tkinter for Windows and macOS.
- Per-project document roots, web server selection, PHP versions and localhost ports.
- Private, side-by-side component installations within the user's application data directory.
- Verified downloads from approved upstream sources, without machine-wide installers.
- Process supervision, generated configs, diagnostics, logging and version switching.
- Localhost-only defaults. No elevated privileges or system service registration.

## Get started

```console
python -m pip install -e .
python -m local_server
```

On macOS, install a Python distribution with working Tk support. Component runtimes are not bundled.

## Documentation

See [Architecture](docs/ARCHITECTURE.md), [Development](docs/DEVELOPMENT.md), [Security](docs/SECURITY.md), and [Roadmap](docs/ROADMAP.md).

## Development status

This repository starts as a deliberately honest foundation, not as a fully operational web-server distribution. The component catalog is empty until platform-specific, checksum-verified packages are curated. GitHub issues and Projects will be planned separately.
