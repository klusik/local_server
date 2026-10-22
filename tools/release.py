"""Merge qualified develop into main and atomically publish an annotated version tag."""

import argparse
import json
import os
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from tools.integrate_develop import ROOT, SHA, git

VERSION: re.Pattern[str] = re.compile(r"v_[0-9]+\.[0-9]+(?:\.[0-9]+)?\Z")
type ReadAPI = Callable[[str], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ReleasePlan:
    """Immutable source, target, tooling and integration selected before building."""

    version: str
    main: str
    develop: str
    workflow: str
    integration: int
    attempt: int

    def to_json(self) -> str:
        """Encode the plan for job outputs and the artifact manifest.

        Returns:
            str: Single-line JSON with only validated immutable release inputs.
        """
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_json(cls, content: str) -> "ReleasePlan":
        """Decode and validate a plan received from the selection job.

        Args:
            content (str): JSON emitted by the release selection helper.

        Returns:
            ReleasePlan: Validated version, commit SHAs and integration evidence.
        """
        plan = cls(**json.loads(content))
        validate_version(plan.version)
        if not all(
            SHA.fullmatch(value) for value in (plan.main, plan.develop, plan.workflow)
        ):
            raise ValueError("Release plan must contain exact commit SHAs.")
        if type(plan.integration) is not int or type(plan.attempt) is not int:
            raise ValueError("Integration identity must contain integer IDs.")
        if plan.integration <= 0 or plan.attempt <= 0:
            raise ValueError("Integration identity must be positive.")
        return plan


def validate_version(version: str) -> None:
    """Accept only the two supported numeric version tag formats.

    Args:
        version (str): Literal tag in v_X.Y or v_X.Y.Z format.
    """
    if not VERSION.fullmatch(version):
        raise ValueError("Version must have the format v_X.Y or v_X.Y.Z.")


def read_api(path: str) -> dict[str, Any]:
    """Read repository Actions metadata with the job's temporary GitHub token.

    Args:
        path (str): Relative API path generated internally by the release tool.

    Returns:
        dict[str, Any]: Decoded JSON object supplied by the GitHub API.
    """
    repository = os.environ["GITHUB_REPOSITORY"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository identity.")
    request = Request(
        f"https://api.github.com/repos/{repository}/{path}",
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "LocalServer-release",
        },
    )
    with urlopen(request, timeout=30) as response:
        result: dict[str, Any] = json.load(response)
    return result


def qualification(candidate: str, api: ReadAPI) -> tuple[int, int]:
    """Find successful manual integration evidence for the exact develop commit.

    Args:
        candidate (str): Immutable develop SHA to release.
        api (ReadAPI): Reader for repository-scoped GitHub Actions metadata.

    Returns:
        tuple[int, int]: Successful integration run ID and its completed attempt.
    """
    if not SHA.fullmatch(candidate):
        raise ValueError("Develop must be an exact commit SHA.")
    runs = api(
        "actions/workflows/develop-integration.yml/runs"
        f"?event=workflow_dispatch&head_sha={candidate}&per_page=100"
    )["workflow_runs"]
    required = {
        "Authorize and pin source/develop",
        "basic / BASIC (source policy and CI regression tests)",
        "Fast-forward develop to tested commit",
        *(
            f"full / Test ({os}-latest, Python 3.14)"
            for os in ("ubuntu", "windows", "macos")
        ),
    }
    for run in runs:
        if (
            run.get("head_sha") != candidate
            or run.get("event") != "workflow_dispatch"
            or run.get("path") != ".github/workflows/develop-integration.yml"
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
        ):
            continue
        run_id, attempt = int(run["id"]), int(run["run_attempt"])
        result = api(f"actions/runs/{run_id}/attempts/{attempt}/jobs?per_page=100")
        jobs = result["jobs"]
        if (
            result["total_count"] == len(jobs) == len(required)
            and {job["name"] for job in jobs} == required
            and all(
                job["status"] == "completed" and job["conclusion"] == "success"
                for job in jobs
            )
        ):
            return run_id, attempt
    raise ValueError(
        "Develop has no successful complete manual integration for this SHA."
    )


def remote_refs(version: str, root: Path) -> dict[str, str]:
    """Observe both release branches and the requested tag without modifying them.

    Args:
        version (str): Validated version tag.
        root (Path): Checkout used for the release transaction.

    Returns:
        dict[str, str]: Remote reference names mapped to object SHAs.
    """
    validate_version(version)
    output = git(
        [
            "ls-remote",
            "origin",
            "refs/heads/main",
            "refs/heads/develop",
            f"refs/tags/{version}",
        ],
        root,
    )
    return {ref: sha for sha, ref in (line.split("\t") for line in output.splitlines())}


def select(version: str, root: Path, api: ReadAPI = read_api) -> ReleasePlan:
    """Pin qualified develop, main and tooling before starting any build.

    Args:
        version (str): Unique numeric version in v_X.Y or v_X.Y.Z format.
        root (Path): Checkout containing the chosen release tooling.
        api (ReadAPI): Reader used to verify existing integration evidence.

    Returns:
        ReleasePlan: Immutable release inputs carried through build and publication.
    """
    refs = remote_refs(version, root)
    main = refs.get("refs/heads/main", "")
    develop = refs.get("refs/heads/develop", "")
    if not SHA.fullmatch(main) or not SHA.fullmatch(develop):
        raise ValueError("Both main and develop must already exist.")
    if f"refs/tags/{version}" in refs:
        raise ValueError("Version tag already exists; tags are never overwritten.")
    evidence = qualification(develop, api)
    return ReleasePlan(
        version, main, develop, git(["rev-parse", "HEAD"], root), *evidence
    )


def publish(plan: ReleasePlan, root: Path, api: ReadAPI = read_api) -> str:
    """Preserve develop history with a merge and publish main plus tag atomically.

    Args:
        plan (ReleasePlan): Source and evidence pinned before the successful build.
        root (Path): Disposable CI checkout containing the chosen release tooling.
        api (ReadAPI): Reader used to verify existing integration evidence.

    Returns:
        str: Published main commit SHA, also targeted by the annotated version tag.
    """
    ReleasePlan.from_json(plan.to_json())
    version, main, develop = plan.version, plan.main, plan.develop
    refs = {"refs/heads/main": main, "refs/heads/develop": develop}
    evidence = (plan.integration, plan.attempt)
    if remote_refs(version, root) != refs:
        raise ValueError(
            "Release branches or tag changed after selection; start a new run."
        )
    if qualification(develop, api) != evidence:
        raise ValueError(
            "Integration evidence changed after selection; start a new run."
        )
    git(["fetch", "--no-tags", "origin", main, develop], root)
    # The module is already loaded from the selected workflow commit. Switching
    # this disposable checkout only prepares the release tree, never branch code.
    git(["checkout", "--detach", main], root)
    identity = [
        "-c",
        "user.name=github-actions[bot]",
        "-c",
        "user.email=41898282+github-actions[bot]@users.noreply.github.com",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.hooksPath=/dev/null",
    ]
    git(
        [
            *identity,
            "merge",
            "--no-ff",
            "--no-edit",
            develop,
            "-m",
            f"Release {version}",
        ],
        root,
    )
    if git(["rev-parse", "HEAD^{tree}"], root) != git(
        ["rev-parse", f"{develop}^{{tree}}"], root
    ):
        raise ValueError(
            "Merge tree differs from tested develop; resolve changes on develop first."
        )
    message = (
        f"Release {version}\n\nDevelop: {develop}\n"
        f"Integration: {evidence[0]}, attempt {evidence[1]}\n"
    )
    git(
        [*identity, "-c", "tag.gpgsign=false", "tag", "-a", version, "-m", message],
        root,
    )
    if remote_refs(version, root) != refs:
        raise ValueError("Release branches or tag changed; start a new release run.")
    if qualification(develop, api) != evidence:
        raise ValueError("Integration evidence changed; start a new release run.")
    # No force or squash: Git rejects racing main/tag writes and rolls back both
    # ref updates together when either update cannot be accepted.
    git(
        ["push", "--atomic", "origin", "HEAD:refs/heads/main", f"refs/tags/{version}"],
        root,
    )
    return git(["rev-parse", "HEAD"], root)


def main() -> int:
    """Publish the manually requested release without running tests again.

    Returns:
        int: Zero after main and its version tag have both been published.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("select", "publish"))
    parser.add_argument("--version", default="")
    parser.add_argument("--plan-json", default="")
    parser.add_argument("--artifacts", type=Path)
    args = parser.parse_args()
    if args.operation == "select":
        plan = select(args.version, ROOT)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"candidate={plan.develop}\nplan={plan.to_json()}\n")
        return 0
    from tools.release_artifacts import verify_artifacts

    plan = ReleasePlan.from_json(args.plan_json)
    if args.artifacts is None:
        parser.error("Publication requires the completed build artifacts.")
    verify_artifacts(args.artifacts, plan)
    commit = publish(plan, ROOT)
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
        stream.write(f"commit={commit}\n")
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(
            f"Released `{plan.version}` at `{commit}` (merge of tested develop).\n"
        )
    print(f"Released {plan.version}: {commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
