# Architecture

## Scope

Local Server is a **local development environment manager**, not a production
hosting platform, a container runtime, or an operating-system service manager.

Supported targets: Windows x86-64, Windows ARM64 where verified packages exist,
macOS x86-64 and macOS ARM64 (Apple Silicon). A combination is *supported only
after its exact component archive and required dependencies are validated*.

The user chooses external project source directories. Local Server never owns
those sources and deleting a project profile never deletes the web application.

## Layer boundaries

```text
src/local_server/
├── app.py              CLI composition root and Tk startup
├── core/
│   ├── models.py       Validated per-site runtime selection
│   ├── paths.py        Portable application root and explicit state overrides
│   ├── platform.py     Windows/macOS + CPU normalization
│   └── store.py        Versioned, atomic JSON persistence
├── services/
│   └── projects.py     Project profile lifecycle
├── components/
│   ├── catalog.py      Reviewed package records and SHA-256 pins
│   ├── installer.py    HTTPS download, verify, stage, activate
│   ├── archive.py      Safe ZIP and tar.gz extraction
│   ├── manager.py      Receipt inventory, removal guards and worker events
│   ├── locking.py      Cross-process package mutation / recovery lock
│   ├── runtime_bundle.py Strict app-local MSVC DLL catalog schema
│   ├── app_local.py    Verified runtime cache and local DLL deployment
│   └── prerequisites.py Read-only OS/VC++ checks
├── runtime/
│   ├── nginx.py        Foreground localhost-only config renderer
│   ├── processes.py    Tracked local child process supervisor
│   ├── ports.py        Loopback diagnostics and startup socket reservations
│   ├── controller.py   Nginx/PHP transactions and Tk-independent monitoring worker
│   ├── ownership.py    OS-released project/package usage locks
│   ├── windows_job.py  Atomic Windows child/job containment, kill on owner exit
│   ├── apache.py       Explicit future adapter boundary
│   ├── php.py          Private PHP ini/environment and FastCGI diagnostics
│   ├── mysql.py        Per-project MySQL initialization, SQL, accounts and shutdown
│   └── secrets.py      Windows Credential Manager and private directory ACLs
└── ui/
    ├── main_window.py  Project overview and component status
    └── dialogs.py      Modal profile editor
```

The application root is derived from code/executable location, never cwd. Source
checkouts use the repository root. Frozen builds use `sys.executable`'s directory;
macOS `.app` builds use the folder containing the bundle. Temporary bundle
extraction locations are not storage roots. For non-editable Python installations,
an absolute launcher path determines the application folder, falling back to the
Python executable directory. Such a directory must be writable; no silent fallback.

Packages always use `<application>/packages/<name>/<version>/<os>-<arch>/<variant>/`.
Receipts inside each completed package store metadata with relative entrypoints
and `runtime_verified: false`; no absolute package path is persisted. Archives and
private extraction/removal staging use `packages/.staging/` on the same filesystem.
An OS-released `.manager.lock` serializes acquisition, removal and crash recovery
across application instances. Recovery removes only owned staging prefixes while
holding that lock. No background download occurs on launch.

Optional `runtime_bundle` references resolve through the catalog's reviewed
`runtime_bundles` list. A matching ZIP is acquired in the same worker transaction,
verified against its archive hash/size, safely extracted, and cached under
`packages/.runtime-cache/<bundle-id>/`. Each selected DLL must also match its own
SHA-256, permitted MSVC filename and x64 PE machine type. Copies go directly beside
the staged executable, never into system directories or PATH. Vendor DLL conflicts
fail rather than being overwritten. License notices accompany the local DLLs.
The final server receipt contains the bundle metadata; inventory rechecks deployed
DLL hashes. Cache corruption is discarded safely and reviewed bytes fetched again.
Cancellation cleans partial dependency downloads; a complete reusable cache may
remain. Removing a server removes its DLL copies and keeps the shared cache.
No cache-pruning UI is implemented yet.

This mechanism is implemented, but `runtime_bundles` is intentionally empty until
actual DLL source, hashes and redistribution rights are reviewed. Current server
records therefore still enforce the host VC++ runtime. Adding a reviewed bundle
and package reference requires no end-user SDK, compilation or DLL selection.

State defaults to `<application>/.local-server/`, containing `projects.json`,
`generated/<project-uuid>/`, `logs/` and `data/<project-uuid>/` (isolated MySQL
datadir/identity). Priority: CLI `--data-dir` > absolute `LOCAL_SERVER_HOME` > portable
default. An explicit state override does not move packages. An external override
must be copied/reassigned separately when moving the application. Write probes
fail with an actionable error; no system installation or per-user fallback.

Previous `%LOCALAPPDATA%/LocalServer`, macOS Application Support or developer XDG
state is not automatically scanned, migrated or removed. To migrate deliberately,
close the application and copy the old `projects.json` into the new `.local-server`
folder, or select the old root via `--data-dir`. Schema 1 is read and upgraded to
schema 2 on the next save. Legacy `components/` trees lack acquisition receipts and
are not silently trusted; download reviewed packages again. Keep existing source
and database data separately; no destructive migration is performed.

## Project profile example

```json
{
  "schema_version": 2,
  "projects": [
    {
      "id": "a49d1177-4169-4d86-bf41-faf55c4bb175",
      "name": "My PHP gallery",
      "document_root": "/Users/example/Projects/gallery",
      "server": "nginx",
      "php_version": "8.4",
      "http_port": 8080,
      "mysql_enabled": true
    }
  ]
}
```

This sample uses an external macOS directory. External absolute paths, including
foreign-OS paths, remain explicit and loadable for reassignment. Internal document
roots are serialized as `{"portable": "sites/gallery"}` relative to the application
root and resolved on load with escape protection. Missing roots are detected off
the Tk thread; Projects offers explicit reassignment with a native folder picker.
A different directory that happens to exist at an old external path cannot be
identified automatically. Generated server configurations must be regenerated for
the current location; static previews are rendered afresh, not persisted as truth.

An HTTP port is currently unique across saved profiles. Simultaneous Nginx
instances must use separate ports, while upstream PHP ports will also be
distinct. A later virtual-host feature can remove the one-HTTP-port-per-site
constraint while retaining isolation.

## Planned HTTP and PHP process arrangement

```text
Browser
   │ http://127.0.0.1:<project-http-port>
   ▼
Managed Apache or Nginx instance
   ├── static files: selected project document root
   └── .php FastCGI
         │ 127.0.0.1:<private-php-port>
         ▼
       PHP worker bound to selected version
         └── project's php.ini, extension set, logs

Optional MySQL daemon
   └── private data directory, unique port/socket, managed credentials
```

The PHP process model must distinguish Windows `php-cgi` from macOS `php-fpm`.
An Apache adapter must select a verified Apache HTTPD distribution and
appropriate modules. Changing the desired PHP version in the current profile
editor **does not start, stop, or reload any process**.

Eventually PHP switching should be transactional:

1. Validate compatibility, installation and extensions of the requested PHP.
2. Allocate/check a separate loopback FastCGI port.
3. Start and health-check the new worker without disrupting the old one.
4. Render and validate a new server configuration.
5. Reload the web server, confirm a PHP-version probe is served by the new worker.
6. Retire the old worker after in-flight requests settle.
7. On failure, restore the previous configuration and worker.

Zero-downtime switching is a design target, not an implemented guarantee.
Each project's PHP selection is independent of the others.

## Install lifecycle

A curated catalog entry specifies an exact component, version, OS, architecture,
HTTPS archive URL, SHA-256 digest, archive layout and expected executable.
`ComponentInstaller` currently supports ZIP and tar.gz archives, not MSI, PKG,
DMG, arbitrary installer scripts or source compilation.

1. Reject unsupported platform/catalog records and unmet host prerequisites.
2. Stream-download into private temporary storage with bounded size.
3. Verify the full archive against the pinned SHA-256.
4. Preflight all archive entries, rejecting traversal and links.
5. Extract only regular files to an empty private staging directory.
6. Ensure the expected executable exists and its PE machine matches the reviewed
   Windows record; write the relative receipt, then rename the staging directory
   into the side-by-side package location.
7. Clean up temporary archives and partial installations on failure.

The bundled catalog has seven statically inspected Windows x64 acquisition
records; Nginx is explicitly x86/WoW64. No macOS/ARM64 downloads are offered.
See [review evidence](PACKAGE_REVIEW.md) and [runtime verification](RUNTIME.md).
Network-free tests and a real Windows Nginx/PHP smoke test have now been run.

Components uses a Tk-independent worker and throttled immutable events; Tk polls
a queue on the main thread. Downloading, verifying and extracting are separate
phases with byte progress and cooperative cancellation. HTTPS operations have a
10-second socket timeout, not an immediate cancellation guarantee. Retry starts a
new transfer without range-resume. Closing keeps Tk alive until cleanup finishes.
Profile disk IO and folder validation also run behind a main-thread queue bridge.

Inventory is discovered from committed receipts, including older catalog versions.
Removal detaches one package into staging before deletion and refuses links and
junctions. Project roots and `data/` are outside the removal boundary. Guards
conservatively block components requested by saved profiles; PHP matches exact
versions or the requested minor line for legacy profiles. New optional
`nginx_package` and `php_package` fields store exact portable package identities,
including OS, host architecture and variant. PHP's version must agree with its
selected identity. Schema 1/2 profiles without selections still load; startup asks
for explicit local choices. No automatic version fallback is performed.

Reference-counted usage leases hold OS byte locks in `packages/.usage/` and are
acquired under the package mutation lock. Removal checks all live instance locks;
dead lock files can be reclaimed without trusting recorded PIDs. A per-project lock
under `packages/.runtime-projects/` prevents duplicate startup even with different
state overrides. Unmanaged external use is outside this ownership boundary.

## Process ownership and crash recovery

`ProcessSupervisor` tracks direct foreground children started from the private
components directory, refuses shell execution, and writes stdout/stderr logs to
the application home. `RuntimeController` composes selected local Nginx and PHP NTS
packages on Windows x64. Each process is atomically created inside a non-inheritable
Windows Job Object using `PROC_THREAD_ATTRIBUTE_JOB_LIST`; job closure terminates
the owned tree, including Nginx workers. Startup fails if containment is unavailable.

Nginx uses `daemon off;`; PHP uses `php-cgi.exe -c <private ini> -b 127.0.0.1:<port>`.
No FPM or mod_php is involved. A worker serializes lifecycle operations and monitors
process exit and HTTP listener presence. Initial running state requires a direct
FastCGI probe and an HTTP/PHP probe with a random token and exact PHP version/SAPI.
No periodic PHP requests compete with long-running user requests. Rollback stops
newly owned processes before releasing package/project locks. Close cancels pending
startup and waits for cleanup off Tk's event loop. A GUI crash releases kernel job
handles and usage locks; no PID-based recovery kill or global process scan is used.

Configs, includes, logs, sessions and diagnostic scripts live outside document
roots and are regenerated from current paths on each start. See [RUNTIME.md](RUNTIME.md)
for the port handoff interval, security boundary and actual validation evidence.

## Explicit non-goals of the initial scaffold

- No network download on first GUI launch.
- No unprompted installation of Apache, PHP, Nginx or MySQL.
- No system-wide PATH changes, privileged ports, launch agents, services or
  register/unregister operations in the OS.
- No database creation before explicit MySQL-enabled project Start, default root credentials, or unsafe
  `--initialize-insecure` database initialisation.
- No PHP version hot-switching, Apache lifecycle or clean-Windows guarantee.

Optional MySQL starts before PHP/Nginx, using a separate OS-released data lease
in addition to the project/package leases. Authenticated official-client queries
check the exact version, server UUID and database; HTTP/mysqli verifies the full
stack. Its initial datadir is staged, securely initialized and bootstrapped before
promotion. Credentials live in Windows Credential Manager. The worker also handles
non-destructive database/user creation and explicit password reveal. See
[MySQL architecture and limitations](MYSQL.md).

See [Roadmap](ROADMAP.md) for the proposed execution sequence.
