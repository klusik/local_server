# Platform and component compatibility

Acquisition targets **Windows 10/11 x64**. Archives and PE data were inspected
without running binaries. Locally available means extracted with a receipt, not
runtime-functional. Python 3.11+ with Tk is still required; this feature does not
produce a frozen self-contained application.

| Component | Reviewed acquisition | Requirements / limits |
| --- | --- | --- |
| Nginx | 1.31.7 mainline, 1.30.6 stable; upstream ZIP | x86 via WoW64 on x64; Windows beta |
| Apache | 2.4.69-261002 VS18; Apache Lounge ZIP | Third-party ASF-source build; VC++ x64 >=14.51.36247.0; vendor config assumes `C:/Apache24` |
| PHP | 8.5.11, 8.4.26, 8.3.35; official NTS x64 ZIP | CGI/FastCGI, no FPM or TS/mod_php; VC++ x64 >=14.44.35211.0 enforced conservatively |
| MySQL | Community 8.4.13 LTS; Oracle ZIP | VC++ x64 >=14.44.35211.0; per-project database/accounts and lifecycle tested with PHP 8.4.26/Nginx 1.30.6 |
| macOS Intel / ARM64 | No downloads offered | Relocatable archive/dependency/signing review needed |
| Windows ARM64 | No downloads offered | No implicit x64/x86 emulation assumption |

Visual C++ checks read the installed x64 registry record/version and required
system DLL presence. Nginx checks WoW64 DLL presence. These do not prove every
optional module or extension can load. No DLL or package executable is loaded
for the checks. No redistributable, PATH, registry, service or system config is
installed/changed.

App-local dependency acquisition and deployment is prepared: reviewed ZIP bundles
can supply pinned MSVC DLLs directly beside each server executable. No real DLL
bundle has been approved yet, so the current records still check the host runtime.
This remaining curation task is required for one-click acquisition on a clean
Windows host without a previously installed VC++ runtime. Users need no SDK.

Move the whole folder on a compatible OS/CPU; dependencies must still exist on
the destination. External roots and explicit state overrides may need reassignment.
Windows archives do not become macOS binaries when copied.

Vendor templates are retained, including Apache's default absolute ServerRoot.
Nginx uses generated configuration with current paths on every start, including
separate temp directories required by its Windows build. Vendor Apache config is
not activated. Generated previews are not authoritative stored config.
MySQL requires the exact package that initialized its datadir; upgrades,
downgrades and migrations are refused. Windows credentials stay bound to the
original OS account/computer; see [MySQL portability](MYSQL.md).

[Artifact evidence and licenses](PACKAGE_REVIEW.md). Local Server ships no binaries.
Retain all notices and comply with the relevant licenses before redistributing a
folder containing downloaded packages. Nginx 1.30.6 + PHP 8.4.26 have passed actual
Windows x64 acquisition/start/restart/relocation/failure smoke tests on a host with
VC++ already installed. Other catalog combinations and clean Windows remain
unverified; see [runtime evidence](RUNTIME.md). MySQL-enabled projects load mysqli
and PDO MySQL from their selected PHP package; general extension management and framework setup remain
future work. macOS/ARM64 runtime startup is rejected explicitly.
