# Agent guidance

For UI changes, read and follow [AGENTS_DESIGN.md](AGENTS_DESIGN.md).

This is a Python 3.14+ desktop project using Tkinter for Windows/macOS.
Read README.md and docs/ARCHITECTURE.md, docs/SECURITY.md and docs/ROADMAP.md
before altering runtime or installer behavior.

- Preserve all existing docstrings. Type public interfaces and add targeted unit tests.
- Use Google-style docstrings with typed, explained Args and Returns/Yields.
  Annotate all function signatures, including private helpers. Do not use
  `from __future__ import annotations`; quote forward references where needed.
- Format Python to 88 columns with a hard 100-column source limit. Run Ruff,
  strict mypy, tools/check_source.py and tools/check_workflows.py.
- Enforce MVC boundaries: core must not import higher layers; backend must not
  depend on Tkinter/UI; views hand blocking work to services/controllers via
  workers. Review responsibilities as well as automated dependency checks.
- Ordinary pushes run BASIC only. FULL runs on PRs/manual validation. Integrate
  develop only through the manually selected Develop integrate workflow after
  BASIC and the full matrix pass for the exact source commit; never force the
  integration target. Require exactly one squashed non-merge commit above develop
  before qualifying a develop PR or starting the integration matrix.
- Keep Tkinter concerns inside src/local_server/ui; keep IO/network/process work
  off the Tk event loop once those features are integrated.
- Do not claim Apache, Nginx, PHP or MySQL starts or installs until verified
  runtime behavior is implemented and tested on the applicable target OS.
- Do not add guessed download links or hashes to the component catalog.
- No system-wide installation, admin privileges, shell=True, default MySQL
  passwords, external network binding or unsandboxed archive extraction.
- GitHub Actions CI is the preferred test mechanism; local tests are fallback.
- Work on the explicitly provided feature branch. Never push directly to
  develop or main during ordinary feature implementation.
- Keep changes atomic and document compatibility/security implications.
- GitHub Issues, Projects, labels and milestones will be created later when
  explicitly requested. Do not manufacture issue references.
