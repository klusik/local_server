"""Regression tests proving that source-policy violations fail BASIC checks."""

import unittest

from tools.check_source import check_source


class SourcePolicyTests(unittest.TestCase):
    """Check positive examples and independent ways to violate each policy."""

    def rules(
        self, source: str, path: str = "src/local_server/core/example.py"
    ) -> set[str]:
        """Collect rule identifiers for a small source fixture.

        Args:
            source (str): Source fixture to inspect without importing it.
            path (str): Repository-relative source path used for layer checks.

        Returns:
            set[str]: Rules violated by this fixture.
        """
        return {finding.rule for finding in check_source(source, path)}

    def test_future_import_is_rejected_but_literal_is_allowed(self) -> None:
        """Require native annotations without rejecting examples stored in strings."""
        self.assertIn("FUTURE", self.rules("from __future__ import annotations"))
        self.assertNotIn(
            "FUTURE", self.rules("EXAMPLE = 'from __future__ import annotations'")
        )

    def test_python_314_syntax_is_required(self) -> None:
        """Accept modern type aliases and reject malformed Python 3.14 source."""
        self.assertFalse(self.rules("type Record = dict[str, str]"))
        self.assertIn("PY314", self.rules("def malformed(: pass"))

    def test_google_docs_and_annotations_are_required(self) -> None:
        """Cover missing docs, missing parameter types and missing result meaning."""
        self.assertTrue({"DOC", "TYPE", "ARGS"} <= self.rules("def f(value): pass"))
        self.assertIn(
            "RETURN",
            self.rules('def f() -> str:\n    """Read a name."""\n    return "x"'),
        )
        source = '''def f(value: str) -> str:
    """Normalize a name.

    Args:
        value (str): Name to normalize.

    Returns:
        str: Normalized name.
    """
    return value.strip()
'''
        self.assertFalse(self.rules(source))
        self.assertIn(
            "DOC-TYPE", self.rules(source.replace("value (str)", "value (int)"))
        )
        self.assertIn(
            "ARGS", self.rules(source.replace("value (str): Name", "value: Name"))
        )
        self.assertIn(
            "ARGS",
            self.rules(
                source.replace("value (str): Name to normalize.", "value (str):")
            ),
        )

    def test_width_is_an_actual_hard_limit(self) -> None:
        """Accept one hundred columns and reject one hundred and one."""
        self.assertNotIn("WIDTH", self.rules("#" * 100))
        self.assertIn("WIDTH", self.rules("#" * 101))

    def test_backend_cannot_import_ui_directly_or_relatively(self) -> None:
        """Include import aliases and lazy imports in layer enforcement."""
        for source in (
            "import tkinter as tk",
            "from tkinter import ttk",
            "from local_server import ui",
            "from ..ui import dialogs",
            "from .. import ui",
            "from local_server import app",
        ):
            with self.subTest(source=source):
                self.assertIn("MVC", self.rules(source))
        self.assertIn("MVC", self.rules("from ..services import projects"))
        self.assertNotIn("MVC", self.rules("from .models import ProjectProfile"))

    def test_ui_cannot_implement_network_or_process_backend(self) -> None:
        """Disallow network and process imports even inside a UI helper."""
        for source in (
            "import subprocess as sp",
            "from urllib import request",
            "import socket",
        ):
            self.assertIn("MVC", self.rules(source, "src/local_server/ui/dialogs.py"))

    def test_ui_blocking_callbacks_fail_but_worker_handoffs_pass(self) -> None:
        """Only recognized worker submissions can contain blocking IO closures."""
        path = "src/local_server/ui/dialogs.py"
        self.assertIn("MVC-IO", self.rules("path.write_text('x')", path))
        for call in (
            "path.open('rb')",
            "path.is_dir()",
            "path.stat()",
            "clock.sleep(1)",
        ):
            with self.subTest(call=call):
                self.assertIn("MVC-IO", self.rules(call, path))
        self.assertIn("MVC-IO", self.rules("self.service.list_projects()", path))
        self.assertIn("MVC-IO", self.rules("command = lambda: path.read_text()", path))
        self.assertNotIn(
            "MVC-IO",
            self.rules("self._submit_io(lambda: path.read_text(), self.done)", path),
        )
        source = '''def callback(self) -> None:
    """Queue reading."""
    def read() -> str:
        """Read stored text.

        Returns:
            str: Stored text.
        """
        return path.read_text()
    self._io.submit(read, self.done)
'''
        self.assertNotIn("MVC-IO", self.rules(source, path))
        self.assertIn(
            "MVC-IO",
            self.rules(
                source.replace("self._io.submit(read, self.done)", "read()"), path
            ),
        )


if __name__ == "__main__":
    unittest.main()
