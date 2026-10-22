"""Verify release version grammar, integration evidence and real Git transactions."""

import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tools import release
from tools.check_workflows import load_workflows, workflow_policy


def evidence_api(path: str) -> dict[str, Any]:
    """Supply successful integration metadata for any exact fixture commit.

    Args:
        path (str): Repository-relative Actions API request.

    Returns:
        dict[str, Any]: Fixture run or its six successfully completed jobs.
    """
    if "/jobs?" in path:
        names = [
            "Authorize and pin source/develop",
            "basic / BASIC (source policy and CI regression tests)",
            "Fast-forward develop to tested commit",
            *(
                f"full / Test ({os}-latest, Python 3.14)"
                for os in ("ubuntu", "windows", "macos")
            ),
        ]
        return {
            "total_count": 6,
            "jobs": [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in names
            ],
        }
    return {
        "workflow_runs": [
            {
                "head_sha": path.split("head_sha=")[1].split("&")[0],
                "event": "workflow_dispatch",
                "path": ".github/workflows/develop-integration.yml",
                "status": "completed",
                "conclusion": "success",
                "id": 123,
                "run_attempt": 2,
            }
        ]
    }


class ReleasePolicyTests(unittest.TestCase):
    """Reject malformed inputs and incomplete or unrelated CI evidence."""

    def test_version_formats(self) -> None:
        """Only the two explicit numeric tag forms are accepted without normalization."""
        for version in ("v_0.1", "v_0.1.0", "v_12.345.678", "v_01.2"):
            release.validate_version(version)
        for version in (
            "0.1",
            "v0.1",
            "v_1",
            "v_1.2.3.4",
            "v_1.2-rc1",
            "v_-1.2",
            "v_1.a",
            "v_1.2\n",
            " v_1.2",
            "v_١.٢",
            "--force",
            "v_1.2/evil",
        ):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release.validate_version(version)

    def test_evidence_requires_exact_successful_integration_and_every_job(self) -> None:
        """Wrong commits/events, incomplete attempts and missing platforms cannot qualify."""
        candidate = "a" * 40
        self.assertEqual(release.qualification(candidate, evidence_api), (123, 2))
        run_path = (
            "actions/workflows/develop-integration.yml/runs"
            f"?event=workflow_dispatch&head_sha={candidate}&per_page=100"
        )
        for field, value in (
            ("head_sha", "b" * 40),
            ("event", "push"),
            ("path", "ci.yml"),
            ("status", "in_progress"),
            ("conclusion", "failure"),
        ):
            altered = evidence_api(run_path)
            altered["workflow_runs"][0][field] = value
            with patch.object(release, "read_api", return_value=altered):
                with self.assertRaises(ValueError):
                    release.qualification(candidate, release.read_api)
        for modification in ("missing", "skipped", "failed", "extra-page"):
            jobs = evidence_api("/jobs?")
            if modification == "missing":
                jobs["jobs"].pop()
            elif modification == "extra-page":
                jobs["total_count"] = 101
            else:
                jobs["jobs"][-1]["conclusion"] = modification
            with patch.object(
                release, "read_api", side_effect=[evidence_api(run_path), jobs]
            ):
                with self.assertRaises(ValueError):
                    release.qualification(candidate, release.read_api)

    def test_workflow_mutations_are_rejected(self) -> None:
        """Keep release manual, pinned, versioned and separate from the test matrix."""
        original = load_workflows()
        self.assertEqual(workflow_policy(original), [])
        for field, value in (
            ("on", {"push": {}}),
            ("concurrency", {"group": "release"}),
        ):
            altered = deepcopy(original)
            altered["release.yml"][field] = value
            self.assertTrue(workflow_policy(altered))
        altered = deepcopy(original)
        altered["release.yml"]["jobs"]["full"] = {"uses": "./python-checks.yml"}
        self.assertTrue(workflow_policy(altered))
        altered = deepcopy(original)
        altered["release.yml"]["on"]["workflow_dispatch"]["inputs"]["version"][
            "required"
        ] = False
        self.assertTrue(workflow_policy(altered))


class ReleaseGitTests(unittest.TestCase):
    """Exercise publication against a disposable local origin with genuine Git refs."""

    def setUp(self) -> None:
        """Prepare develop history and a divergent main registration commit."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.root = directory / "work"
        self.root.mkdir()
        self.remote = directory / "origin.git"
        self.git("init", "--bare", str(self.remote))
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Release fixture")
        self.git("config", "user.email", "release@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(directory / "no-hooks"))
        self.base = self.commit("app.txt", "base")
        self.git("switch", "-c", "develop")
        self.commit("app.txt", "develop first commit")
        self.develop = self.commit("workflow.txt", "same registration")
        self.git("switch", "main")
        self.main = self.commit("workflow.txt", "same registration")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "origin", "main", "develop")

    def git(self, *arguments: str) -> str:
        """Execute Git only in the disposable fixture.

        Args:
            arguments (str): Literal Git arguments.

        Returns:
            str: Stripped Git standard output.
        """
        return release.git(arguments, self.root)

    def commit(self, filename: str, value: str) -> str:
        """Commit one fixture file on the selected branch.

        Args:
            filename (str): Relative fixture filename.
            value (str): File contents and commit description.

        Returns:
            str: New commit SHA.
        """
        (self.root / filename).write_text(value, encoding="utf-8")
        self.git("add", filename)
        self.git("commit", "-m", value)
        return self.git("rev-parse", "HEAD")

    def test_merge_preserves_history_and_tags_tested_tree(self) -> None:
        """Two develop commits survive beneath a two-parent release merge and annotated tag."""
        plan = release.select("v_0.1", self.root, evidence_api)
        published = release.publish(plan, self.root, evidence_api)
        refs = release.remote_refs("v_0.1", self.root)
        self.assertEqual(refs["refs/heads/main"], published)
        self.assertEqual(refs["refs/heads/develop"], self.develop)
        self.assertEqual(self.git("rev-parse", "v_0.1^{}"), published)
        self.assertEqual(self.git("cat-file", "-t", "v_0.1"), "tag")
        self.assertEqual(self.git("rev-parse", "HEAD^1"), self.main)
        self.assertEqual(self.git("rev-parse", "HEAD^2"), self.develop)
        self.assertEqual(
            self.git("rev-parse", "HEAD^{tree}"),
            self.git("rev-parse", f"{self.develop}^{{tree}}"),
        )
        with self.assertRaisesRegex(ValueError, "already exists"):
            release.select("v_0.1", self.root, evidence_api)

    def test_untested_main_changes_cannot_enter_release(self) -> None:
        """A clean merge still fails if main contributes content outside tested develop."""
        self.main = self.commit("untested.txt", "main-only content")
        self.git("push", "origin", "main")
        with self.assertRaisesRegex(ValueError, "differs from tested develop"):
            release.publish(
                release.select("v_0.1", self.root, evidence_api),
                self.root,
                evidence_api,
            )
        self.assertEqual(
            release.remote_refs("v_0.1", self.root),
            {
                "refs/heads/main": self.main,
                "refs/heads/develop": self.develop,
            },
        )

    def test_failed_evidence_or_merge_leaves_remote_unchanged(self) -> None:
        """Unqualified develop and merge conflicts fail before remote publication."""
        before = release.remote_refs("v_0.1", self.root)
        with patch.object(
            release, "qualification", side_effect=ValueError("unqualified")
        ):
            with self.assertRaisesRegex(ValueError, "unqualified"):
                release.select("v_0.1", self.root, evidence_api)
        self.assertEqual(release.remote_refs("v_0.1", self.root), before)
        self.main = self.commit("app.txt", "conflicting main")
        self.git("push", "origin", "main")
        with self.assertRaises(subprocess.CalledProcessError):
            release.publish(
                release.select("v_0.1", self.root, evidence_api),
                self.root,
                evidence_api,
            )
        self.assertNotIn("refs/tags/v_0.1", release.remote_refs("v_0.1", self.root))

    def test_racing_tag_rejects_main_update_atomically(self) -> None:
        """A tag created after the final observation rejects both pushed updates."""
        actual_git = release.git

        def race(arguments: list[str], root: Path) -> str:
            """Create a remote tag just before the atomic release push.

            Args:
                arguments (list[str]): Git command requested by release publication.
                root (Path): Disposable checkout.

            Returns:
                str: Git output, or a raised atomic push rejection.
            """
            if arguments[0] == "push":
                actual_git(["push", "origin", f"{self.base}:refs/tags/v_0.1"], root)
            return actual_git(arguments, root)

        with patch.object(release, "git", side_effect=race):
            with self.assertRaises(subprocess.CalledProcessError):
                release.publish(
                    release.select("v_0.1", self.root, evidence_api),
                    self.root,
                    evidence_api,
                )
        refs = release.remote_refs("v_0.1", self.root)
        self.assertEqual(refs["refs/heads/main"], self.main)
        self.assertEqual(refs["refs/tags/v_0.1"], self.base)

    def test_develop_cannot_change_after_build_selection(self) -> None:
        """A newer qualified head cannot replace the commit whose artifacts were built."""
        plan = release.select("v_0.1", self.root, evidence_api)
        self.git("switch", "develop")
        newer = self.commit("app.txt", "develop advanced during build")
        self.git("push", "origin", "develop")
        with self.assertRaisesRegex(ValueError, "changed after selection"):
            release.publish(plan, self.root, evidence_api)
        refs = release.remote_refs("v_0.1", self.root)
        self.assertEqual(refs["refs/heads/main"], self.main)
        self.assertEqual(refs["refs/heads/develop"], newer)
        self.assertNotIn("refs/tags/v_0.1", refs)


if __name__ == "__main__":
    unittest.main()
