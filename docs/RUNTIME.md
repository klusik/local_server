# Windows Nginx + PHP runtime with optional MySQL

Implemented on `feature/nginx-php-runtime`, based on `develop`. Downloaded binaries
are not tracked in Git. Nothing starts automatically when opening the desktop app.

## Workflow

1. Download Nginx and PHP NTS in Components.
2. Edit a project, choose its root/HTTP port and exact local package identities,
   including variants. Legacy profiles still load but require explicit selections.
3. Use Start. Running requires PHP execution through both direct FastCGI and HTTP,
   matching a random diagnostic token, exact PHP version and CGI SAPI.
4. Open the website or logs; Stop/Restart affect only this project's owned processes.
   Stop before editing/relinking/removing the profile. Restart includes downtime.

Apache remains a profile setting only. Optional Windows MySQL now has its own
[runtime and database/user manager](MYSQL.md). No FPM, mod_php, live version switching
or general extension manager is implemented. MySQL enables mysqli/PDO MySQL in the private
ini. Exact package identities are portable; executable
absolute paths are never saved. Missing selections/packages/roots need reassignment.

## Lifecycle and data boundaries

- Start accepts only receipt-backed, selected Windows x64 packages. PHP must be NTS
  x64 `php-cgi.exe`; prerequisites are checked again before execution.
- HTTP and FastCGI use distinct unprivileged `127.0.0.1` ports. HTTP conflicts fail
  with a request to choose another port, without killing foreign processes.
- Configs/includes, logs, PHP sessions/uploads and temporary diagnostic scripts stay
  outside document roots and are regenerated from current paths. State/packages may
  not overlap document roots. User project files are never modified or deleted.
- Exclusive startup socket reservations must be released before PHP/Nginx bind.
  Windows `nginx -t` also opens sockets, so its reservation is released for validation
  and checked again afterwards. These binaries do not accept inherited sockets.
  Child polling and exact random-token health responses detect a failed handoff;
  the release/bind interval is not an atomic transfer or a hostile-local-user defense.
- Failed startup stops newly owned children before releasing leases. Stop waits for
  the entire owned job tree. If stopping fails, ownership remains protected for retry.
- `PROC_THREAD_ATTRIBUTE_JOB_LIST` assigns children atomically to non-inheritable
  kill-on-close Windows jobs before child code executes. Nginx workers inherit the
  job. Missing containment blocks startup. A crashed owner releases kernel handles,
  terminating descendants without trusting stale PIDs or scanning/killing by name.
- Byte locks under the package root protect live package use across app instances,
  including separate state overrides. A per-project UUID lock prevents duplicate
  startup. Released stale lock files can be reclaimed without PID-based recovery.
- The worker monitors process exits and HTTP listener availability. It does not
  repeatedly execute PHP probes that could interrupt long-running user requests.
  Liveness is distinct from application/framework health.
- Missing FastCGI yields an upstream error, never PHP source. Script-like suffixes,
  backups and PATH_INFO cannot become static source responses. Windows may normalize
  trailing dots/spaces into genuine PHP execution; that path still fails closed if
  the worker is unavailable.
- Close cancels pending starts and waits for cleanup workers. No installer, service,
  elevated privilege, global PATH or registry change is involved. Close before copying
  the portable folder. Stop uses bounded forced job termination, not request draining.

Local PHP retains the user's permissions. This is not an application sandbox or a
defense against users who can modify application storage.

## Executed verification — 2026-10-21

Tests ran locally on Windows x64 with Python 3.14 and an existing VC++ runtime.
The existing 74 tests were run first. Sandbox temp permissions were separated from
intermittent Windows directory rename failures, now handled with bounded retry.
The final suite passed all **100 tests**. New tests cover transactions, rollback,
ports, selections, paths, leases and crashes. Python compilation and `git diff
--check` also passed. Shared button artwork now includes a restrained glossy upper
highlight and lower shadow; Tk measured normal/primary/icon button heights at 39 px.

`tools/smoke_nginx_php.py` acquired only reviewed Nginx 1.30.6 and PHP 8.4.26 NTS x64
through the installer, checking pinned archive SHA-256, size and PE architecture.
Both before and after moving the complete disposable app/state/packages/site tree
into another path with spaces, these checks passed:

- `nginx -t`, direct FastCGI and HTTP/PHP exact-version probes.
- PHP execution and static serving; Start/Stop/Restart and two parallel projects.
- Duplicate startup refusal and removal refusal through a second manager/state root.
- HTTP 502 without source after stopping PHP while Nginx remained alive; backups,
  PHTML, PATH_INFO and trailing-dot/space requests also did not reveal source.
- Monitor rollback, released leases and unchanged temporary project files, with
  no diagnostic PHP written into the project.

Separate real Windows kernel tests killed a disposable Python owner and verified
termination of its child/grandchild plus lock recovery. No Apache/MySQL binary,
configurator or database initialization was run. The desktop opened with a temporary
profile and its controls were visually inspected. The user subsequently opened
the current app and approved the compact/glossy design. A full interactive runtime
lifecycle remains unverified. Initial checks ran locally before publication;
GitHub Actions discovers the new tests on push. Windows-only tests skip elsewhere.

## Remaining limits

Clean Windows without a VC++ runtime is **not certified or ready**. No concrete,
licensed app-local DLL ZIP has been approved; see the
[MSVC review](PACKAGE_REVIEW.md#msvc-app-local-review--2026-10-21).

Other catalog combinations, optional PHP extensions/frameworks, non-ASCII/very-long
paths, removable-media filesystems, macOS/ARM64 runtimes and frozen packaging remain
unverified. Logs and the runtime library cache have no automatic retention/pruning.

## MySQL verification — 2026-10-21

Implemented on `feature/mysql-runtime` from `origin/develop` at `59f72b7`.
The baseline CI run [39584765607](https://github.com/klusik/local_server/actions/runs/39584765607)
was successful. Before changes, all 100 existing tests passed locally after
setting writable sandbox temp paths. The final Windows x64 suite passed all
**128 tests**, including the explicit real Credential Manager roundtrip and
Windows kernel containment tests. Python compilation and `git diff --check` passed.
No tests used `test_server` or a user datadir.

`tools/smoke_mysql.py` used receipt-backed Nginx 1.30.6, PHP 8.4.26 NTS and MySQL
Community 8.4.13 copied into a fresh disposable application. The MySQL archive
passed the existing installer's pinned SHA-256/size/PE checks; upstream timeouts
required a longer diagnostic download timeout, without changing TLS/integrity.
The following actual checks passed, including before/after moving the entire
disposable application to a different path with spaces:

- Secure initialization, SQL identity/version checks, HTTP/mysqli SQL and real
  mysqli/PDO extension loading; a newly created account also connected through
  PHP before its authentication cache was populated by the official client.
- Database/user creation, denied access and hidden schemas outside the account's
  grant; separate project server UUIDs/data/credentials and refusal of another
  project's credentials on the second instance.
- Preserved table contents through restart, graceful stop/start, relocation and
  unexpected owned database/PHP exits; complete stack rollback and released leases.
- Actual cancellation of first initialization, SQL port collision, duplicate
  startup, cross-manager package removal refusal, incompatible data-version
  refusal and missing vault credentials without replacing/deleting existing data.
- Live server variables confirmed IPv4 loopback, disabled pipe/shared memory,
  no admin address and disabled persisted globals; no active X Plugin.
- No generated password in ordinary configs/logs/profiles/owned argv, and no PHP
  source response after stopping PHP while Nginx remained up.

The smoke test gracefully closes its owned processes and removes its own data and
vault entries. A separate disposable UI window launched successfully, but automated
visual/interaction verification did not complete because app-access approval timed
out. Its empty test database was subsequently shut down and cleaned independently.
The real gallery workload, full interactive manager workflow, clean Windows and
cross-machine vault restoration remain unverified. See [MYSQL.md](MYSQL.md).
