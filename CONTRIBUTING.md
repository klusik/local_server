# Contributing

Current development is bootstrapping the Local Server manager. The GitHub
Project board and issue backlog will be created in a later step.

## Standards

- Support Python 3.14+; use standard library code unless a dependency has a
  documented maintenance and security justification.
- Prefer typed services with Tkinter restricted to the user-interface layer.
- Keep existing docstrings and add public API documentation when needed.
- Use Google docstrings with typed, explained Args and Returns/Yields entries.
- Type function signatures and ambiguous state; run strict mypy and source policy.
- Do not import future annotations; quote forward references on Python 3.14.
- Format Python to 88 columns and keep every source line within 100 columns.
- Respect MVC boundaries: core models do not depend on controllers/views,
  backend does not depend on Tkinter, and views submit blocking work to workers.
- Guard input boundaries, filesystem operations, network downloads and child
  process lifetime.
- Unit-test all new core components and update relevant docs.
- Run GitHub CI across the declared OS/Python matrix; use local tests as fallback.
- Keep change sets scoped, with clear commit messages and a linear history when
  merging independently reviewed features.
- Do not commit downloaded server binaries, user source projects, local state,
  credentials or generated config files.

## Workflow

Create a descriptive feature branch from current develop, implement and document
the change, then open a pull request. Pushes run BASIC; PRs and manual validation
run FULL after requiring one squashed, non-merge feature commit directly above
develop. Use the manually selected **Develop integrate** workflow to qualify
the exact feature commit and fast-forward develop after all checks pass. See
[Development](docs/DEVELOPMENT.md) for initial workflow registration and execution.
Do not create issue IDs,
milestones or project items before they have been discussed and approved.
