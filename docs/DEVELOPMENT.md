# Development

## Requirements

- Python 3.14 or newer
- Tkinter support in the chosen Python distribution
- Windows 10/11 or macOS for managed component runtimes
- Git for development, but no git command is required by the application

Runtime Python dependencies: **none outside the standard library**.
Build/editable-install tooling uses setuptools.

## Setup

```console
git clone https://github.com/klusik/local_server.git
cd local_server

python -m venv .venv
```

Activate the environment:

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS:

```sh
source .venv/bin/activate
```

Install development tooling and run:

```console
python -m pip install -e '.[dev]'
python -m local_server
```

Or use the command-line entry point:

```console
local-server --version
local-server --data-dir /absolute/path/to/localserver-test
```

The Windows equivalent of `--data-dir` should be an absolute path on that host.
On macOS, use a Python with properly supported Tcl/Tk. Tk is intentionally
imported lazily so headless unit tests never require a graphical display.

## Tests

```console
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m mypy
python tools/check_source.py
python tools/check_workflows.py
python -m compileall -q src tests
python -m unittest discover -s tests -v
```

GitHub Actions has two profiles:

- **BASIC** runs on every push: Ruff lint/format, strict mypy, source policy,
  MVC boundaries, and regression tests for those checks and Git integration.
  It uses one Ubuntu/Python 3.14 job with a three-minute ceiling, including setup.
  It does not run the application test suite or provision Windows/macOS runners.
  On develop PRs it additionally requires one squash commit before qualification;
  intermediate multi-commit pushes may still run ordinary BASIC checks.
- **FULL** runs after BASIC on pull requests, manual Python CI runs and manual
  Develop integrate runs. It runs all headless tests on Python 3.14
  across Ubuntu, Windows and macOS (three jobs).

Development tool versions are pinned in `.[dev]`; they are not runtime
dependencies. BASIC is intended to finish quickly, but runner provisioning and
package downloads can vary. Its timeout is a ceiling, not a promised duration.
Ubuntu is a headless *test runner*, not a promised web-runtime target.

### Source policy and MVC

All owned Python under `src/`, `tests/` and `tools/` must parse as Python 3.14,
have annotated function parameters and returns, and document each function's
purpose. Google-style `Args` entries include the parameter name, type and useful
explanation; `Returns`/`Yields` describe non-None results and their types.
Preserve existing documentation when extending it. Ruff enforces the Google
convention; `check_source.py` additionally requires typed argument descriptions,
private-function documentation and a hard 100-column maximum, including strings.
The formatter targets 88 columns; short lines do not need padding to 80 columns.
Use native Python 3.14 annotations. `from __future__ import annotations` is
forbidden; quote forward references when the referenced type is not yet defined
or is available only during type checking.

Strict mypy checks application and tool code, including variable assignments and
return values. Straightforward local variables may use inferred types; annotate
public fields, optional state and ambiguous containers explicitly. Tests also
require typed signatures, while deliberately invalid fixtures are exercised at
runtime. `Any` remains permitted at dynamic JSON, ctypes and Tk keyword-option
boundaries; it must not replace a known domain type. Windows ctypes APIs are
checked with Windows type stubs (`platform = "win32"`) on every host; the full
runtime test matrix separately covers platform-dependent behavior.

The current architecture maps MVC responsibilities onto existing modules:

- `core` contains validated models and persistence. It cannot import services,
  component management, runtime controllers or UI.
- `services`, `components` and `runtime` implement use cases, IO and process
  controllers. They cannot import Tkinter, UI or the application composition root.
- `ui` renders state and submits commands to workers. Direct network/process
  implementation imports and blocking file/service calls in callbacks fail BASIC.
  Recognized `_submit_io` / `_io.submit` closures may perform background IO.
- `app.py` composes the application and may lazily import Tkinter at startup.

These are static dependency and direct-call checks, including relative imports.
They do not prove thread safety or detect every dynamic import/call. Review must
still assess responsibilities, callback handoff and whether business rules have
leaked into a view. UI workers deliver results through queues; only the Tk thread
updates widgets.

### Manual develop integration

Open **Actions → Develop integrate → Run workflow**, select the source branch
in **Use workflow from**, then run. Equivalently, with GitHub CLI installed:

```console
gh workflow run develop-integration.yml --ref feature/my-change
```

The selected branch must contain **exactly one squashed, non-merge commit whose
sole parent is current `develop`**, including the workflow/helpers. Merely being
fast-forwardable is insufficient. Two or more feature commits, a merge tip,
an unchanged develop tip or an outdated base fail before the full matrix starts.
Both the initiating and re-running actor must have `maintain`
or `admin` repository permission. Any source branch name is supported except the
target `develop` itself; tags are rejected. The selected commit owns the workflow,
local reusable workflows and checks. Changes to CI on that branch take effect in
that run; they need not match or be copied to `main` first.

The run pins the source SHA and observed develop SHA, runs BASIC, then FULL on
that exact candidate. Only after both succeed does a fresh publication job get
`contents: write`. It rechecks source and target heads and performs a normal
fast-forward push of the tested SHA. It creates no merge/squash commit, does not
rebase and never forces a ref. A moved/deleted source, changed develop, divergent
history, unsquashed work, failed/skipped/cancelled job or rejected push leaves develop
unchanged by this run. Squash completed work above current develop and start a new
run after a rejected integration. Concurrent integrations share one queue;
source/target checks still protect against unrelated writers. A racing divergent
push is rejected by Git itself. A racing ancestor update can only be advanced to
the same fully tested candidate via Git's ordinary fast-forward rules.

GitHub requires **one initial registration of a workflow with
`workflow_dispatch` on the repository's default branch** before its manual button
or CLI dispatch is available. Install the workflow through the repository's
normal reviewed default-branch process once; this change does not bypass that
provider requirement or push directly to main. After registration, future CI
edits execute from the selected feature branch without another main update.
See [GitHub's manual workflow documentation](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).

Repository rules must allow the workflow's normal fast-forward to develop; this
implementation does not disable protection or add bypass tokens. A push using
`GITHUB_TOKEN` normally does not start another push workflow, so publication
depends on its own complete qualification rather than a subsequent push run.
The feature branch remains available after integration.

### Manual release

Open **Actions → Release → Run workflow**, choose the workflow implementation
in **Use workflow from** (including a `feature/` branch with CI edits), and enter
the required **version**, for example `v_0.2` or `v_0.2.1`. Only `v_X.Y` and
`v_X.Y.Z` are accepted: each component contains one or more ASCII digits.
No prefixes other than `v_`, suffixes, whitespace or fourth component are accepted.
The selected branch owns the release implementation; the released source is
always the current remote `develop`, irrespective of the selected workflow branch.

```console
gh workflow run release.yml --ref feature/my-ci-change -f version=v_0.2
```

Release does **not rerun tests**. It reads the successful manual Develop integrate
run for the exact develop SHA and requires successful BASIC, all three Python 3.14
platform jobs and publication in that completed attempt. Both the initiating and
re-running actor must have `maintain` or `admin` permission. Releases are serialized.
Use `v_X.Y` for regular releases and `v_X.Y.Z` for bugfixes and small changes.

Before building, selection pins main, develop, workflow SHA, version and the
integration run/attempt. A read-only Windows x64 job checks out that exact develop
separately from the selected workflow implementation. It builds with Python 3.14,
PyInstaller 6.22.3 (`--onefile --windowed`, including Python, Tk and catalog JSON)
and SHA-256-pinned Inno Setup 7.1.0. Build tools are installed only on the disposable
CI runner; the Inno compiler uses a user directory without requesting elevation.
Build/version metadata is embedded without editing the source checkout.

The build executes the actual EXE without Python/Tk developer environment paths,
initializes bundled Tk, reads the catalog and checks storage beside the EXE from
another working directory and a second location. It checks the generated EXE and
installer execution manifests for `asInvoker`, silently installs the exact EXE,
runs the installed bundle probe, then uninstalls and verifies retained user data.
These are packaging smoke checks, not another BASIC/FULL source qualification.
They run on a hosted Windows runner, not a pristine standard-user Windows machine.

The installer defaults to `%LOCALAPPDATA%\Programs\LocalServer`, allows the user
to select another writable directory, and never requests admin rights or offers an
all-users override. The installed application uses the same portable layout.
Uninstall removes application files and its current-user shortcut/registration,
while retaining downloaded packages, profiles and databases. Portable users copy
the entire application folder when moving state and packages. Server components
and their existing VC++ prerequisites remain separate from the bundled Python/Tk app.

Only after a successful build and upload, publication verifies the downloaded
manifest, both file hashes and the original pinned plan. It rejects source/target
drift rather than releasing a different develop head. It performs an ordinary **`--no-ff` merge** of
develop into main. It preserves all develop commits; it never squashes develop.
The merge tree must equal the already tested develop tree. A conflict or additional
main-only content must first be resolved and qualified on develop. It creates an
annotated version tag pointing to the resulting main commit, recording the develop
SHA and integration run/attempt. Main and the tag are pushed together using
`git push --atomic`, without force. Existing tags are never overwritten. Changed
branch heads, missing evidence or rejected updates fail the release; an atomic
push rejection leaves both release refs unchanged by this run. Normal repository
protections still apply, without a bypass token. A new run is required after failure.

After main/tag publication, a separate job creates a **draft** GitHub Release:

- `LocalServer-v_0.2-windows-x64-portable.exe`
- `LocalServer-v_0.2-windows-x64-installer.exe`

Every release uses its actual version in both names. The manifest binds both sizes
and SHA-256 hashes to the pinned source/tooling/evidence; it is retained with the
CI artifact for 30 days. The draft job verifies GitHub's uploaded asset hashes.
It never publishes the draft automatically or overwrites conflicting assets.
If draft creation/upload fails after merge, main/tag remain released; re-run the
failed **draft** job to resume missing uploads without rebuilding or merging again.
If the merge fails, no draft is created. Build failure never advances main or its tag.
Artifacts are currently unsigned. Documentation publishing remains future work.

As with integration,
GitHub needs one initial registration of `release.yml` on the default branch;
subsequent edits execute directly from the chosen feature branch. The default branch
must also contain the local reusable workflow definitions referenced by integration
so the native GitHub button can load the complete workflow graph.

The current tests cover profile validation, atomic persistence, CRUD,
catalog/platform validation, ZIP and tar.gz safety, verified installer behavior,
rendered Nginx configs, process ownership and loopback port diagnostics.
`test_runtime.py` adds transaction, rollback, port, lease, path and source-routing
checks. `test_windows_job.py` uses disposable Python children to verify atomic job
containment, descendant termination after an owner crash and lock recovery.
Windows-only tests skip on other platforms.

For the explicit real-binary smoke test on Windows x64 (PowerShell):

```powershell
$env:PYTHONPATH = 'src'
python tools/smoke_nginx_php.py --acquire
```

`--acquire` permits downloading only the two selected SHA-256-pinned Nginx/PHP
catalog entries. Omit it to use already available packages. All test projects and
relocated copies live in disposable `.test-tmp/` directories. No Apache or MySQL
binary is run. The host's VC++ runtime must already satisfy the package checks.
If sandbox temp permissions fail, set `TMP` and `TEMP` to a writable test directory.

For MySQL, acquire the exact reviewed Community 8.4.13 package in Components,
then run `python tools/smoke_mysql.py` with `PYTHONPATH=src` on Windows x64.
This additionally initializes disposable databases, uses temporary Windows vault
entries, checks SQL/PHP/HTTP, isolation, relocation, shutdown and failure paths,
then removes its own data/credentials. It never opens `test_server` or an existing
user datadir. Opt into the small real-vault unit test with
`LOCAL_SERVER_TEST_VAULT=1`; otherwise that test skips. Other tests mock OS secrets.

## Developer state isolation

Normal state paths are described in [Architecture](ARCHITECTURE.md). For a test
workspace, pass `--data-dir` or set the absolute `LOCAL_SERVER_HOME`
environment variable for state. Packages always remain beside the application,
including in an editable source checkout. `packages/` and `.local-server/` are
ignored; never add archives, binaries or review scratch files to Git.

The main window edits profiles and previews Nginx config. Components manages
reviewed portable archives with progress, cancellation/retry and guarded removal.
It starts explicitly selected Nginx/PHP and optional MySQL packages on Windows x64,
including secure per-project initialization and database/user creation. PHP switching
still requires stop/start. See
[runtime verification](RUNTIME.md) for completed and pending checks. Initial tests
ran locally; GitHub Actions runs BASIC on pushes and the cross-platform matrix
on PRs and manual full validation/integration.

## Design constraints

- Keep domain models and backend services independent from Tkinter widgets.
- Never block Tk's event loop with network, extraction or child-process waits.
- Put installation/progress workers behind a cancellable queue bridge before
  surfacing downloads in the UI. Only the main thread may update Tk widgets.
- Keep downloaded/runtime files out of Git and out of project source roots.
- Never run generic shell scripts from untrusted archive metadata.
- Validate paths, versions, digests, network addresses and ports at boundaries.
- Preserve docstrings when refactoring.
- Prefer GitHub CI tests; local tests are a development fallback.
- Work on a feature branch after initialization; do not push directly to
  protected release branches without a planned review/release process.
- Do not create GitHub issues or a Project board until that work is requested.

## Creating a reviewed catalog entry

See [Package catalog](PACKAGE_CATALOG.md). Official vendor websites are
starting points for discovery; every downloadable artifact must have its
actual, independent checksum and platform dependencies verified.

## Licensing

The project's open-source/proprietary license has **not been chosen yet**.
Do not redistribute third-party binaries until their licenses, attribution,
and required notices have been reviewed.
