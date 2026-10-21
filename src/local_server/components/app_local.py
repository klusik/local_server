"""Acquire and copy only pinned MSVC DLLs beside a staged server executable."""

import hashlib
import json
import os
import struct
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import IO, Callable

from local_server.core.paths import AppPaths, reject_links

from .archive import safe_extract
from .runtime_bundle import RuntimeBundle

RUNTIME_RECEIPT = ".local-server-runtime.json"
Check = Callable[[], None]
Progress = Callable[[str, int, int], None]
Download = Callable[[RuntimeBundle, IO[bytes], Check, Progress], None]


class RuntimeIntegrityError(ValueError):
    """A reviewed app-local DLL or cached runtime has changed."""


def verify_runtime_files(
    bundle: RuntimeBundle, root: Path, *, deployed: bool, check: Check = lambda: None
) -> None:
    """Check each pinned DLL's bytes and x64 PE header without loading code.

    Args:
        bundle (RuntimeBundle): Reviewed runtime archive and per-file checksum metadata.
        root (Path): Private root directory containing the managed resource.
        deployed (bool): Whether paths refer to DLLs beside the server executable.
        check (Check): Callback that raises when cancellation is requested.
    """
    for dll in bundle.files:
        check()
        path = root / (dll.name if deployed else dll.source)
        reject_links(root, path)
        digest = hashlib.sha256()
        try:
            if path.stat().st_size > 64 * 1024**2:
                raise RuntimeIntegrityError(f"Runtime DLL is too large: {dll.name}")
            with path.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    check()
                    digest.update(block)
                stream.seek(0)
                header = stream.read(64)
                if len(header) != 64 or header[:2] != b"MZ":
                    raise RuntimeIntegrityError(
                        f"Runtime DLL is not a PE image: {dll.name}"
                    )
                offset = struct.unpack_from("<I", header, 60)[0]
                if offset > 1024 * 1024:
                    raise RuntimeIntegrityError("Invalid runtime DLL header")
                stream.seek(offset)
                pe = stream.read(6)
        except OSError as exc:
            raise RuntimeIntegrityError(
                f"Runtime DLL is missing or unreadable: {dll.name}"
            ) from exc
        if digest.hexdigest().lower() != dll.sha256.lower():
            raise RuntimeIntegrityError(f"Runtime DLL SHA-256 mismatch: {dll.name}")
        if (
            len(pe) != 6
            or pe[:4] != b"PE\0\0"
            or struct.unpack_from("<H", pe, 4)[0] != 0x8664
        ):
            raise RuntimeIntegrityError(f"Runtime DLL is not Windows x64: {dll.name}")


def prepare_runtime(
    bundle: RuntimeBundle,
    paths: AppPaths,
    *,
    download: Download,
    check: Check,
    progress: Progress,
    remove: Callable[[Path], None],
) -> Path:
    """Acquire a receipt-backed DLL cache while the caller holds the package lock.

    Args:
        bundle (RuntimeBundle): Reviewed runtime archive and per-file checksum metadata.
        paths (AppPaths): Application-managed storage layout.
        download (Download): Callback that acquires and verifies the reviewed runtime
            archive.
        check (Check): Callback that raises when cancellation is requested.
        progress (Progress): Worker callback reporting completed work without updating
            Tk.
        remove (Callable[[Path], None]): Whether to remove the selected package rather
            than install it.

    Returns:
        Path: Verified runtime cache directory ready for app-local deployment.
    """
    bundle.validate()
    target = paths.runtime_cache / bundle.id
    reject_links(paths.components, target)
    if target.exists():
        try:
            receipt = target / RUNTIME_RECEIPT
            reject_links(target, receipt)
            if receipt.stat().st_size > 64 * 1024:
                raise RuntimeIntegrityError("Oversized runtime receipt")
            cached = RuntimeBundle.from_dict(
                json.loads(receipt.read_text(encoding="utf-8"))
            )
            if cached != bundle:
                raise RuntimeIntegrityError(
                    "Runtime receipt differs from reviewed metadata"
                )
            verify_runtime_files(bundle, target, deployed=False, check=check)
            _verify_notices(bundle, target)
            return target
        except (OSError, ValueError):
            check()
            # A damaged cache is disposable. Refuse redirected trees in remove(),
            # then fetch the reviewed bytes again; never use an unchecked cache.
            remove(target)
    archive_name: str | None = None
    staging: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=paths.downloads, prefix=".package-", delete=False
        ) as stream:
            archive_name = stream.name
            download(bundle, stream, check, progress)
        staging = Path(tempfile.mkdtemp(dir=paths.downloads, prefix=".install-"))
        safe_extract(
            Path(archive_name),
            staging,
            "zip",
            check=check,
            progress=lambda done, total: progress("extracting", done, total),
        )
        verify_runtime_files(bundle, staging, deployed=False, check=check)
        _verify_notices(bundle, staging)
        with (staging / RUNTIME_RECEIPT).open("x", encoding="utf-8") as stream:
            json.dump(asdict(bundle), stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        check()
        os.rename(staging, target)
        staging = None
        return target
    finally:
        try:
            if archive_name:
                Path(archive_name).unlink(missing_ok=True)
        finally:
            if staging:
                remove(staging)


def _verify_notices(bundle: RuntimeBundle, root: Path) -> None:
    """Verify that reviewed license notices accompany the runtime files.

    Args:
        bundle (RuntimeBundle): Reviewed runtime archive and per-file checksum metadata.
        root (Path): Private root directory containing the managed resource.
    """
    for relative in bundle.notices:
        path = root / relative
        reject_links(root, path)
        if not path.is_file():
            raise RuntimeIntegrityError(f"Runtime license notice missing: {relative}")


def deploy_runtime(
    bundle: RuntimeBundle, cache: Path, executable_dir: Path, *, check: Check
) -> None:
    """Copy pinned DLLs and notices locally; never change PATH or system files.

    Args:
        bundle (RuntimeBundle): Reviewed runtime archive and per-file checksum metadata.
        cache (Path): Private directory containing verified runtime files.
        executable_dir (Path): Directory beside the staged server executable.
        check (Check): Callback that raises when cancellation is requested.
    """
    for dll in bundle.files:
        check()
        source = cache / dll.source
        destination = executable_dir / dll.name
        reject_links(cache, source)
        reject_links(executable_dir, destination)
        if destination.exists():
            if destination.stat().st_size > 64 * 1024**2:
                raise RuntimeIntegrityError(
                    f"Conflicting runtime DLL is too large: {dll.name}"
                )
            with destination.open("rb") as existing:
                digest = hashlib.file_digest(existing, "sha256").hexdigest()
            if digest.lower() != dll.sha256.lower():
                raise RuntimeIntegrityError(
                    f"Vendor archive contains a conflicting runtime DLL: {dll.name}"
                )
        else:
            _copy_file(source, destination, check)
    verify_runtime_files(bundle, executable_dir, deployed=True, check=check)
    notices_dir = executable_dir / ".local-server-runtime-notices" / bundle.id
    notices_dir.mkdir(parents=True, exist_ok=False)
    for relative in bundle.notices:
        check()
        target = notices_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _copy_file(cache / relative, target, check)


def _copy_file(source: Path, destination: Path, check: Check) -> None:
    """Copy a verified file while honoring cancellation.

    Args:
        source (Path): Validated input stream or file path.
        destination (Path): Private target path for the validated files.
        check (Check): Callback that raises when cancellation is requested.
    """
    with source.open("rb") as src, destination.open("xb") as dst:
        while block := src.read(256 * 1024):
            check()
            dst.write(block)
