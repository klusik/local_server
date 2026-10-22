"""Protect build-before-merge ordering, artifact provenance and resumable drafts."""

import json
import tempfile
import unittest
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from tools import release_draft
from tools.build_windows import version_resource
from tools.check_workflows import load_workflows, workflow_policy
from tools.release import ReleasePlan
from tools.release_artifacts import asset_names, verify_artifacts, write_manifest


class ReleaseBuildTests(unittest.TestCase):
    """Use disposable distribution bytes; never create a real release from unit tests."""

    def setUp(self) -> None:
        """Create two sample assets bound to one immutable source and workflow plan."""
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.plan = ReleasePlan("v_0.2", "a" * 40, "b" * 40, "c" * 40, 123, 1)
        for name in asset_names(self.plan.version):
            (self.directory / name).write_bytes(
                b"MZ disposable fixture " + name.encode()
            )
        write_manifest(self.directory, self.plan)

    def test_artifacts_reject_modified_missing_or_differently_sourced_builds(
        self,
    ) -> None:
        """A valid hash alone cannot authorize another source, version or workflow."""
        self.assertEqual(len(verify_artifacts(self.directory, self.plan)), 2)
        for plan in (
            replace(self.plan, develop="d" * 40),
            replace(self.plan, workflow="d" * 40),
            replace(self.plan, main="d" * 40),
            replace(self.plan, version="v_0.2.1"),
        ):
            with self.assertRaises(ValueError):
                verify_artifacts(self.directory, plan)
        portable = self.directory / asset_names(self.plan.version)[0]
        content = portable.read_bytes()
        portable.write_bytes(content + b"tampered")
        with self.assertRaises(ValueError):
            verify_artifacts(self.directory, self.plan)
        portable.unlink()
        with self.assertRaises(ValueError):
            verify_artifacts(self.directory, self.plan)

    def test_plan_and_windows_version_metadata(self) -> None:
        """Untrusted job outputs cannot substitute refs or invalid version resources."""
        self.assertEqual(ReleasePlan.from_json(self.plan.to_json()), self.plan)
        for field, value in (
            ("version", "v0.2"),
            ("develop", "develop"),
            ("attempt", True),
        ):
            content = asdict(self.plan)
            content[field] = value
            with self.assertRaises(ValueError):
                ReleasePlan.from_json(json.dumps(content))
        self.assertIn("filevers=(0, 2, 0, 0)", version_resource("v_0.2"))
        self.assertIn("filevers=(0, 2, 1, 0)", version_resource("v_0.2.1"))
        with self.assertRaises(ValueError):
            version_resource("v_65536.2")

    def test_main_cannot_publish_before_successful_build(self) -> None:
        """Catch build bypasses, unpinned source and draft creation before the merge."""
        original = load_workflows()
        for job, field, value in (
            ("publish", "needs", ["select"]),
            ("publish", "if", "${{ always() }}"),
            ("draft", "needs", ["select", "build"]),
        ):
            altered = deepcopy(original)
            altered["release.yml"]["jobs"][job][field] = value
            self.assertTrue(workflow_policy(altered))
        altered = deepcopy(original)
        for step in altered["release.yml"]["jobs"]["build"]["steps"]:
            if step.get("with", {}).get("path") == "source":
                step["with"]["ref"] = "${{ github.sha }}"
        self.assertTrue(workflow_policy(altered))

    def test_installer_is_per_user_and_preserves_data(self) -> None:
        """Installer policy cannot silently switch to elevation or recursive data removal."""
        root = Path(__file__).resolve().parents[1]
        script = (root / "packaging/windows.iss").read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", script)
        self.assertIn("PrivilegesRequiredOverridesAllowed=\n", script)
        self.assertIn("DefaultDirName={localappdata}\\Programs\\LocalServer", script)
        self.assertNotIn("[UninstallDelete]", script)
        self.assertNotIn("HKLM", script)
        self.assertNotIn("{commonpf}", script)

    def test_partial_upload_can_resume_without_merging_or_overwriting(self) -> None:
        """Retry an interrupted draft job and upload only the missing executable."""
        records = verify_artifacts(self.directory, self.plan)
        commit = "d" * 40
        state: dict[str, Any] = {
            "id": 7,
            "body": f"Main merge: `{commit}`",
            "draft": True,
            "target_commitish": commit,
            "tag_name": self.plan.version,
            "assets": [],
            "html_url": "https://example.invalid/draft",
        }
        created = False
        fail_once = True
        uploaded: list[str] = []

        def api(arguments: list[str], payload: dict[str, Any] | None = None) -> Any:
            """Model GitHub's draft metadata and an interrupted second upload.

            Args:
                arguments (list[str]): GitHub CLI request arguments.
                payload (dict[str, Any] | None): Optional release creation JSON.

            Returns:
                Any: Metadata response or no result for a successful upload.
            """
            nonlocal created, fail_once
            if arguments[0] == "release":
                name = Path(arguments[3]).name
                if uploaded and fail_once:
                    fail_once = False
                    raise OSError("interrupted upload")
                uploaded.append(name)
                row = records[name]
                state["assets"].append(
                    {
                        "name": name,
                        "state": "uploaded",
                        "size": row["size"],
                        "digest": f"sha256:{row['sha256']}",
                    }
                )
                self.assertNotIn("--clobber", arguments)
                return None
            if payload is not None:
                self.assertTrue(payload["draft"])
                self.assertEqual(payload["target_commitish"], commit)
                self.assertFalse(created)
                created = True
                return deepcopy(state)
            if "?per_page=" in arguments[1]:
                return [deepcopy(state)] if created else []
            return deepcopy(state)

        with (
            patch.object(
                release_draft, "git", return_value=f"{commit}\trefs/tags/v_0.2^{{}}"
            ),
            patch.object(release_draft, "gh_json", side_effect=api),
        ):
            with self.assertRaisesRegex(OSError, "interrupted"):
                release_draft.publish_draft(
                    self.plan, self.directory, commit, "owner/repo"
                )
            url = release_draft.publish_draft(
                self.plan, self.directory, commit, "owner/repo"
            )
        self.assertEqual(url, state["html_url"])
        self.assertEqual(len(uploaded), 2)
        self.assertEqual(len(set(uploaded)), 2)
        self.assertTrue(state["draft"])

    def test_uploaded_hash_or_published_release_cannot_be_overwritten(self) -> None:
        """Reject published releases and conflicting uploaded bytes without write calls."""
        records = verify_artifacts(self.directory, self.plan)
        name = next(iter(records))
        with self.assertRaises(ValueError):
            release_draft.verify_uploaded(
                [
                    {
                        "name": name,
                        "state": "uploaded",
                        "size": records[name]["size"],
                        "digest": "sha256:" + "0" * 64,
                    },
                ],
                {name: records[name]},
            )
        commit = "d" * 40
        with (
            patch.object(
                release_draft, "git", return_value=f"{commit}\trefs/tags/v_0.2^{{}}"
            ),
            patch.object(
                release_draft,
                "gh_json",
                return_value=[
                    {
                        "draft": False,
                        "tag_name": self.plan.version,
                        "target_commitish": commit,
                        "assets": [],
                    }
                ],
            ) as api,
        ):
            with self.assertRaisesRegex(ValueError, "published"):
                release_draft.publish_draft(
                    self.plan, self.directory, commit, "owner/repo"
                )
        self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
