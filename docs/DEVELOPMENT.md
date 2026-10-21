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
`test_runtime.py` adds transaction, rollback, port, lease, path and source-routing
checks. `test_windows_job.py` uses disposable Python children to verify atomic job
containment, descendant termination after an owner crash and lock recovery.
Windows-only tests skip on other platforms.

For the explicit real-binary smoke test on Windows x64 (PowerShell):

```powershell
$env:PYTHONPATH = 'src'
python tools/smoke_nginx_php.py --acquire
```

`--acquire` permits downloading only the two selected SHA-256-pinned Nginx/PHP
catalog entries. Omit it to use already available packages. All test projects and
relocated copies live in disposable `.test-tmp/` directories. No Apache or MySQL
binary is run. The host's VC++ runtime must already satisfy the package checks.
If sandbox temp permissions fail, set `TMP` and `TEMP` to a writable test directory.

For MySQL, acquire the exact reviewed Community 8.4.13 package in Components,
then run `python tools/smoke_mysql.py` with `PYTHONPATH=src` on Windows x64.
This additionally initializes disposable databases, uses temporary Windows vault
entries, checks SQL/PHP/HTTP, isolation, relocation, shutdown and failure paths,
then removes its own data/credentials. It never opens `test_server` or an existing
user datadir. Opt into the small real-vault unit test with
`LOCAL_SERVER_TEST_VAULT=1`; otherwise that test skips. Other tests mock OS secrets.

## Developer state isolation

Normal state paths are described in [Architecture](ARCHITECTURE.md). For a test
workspace, pass `--data-dir` or set the absolute `LOCAL_SERVER_HOME`
environment variable for state. Packages always remain beside the application,
including in an editable source checkout. `packages/` and `.local-server/` are
ignored; never add archives, binaries or review scratch files to Git.

The main window edits profiles and previews Nginx config. Components manages
reviewed portable archives with progress, cancellation/retry and guarded removal.
It starts explicitly selected Nginx/PHP and optional MySQL packages on Windows x64,
including secure per-project initialization and database/user creation. PHP switching
still requires stop/start. See
[runtime verification](RUNTIME.md) for completed and pending checks. Initial tests
ran locally; GitHub Actions runs the cross-platform matrix on pushes and PRs.

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
