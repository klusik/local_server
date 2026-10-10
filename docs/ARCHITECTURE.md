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
│   ├── paths.py        Per-user data and binary directories
│   ├── platform.py     Windows/macOS + CPU normalization
│   └── store.py        Versioned, atomic JSON persistence
├── services/
│   └── projects.py     Project profile lifecycle
├── components/
│   ├── catalog.py      Reviewed package records and SHA-256 pins
│   ├── installer.py    HTTPS download, verify, stage, activate
│   └── archive.py      Safe ZIP and tar.gz extraction
├── runtime/
│   ├── nginx.py        Foreground localhost-only config renderer
│   ├── processes.py    Tracked local child process supervisor
│   ├── ports.py        Non-reserving port diagnostic
│   ├── apache.py       Explicit future adapter boundary
│   ├── php.py          Explicit future adapter boundary
│   └── mysql.py        Explicit future adapter boundary
└── ui/
    ├── main_window.py  Project overview and component status
    └── dialogs.py      Modal profile editor
```

All persistent state is under the per-user application home:

| Platform | Default root |
| --- | --- |
| Windows | `%LOCALAPPDATA%\LocalServer` |
| macOS | `~/Library/Application Support/LocalServer` |
| Other OS (developer-only) | `~/.local/share/local-server` |

`LOCAL_SERVER_HOME` or `--data-dir` can override the state root explicitly.
The layout consists of `projects.json`, `downloads/`, `components/`, `logs/`
and `generated/<project-uuid>/`. Component installations use
`components/<name>/<version>/<os>-<arch>/`, never `Program Files`,
`/usr/local` or other system paths.

## Project profile example

```json
{
  "schema_version": 1,
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

This sample uses a macOS directory. Windows stores an absolute Windows path.
Configurations are machine-local, not portable exports.

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

1. Reject unsupported platform/catalog records.
2. Stream-download into private temporary storage with bounded size.
3. Verify the full archive against the pinned SHA-256.
4. Preflight all archive entries, rejecting traversal and links.
5. Extract only regular files to an empty private staging directory.
6. Ensure the expected executable exists, then rename the staging directory
   into the side-by-side component location.
7. Clean up temporary archives and partial installations on failure.

The initial bundled catalog is deliberately empty, so no unreviewed version
is offered for download. The installer library is functional and covered by
network-free unit tests; the component acquisition UI and automatic integration
are future milestones.

## Process ownership and crash recovery

`ProcessSupervisor` tracks direct foreground children started from the private
components directory, refuses shell execution, and writes stdout/stderr logs to
the application home. This generic primitive is implemented, but no orchestration
of a full Apache/Nginx/PHP/MySQL stack is wired up yet.

Nginx configuration rendering uses `daemon off;` to permit later direct
process tracking. PHP-FPM and MySQL need their own correct foreground modes.
After a GUI crash or OS reboot, orphan detection and recovery will be required;
these safeguards are not implemented and no background daemon is installed.

## Explicit non-goals of the initial scaffold

- No network download on first GUI launch.
- No unprompted installation of Apache, PHP, Nginx or MySQL.
- No system-wide PATH changes, privileged ports, launch agents, services or
  register/unregister operations in the OS.
- No automatic first-run database creation, default root credentials, or unsafe
  `--initialize-insecure` database initialisation.
- No claim of running PHP, PHP version hot-switching, or a fully operational stack.

See [Roadmap](ROADMAP.md) for the proposed execution sequence.
