"""Validate the integration authorization graph and cheap push CI contract."""

from pathlib import Path
from typing import Any

import yaml

ROOT: Path = Path(__file__).resolve().parents[1]


def workflow_policy(workflows: dict[str, Any]) -> list[str]:
    """Check parsed workflows for unsafe integration or unintended full push tests.

    Args:
        workflows (dict[str, Any]): Workflow filenames mapped to parsed YAML data.

    Returns:
        list[str]: Violations of the repository's CI execution and publication contract.
    """
    errors: list[str] = []
    ci = workflows["ci.yml"]
    integrate = workflows["develop-integration.yml"]
    if set(integrate["on"]) != {"workflow_dispatch"}:
        errors.append("Integration must only accept explicit manual dispatch.")
    if ci["jobs"]["full"].get("if") != "${{ github.event_name != 'push' }}":
        errors.append("Full CI must not run on ordinary pushes.")
    if ci["jobs"]["basic"].get("if"):
        errors.append("BASIC checks must run on every push.")
    squash_steps = [
        step
        for step in workflows["basic-checks.yml"]["jobs"]["source"]["steps"]
        if "check-squash" in step.get("run", "")
    ]
    if len(squash_steps) != 1 or squash_steps[0].get("if") != (
        "${{ github.event_name == 'pull_request' && github.base_ref == 'develop' }}"
    ):
        errors.append(
            "Develop PRs must require one squash commit before FULL qualification."
        )
    if integrate.get("concurrency") != {
        "group": "develop-integration",
        "cancel-in-progress": False,
    }:
        errors.append(
            "Integrations must be serialized without cancelling an active publication."
        )
    if integrate["jobs"]["select"].get("outputs") != {
        "candidate": "${{ steps.select.outputs.candidate }}",
        "base": "${{ steps.select.outputs.base }}",
    }:
        errors.append("Selection must export immutable candidate and develop SHAs.")
    for name in ("basic", "full"):
        job = integrate["jobs"][name]
        expected = "basic-checks.yml" if name == "basic" else "python-checks.yml"
        if job.get("uses") != f"./.github/workflows/{expected}" or job.get("with") != {
            "candidate": "${{ needs.select.outputs.candidate }}"
        }:
            errors.append(
                "All integration checks must use branch-owned CI and the exact selected SHA."
            )
    publication = integrate["jobs"]["publish"]
    if set(publication.get("needs", [])) != {"select", "basic", "full"}:
        errors.append(
            "Publication must depend on selection, BASIC and the full matrix."
        )
    condition = publication.get("if", "")
    if (
        any(
            term not in condition
            for term in (
                "github.event_name == 'workflow_dispatch'",
                "needs.basic.result == 'success'",
                "needs.full.result == 'success'",
            )
        )
        or "always()" in condition
    ):
        errors.append("Only successful manual qualification may authorize publication.")
    for filename, workflow in workflows.items():
        if workflow.get("permissions") != {"contents": "read"}:
            errors.append(f"{filename}: default token permissions must be read-only.")
        for name, job in workflow["jobs"].items():
            if job.get("permissions", {}).get("contents") == "write":
                if filename != "develop-integration.yml" or name != "publish":
                    errors.append(
                        "Only the publication job may receive repository write access."
                    )
            for step in job.get("steps", []):
                if step.get("uses", "").startswith("actions/checkout@"):
                    if step.get("with", {}).get("persist-credentials") is not False:
                        errors.append("Checkouts must not persist token credentials.")
                    ref = step.get("with", {}).get("ref")
                    if ref not in {
                        "${{ github.sha }}",
                        "${{ inputs.candidate }}",
                        "${{ needs.select.outputs.candidate }}",
                    }:
                        errors.append(
                            "Checkouts must be pinned to a workflow-selected commit."
                        )
    matrix = workflows["python-checks.yml"]["jobs"]["unittest"]["strategy"]["matrix"]
    if set(matrix["os"]) != {"ubuntu-latest", "windows-latest", "macos-latest"}:
        errors.append("Full qualification must cover all three test platforms.")
    if set(matrix["python-version"]) != {"3.14"}:
        errors.append("Full qualification must cover the Python 3.14 minimum.")
    return errors


def load_workflows(root: Path = ROOT) -> dict[str, Any]:
    """Read owned workflows using YAML rules that preserve GitHub's on key.

    Args:
        root (Path): Private root directory containing the managed resource.

    Returns:
        dict[str, Any]: Workflow filenames mapped to their parsed definitions.
    """
    # SafeLoader's YAML 1.1 resolver treats 'on' as True; normalize only that key.
    result: dict[str, Any] = {}
    for path in sorted((root / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        if True in workflow:
            workflow["on"] = workflow.pop(True)
        result[path.name] = workflow
    return result


def main() -> int:
    """Validate the committed workflow graph.

    Returns:
        int: Zero for a valid graph, or one when the CI contract is broken.
    """
    errors = workflow_policy(load_workflows())
    for error in errors:
        print(error)
    print(f"Workflow policy: {len(errors)} violation(s)")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
