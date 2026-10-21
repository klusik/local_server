"""Explicitly tracked foreground processes for managed private binaries."""

import os
import re
import subprocess
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Mapping, Sequence

from local_server.core.paths import AppPaths, reject_links

if TYPE_CHECKING:
    from .windows_job import WindowsJob, WindowsProcess

_PROCESS_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


@dataclass(slots=True)
class ManagedProcess:
    """A directly tracked child process, not a system daemon."""

    name: str
    handle: "subprocess.Popen[bytes] | WindowsProcess"
    log_file: Path
    job: "WindowsJob | None" = None

    @property
    def running(self) -> bool:
        """Report whether the owned child process remains alive.

        Returns:
            bool: Whether the directly owned child has not yet exited.
        """
        return self.handle.poll() is None


class ProcessSupervisor:
    """Start and stop non-daemonizing binaries installed in application storage."""

    def __init__(self, paths: AppPaths) -> None:
        """Track children and logs within application-managed storage.

        Args:
            paths (AppPaths): Application-managed storage layout.
        """
        self.paths = paths
        self._children: dict[str, ManagedProcess] = {}

    def start(
        self,
        name: str,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str] | None = None,
        contain: bool = False,
        private_log: Path | None = None,
        private_input: Path | None = None,
    ) -> ManagedProcess:
        """Start one private executable with no shell or global service install.

        Args:
            name (str): Logical child-process name used for ownership and log lookup.
            argv (Sequence[str]): Executable path followed by literal process arguments.
            cwd (Path): Existing working directory for the child process.
            env (Mapping[str, str] | None): Explicit child environment, or None to
                inherit the current environment.
            contain (bool): Whether to require Windows job containment for the child
                tree.
            private_log (Path | None): Optional private log path overriding the ordinary
                process log.
            private_input (Path | None): Optional private file for child standard input.

        Returns:
            ManagedProcess: Handle wrapper for the directly owned child process.
        """
        if not _PROCESS_NAME.fullmatch(name):
            raise ValueError("Invalid managed process name")
        current = self._children.get(name)
        if current is not None and current.running:
            raise RuntimeError(f"Process {name} is already running")
        if current is not None:
            self.stop(name)
        if not argv or not all(isinstance(arg, str) for arg in argv):
            raise ValueError("argv must contain strings")
        executable = Path(argv[0]).resolve()
        reject_links(self.paths.components, Path(argv[0]))
        try:
            executable.relative_to(self.paths.components.resolve())
        except ValueError as exc:
            raise ValueError(
                "Executable must be inside the managed components directory"
            ) from exc
        if not executable.is_file():
            raise FileNotFoundError(executable)
        if not Path(cwd).is_dir():
            raise ValueError("Process working directory does not exist")

        self.paths.ensure()
        log_file = (
            private_log if private_log is not None else self.paths.logs / f"{name}.log"
        )
        reject_links(self.paths.root, log_file)
        if private_input is not None:
            reject_links(self.paths.root, private_input)
        arguments = [str(executable), *argv[1:]]
        handle: subprocess.Popen[bytes] | WindowsProcess
        job = None
        if contain:
            if os.name != "nt":
                raise NotImplementedError(
                    "Contained runtime execution requires Windows"
                )
            from .windows_job import WindowsJob

            job = WindowsJob()
        try:
            with ExitStack() as stack:
                log_stream = stack.enter_context(log_file.open("ab"))
                input_stream = (
                    stack.enter_context(private_input.open("rb"))
                    if private_input
                    else None
                )
                if job:
                    kwargs = (
                        {"input_descriptor": input_stream.fileno()}
                        if input_stream
                        else {}
                    )
                    handle = job.start(
                        arguments,
                        cwd=cwd,
                        env=env,
                        log_descriptor=log_stream.fileno(),
                        **kwargs,
                    )
                else:
                    handle = subprocess.Popen(
                        arguments,
                        cwd=cwd,
                        stdout=log_stream,
                        stderr=subprocess.STDOUT,
                        stdin=input_stream if input_stream else subprocess.DEVNULL,
                        shell=False,
                        close_fds=True,
                        env=dict(env) if env is not None else None,
                    )
        except BaseException:
            if job:
                job.close()
            raise
        managed = ManagedProcess(name=name, handle=handle, log_file=log_file, job=job)
        self._children[name] = managed
        return managed

    def status(self, name: str) -> str:
        """Return running/stopped/unmanaged for a tracked child.

        Args:
            name (str): Logical child-process name used for ownership and log lookup.

        Returns:
            str: One of running, stopped or unmanaged for the named child.
        """
        current = self._children.get(name)
        if current is None:
            return "unmanaged"
        return "running" if current.running else "stopped"

    def stop(self, name: str, *, timeout: float = 5.0) -> bool:
        """Stop only the named owned child, escalating after a bounded timeout.

        Args:
            name (str): Logical child-process name used for ownership and log lookup.
            timeout (float): Maximum wait in seconds, or None for an unbounded wait.

        Returns:
            bool: Whether a tracked child existed and was stopped.
        """
        current = self._children.get(name)
        if current is None:
            return False
        if current.job:
            current.job.close()
            current.handle.wait(timeout=timeout)
        elif current.running:
            current.handle.terminate()
            try:
                current.handle.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                current.handle.kill()
                current.handle.wait()
        self._children.pop(name, None)
        return True

    def stop_all(self) -> None:
        """Stop every child started through this supervisor."""
        for name in list(self._children):
            self.stop(name)
