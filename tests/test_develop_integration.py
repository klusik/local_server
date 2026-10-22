"""Exercise real fast-forward publication and the CI gates that authorize it."""

import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from tools import integrate_develop as integration
from tools.check_workflows import load_workflows, workflow_policy

ROOT: Path = Path(__file__).resolve().parents[1]


class DevelopIntegrationTests(unittest.TestCase):
    """Use a disposable local origin; never mutate the application repository."""

    def setUp(self) -> None:
        """Create a local remote and a feature commit above develop."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        directory = Path(self.temp.name)
        self.remote = directory / "origin.git"
        self.root = directory / "work"
        self.root.mkdir()
        self.git("init", "--bare", str(self.remote))
        self.git("init", "-b", "develop")
        self.git("config", "user.email", "ci-fixture@example.invalid")
        self.git("config", "user.name", "CI fixture")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(directory / "no-hooks"))
        self.base = self.commit("base")
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "origin", "develop")
        self.branch = "feature/ci-definition-change"
        self.git("switch", "-c", self.branch)
        self.candidate = self.commit("feature")
        self.git("push", "origin", self.branch)

    def git(self, *arguments: str) -> str:
        """Execute Git in this test's disposable checkout.

        Args:
            arguments (str): Literal Git subcommand and arguments.

        Returns:
            str: Stripped command output.
        """
        return integration.git(arguments, self.root)

    def commit(self, value: str) -> str:
        """Create a deterministic content change on the currently selected branch.

        Args:
            value (str): Fixture file content and commit message.

        Returns:
            str: New commit SHA.
        """
        (self.root / "fixture.txt").write_text(value, encoding="utf-8")
        self.git("add", "fixture.txt")
        self.git("commit", "-m", value)
        return self.git("rev-parse", "HEAD")

    def test_success_publishes_the_exact_tested_commit(self) -> None:
        """A normal fast-forward preserves the tested commit without generating a merge."""
        self.assertEqual(
            integration.select(self.branch, self.candidate, self.root), self.base
        )
        integration.publish(self.branch, self.candidate, self.base, self.root)
        heads = integration.remote_heads(self.branch, self.root)
        self.assertEqual(heads["refs/heads/develop"], self.candidate)
        self.assertEqual(self.git("rev-parse", "HEAD^"), self.base)

    def test_changed_source_is_rejected(self) -> None:
        """A newer source head cannot borrow the earlier commit's test results."""
        newer = self.commit("new source")
        self.git("push", "origin", self.branch)
        self.git("checkout", "--detach", self.candidate)
        with self.assertRaisesRegex(ValueError, "Source branch moved"):
            integration.publish(self.branch, self.candidate, self.base, self.root)
        self.assertNotEqual(newer, self.candidate)
        self.assertEqual(
            integration.remote_heads(self.branch, self.root)["refs/heads/develop"],
            self.base,
        )

    def test_multiple_commits_are_rejected_before_qualification(self) -> None:
        """A fast-forwardable two-commit feature must be squashed before any FULL run."""
        candidate = self.commit("second feature commit")
        self.git("push", "origin", self.branch)
        with self.assertRaisesRegex(ValueError, "one squashed non-merge commit"):
            integration.select(self.branch, candidate, self.root)
        with self.assertRaisesRegex(ValueError, "one squashed non-merge commit"):
            integration.publish(self.branch, candidate, self.base, self.root)
        self.assertEqual(
            integration.remote_heads(self.branch, self.root)["refs/heads/develop"],
            self.base,
        )

    def test_merge_commit_is_rejected_before_qualification(self) -> None:
        """The feature tip must have develop as its single parent, not merge parents."""
        self.git("switch", "-c", "side", self.base)
        (self.root / "side.txt").write_text("side", encoding="utf-8")
        self.git("add", "side.txt")
        self.git("commit", "-m", "side")
        self.git("switch", self.branch)
        self.git("merge", "--no-ff", "side", "-m", "merge feature work")
        candidate = self.git("rev-parse", "HEAD")
        self.git("push", "origin", self.branch)
        with self.assertRaisesRegex(ValueError, "one squashed non-merge commit"):
            integration.select(self.branch, candidate, self.root)

    def test_changed_develop_is_rejected_even_when_still_an_ancestor(self) -> None:
        """Re-running qualification is required when the selected base changes."""
        self.git("push", "origin", f"{self.candidate}:refs/heads/develop")
        with self.assertRaisesRegex(ValueError, "Develop moved"):
            integration.publish(self.branch, self.candidate, self.base, self.root)

    def test_divergent_source_never_rewrites_develop(self) -> None:
        """An unrelated develop change must be incorporated before integration."""
        self.git("switch", "develop")
        advanced = self.commit("other development")
        self.git("push", "origin", "develop")
        self.git("checkout", "--detach", self.candidate)
        with self.assertRaises(subprocess.CalledProcessError):
            integration.select(self.branch, self.candidate, self.root)
        self.assertEqual(
            integration.remote_heads(self.branch, self.root)["refs/heads/develop"],
            advanced,
        )

    def test_racing_divergent_push_is_rejected_by_git(self) -> None:
        """A target update after the last observation cannot be overwritten."""
        self.git("switch", "develop")
        advanced = self.commit("racing development")
        self.git("checkout", "--detach", self.candidate)
        actual_git = integration.git

        def race(arguments: list[str], root: Path) -> str:
            """Advance the target just before the candidate push reaches origin.

            Args:
                arguments (list[str]): Git command invoked by publication.
                root (Path): Private root directory containing the managed resource.

            Returns:
                str: Actual Git command output, or a rejected non-fast-forward error.
            """
            if arguments[0] == "push":
                actual_git(["push", "origin", f"{advanced}:refs/heads/develop"], root)
            return actual_git(arguments, root)

        with patch.object(integration, "git", side_effect=race):
            with self.assertRaises(subprocess.CalledProcessError):
                integration.publish(self.branch, self.candidate, self.base, self.root)
        self.assertEqual(
            integration.remote_heads(self.branch, self.root)["refs/heads/develop"],
            advanced,
        )

    def test_missing_or_deleted_refs_are_not_recreated(self) -> None:
        """Deletion of either selected branch blocks publication."""
        self.git("push", "origin", "--delete", self.branch)
        with self.assertRaisesRegex(ValueError, "Source branch moved"):
            integration.select(self.branch, self.candidate, self.root)
        self.git("push", "origin", self.branch)
        self.git("push", "origin", "--delete", "develop")
        with self.assertRaisesRegex(ValueError, "develop branch must already exist"):
            integration.select(self.branch, self.candidate, self.root)

    def test_request_rejects_bad_refs_shas_and_mismatched_checkout(self) -> None:
        """Reject option-like refs, output injection and candidates not checked out."""
        for branch, candidate in (
            ("develop", self.candidate),
            ("--force", self.candidate),
            ("feature/x\nbase=evil", self.candidate),
            (self.branch, "HEAD"),
            (self.branch, self.base),
        ):
            with self.subTest(branch=branch, candidate=candidate):
                with self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    integration.select(branch, candidate, self.root)


class WorkflowPolicyTests(unittest.TestCase):
    """Prove that workflow changes cannot silently weaken the integration contract."""

    def test_committed_workflows_obey_the_contract(self) -> None:
        """Validate actual YAML definitions, including reusable workflow references."""
        self.assertEqual(workflow_policy(load_workflows()), [])

    def test_unsafe_workflow_mutations_are_rejected(self) -> None:
        """Catch automatic integration, missing gates and write tokens in tests."""
        original = load_workflows()
        mutations = (
            ("develop-integration.yml", "on", {"push": None}),
            ("ci.yml", "permissions", {"contents": "write"}),
        )
        for filename, field, value in mutations:
            altered = deepcopy(original)
            altered[filename][field] = value
            self.assertTrue(workflow_policy(altered))
        altered = deepcopy(original)
        altered["develop-integration.yml"]["jobs"]["publish"]["needs"].remove("full")
        self.assertTrue(workflow_policy(altered))
        altered = deepcopy(original)
        altered["ci.yml"]["jobs"]["full"]["if"] = "${{ always() }}"
        self.assertTrue(workflow_policy(altered))
        altered = deepcopy(original)
        altered["develop-integration.yml"]["jobs"]["basic"]["with"]["candidate"] = (
            "main"
        )
        self.assertTrue(workflow_policy(altered))
        altered = deepcopy(original)
        for step in altered["basic-checks.yml"]["jobs"]["source"]["steps"]:
            if "check-squash" in step.get("run", ""):
                step["if"] = "${{ false }}"
        self.assertTrue(workflow_policy(altered))


if __name__ == "__main__":
    unittest.main()
