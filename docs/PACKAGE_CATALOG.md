# Package catalog

`src/local_server/components/package_catalog.json` is a static reviewed manifest,
never automatically refreshed at launch. Seven initial artifacts and their exact
evidence are recorded in [PACKAGE_REVIEW.md](PACKAGE_REVIEW.md).

Schema-1 records specify component, exact version, target OS/architecture, binary
architecture, variant, HTTPS URL, pinned SHA-256, archive type, relative entrypoint,
strip count, source, checksum evidence, license, requirements, notes, byte size and
enforced Visual C++ floor. Identity is `component/version/os-arch/variant`.
Case-only duplicates, Windows device aliases and unknown record fields are rejected.
`arch` describes the host; `binary_arch` exposes Nginx x86 on x64/WoW64 explicitly.

Only ZIP and tar.gz are supported. No MSI, PKG, DMG, source compilation, installers
or downloaded scripts. Windows PHP must be `nts-cgi`: TS/mod_php and FPM cannot
be selected through this acquisition workflow. Future Apache/Nginx adapters will
use separate PHP CGI/FastCGI workers. Extensions must match version, architecture,
NTS and compiler ABI; extension management is not implemented.

Only exact host matches are offered. No macOS or ARM64 downloads are approved.
Receipts keep older/off-platform local packages discoverable and removable.

## App-local dependencies

The optional top-level `runtime_bundles` list contains reviewed Windows x64 ZIP
records. Each defines `id`, four-part MSVC `version`, `os`, `arch`, `url`, archive
`sha256`, exact `size_bytes`, `source`, `license`, `license_source`, `files` and
`notices`. Each file maps a canonical archive-relative `source` to a permitted
MSVC DLL `name` and its own `sha256`. Core `vcruntime140.dll`, `vcruntime140_1.dll`
and `msvcp140.dll` are required. Windows system DLLs and debug runtime names cannot
be supplied. No placeholder URL/hash is active.

A server's `runtime_bundle` references the exact ID. Missing bundles, wrong
architectures or versions below the server's VC++ floor fail catalog loading.
The installer acquires/deploys DLLs automatically, preserving notices and refusing
vendor DLL conflicts. Host VC++ checks are skipped only for a reviewed app-local
dependency; OS checks still apply.

The list is currently empty. DLL redistribution approval is not inferred from the
existence of a system redistributable EXE. A maintainer must review a legally
distributable DLL ZIP and its notices before enabling a reference.
The [follow-up MSVC review](PACKAGE_REVIEW.md#msvc-app-local-review--2026-10-21)
documents the specific unresolved source/license evidence; no placeholder was added.

## Review and refresh policy

Review official release/download pages, licenses, dependencies and advisories.
Review Apache's Windows distributor separately: ASF does not ship Windows binaries.
Never infer filenames, hashes, architectures or relocation support from another
version. Follow actual published archive links over certificate-validated HTTPS.

Inspect bytes without executing code: full SHA-256, publisher digest/signature
evidence, exact size, entrypoint, PE machine type, layout and license/dependency
notices. Preserve upstream notices. Record whether SHA-256 is publisher-provided
or measured and whether a signature was actually checked. MD5 can cross-check a
vendor listing but is never the application integrity gate.

Update the manifest and review evidence together before each release and promptly
after relevant security advisories. Do not silently repin changed bytes under an
existing identity. Investigate and review a new explicit build instead.

Static archive review establishes acquisition eligibility only. Clean-machine
runtime and relocation tests, loader diagnostics, signing/notarization and full
integration checks remain necessary before advertising runnable support.
