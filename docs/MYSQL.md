# Per-project MySQL on Windows x64

Actual reviewed MySQL 8.4.13, PHP 8.4.26 NTS and Nginx 1.30.6 binaries have passed
the disposable Windows smoke test. Other combinations are not certified.

## Workflow

Download MySQL Community in Components, enable MySQL in Edit project, and choose
the exact package/variant and an unused SQL port. Old profiles retain
`mysql_enabled`; startup requires an explicit `mysql_package`. `mysql_port`
defaults to 3307. Start initializes first-use data and verifies SQL before starting
PHP/Nginx. Running additionally requires actual SQL through HTTP/mysqli and both
mysqli/PDO MySQL extensions loaded from the selected PHP package.

**DB** opens the project's database/user manager. Enter a database name and use
Create database. Select that database, enter a username and Create user. Each
account gets a generated password and privileges on that database only, without
global privileges or GRANT OPTION. Database names allow lowercase ASCII letters
and digits (48 characters); usernames also allow underscores (32 characters).
Both start with a letter. System/reserved names are refused.

Default connection shows the initial project database/user. Show password or
Show selected credentials reveals only the requested application password in a
selectable field. Clipboard copying is manual. Host is always `127.0.0.1`; use
the displayed SQL port. No administrator password is shown. Configure your own
application; no `.env`, source or website configuration is changed.

There are no drop/delete/reset/migration actions. Account DDL is not transactional:
failure preserves partial resources and their secret, records `creating`, and
refuses silently retrying/resetting that account. Deliberate external repair may
be needed. Successful accounts cannot see/query other application databases.

## Storage and isolation

```text
.local-server/
  data/<project-uuid>.lock             OS-released data lease
  data/<project-uuid>/
    identity.json                      project, exact package, server UUID, vault reference, phase
    accounts.json                      grants/vault references, no passwords
    datadir/                           persistent MySQL database files
    staging-data/                      first initialization, before promotion
  generated/<project-uuid>/mysql/
    my.ini                             regenerated paths/policy, no passwords
    mysql-error.log                     ordinary/redacted errors
    mysql.pid, tmp/
    sensitive-<random>/                 private short-lived bootstrap/client IO
```

An explicit `--data-dir` changes state location; binaries stay in `packages/`.
State/packages cannot overlap a document root. Every project has a separate
daemon, data, server UUID, administrator/application accounts and passwords.
Accounts lack global PROCESS/FILE/user-management privileges. This separates SQL
access within a shared Windows account: PHP can still read files that OS user can
access. It is not an OS sandbox for hostile PHP applications.

Data identity must match the project and exact package including variant.
Unknown/incomplete markers, missing critical files or a mismatching selection
fail before opening data. There is no automatic upgrade/downgrade/migration or
replacement database. `upgrade=NONE` also disables server upgrade steps. Rollback,
profile removal and package removal preserve existing database data.

## Secure initialization and lifecycle

Initialization uses vendor `--initialize`, never an insecure initialization.
MySQL's temporary expired root password goes only to private bootstrap output.
First NORMAL startup uses documented `--init-file` to set a strong random root
password and create the project database/restricted account. Account DDL is not
attempted within initialization mode. Authenticated SQL checks precede graceful
shutdown, staging promotion and a normal start. No temporary/default password is
used for a client login. Initialization failure/cancellation discards only data
created by that transaction; pre-existing incomplete data is refused and preserved.

Windows Credential Manager stores current-user/local-machine generic credentials
under random UUID targets. Only references go into data identity. Private
directories get a protected inheritable DACL for the current user and SYSTEM
before writing secrets; unsupported ACL filesystems fail closed. Official
`mysql.exe` receives SQL/passwords through private stdin/option files, with
`--no-login-paths`, a cleaned MySQL environment and no shell. No custom MySQL
authentication implementation or Python connector dependency is added. Client
processes are contained and time-limited. Private files/output are removed after
use; crash leftovers are cleaned under the data lease on the next attempt.
Unlinking does not guarantee secure disk erasure. Bootstrap error details are
redacted before being added to ordinary logs.

MySQL binds only `127.0.0.1`. X Plugin, named pipes and shared memory are disabled.
No admin address is configured, hence no admin listener. Persisted globals are
not loaded. General/slow/binary logs, local infile and server-side file import/
export are disabled. Port conflicts never authorize killing another process.
Socket release/bind remains non-atomic; owned-child checks plus authenticated
version/server-UUID/database queries detect an unsuccessful handoff.

Startup is MySQL → PHP → Nginx. Diagnostic PHP lives outside the website and
receives credentials in a private loopback POST, not a script, URL, argv or log.
The Nginx access log does not include its body. The PHP probe executes
`SELECT 1, @@server_uuid`. Missing PHP still fails closed against source disclosure.
Monitoring checks owned processes and authenticated SQL without repeatedly
occupying the PHP worker. All IO/process/SQL operations run on the runtime worker;
Tk updates widgets on its main thread.

Stop retires Nginx/PHP, verifies the owned database UUID and requests
`mysqladmin shutdown`. A bounded timeout falls back only to that tracked job.
Windows jobs terminate children after owner crashes. Package/project/data leases
protect cross-instance use, including different package roots sharing state.
Stale PIDs never authorize process adoption/termination. Closing cancels pending
startup and waits for cleanup off the Tk event loop.

## Portability and remaining limits

Close before moving the whole application and hidden state. An actual move to
another path with spaces preserved SQL contents, users and server identity.
Explicit external state needs separate copying/reassignment. Another Windows
user/computer lacks the original Credential Manager entries: startup explains
recovery and preserves data. Return to the original account/computer or restore
its vault credentials through a deliberate external procedure. Credential
export/import and password reset are not implemented.

The host still needs the catalog's VC++ x64 runtime. No concrete app-local MSVC
bundle is approved and clean Windows remains unsupported. The product does not
request elevation, install services/SDKs/compilers or change system PATH/registry.
macOS/ARM64, cross-machine vault restoration, backups/migrations, arbitrary PHP
extensions and the real gallery workload remain unverified. No phpMyAdmin/SQL
editor is added. Separate project daemons have a higher memory cost than sharing
a server.

## Vendor references

- [Secure initialization](https://dev.mysql.com/doc/refman/8.4/en/data-directory-initialization.html)
- [Windows init-file password assignment](https://dev.mysql.com/doc/refman/8.4/en/resetting-permissions.html)
- [Disabling X Plugin](https://dev.mysql.com/doc/refman/8.4/en/x-plugin-disabling.html)
- [Option/login-path isolation](https://dev.mysql.com/doc/refman/8.4/en/option-file-options.html)
- [Variables and absent-by-default admin interface](https://dev.mysql.com/doc/refman/8.4/en/server-system-variables.html)
- [Upgrade NONE](https://dev.mysql.com/doc/refman/8.4/en/upgrading-what-is-upgraded.html)
- [mysqladmin shutdown](https://dev.mysql.com/doc/refman/8.4/en/mysqladmin.html)
