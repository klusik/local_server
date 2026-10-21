# Security policy and local threat model

## Security boundary

Local Server is a user-level developer tool, **not a secure sandbox**.
PHP web applications execute with the current user's permissions, so an
untrusted application can read/write files that the user can access.
Do not expose these development servers to the public internet.

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
- Project-specific FastCGI configuration and lifecycle; never expose FPM or
  CGI workers on a non-loopback interface.
- Explicit PHP-CGI security parameters and version-specific testing.
- Run MySQL with private data directory and strong generated credentials,
  never shared default root credentials.
- Store database secrets in Windows Credential Manager or macOS Keychain,
  not in project JSON or plain-text logs.
- Detect/reap orphaned children after crashes and failed start sequences.
- Reserve ports during startup or validate atomically to reduce check/use race.
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
do not independently prove a publisher's signing identity. No signature validation
or runtime health is claimed. Only explicit user download actions contact a server.

VC++ prerequisites are read from registry/version metadata and DLL presence; no
registry changes or DLL/package execution occur. Missing prerequisites block
acquisition with an explanation. These checks do not replace runtime loader tests.

Portable media must be writable and trusted. Write failure never triggers system
installation or a fallback directory. File locks and atomic rename depend on the
destination filesystem; unmount/power failure and copying an active folder can
still corrupt data. Close the app before copying. A user able to modify the app
folder can also modify packages/receipts; this is not a tamper-proof sandbox.
Future adapters must regenerate configs after moving and integrate runtime usage
leases with cross-process ownership before enabling execution.

## Reporting security issues

Avoid publishing exploits, secrets or sensitive local path information in
public issue threads. Contact the maintainer privately before opening a public
vulnerability report. A dedicated private reporting mechanism will be set up
when the project is ready.
