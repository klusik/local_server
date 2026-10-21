# Artifact review — 2026-10-21

All seven ZIPs were downloaded over certificate-validated HTTPS and inspected as
data: SHA-256, exact length, entrypoint, PE machine field, layout and license-file
presence. No application, test suite, downloaded executable or dependency was run.
Direct PE import tables were also read without loading code: Nginx imports only
Windows system libraries; Apache/PHP/MySQL import the MSVC runtime as documented,
plus their bundled runtime libraries. This is not a recursive optional-module audit.
No runtime was activated. This is static acquisition evidence, not clean-machine
runtime or relocation certification.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| httpd-2.4.69-261002-Win64-VS18.zip | 14495717 | `ca272e0b75abad78b1e4029a0753b20ff2232d2d857e8eebeea5d469c5776977` |
| nginx-1.31.7.zip | 2795610 | `7c717ccf861f8925be64431d06d57634512a5014bcc8d149f279928f5e8151bf` |
| nginx-1.30.6.zip | 2773293 | `c6ee35edb0a861063323f709192ae50d1eefaf2ea7d00678bd2b22d8542dc61e` |
| php-8.5.11-nts-Win32-vs17-x64.zip | 36048897 | `0ea96e0d2b9b737a6036f05cf4e95c49313faa6d0f27bd97edb2742503f0c043` |
| php-8.4.26-nts-Win32-vs17-x64.zip | 35103568 | `da68394f9193b7f6b89d0c76861a4034ae10efee7fd55a7255d8118c2acf70d7` |
| php-8.3.35-nts-Win32-vs16-x64.zip | 33873909 | `25a8e2ac9ff30f1d768d1447c09a600617fa6e6082729f6e95f008b59c91fe45` |
| mysql-8.4.13-winx64.zip | 281154912 | `e9cd98b1d23f122987b1afca26ad942efec5891481103d48ae3cde237fa3ea54` |

## Apache

The [ASF Windows guide](https://httpd.apache.org/docs/2.4/platform/windows.html)
explains the external binary-distributor boundary.
[Apache Lounge](https://www.apachelounge.com/download/) supplies the VS18 x64 ZIP;
its [published SHA-256](https://www.apachelounge.com/download/VS18/binaries/httpd-2.4.69-261002-Win64-VS18.zip.txt)
matches the measured bytes. This is not an ASF-published Windows binary.
Its [distribution statement](https://www.apachelounge.com/contact.html) references
Apache License 2.0 and disclaims ASF affiliation.

Root documentation and `Apache24/` coexist; **strip count is zero**, retaining
all files. Entry: `Apache24/bin/httpd.exe`, PE `0x8664`. `Apache24/LICENSE.txt` and
`NOTICE.txt` remain intact. The ReadMe and page require VC++ 2017–2026 x64; the
reviewed page requests 14.51.36247, enforced as >=14.51.36247.0. APR, OpenSSL,
zlib and Brotli are included; arbitrary external modules are outside the review.
Vendor config defaults to `C:/Apache24`; it is retained but not activated.
The future adapter must generate configuration using the actual package location.

The distributor required an HTTPS Referer in this environment. The downloader
sends the source page as Referer and rejects HTTP redirects. No insecure fallback
is implemented. Detached PGP signatures were not validated.

## Nginx

Both archives are linked from the [official download page](https://nginx.org/en/download.html).
SHA-256 was measured from those HTTPS bytes; nginx does not publish SHA-256 with
these links. Detached `.asc` signatures exist but were not validated. This is an
HTTPS-derived bootstrap pin, not independently authenticated signing evidence.

Both executable PE fields are `0x014c` (**x86**), explicitly offered on x64 as
`win32-wow64`. One `nginx-<version>/` root is stripped. `docs/LICENSE`,
`docs/OpenSSL.LICENSE` and `docs/zlib.LICENSE` remain. Nginx uses BSD-2-Clause;
dependencies keep their own notices. The [Windows guide](https://nginx.org/en/docs/windows.html)
describes relative-prefix operation and beta/performance limits. No separate VC++
redistributable requirement is advertised for these archives; WoW64 is checked.

## PHP

[Official Windows release metadata](https://downloads.php.net/~windows/releases/releases.json)
publishes the selected filenames and SHA-256; downloaded bytes match. Entry:
`php-cgi.exe` at archive root, PE `0x8664`. `license.txt`, `README.md` and
`readme-redist-bins.txt` remain with dependency attribution. These 8.3–8.5 releases
use PHP-3.01 and Zend-2.0; see the [version-specific license](https://www.php.net/license/3_01.txt).

The [Windows manual](https://www.php.net/manual/en/install.windows.manual.php)
distinguishes TS for an Apache module from NTS for FastCGI and requires the matching
Visual C runtime. Only NTS CGI/FastCGI is selected. The enforced x64 runtime floor
14.44.35211.0 is conservative policy, not a claim about each build's exact minimum.
[Microsoft's guidance](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)
requires a matching architecture and runtime at least as recent as the toolset.
No Windows FPM, mod_php, extensions or working FastCGI integration is claimed.

## MySQL

The [Oracle 8.4 LTS listing](https://dev.mysql.com/downloads/mysql/8.4.html) links
the standard Windows x64 ZIP, not MSI or debug/test ZIP. Its link resolves to
`https://cdn.mysql.com//Downloads/MySQL-8.4/mysql-8.4.13-winx64.zip`.
Measured MD5 matches the listing: `7b94489d5524dea9b27097068bea25a8`.
SHA-256 above was measured from those official HTTPS bytes and is the application
integrity gate. MD5 is an additional listing cross-check, not strong authenticity
evidence. Oracle's detached signature was not verified.

Strip `mysql-8.4.13-winx64/`; entry `bin/mysqld.exe`, PE `0x8664`.
Unpacked size: 1,263,141,970 bytes. `LICENSE` and `README` remain.
[Windows requirements](https://dev.mysql.com/doc/refman/8.4/en/windows-installation.html)
specify VC++ 2019. Policy conservatively enforces x64 >=14.44.35211.0. Bundled
libraries stay in their original locations. The [Oracle licensing statement](https://www.mysql.com/about/legal/licensing/oem/)
describes GPLv2 with additional permissions and separate commercial licensing.
This does not grant blanket permission to redistribute a proprietary combined
product. Only extraction is implemented: no Configurator, initialization,
credentials, startup or service registration.

## Dependency deployment boundary

Microsoft's [redistribution documentation](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files)
supports `/install /quiet /norestart` for the redistributable, but central deployment
requires elevation/UAC and changes the host. This feature does not execute such an
installer. [App-local deployment](https://learn.microsoft.com/en-us/cpp/windows/walkthrough-deploying-a-visual-cpp-application-to-an-application-local-folder?view=msvc-170)
can avoid elevation by placing licensed runtime DLLs beside the executable.
It requires an approved source, license rights, exact DLL/version/architecture
review, updates and clean-host validation. No app-local MSVC DLL bundle has been
curated here; the current acquisition guard checks the host runtime instead.
The installer/schema/cache/receipt path for automatic app-local DLL acquisition
is prepared, with unit tests authored but not run. Enabling a real source remains
a deliberate catalog curation step rather than an end-user configuration task.

## Pending validation

Unit tests were added but intentionally not run. UI interaction, complete
application acquisition, clean-Windows dependency failures, movement between
drives/USB filesystems, signature checking and runtime/module loading remain
unexecuted. No macOS or ARM64 archive is approved. Static pins require review
before release; the catalog is not a continuing security-update service.

## MSVC app-local review — 2026-10-21

Follow-up research checked Microsoft's current
[redistribution documentation](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170),
[VS2022 distributable list](https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution)
and [app-local walkthrough](https://learn.microsoft.com/en-us/cpp/windows/walkthrough-deploying-a-visual-cpp-application-to-an-application-local-folder?view=msvc-170).
They document local deployment beside executables, with redistribution limited to
licensed Visual Studio users under the relevant product terms. The VS2022 list
covers its `VC/redist` tree and excludes debug runtime folders. A downloadable EXE
alone does not establish this project's distribution rights.

The candidate scope for PHP is release MSVC v14 **x64**, including
`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`, at least the catalog's
14.44.35211.0 policy floor. This identifies review targets, not an approved concrete
DLL set/version. Reviewed x86 Nginx does not require that x64 bundle.

No project-specific Visual Studio license entitlement or distributable ZIP with
stable origin, exact DLL versions/hashes and preserved license notices was verified.
Therefore `runtime_bundles` stays empty. No guessed URL/hash, system DLL copy,
third-party repack or redistributable installer was substituted. Approval still
needs documented entitlement/terms, reviewed immutable archive bytes, per-DLL
integrity/architecture review and clean-Windows loader validation. End users must
not need an SDK or manual DLL selection.

The preceding pending-validation section describes the original acquisition work.
Subsequent unit and actual Nginx/PHP acquisition/runtime/relocation checks are
recorded in [RUNTIME.md](RUNTIME.md); they used a pre-existing host VC++ runtime.
