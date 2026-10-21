"""Pin and fast-forward a manually selected branch after complete CI validation."""

import argparse
import os
import re
import subprocess
from pathlib import Path
from typing import Sequence

ROOT: Path = Path(__file__).resolve().parents[1]
SHA: re.Pattern[str] = re.compile(r"[a-f0-9]{40}\Z")


def git(arguments: Sequence[str], root: Path) -> str:
    """Execute literal Git arguments without invoking a shell.

    Args:
        arguments (Sequence[str]): Git subcommand and its literal arguments.
        root (Path): Private root directory containing the managed resource.

    Returns:
        str: Stripped standard output; failed commands raise CalledProcessError.
    """
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    ).stdout.strip()


def validate_request(branch: str, candidate: str, root: Path) -> None:
    """Require a branch checkout and the immutable commit selected by GitHub.

    Args:
        branch (str): Source branch name without refs/heads/.
        candidate (str): Exact commit tested by every required job.
        root (Path): Private root directory containing the managed resource.
    """
    if not branch or branch.startswith("-") or branch == "develop":
        raise ValueError("Select a source branch other than develop.")
    if not SHA.fullmatch(candidate):
        raise ValueError("Candidate must be an exact SHA-1 commit.")
    git(["check-ref-format", f"refs/heads/{branch}"], root)
    if git(["rev-parse", "HEAD"], root) != candidate:
        raise ValueError("Checkout differs from the tested candidate.")


def remote_heads(branch: str, root: Path) -> dict[str, str]:
    """Observe source and target heads without updating either branch.

    Args:
        branch (str): Validated source branch name.
        root (Path): Private root directory containing the managed resource.

    Returns:
        dict[str, str]: Fully qualified branch references mapped to commit SHAs.
    """
    output = git(
        [
            "ls-remote",
            "--heads",
            "origin",
            f"refs/heads/{branch}",
            "refs/heads/develop",
        ],
        root,
    )
    return {ref: sha for sha, ref in (line.split("\t") for line in output.splitlines())}


def select(branch: str, candidate: str, root: Path) -> str:
    """Pin an existing develop head that is an ancestor of the candidate.

    Args:
        branch (str): Explicitly selected source branch.
        candidate (str): Immutable workflow commit to test.
        root (Path): Private root directory containing the managed resource.

    Returns:
        str: Observed develop SHA required again before publication.
    """
    validate_request(branch, candidate, root)
    heads = remote_heads(branch, root)
    if heads.get(f"refs/heads/{branch}") != candidate:
        raise ValueError("Source branch moved or disappeared; start a new run.")
    base = heads.get("refs/heads/develop", "")
    if not SHA.fullmatch(base):
        raise ValueError("The develop branch must already exist.")
    git(["merge-base", "--is-ancestor", base, candidate], root)
    require_squashed(candidate, base, root)
    return base


def require_squashed(candidate: str, base: str, root: Path) -> None:
    """Require exactly one non-merge source commit directly above develop.

    Args:
        candidate (str): Immutable source commit selected for qualification.
        base (str): Observed develop commit that must be the sole source parent.
        root (Path): Checkout containing both commits and their complete history.
    """
    if not SHA.fullmatch(candidate) or not SHA.fullmatch(base):
        raise ValueError("Source and develop must be exact SHA-1 commits.")
    parents = git(["rev-list", "--parents", "-n", "1", candidate], root).split()
    if parents != [candidate, base]:
        raise ValueError(
            "Source must be exactly one squashed non-merge commit "
            "directly above current develop."
        )


def publish(branch: str, candidate: str, base: str, root: Path) -> None:
    """Recheck branch heads and advance develop with a normal fast-forward push.

    Args:
        branch (str): Source branch selected before qualification.
        candidate (str): Exact commit that passed all required checks.
        base (str): Develop head observed before qualification.
        root (Path): Private root directory containing the managed resource.
    """
    if not SHA.fullmatch(base):
        raise ValueError("Expected develop must be an exact SHA-1 commit.")
    validate_request(branch, candidate, root)
    if remote_heads(branch, root).get("refs/heads/develop") != base:
        raise ValueError("Develop moved while checks ran; start a new integration.")
    observed = select(branch, candidate, root)
    if observed != base:
        raise ValueError("Develop moved while checks ran; start a new integration.")
    # No merge, rebase, force, workflow-file comparison to main, or generated commit.
    # A racing divergent update is also rejected atomically by Git's normal push.
    git(["push", "origin", f"{candidate}:refs/heads/develop"], root)


def main() -> int:
    """Run selection or publication for the manual integration workflow.

    Returns:
        int: Zero on success; invalid requests and failed Git commands raise.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("select", "publish", "check-squash"))
    parser.add_argument("--branch", default="")
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--base", default="")
    args = parser.parse_args()
    if args.operation == "check-squash":
        require_squashed(args.candidate, args.base, ROOT)
    elif args.operation == "publish":
        publish(args.branch, args.candidate, args.base, ROOT)
    else:
        base = select(args.branch, args.candidate, ROOT)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"candidate={args.candidate}\nbase={base}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
