# Contributing

Current development is bootstrapping the Local Server manager. The GitHub
Project board and issue backlog will be created in a later step.

## Standards

- Support Python 3.11+; use standard library code unless a dependency has a
  documented maintenance and security justification.
- Prefer typed services with Tkinter restricted to the user-interface layer.
- Keep existing docstrings and add public API documentation when needed.
- Guard input boundaries, filesystem operations, network downloads and child
  process lifetime.
- Unit-test all new core components and update relevant docs.
- Run GitHub CI across the declared OS/Python matrix; use local tests as fallback.
- Keep change sets scoped, with clear commit messages and a linear history when
  merging independently reviewed features.
- Do not commit downloaded server binaries, user source projects, local state,
  credentials or generated config files.

## Workflow

Create a descriptive feature branch from the current main branch, implement
and document the change, then open a pull request. This initial bootstrap is
committed on main because the repository was empty. Do not create issue IDs,
milestones or project items before they have been discussed and approved.
