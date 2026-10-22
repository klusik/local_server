# Security policy and local threat model

## Security boundary

Local Server is a user-level developer tool, **not a secure sandbox**.
PHP web applications execute with the current user's permissions, so an
untrusted application can read/write files that the user can access.
Do not expose these development servers to the public internet.

MySQL uses separate instances/datadirs, generated administrator and limited
application credentials, and Windows Credential Manager. Private bootstrap/client
IO is ACL-protected and removed after use; SQL/passwords never enter argv or project
JSON. X/named-pipe/shared-memory/admin listeners are disabled or absent. Exact
data/server identity forbids silent migration/replacement. New managed accounts
get only one database. These SQL boundaries share a Windows account; see
[MYSQL.md](MYSQL.md) for portability, ACL and disk-erasure limits.

## Already enforced by the scaffold

- Generated Nginx sites listen only on IPv4 loopback `127.0.0.1`.
- A missing FastCGI worker causes PHP and PHTML requests to be denied.
- External project roots remain explicit; internal roots are stored relatively
  with traversal/escape checks, and resolved from the current application root.
- Managed process executables must be inside the private component root.
- Processes are spawned with an argument list and `shell=False`.
- Download catalog packages require HTTPS plus SHA-256 pins.
- HTTPS-to-HTTP redirects are rejected by the downloader.
- Archives are extracted into fresh staging directories; traversal, links,
  special files, duplicate targets and decompression size excess are rejected.
- Acquired binaries stay under the portable `packages/` directory; all state
  defaults beside the application. Explicit state overrides remain available.
- Windows device aliases (including superscript digits), ADS, controls, trailing
  dot/space aliases, case collisions and reparse points are rejected.
- Bounded download size (2 GiB), unpacked size (4 GiB), member count (20,000),
  exact per-member sizes and reviewed archive length limit resource consumption.
- A receipt is committed only after digest verification and complete extraction.
  Expected Windows executable architecture is checked without loading it.
- OS-released package locks serialize mutations and interrupted-work cleanup.
- Optional app-local MSVC ZIP dependencies require archive and per-DLL SHA-256,
  exact architecture/version, approved names and license notices. DLLs are copied
  beside staged executables; conflicting vendor DLLs fail. No system DLL names,
  downloaded installers or scripts are accepted. The bundled runtime list is
  currently empty pending source/license review.
- Removal is confined to one receipt-backed binary tree; profiles, project sources
  and future database data are never removed by package management.
- No sudo/Administrator flow, system services, hosts-file changes or
  PATH modifications are performed.
- Project settings are atomically replaced to avoid partially written JSON.
- On POSIX, application data directories are owner-only by default.

## Security controls still required

- Source provenance and detached signature validation where supported.
- Trusted binary/package signing review on each supported OS.
- Archive/path fuzzing and adversarial filesystem race testing.
- Equivalent FastCGI lifecycle and dependency validation for future macOS support;
  Windows PHP-CGI configuration/lifecycle is implemented and loopback-only.
- Broader PHP-version/extension security testing beyond the verified 8.4.26 stack.
- Equivalent macOS MySQL lifecycle and Keychain support; Windows isolation,
  generated credentials and Credential Manager storage are implemented.
- Safe HTTPS certificate handling, enabled only with explicit user consent.
- Full-stack integration tests and runtime update vulnerability monitoring.

## Download integrity is not provenance

A correct SHA-256 protects against an artifact changing from the reviewed
hash. It does not itself establish that the artifact or its distributor is
trustworthy. Packages must be manually reviewed and sourced from trusted,
legally redistributable vendor/distribution channels.

The static catalog's review evidence is in [PACKAGE_REVIEW.md](PACKAGE_REVIEW.md).
PHP and Apache SHA-256 values match publisher metadata; Nginx/MySQL pins were
measured from official HTTPS archives (MySQL also matched the vendor's MD5 listing).
Detached signatures were not verified. TLS plus measured SHA-256 bootstrap pins
do not independently prove a publisher's signing identity. Signature validation
is not claimed. Explicit Nginx/PHP startup has separate runtime health probes;
only explicit user download actions contact an upstream download server.

VC++ prerequisites are read from registry/version metadata and DLL presence; no
registry changes or DLL/package execution occur. Missing prerequisites block
acquisition with an explanation. These checks do not replace runtime loader tests.

Portable media must be writable and trusted. Write failure never triggers system
installation or a fallback directory. File locks and atomic rename depend on the
destination filesystem; unmount/power failure and copying an active folder can
still corrupt data. Close the app before copying. A user able to modify the app
folder can also modify packages/receipts; this is not a tamper-proof sandbox.
The Windows Nginx/PHP controller regenerates configs, holds cross-instance usage
leases, and creates child trees atomically in kill-on-close jobs. Shutdown waits
for owned descendants before releasing reservations. Stale ownership files contain
no PID authority. No process is adopted or killed merely because of a name/port.

Startup binds exclusive loopback sockets for HTTP and FastCGI. They must be released
before `php-cgi`, Windows `nginx -t` and Nginx can bind; those executables do not
support inheriting the reserved sockets. Process polling plus random-token,
exact-version FastCGI/HTTP probes reject a failed handoff. This reduces the race
but does not provide an atomic socket transfer or resist a malicious local user.

PHP requests use FastCGI with `try_files`, explicit `SCRIPT_FILENAME`, empty
`HTTP_PROXY`, `cgi.fix_pathinfo=0`, and a private ini with additional ini scanning
disabled. Script-like suffixes and PATH_INFO fallbacks cannot become static source
responses; missing FastCGI yields an upstream error. Diagnostic scripts are created
only under private generated state, never in a user's project. State/packages may
not overlap a document root. These controls are not an application sandbox.

## CI integration boundary

Push CI is read-only BASIC validation. Manual Develop integrate executes the
workflow and checks owned by the explicitly selected branch; maintain/admin
permission is required for both initiating and re-running actors. Those actors
are trusted to review CI edits before dispatch. This is not a sandbox for an
untrusted feature workflow: a maintainer who can edit a workflow can also edit
its checks. Fork PR validation has no publication token or integration trigger.

Source selection and testing use read-only repository tokens; checkout does not
persist credentials. Selection requires exactly one non-merge source commit
directly above observed develop; multiple commits never enter full qualification.
Only the final publication job receives contents write,
after BASIC and every full-matrix job succeed for the pinned candidate. It
rechecks both remote heads and uses a normal fast-forward push, never a force
update, branch-protection bypass or unchecked generated merge. Branch rules are
enforced by GitHub and may reject publication. No runtime downloads, real server
smoke tests, credential-vault opt-in or system installation is added to CI.

## Windows distribution boundary

Release reads exact-SHA develop integration evidence without rerunning source
tests, pins main/develop/tooling before building, and requires a successful
PyInstaller one-file and Inno Setup 7 build plus offline bundle/install smoke checks
before main publication. Build runs read-only; only main/tag publication and draft
attachment receive contents write. The artifact manifest binds source, tooling,
version, integration attempt and both EXE hashes. Main must still match the
selected head and the merge tree must equal qualified develop.

Generated executables use `asInvoker`; the installer fixes `PrivilegesRequired=lowest`
without overrides and defaults to the current user's LocalAppData Programs folder.
It creates no service, system PATH entry or machine-wide component installation.
Uninstall retains user-created state and packages. Python/Tk are bundled; separate
web/database packages keep their documented host VC++ requirements. Artifacts are
unsigned: neither code signing nor clean-machine runtime verification is claimed.
Draft upload verifies GitHub's asset digests and never overwrites a conflicting
asset or automatically publishes a release. Partial draft uploads can be resumed
by rerunning the draft job; main/tag are not rolled back after a later API failure.

## Reporting security issues

Avoid publishing exploits, secrets or sensitive local path information in
public issue threads. Contact the maintainer privately before opening a public
vulnerability report. A dedicated private reporting mechanism will be set up
when the project is ready.
