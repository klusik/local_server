# Local Server

Cross-platform desktop manager for isolated local web development environments.

> **Status: Windows x64 Nginx + PHP + optional MySQL implemented and smoke-tested.**
> Components provides explicit downloads, SHA-256 verification, safe extraction,
> cancellation/retry and removal. The reviewed catalog targets Windows x64.
> Projects can start, stop and restart explicitly selected local Nginx/PHP packages.
> Each project has its own MySQL instance/data/accounts and a database/user manager.
> Apache and live PHP switching remain unimplemented. Clean Windows without
> a system VC++ runtime remains unsupported until an app-local DLL bundle is approved.

## Goals

- Python 3.14+ and Tkinter for Windows and macOS.
- Per-project document roots, web server selection, PHP versions and localhost ports.
- Portable, side-by-side archives in `packages/` beside the application.
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

The desktop workspace includes project search, web-server filtering, a selected
profile summary and local URL copying. Use Ctrl+F to search, Ctrl+N to add a
profile and F5 to reload profiles. New profiles suggest a port not already used
by a saved profile; this does not check operating-system port availability.
Download Nginx and PHP in Components, then select their exact local packages in
the project editor and use Start. A running state requires an executed PHP probe;
Open website and Logs become available in the project actions. Stop before editing
the running profile. Nothing starts automatically when opening Local Server.
See [runtime behavior and verification](docs/RUNTIME.md).

For MySQL, download the reviewed Community ZIP, enable MySQL in Edit project,
select its exact local package/port and Start. Running requires authenticated SQL
and an HTTP/PHP SQL query. The **DB** action creates project databases and users,
with each account limited to one database. Connection passwords are revealed only
on request; configure your application yourself. No website files are changed.
See [MySQL storage, isolation and portability](docs/MYSQL.md).

See [Architecture](docs/ARCHITECTURE.md), [Development](docs/DEVELOPMENT.md), [Security](docs/SECURITY.md), and [Roadmap](docs/ROADMAP.md).

## Portable storage

From sources, the repository folder is the application root, independent of the
working directory. A future frozen build uses the executable's folder (on macOS,
the folder containing the `.app`, not its temporary extraction directory).

```text
LocalServer/
  packages/<component>/<version>/<os>-<arch>/<variant>/
  packages/.staging/                  temporary downloads/extraction/removal
  .local-server/projects.json        profile state
  .local-server/generated/           generated config, recreated for current paths
  .local-server/logs/
  .local-server/data/<project-uuid>/   private MySQL data and identity (no passwords)
```

State priority: `--data-dir` > absolute `LOCAL_SERVER_HOME` >
`<application>/.local-server`. Packages always stay in `<application>/packages`.
There is no automatic fallback to per-user or system directories. Use a writable
folder; read-only USB drives or protected application locations report an error.
Local binaries, archives, temporary files and state are ignored by Git.

Move the **whole folder**, including hidden `.local-server`. Document roots inside
it are stored relatively. External roots retain explicit absolute paths; missing
roots offer **Choose document root…** in Projects. A different external directory
at the old path cannot be recognized automatically. An explicit external state
override must be moved/reassigned separately.

Portability concerns location, not operating systems. Windows archives do not work
on macOS or ARM64. Apache/PHP/MySQL require a separately available Visual C++ x64
runtime; its version and DLL presence are checked read-only before download.
Nginx is an official **32-bit** Windows beta, explicitly offered on x64 via WoW64.
No system dependency is installed by Local Server.

The pipeline also supports reviewed **app-local MSVC DLL bundles**: a referenced
bundle is downloaded automatically, verified per archive and per DLL, and copied
beside the server executable with its license notices. The end user needs no SDK
or manual DLL selection. No real DLL bundle has been curated yet, so the seven
current entries still require the host runtime. No system installer is substituted.

In **Components**, choose a component/version and use Download. The table separates
downloading, verifying, extracting, locally available and error states. `×` cancels;
Retry starts a fresh transfer. `ⓘ` shows source/license/requirements/error detail.
Remove deletes one binary version and refuses versions requested by project
profiles or reserved by runtimes in any instance sharing the package folder. It keeps projects and
database data. Local availability does **not** certify a working runtime.

## Development status

See [reviewed artifacts and hashes](docs/PACKAGE_REVIEW.md),
[catalog policy](docs/PACKAGE_CATALOG.md) and [compatibility](docs/COMPATIBILITY.md).
The repository ships metadata, not third-party binaries. Signature verification,
clean-machine runtime smoke tests, Apache startup and frozen app packaging
remain future work. Existing per-user state is not silently imported; migration
is described in [Architecture](docs/ARCHITECTURE.md).
