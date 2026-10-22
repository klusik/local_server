"""Attach the verified Windows build to a GitHub draft after main is released."""

import argparse
import json
import os
import re
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.integrate_develop import ROOT, SHA, git
from tools.release import ReleasePlan
from tools.release_artifacts import verify_artifacts


def gh_json(arguments: Sequence[str], payload: dict[str, Any] | None = None) -> Any:
    """Read structured GitHub CLI output without placing credentials in arguments.

    Args:
        arguments (Sequence[str]): Literal CLI subcommand and options.
        payload (dict[str, Any] | None): Optional JSON request supplied through stdin.

    Returns:
        Any: GitHub JSON at the external API boundary.
    """
    result = subprocess.run(
        ["gh", *arguments],
        check=True,
        text=True,
        capture_output=True,
        input=json.dumps(payload) if payload is not None else None,
        timeout=180,
    )
    return (
        json.loads(result.stdout)
        if arguments[0] == "api" and result.stdout.strip()
        else None
    )


def verify_uploaded(assets: list[dict[str, Any]], records: dict[str, Any]) -> None:
    """Require the exact two release assets with matching provider SHA-256 metadata.

    Args:
        assets (list[dict[str, Any]]): GitHub's release-asset metadata.
        records (dict[str, Any]): Locally verified build file sizes and hashes.
    """
    if {asset["name"] for asset in assets} != set(records) or len(assets) != len(
        records
    ):
        raise ValueError("Draft must contain exactly the two expected Windows assets.")
    for asset in assets:
        record = records[asset["name"]]
        if (
            asset["state"] != "uploaded"
            or asset["size"] != record["size"]
            or asset.get("digest") != f"sha256:{record['sha256']}"
        ):
            raise ValueError("Uploaded release asset differs from the verified build.")


def publish_draft(
    plan: ReleasePlan, directory: Path, commit: str, repository: str
) -> str:
    """Create or resume a draft without publishing it or overwriting existing files.

    Args:
        plan (ReleasePlan): Original source/tooling/version selected before the build.
        directory (Path): Verified artifacts downloaded from this run's build job.
        commit (str): Main merge commit returned by the completed publication job.
        repository (str): Repository identity supplied by the current GitHub run.

    Returns:
        str: URL of the draft containing both verified executables.
    """
    records = verify_artifacts(directory, plan)
    if not SHA.fullmatch(commit) or not re.fullmatch(r"[\w.-]+/[\w.-]+", repository):
        raise ValueError("Invalid release commit or repository identity.")
    refs = git(["ls-remote", "origin", f"refs/tags/{plan.version}^{{}}"], ROOT)
    if not refs or refs.split()[0] != commit:
        raise ValueError(
            "The annotated release tag must point to the published main commit."
        )
    base = f"repos/{repository}/releases"
    existing: dict[str, Any] | None = None
    page = 1
    while existing is None:
        releases = gh_json(["api", f"{base}?per_page=100&page={page}"])
        existing = next(
            (item for item in releases if item["tag_name"] == plan.version), None
        )
        if len(releases) < 100:
            break
        page += 1
    if existing is None:
        hashes = "\n".join(
            f"- `{name}`: SHA-256 `{row['sha256']}`" for name, row in records.items()
        )
        body = (
            f"Source develop: `{plan.develop}`\n\nMain merge: `{commit}`\n\n"
            "Windows x64: portable one-file EXE and a per-user installer. "
            "Python and Tk are included; server packages are acquired separately.\n\n"
            f"Integration: https://github.com/{repository}/actions/runs/{plan.integration}\n\n"
            f"{hashes}\n"
        )
        existing = gh_json(
            ["api", "--method", "POST", base, "--input", "-"],
            {
                "tag_name": plan.version,
                "target_commitish": commit,
                "name": f"Local Server {plan.version[2:]}",
                "body": body,
                "draft": True,
                "prerelease": False,
            },
        )
    if (
        existing["draft"] is not True
        or existing["tag_name"] != plan.version
        or f"Main merge: `{commit}`" not in existing.get("body", "")
    ):
        raise ValueError(
            "Existing release is published or belongs to a different commit."
        )
    uploaded = {asset["name"]: asset for asset in existing["assets"]}
    if set(uploaded) - set(records):
        raise ValueError(
            "Existing draft has unexpected assets; refusing to overwrite it."
        )
    for name, record in records.items():
        if name in uploaded:
            verify_uploaded([uploaded[name]], {name: record})
        else:
            gh_json(
                [
                    "release",
                    "upload",
                    plan.version,
                    str(directory / name),
                    "--repo",
                    repository,
                ]
            )
    result = gh_json(["api", f"{base}/{existing['id']}"])
    if result["draft"] is not True or result["tag_name"] != plan.version:
        raise ValueError("Release must remain a draft.")
    verify_uploaded(result["assets"], records)
    return str(result["html_url"])


def main() -> int:
    """Create the distribution draft after a successful main merge.

    Returns:
        int: Zero after both exact assets are present on the private draft.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    url = publish_draft(
        ReleasePlan.from_json(args.plan_json),
        args.artifacts.resolve(),
        args.commit,
        os.environ["GITHUB_REPOSITORY"],
    )
    with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
        stream.write(f"Draft release with both verified Windows EXEs: {url}\n")
    print(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
