# Implementation roadmap

This is the implementation plan; **do not infer issue or milestone numbers**.
GitHub issues, Project board and release milestones will be created later.

## Phase 0: Repository scaffold (current)

- [x] Python 3.11+ `src/` package layout and Tkinter entry point.
- [x] Portable state directory, explicit overrides and atomic JSON storage.
- [x] Create/edit/delete project profiles without touching project sources.
- [x] Project server, PHP version, HTTP port and optional MySQL flags.
- [x] Structured platform identification for Windows and macOS.
- [x] SHA-256-pinned package schema, safe archive extraction and installer API.
- [x] Foreground child-process supervisor and Nginx config renderer.
- [x] Headless unit tests and multiplatform GitHub Actions.
- [x] Security, architecture, development and compatibility documentation.
- [x] Explicit portable runtime archive downloads (static acquisition review).
- [ ] Runtime startup remains unavailable.

## Phase 1: Runtime availability and packages

- [x] Curate seven Windows x64 acquisition records, origins, license notices,
      HTTPS URLs, SHA-256 pins and a manual refresh policy; Nginx is x86/WoW64.
- [ ] Independently authenticate detached signatures; current Nginx/MySQL pins
      are derived from inspected official HTTPS bytes, not verified signatures.
- [ ] Decide whether to build macOS Apache/PHP and Windows Apache from source
      using reproducible CI artifacts; avoid untrusted binaries.
- [ ] Implement minimum macOS support requirements and preflight of binary
      dependencies, dynamic libraries, codesigning/notarization requirements.
- [x] Components download/version/removal UI, phase progress, cancel and retry.
- [x] Byte limits, fresh staging, receipts, locks and interrupted-work cleanup.
- [x] Portable defaults, relative internal roots and external-root reassignment.
- [ ] Free-space/quota prediction, range-resume and automated update notifications.
- [ ] Test real binaries on Windows x86-64, macOS Intel and macOS Apple Silicon.
      Windows ARM64 is conditional on verified binaries or validated emulation.
- [ ] Review licensed, version-pinned app-local VC++ DLL distribution so Windows
      archives can work on clean hosts without a system runtime installer. DLLs
      must be placed beside each executable as required by the Windows loader;
      keeping a redistributable installer in packages alone is insufficient.
- [x] Prepare automatic app-local ZIP acquisition, per-DLL hashes/PE validation,
      local deployment/notices, receipts and reuse without system installation.

## Phase 2: Nginx runtime

- [ ] Bind foreground Nginx instances to 127.0.0.1 only.
- [ ] Generate valid prefix, mime.types, log and pid configurations.
- [ ] Validate generated config using Nginx `-t` before starting/reloading.
- [ ] Add start/stop/restart to the UI and surface actual health checks.
- [ ] Report already occupied ports without killing unrelated processes.
- [ ] Recover/clean up stale processes after interrupted sessions.

## Phase 3: Side-by-side PHP versions

- [ ] Windows: approved PHP ZIP binaries and FastCGI `php-cgi.exe` lifecycle.
- [ ] macOS: approved relocatable PHP builds and `php-fpm` lifecycle.
- [ ] Isolate each project's PHP ini, extensions, sockets/ports and logs.
- [ ] Keep multiple PHP versions running for multiple projects simultaneously.
- [ ] Implement transactional live version switching with probe and rollback.
- [ ] Add PHP version diagnostics, extension management and config UI.
- [ ] Test compatibility with Apache and Nginx adapters separately.

## Phase 4: Apache backend

- [ ] Curate Windows build provenance and compatible runtime prerequisites.
- [ ] Curate macOS binaries or reproducible source-build process.
- [ ] Generate HTTPD configurations from approved modules and paths.
- [ ] Implement external FastCGI PHP integration, no system PHP takeover.
- [ ] Add config checks, lifecycle, logs and backend switch rollback.

## Phase 5: MySQL

- [x] Pin MySQL Community 8.4.13 Windows x64 ZIP for acquisition only.
- [ ] Create an isolated database directory on selected private volume.
- [ ] Securely initialize credentials, store secrets in OS keychain/credential
      manager, and bind to local-only socket or loopback.
- [ ] Implement start/stop/restart and health checks.
- [ ] Plan backups, recovery, major-version migrations and compatible data
      formats, without sharing writable data directories across versions.
- [ ] Add GUI for optional database attachment per project.

## Phase 6: Development experience

- [ ] Per-project dashboard with Start All/Stop All and clear process state.
- [ ] Access/error logs, port diagnostics and network conflict resolution.
- [ ] Virtual hosts such as `project.test` with DNS/hosts-file changes only
      after explicit consent and fallback to distinct localhost ports.
- [ ] Custom PHP settings and per-project environment variables.
- [ ] Self-contained config export/import with secrets excluded by default.
- [ ] Optional HTTPS using locally trusted certificates, opt-in trust install.

## Phase 7: Distribution and release process

- [ ] User-level Windows distributable and signed macOS application.
- [ ] Verify Tk bundling, architectures, updates and code signing.
- [ ] Component cache controls and fully reversible uninstall.
- [ ] CI unit/integration/security tests plus smoke tests on clean machines.
- [ ] Define release branch rules, semantic versioning and release artifacts.

## Acceptance criteria for a first practical release

A user can install Local Server in their own account, select an existing
project root, download a vetted Nginx+PHP+MySQL stack, open their app on
127.0.0.1 without changing system services, add a second project on another
PHP version, switch that version with rollback, and stop all children cleanly.
The application must report missing upstream packages honestly and must never
serve PHP source code if FastCGI is unavailable.
