# Development

## Requirements

- Python 3.11 or newer
- Tkinter support in the chosen Python distribution
- Windows 10/11 or macOS for managed component runtimes
- Git for development, but no git command is required by the application

Runtime Python dependencies: **none outside the standard library**.
Build/editable-install tooling uses setuptools.

## Setup

```console
git clone https://github.com/klusik/local_server.git
cd local_server

python -m venv .venv
```

Activate the environment:

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS:

```sh
source .venv/bin/activate
```

Install and run:

```console
python -m pip install -e .
python -m local_server
```

Or use the command-line entry point:

```console
local-server --version
local-server --data-dir /absolute/path/to/localserver-test
```

The Windows equivalent of `--data-dir` should be an absolute path on that host.
On macOS, use a Python with properly supported Tcl/Tk. Tk is intentionally
imported lazily so headless unit tests never require a graphical display.

## Tests

```console
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

GitHub Actions tests Python 3.11 and 3.13 on Ubuntu, Windows and macOS.
Ubuntu is a headless *test runner*, not a promised web-runtime target.

The current tests cover profile validation, atomic persistence, CRUD,
catalog/platform validation, ZIP and tar.gz safety, verified installer behavior,
rendered Nginx configs, process ownership and loopback port diagnostics.
Full HTTP/PHP/MySQL integration tests must be added with real vetted binaries.

## Developer state isolation

Normal state paths are described in [Architecture](ARCHITECTURE.md). For a test
workspace, pass `--data-dir` or set the absolute `LOCAL_SERVER_HOME`
environment variable for state. Packages always remain beside the application,
including in an editable source checkout. `packages/` and `.local-server/` are
ignored; never add archives, binaries or review scratch files to Git.

The main window edits profiles and previews Nginx config. Components manages
reviewed portable archives with progress, cancellation/retry and guarded removal.
It does not start servers, initialize MySQL or switch running PHP versions.
See [artifact review](PACKAGE_REVIEW.md) for what was inspected and what remains
untested. The tests added on `feature/portable-packages` were intentionally not run
during implementation at the user's request; CI has not been triggered by a push.

## Design constraints

- Keep domain models and backend services independent from Tkinter widgets.
- Never block Tk's event loop with network, extraction or child-process waits.
- Put installation/progress workers behind a cancellable queue bridge before
  surfacing downloads in the UI. Only the main thread may update Tk widgets.
- Keep downloaded/runtime files out of Git and out of project source roots.
- Never run generic shell scripts from untrusted archive metadata.
- Validate paths, versions, digests, network addresses and ports at boundaries.
- Preserve docstrings when refactoring.
- Prefer GitHub CI tests; local tests are a development fallback.
- Work on a feature branch after initialization; do not push directly to
  protected release branches without a planned review/release process.
- Do not create GitHub issues or a Project board until that work is requested.

## Creating a reviewed catalog entry

See [Package catalog](PACKAGE_CATALOG.md). Official vendor websites are
starting points for discovery; every downloadable artifact must have its
actual, independent checksum and platform dependencies verified.

## Licensing

The project's open-source/proprietary license has **not been chosen yet**.
Do not redistribute third-party binaries until their licenses, attribution,
and required notices have been reviewed.
