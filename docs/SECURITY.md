# Security policy and local threat model

## Security boundary

Local Server is a user-level developer tool, **not a secure sandbox**.
PHP web applications execute with the current user's permissions, so an
untrusted application can read/write files that the user can access.
Do not expose these development servers to the public internet.

## Already enforced by the scaffold

- Generated Nginx sites listen only on IPv4 loopback `127.0.0.1`.
- A missing FastCGI worker causes PHP and PHTML requests to be denied.
- Only absolute project root paths and validated runtime parameters are stored.
- Managed process executables must be inside the private component root.
- Processes are spawned with an argument list and `shell=False`.
- Download catalog packages require HTTPS plus SHA-256 pins.
- HTTPS-to-HTTP redirects are rejected by the downloader.
- Archives are extracted into fresh staging directories; traversal, links,
  special files, duplicate targets and decompression size excess are rejected.
- Installed binaries are placed under the per-user component directory.
- No sudo/Administrator flow, system services, hosts-file changes or
  PATH modifications are performed.
- Project settings are atomically replaced to avoid partially written JSON.
- On POSIX, application data directories are owner-only by default.

## Security controls still required

- Source provenance and detached signature validation where supported.
- Trusted binary/package signing review on each supported OS.
- Stronger archive Windows path handling (reserved device names) and fuzzing.
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

The initial bundled package manifest is empty by design; no automatic runtime
downloads occur in the GUI.

## Reporting security issues

Avoid publishing exploits, secrets or sensitive local path information in
public issue threads. Contact the maintainer privately before opening a public
vulnerability report. A dedicated private reporting mechanism will be set up
when the project is ready.
