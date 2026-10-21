# Agent guidance

For UI changes, read and follow [AGENTS_DESIGN.md](AGENTS_DESIGN.md).

This is a Python 3.11+ desktop project using Tkinter for Windows/macOS.
Read README.md and docs/ARCHITECTURE.md, docs/SECURITY.md and docs/ROADMAP.md
before altering runtime or installer behavior.

- Preserve all existing docstrings. Type public interfaces and add targeted unit tests.
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
