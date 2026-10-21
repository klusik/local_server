"""Reserved MySQL adapter boundary for private data directories."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, TypedDict

from local_server.components.catalog import PackageSpec
from local_server.core.models import ProjectProfile
from local_server.core.paths import AppPaths, reject_links
from .ownership import OwnershipLock
from .ports import PortReservation
from .processes import ManagedProcess, ProcessSupervisor
from .secrets import WindowsCredentialStore, restrict_directory


class AccountRecord(TypedDict):
    """Non-secret inventory of one managed database account."""

    database: str
    user: str
    credential: str
    state: str


class DatabaseInventory(TypedDict):
    """Application databases and account metadata from one project instance."""

    databases: list[str]
    accounts: list[AccountRecord]


def _quoted(path: Path) -> str:
    value = path.resolve().as_posix()
    if any(character in value for character in '\"\r\n\x00'):
        raise ValueError("Unsupported MySQL configuration path")
    return '"' + value + '"'


def mysql_environment() -> dict[str, str]:
    """Ignore inherited client passwords, plugins and option-file overrides."""
    return {key: value for key, value in os.environ.items()
            if not key.upper().startswith(("MYSQL", "LIBMYSQL"))}


def render_mysql_config(package: Path, data: Path, config: Path, port: int,
                        *, error_log: Path | None = None) -> str:
    """Render only a loopback SQL listener, with no automatic data upgrades."""
    return (f"[mysqld]\nbasedir={_quoted(package)}\ndatadir={_quoted(data)}\n"
            f"port={port}\nbind-address=127.0.0.1\nmysqlx=0\n"
            "named-pipe=OFF\nshared-memory=OFF\npersisted-globals-load=OFF\n"
            "upgrade=NONE\nlocal-infile=OFF\nsecure-file-priv=NULL\n"
            "general-log=OFF\nslow-query-log=OFF\nskip-log-bin\n"
            f"pid-file={_quoted(config / 'mysql.pid')}\n"
            f"tmpdir={_quoted(config / 'tmp')}\n"
            f"log-error={_quoted(error_log or config / 'mysql-error.log')}\n")


class MysqlAdapter:
    """Pending secure initialisation, secrets handling and process supervision."""

    def __init__(self, paths: AppPaths, project: ProjectProfile, package: PackageSpec,
                 package_dir: Path, supervisor: ProcessSupervisor, cancelled: threading.Event,
                 *, vault: WindowsCredentialStore | None = None,
                 progress: Callable[[str], None] | None = None) -> None:
        self.paths, self.project, self.package = paths, project, package
        self.package_dir, self.supervisor, self.cancelled = package_dir, supervisor, cancelled
        self.vault = vault or WindowsCredentialStore()
        self.progress = progress or (lambda _state: None)
        self.directory = paths.databases / str(uuid.UUID(project.id))
        self.config = paths.project_config_dir(project.id) / "mysql"
        self.name = "mysql-" + project.id
        self.database = "ls" + uuid.UUID(project.id).hex
        self.user = "ls" + uuid.UUID(project.id).hex[:20]
        self.passwords: dict[str, str] = {}
        self.identity: dict[str, str | int] = {}
        self.lock: OwnershipLock | None = None
        self.process: ManagedProcess | None = None
        self.private: tempfile.TemporaryDirectory[str] | None = None
        self.fresh = False
        self.transients: set[str] = set()

    def _cancel(self) -> None:
        if self.cancelled.is_set():
            raise RuntimeError("MySQL startup cancelled; existing database data is preserved")

    def _record_bootstrap_failure(self) -> None:
        if self.private is None:
            return
        lines = []
        for path in Path(self.private.name).glob("*.err"):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "[ERROR]" in line and "temporary password" not in line.lower():
                    for password in self.passwords.values():
                        line = line.replace(password, "[redacted]")
                    lines.append(re.sub(r"'[^']*'", "'[redacted]'", line))
        if lines:
            with (self.config / "mysql-error.log").open("a", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")

    def _write_identity(self, state: str) -> None:
        self.identity["state"] = state
        temporary = self.directory / "identity.tmp"
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(self.identity, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.directory / "identity.json")

    def _load_identity(self) -> None:
        try:
            self.identity = json.loads((self.directory / "identity.json").read_text(encoding="utf-8"))
            if (not isinstance(self.identity, dict) or self.identity.get("schema") != 1
                    or self.identity.get("project") != self.project.id
                    or self.identity.get("package") != self.package.key
                    or self.identity.get("state") != "ready"
                    or not self.identity.get("server_uuid")):
                raise ValueError("incompatible identity")
            uuid.UUID(str(self.identity["server_uuid"]))
            uuid.UUID(str(self.identity["credential"]))
            for filename in ("auto.cnf", "ibdata1", "mysql.ibd"):
                if not (self.directory / "datadir" / filename).is_file():
                    raise ValueError("missing database files")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise RuntimeError("MySQL datadir is incomplete, unknown, or belongs to another project/package. "
                               "Select the original exact MySQL package. No upgrade, migration, "
                               "replacement database or automatic recovery was performed.") from exc
        self.passwords = self.vault.get(str(self.identity["credential"]))
        if set(self.passwords) != {"root", "project"}:
            raise RuntimeError("Stored MySQL administration credentials are incomplete; data is preserved")

    def _client(self, *, admin: bool = False, shutdown: bool = False,
                sql: str | None = None) -> str:
        # All output is private: account errors must never enter general logs.
        assert self.private is not None
        private = Path(self.private.name)
        options = private / ("client-" + uuid.uuid4().hex + ".ini")
        output = options.with_suffix(".out")
        input_file = options.with_suffix(".sql")
        password = self.passwords["root" if admin else "project"]
        # Generated passwords use only ASCII alphanumerics, '-' and '_'.
        if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in password):
            raise RuntimeError("Stored MySQL password has an unsupported encoding")
        options.write_text("[client]\nprotocol=TCP\nhost=127.0.0.1\n"
                           f"port={self.project.mysql_port}\nuser={'root' if admin else self.user}\n"
                           f"password={password}\nconnect-timeout=2\nget-server-public-key\n",
                           encoding="utf-8")
        name = "mysql-client-" + self.project.id
        executable = self.package_dir / "bin" / ("mysqladmin.exe" if shutdown else "mysql.exe")
        argv = [str(executable), "--defaults-file=" + str(options), "--no-login-paths"]
        if shutdown:
            argv += ["shutdown"]
        else:
            argv += ["--batch", "--skip-column-names", "--database=" + self.database]
            input_file.write_text(sql or "SELECT CONCAT('1|',@@version,'|',@@server_uuid,'|',DATABASE());\n",
                                  encoding="utf-8")
        try:
            child = self.supervisor.start(name, argv, cwd=self.config, contain=True,
                                          env=mysql_environment(), private_log=output,
                                          private_input=None if shutdown else input_file)
            self.transients.add(name)
            if child.handle.wait(timeout=5) != 0:
                raise OSError("MySQL authenticated SQL connection failed (credentials, port or database).")
            return output.read_text(encoding="utf-8").strip()
        except subprocess.TimeoutExpired:
            raise OSError("MySQL authenticated SQL operation timed out") from None
        finally:
            self.supervisor.stop(name)
            self.transients.discard(name)
            options.unlink(missing_ok=True)
            output.unlink(missing_ok=True)
            input_file.unlink(missing_ok=True)

    def probe(self, *, admin: bool = False) -> None:
        """Authenticate, execute SQL and match the exact server/database identity."""
        output = self._client(admin=admin)
        fields = output.split("|")
        if (len(fields) != 4 or fields[0] != "1" or fields[1] != self.package.version
                or fields[3] != self.database):
            raise OSError("MySQL SQL result/version/database mismatch")
        try:
            uuid.UUID(fields[2])
        except ValueError:
            raise OSError("MySQL server identity is invalid") from None
        if self.identity.get("server_uuid") and fields[2] != self.identity["server_uuid"]:
            raise OSError("MySQL server identity mismatch")
        self.identity["server_uuid"] = fields[2]

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + 60
        while True:
            self._cancel()
            if self.process is None or not self.process.running:
                raise RuntimeError("Owned MySQL process exited during startup. See MySQL logs.")
            try:
                self.probe()
                self.probe(admin=True)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("MySQL SQL health check failed: credentials, startup or port handoff. "
                                       "Database files are preserved; see MySQL logs.") from None
                time.sleep(0.2)

    def _launch(self, data: Path, *, bootstrap: bool = False) -> None:
        assert self.private is not None
        self._cancel()
        reservation = PortReservation(self.project.mysql_port)
        try:
            private = Path(self.private.name)
            ini = self.config / "my.ini"
            ini.write_text(render_mysql_config(self.package_dir, data, self.config, self.project.mysql_port,
                           error_log=private / "bootstrap.err" if bootstrap else None), encoding="utf-8")
            argv = [str(self.package_dir / self.package.entrypoint), "--defaults-file=" + str(ini)]
            if bootstrap:
                argv.append("--init-file=" + str(private / "bootstrap.sql"))
            reservation.close()
            self.process = self.supervisor.start(self.name, argv, cwd=self.config, contain=True,
                env=mysql_environment(), private_log=private / "bootstrap.out" if bootstrap else None)
            self._wait_ready()
        finally:
            reservation.close()

    def _shutdown(self) -> None:
        if self.process is None:
            return
        if self.process.running:
            try:
                # A port alone never authorizes stopping a server.
                self.probe(admin=True)
                self._client(admin=True, shutdown=True)
                self.process.handle.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                pass  # Escalate only this tracked process/job after the bounded attempt.
        self.supervisor.stop(self.name)
        self.process = None

    def start(self) -> None:
        """Never initialize an unsecured database or global machine service."""
        self._cancel()
        for path in (self.directory, self.config, self.paths.databases / (self.project.id + ".lock")):
            reject_links(self.paths.root, path)
        try:
            self.lock = OwnershipLock(self.paths.databases / (self.project.id + ".lock"))
        except OSError:
            raise RuntimeError("MySQL datadir is in use by another Local Server instance") from None
        try:
            self.config.mkdir(parents=True, exist_ok=True)
            for path in self.config.rglob("*"):
                reject_links(self.paths.root, path)
            restrict_directory(self.config)
            # Only our private transient output is recovered, under the data lease.
            # Even an incomplete datadir is left untouched after an owner crash.
            for path in self.config.glob("sensitive-*"):
                if path.is_dir():
                    shutil.rmtree(path)
            # Reject nested reparse points before opening state or executing MySQL.
            if self.directory.exists():
                for path in self.directory.rglob("*"):
                    reject_links(self.paths.root, path)
                self._load_identity()
            (self.config / "tmp").mkdir(exist_ok=True)
            for path in self.config.rglob("*"):
                reject_links(self.paths.root, path)
            self.private = tempfile.TemporaryDirectory(prefix="sensitive-", dir=self.config)
            restrict_directory(Path(self.private.name))
            # Fail before initializing anything when a foreign listener owns the port.
            try:
                check = PortReservation(self.project.mysql_port)
            except OSError:
                raise RuntimeError(f"MySQL port {self.project.mysql_port} is occupied. Choose another port.") from None
            check.close()
            if not self.directory.exists():
                self.progress("initializing")
                self.directory.mkdir()
                self.fresh = True
                restrict_directory(self.directory)
                self.passwords = {"root": secrets.token_urlsafe(36), "project": secrets.token_urlsafe(36)}
                self.identity = {"schema": 1, "project": self.project.id, "package": self.package.key,
                                 "credential": str(uuid.uuid4())}
                self.vault.put(str(self.identity["credential"]), self.passwords)
                self._write_identity("initializing")
                self._initialize()
            self.progress("starting")
            self._launch(self.directory / "datadir")
        except BaseException:
            try:
                self._record_bootstrap_failure()
            except OSError:
                pass
            self.stop()
            raise

    def _initialize(self) -> None:
        assert self.private is not None
        private = Path(self.private.name)
        data = self.directory / "staging-data"
        argv = [str(self.package_dir / self.package.entrypoint), "--no-defaults", "--initialize",
                "--basedir=" + str(self.package_dir), "--datadir=" + str(data),
                "--log-error=" + str(private / "initialize.err")]
        name = "mysql-init-" + self.project.id
        child = self.supervisor.start(name, argv, cwd=self.config, contain=True,
                                     env=mysql_environment(), private_log=private / "initialize.out")
        self.transients.add(name)
        try:
            deadline = time.monotonic() + 120
            while child.running:
                self._cancel()
                if time.monotonic() >= deadline:
                    raise RuntimeError("MySQL initialization timed out")
                time.sleep(0.1)
            if child.handle.wait() != 0:
                raise RuntimeError("Secure MySQL initialization failed; sensitive bootstrap output is withheld")
        finally:
            self.supervisor.stop(name)
            self.transients.discard(name)
        # The documented init-file bootstrap runs at first NORMAL startup.
        # Account management is deliberately not attempted inside --initialize.
        (private / "bootstrap.sql").write_text(
            "ALTER USER 'root'@'localhost' IDENTIFIED BY '" + self.passwords["root"] + "';\n"
            f"CREATE DATABASE `{self.database}`;\n"
            f"CREATE USER '{self.user}'@'127.0.0.1' IDENTIFIED BY '{self.passwords['project']}';\n"
            f"CREATE USER '{self.user}'@'localhost' IDENTIFIED BY '{self.passwords['project']}';\n"
            f"GRANT ALL PRIVILEGES ON `{self.database}`.* TO '{self.user}'@'127.0.0.1';\n"
            f"GRANT ALL PRIVILEGES ON `{self.database}`.* TO '{self.user}'@'localhost';\n",
            encoding="utf-8")
        self._launch(data, bootstrap=True)
        self._shutdown()
        self._cancel()
        data.rename(self.directory / "datadir")
        self._write_identity("ready")
        self.fresh = False
        for path in private.iterdir():
            path.unlink()

    def stop(self) -> None:
        """Gracefully stop the owned server, then release its data ownership lease."""
        for name in self.transients.copy():
            self.supervisor.stop(name)
            self.transients.discard(name)
        self._shutdown()
        if self.private:
            self.private.cleanup()
            self.private = None
        if self.fresh:
            # Only files created in THIS transaction are discarded. An incomplete
            # directory found at startup is never deleted or silently retried.
            for path in self.directory.rglob("*"):
                reject_links(self.paths.root, path)
            shutil.rmtree(self.directory)
            self.fresh = False
            if self.identity.get("credential"):
                self.vault.delete(str(self.identity["credential"]))
        self.passwords.clear()
        if self.lock:
            self.lock.close()
            self.lock = None

    def connection(self, *, reveal: bool = False) -> dict[str, str | int]:
        """Expose project connection fields; disclose its password only on request."""
        result: dict[str, str | int] = {"host": "127.0.0.1", "port": self.project.mysql_port,
                                      "database": self.database, "user": self.user}
        if reveal:
            result["password"] = self.passwords["project"]
        return result

    @staticmethod
    def _identifier(value: str, *, user: bool = False) -> str:
        pattern = r"[a-z][a-z0-9_]{0,31}" if user else r"[a-z][a-z0-9]{0,47}"
        if not isinstance(value, str) or not re.fullmatch(pattern, value):
            raise ValueError("Use lowercase ASCII letters and digits" +
                             ("/underscores (up to 32 characters)" if user else " (up to 48 characters)") +
                             "; start with a letter")
        if value in {"mysql", "sys", "information_schema", "performance_schema", "root"} or value.startswith("mysql"):
            raise ValueError("This MySQL name is reserved")
        return value

    def _accounts(self) -> list[AccountRecord]:
        path = self.directory / "accounts.json"
        if not path.exists():
            return []
        reject_links(self.paths.root, path)
        records = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(records, list):
            raise RuntimeError("MySQL account inventory is invalid")
        for record in records:
            if not isinstance(record, dict) or set(record) != {"database", "user", "credential", "state"}:
                raise RuntimeError("MySQL account inventory is invalid")
            self._identifier(record["database"])
            self._identifier(record["user"], user=True)
            uuid.UUID(record["credential"])
            if record["state"] not in {"creating", "ready"}:
                raise RuntimeError("MySQL account state is invalid")
        return records

    def _save_accounts(self, records: list[AccountRecord]) -> None:
        path = self.directory / "accounts.tmp"
        reject_links(self.paths.root, path)
        reject_links(self.paths.root, self.directory / "accounts.json")
        with path.open("w", encoding="utf-8") as stream:
            json.dump(records, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(path, self.directory / "accounts.json")

    def databases(self) -> DatabaseInventory:
        """List this instance's application databases and managed account grants."""
        self.probe(admin=True)
        output = self._client(admin=True, sql="SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA "
            "WHERE SCHEMA_NAME NOT IN ('mysql','sys','information_schema','performance_schema') ORDER BY SCHEMA_NAME;")
        return {"databases": output.splitlines(), "accounts": self._accounts()}

    def create_database(self, name: str) -> DatabaseInventory:
        """Create an empty database only in this project's authenticated instance."""
        name = self._identifier(name)
        self.probe(admin=True)
        self._client(admin=True, sql=f"CREATE DATABASE `{name}`;")
        return self.databases()

    def create_user(self, database: str, user: str) -> DatabaseInventory:
        """Create a local account granted only one database; preserve partial DDL on error."""
        database, user = self._identifier(database), self._identifier(user, user=True)
        inventory = self.databases()
        if database not in inventory["databases"]:
            raise ValueError("Select an existing database in this project")
        records = inventory["accounts"]
        if user == self.user or any(record["user"] == user for record in records):
            raise ValueError("This account already exists or has an incomplete creation; choose a new name")
        reference, password = str(uuid.uuid4()), secrets.token_urlsafe(36)
        self.vault.put(reference, {"password": password})
        record: AccountRecord = {"database": database, "user": user, "credential": reference, "state": "creating"}
        records.append(record)
        try:
            self._save_accounts(records)
        except BaseException:
            self.vault.delete(reference)
            raise
        try:
            self._client(admin=True, sql=(
                f"CREATE USER '{user}'@'127.0.0.1' IDENTIFIED BY '{password}';\n"
                f"CREATE USER '{user}'@'localhost' IDENTIFIED BY '{password}';\n"
                f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{user}'@'127.0.0.1';\n"
                f"GRANT ALL PRIVILEGES ON `{database}`.* TO '{user}'@'localhost';\n"))
        except OSError:
            raise RuntimeError("MySQL account creation did not finish. Any partial account/database and "
                               "its saved credentials are preserved; no DDL was undone. See account state.") from None
        record["state"] = "ready"
        self._save_accounts(records)
        return self.databases()

    def account_connection(self, user: str) -> dict[str, str | int]:
        """Reveal only the explicitly requested managed application's password."""
        record = next((record for record in self._accounts() if record["user"] == user), None)
        if record is None or record["state"] != "ready":
            raise ValueError("Select a successfully created account")
        values = self.connection()
        values.update(user=record["user"], database=record["database"],
                      password=self.vault.get(record["credential"])["password"])
        return values
