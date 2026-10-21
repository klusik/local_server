"""Enforce documentation, annotation and MVC boundaries without importing the app."""

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT: Path = Path(__file__).resolve().parents[1]
BACKEND: frozenset[str] = frozenset({"core", "components", "runtime", "services"})
BLOCKING_MODULES: frozenset[str] = frozenset(
    {"subprocess", "socket", "http", "urllib", "shutil"}
)
FILE_OPERATIONS: frozenset[str] = frozenset(
    {
        "open",
        "read",
        "write",
        "read_text",
        "read_bytes",
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "rmdir",
        "stat",
        "lstat",
        "is_file",
        "is_dir",
        "iterdir",
        "glob",
        "rglob",
        "resolve",
        "rename",
        "sleep",
    }
)


@dataclass(frozen=True)
class Finding:
    """One actionable policy violation with its source location."""

    path: str
    line: int
    rule: str
    message: str


def dotted(node: ast.AST) -> str:
    """Resolve a syntactic attribute chain without executing any source.

    Args:
        node (ast.AST): Expression representing an imported name or attribute.

    Returns:
        str: Dotted expression, or an empty string for a computed expression.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted(node.value)}.{node.attr}".strip(".")
    return ""


def imported_modules(node: ast.Import | ast.ImportFrom, module: str) -> list[str]:
    """Resolve absolute and relative import destinations for layer checks.

    Args:
        node (ast.Import | ast.ImportFrom): Import statement to inspect.
        module (str): Fully qualified module containing the import.

    Returns:
        list[str]: Imported modules, including names imported from a package.
    """
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    prefix = module.split(".")[: -node.level] if node.level else []
    base = ".".join([*prefix, *([node.module] if node.module else [])])
    return [base, *(f"{base}.{alias.name}" for alias in node.names)]


def annotation_name(node: ast.expr) -> str:
    """Normalize a native annotation or a quoted forward reference for doc checks.

    Args:
        node (ast.expr): Type annotation from a function signature.

    Returns:
        str: Comparable annotation text without insignificant whitespace.
    """
    value = node.value if isinstance(node, ast.Constant) else None
    text = value if isinstance(value, str) else ast.unparse(node)
    return re.sub(r"\s+", "", text)


def check_source(source: str, path: str) -> list[Finding]:
    """Inspect Python text for project policy violations.

    Args:
        source (str): UTF-8 source text to parse, never execute.
        path (str): Repository-relative source path used for layer checks.

    Returns:
        list[Finding]: Documentation, compatibility and architecture violations.
    """
    findings: list[Finding] = []

    def report(line: int, rule: str, message: str) -> None:
        """Record one source finding.

        Args:
            line (int): One-based source line.
            rule (str): Stable policy rule identifier.
            message (str): Actionable explanation of the violation.
        """
        findings.append(Finding(path, line, rule, message))

    try:
        tree = ast.parse(source, filename=path, feature_version=(3, 14))
    except SyntaxError as exc:
        return [Finding(path, exc.lineno or 1, "PY314", str(exc.msg))]
    for number, line in enumerate(source.splitlines(), 1):
        if len(line.expandtabs(4)) > 100:
            report(number, "WIDTH", "Keep every source line within 100 columns.")
    parts = Path(path).with_suffix("").parts
    module = ".".join(parts[1:]) if parts[0] == "src" else ".".join(parts)
    layer = parts[2] if len(parts) > 2 and parts[:2] == ("src", "local_server") else ""
    if parts[-1] == "__init__":
        module += ".__init__" if not module.endswith(".__init__") else ""

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(alias.name == "annotations" for alias in node.names):
                report(
                    node.lineno,
                    "FUTURE",
                    "Use native Python 3.14 annotations and quoted forward references.",
                )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for imported in imported_modules(node, module):
                if layer in BACKEND and (
                    imported == "tkinter"
                    or imported.startswith("tkinter.")
                    or imported == "local_server.ui"
                    or imported.startswith("local_server.ui.")
                    or imported == "local_server.app"
                ):
                    report(
                        node.lineno,
                        "MVC",
                        "Backend code must not depend on Tkinter, UI or the composition root.",
                    )
                if layer == "core" and any(
                    imported == f"local_server.{name}"
                    or imported.startswith(f"local_server.{name}.")
                    for name in BACKEND - {"core"}
                ):
                    report(
                        node.lineno,
                        "MVC",
                        "Core models and persistence must not import higher layers.",
                    )
                if layer == "ui" and imported.split(".")[0] in BLOCKING_MODULES:
                    report(
                        node.lineno,
                        "MVC",
                        "Network and process implementations belong in backend services.",
                    )
                if layer != "ui" and layer not in BACKEND and path.startswith("src/"):
                    if imported.startswith("tkinter") and module != "local_server.app":
                        report(
                            node.lineno,
                            "MVC",
                            "Keep Tkinter inside UI or the application composition root.",
                        )
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node) or ""
            if not doc:
                report(
                    node.lineno,
                    "DOC",
                    "Explain what this function does in a docstring.",
                )
            args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            args += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
            for arg in args:
                if arg.arg in {"self", "cls"}:
                    continue
                if arg.annotation is None:
                    report(node.lineno, "TYPE", f"Annotate parameter {arg.arg}.")
                pattern = rf"^    \*{{0,2}}{re.escape(arg.arg)} \([^\n]+\):[ \t]*\S"
                documented = re.search(pattern, doc, re.MULTILINE)
                if "\nArgs:\n" not in doc or not documented:
                    report(
                        node.lineno,
                        "ARGS",
                        f"Document {arg.arg} as 'name (type): explanation' in Google Args.",
                    )
                elif arg.annotation is not None:
                    entry = documented.group().split("(", 1)[1].rsplit("):", 1)[0]
                    actual = re.sub(r"\s+", "", entry)
                    expected = annotation_name(arg.annotation)
                    # Long generic signatures may use their outer container name.
                    if actual not in {expected, expected.split("[", 1)[0]}:
                        report(
                            node.lineno,
                            "DOC-TYPE",
                            f"Docstring type for {arg.arg} differs from its annotation.",
                        )
            if node.returns is None:
                report(
                    node.lineno, "TYPE", "Annotate the return value, including -> None."
                )
            elif ast.unparse(node.returns) != "None":
                if not re.search(r"\n(?:Returns|Yields):\n    [^\n]+:[ \t]*\S", doc):
                    report(
                        node.lineno,
                        "RETURN",
                        "Document the result type and meaning in Google Returns or Yields.",
                    )

    if layer == "ui":
        findings.extend(check_ui_calls(tree, path))
    return findings


def check_ui_calls(tree: ast.Module, path: str) -> list[Finding]:
    """Reject direct blocking work in UI callbacks while recognizing worker handoff.

    Args:
        tree (ast.Module): Parsed UI module.
        path (str): Repository-relative source path used for layer checks.

    Returns:
        list[Finding]: Direct disk, network, process or persistence calls on the UI
            thread.
    """
    workers: set[ast.AST] = set()
    parents = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or dotted(node.func) not in {
            "self._submit_io",
            "self._io.submit",
        }:
            continue
        if not node.args:
            continue
        operation = node.args[0]
        if isinstance(operation, ast.Lambda):
            workers.add(operation)
        if isinstance(operation, ast.Name):
            scope: ast.AST = node
            while scope in parents and not isinstance(
                scope, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                scope = parents[scope]
            workers.update(
                child
                for child in ast.walk(scope)
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child is not scope
                and child.name == operation.id
            )

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        ancestor: ast.AST = node
        while ancestor in parents and ancestor not in workers:
            ancestor = parents[ancestor]
        if ancestor in workers:
            continue
        called = dotted(node.func)
        name = node.func.attr if isinstance(node.func, ast.Attribute) else called
        backend = any(
            part in called.split(".")
            for part in {"service", "store", "manager", "supervisor", "controller"}
        )
        blocking = (
            name in FILE_OPERATIONS
            or called
            in {"open", "time.sleep", "webbrowser.open", "os.system", "os.popen"}
            or backend
            and name
            in {
                "load",
                "save",
                "inventory",
                "install",
                "remove",
                "start",
                "stop",
                "restart",
                "list_projects",
                "create_project",
                "update_project",
                "delete_project",
            }
        )
        if blocking:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    "MVC-IO",
                    "Submit blocking work to a backend worker "
                    "instead of running it in a UI callback.",
                )
            )
    return findings


def main() -> int:
    """Check all owned Python source, tests and development tools.

    Returns:
        int: Zero for a clean repository, or one when a policy violation is found.
    """
    findings = [
        finding
        for directory in ("src", "tests", "tools")
        for path in sorted((ROOT / directory).rglob("*.py"))
        for finding in check_source(
            path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix()
        )
    ]
    for finding in findings:
        print(f"{finding.path}:{finding.line}: {finding.rule} {finding.message}")
    print(f"Source policy: {len(findings)} violation(s)")
    return int(bool(findings))


if __name__ == "__main__":
    sys.exit(main())
