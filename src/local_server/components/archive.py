"""Safe ZIP/tar.gz extraction into newly created private staging directories."""

from __future__ import annotations

import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Callable

MAX_ARCHIVE_ENTRIES = 20_000
MAX_UNPACKED_BYTES = 4 * 1024**3

Check = Callable[[], None]
Progress = Callable[[int, int], None]


def _noop() -> None:
    pass


class ArchiveSafetyError(ValueError):
    """An archive contains an unsafe path, link, or unsupported entry."""


def _relative_path(name: str, strip_components: int) -> Path | None:
    """Map an archive member to a safe relative path or a skipped root directory."""
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/") or "\x00" in normalized:
        raise ArchiveSafetyError(f"Unsafe archive path: {name!r}")
    chunks = normalized.split("/")
    if any(chunk == ".." for chunk in chunks):
        raise ArchiveSafetyError(f"Unsafe archive path: {name!r}")
    pieces = [chunk for chunk in chunks if chunk not in {"", "."}]
    windows_devices = {"CON", "PRN", "AUX", "NUL"}
    windows_devices.update(f"COM{i}" for i in range(1, 10))
    windows_devices.update(f"LPT{i}" for i in range(1, 10))
    if any(
        any(ord(char) < 32 or char in '<>:"|?*' for char in part)
        or part.endswith((".", " "))
        or part.split(".", 1)[0].rstrip(" ").upper() in windows_devices
        or part.split(".", 1)[0].upper() in {"COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³"}
        or len(part) > 255
        for part in pieces
    ):
        raise ArchiveSafetyError(f"Unsafe Windows-compatible archive path: {name!r}")
    if len(pieces) <= strip_components:
        return None
    relative = PurePosixPath(*pieces[strip_components:])
    if relative.is_absolute():
        raise ArchiveSafetyError(f"Unsafe archive path: {name!r}")
    return Path(*relative.parts)


def _copy_checked(source: BinaryIO, destination: Path, maximum: int, check: Check = _noop, progress: Callable[[int], None] = lambda _size: None) -> int:
    """Write a single entry without exceeding its declared extraction budget."""
    copied = 0
    with destination.open("xb") as stream:
        while True:
            check()
            chunk = source.read(min(1024 * 1024, maximum - copied + 1))
            if not chunk:
                break
            copied += len(chunk)
            if copied > maximum:
                raise ArchiveSafetyError("Archive extraction size limit exceeded")
            stream.write(chunk)
            progress(len(chunk))
    return copied


def safe_extract(
    archive_path: Path,
    destination: Path,
    archive_type: str,
    *,
    strip_components: int = 0,
    check: Check = _noop,
    progress: Progress = lambda _done, _total: None,
) -> None:
    """Extract regular files only, rejecting traversal and all symbolic links.

    The caller must supply a new private staging directory. Archive paths are
    validated in a preflight pass before any files are written.
    """
    if archive_type not in {"zip", "tar.gz"}:
        raise ValueError("Unsupported archive type")
    if not isinstance(strip_components, int) or not 0 <= strip_components <= 5:
        raise ValueError("Invalid strip_components")
    destination = Path(destination)
    if (destination.is_symlink() or not destination.is_dir()
        or getattr(destination.lstat(), "st_file_attributes", 0) & 0x400
        or any(destination.iterdir())):
        raise ValueError("Extraction destination must be an empty directory")
    entries: list[tuple[object, Path | None, int, bool]] = []

    if archive_type == "zip":
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_ENTRIES:
                raise ArchiveSafetyError("Too many archive entries")
            for member in members:
                check()
                mode = member.external_attr >> 16
                kind = stat.S_IFMT(mode)
                if kind == stat.S_IFLNK or kind not in {0, stat.S_IFREG, stat.S_IFDIR} or member.external_attr & 0x400:
                    raise ArchiveSafetyError("Archive contains links or special files")
                if member.flag_bits & 1:
                    raise ArchiveSafetyError("Encrypted archives are not supported")
                path = _relative_path(member.filename, strip_components)
                is_dir = member.is_dir()
                entries.append((member, path, member.file_size, is_dir))
            _validate_entries(entries)
            _extract_zip(archive, destination, entries, check, progress)
    else:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for index, member in enumerate(archive):
                check()
                if index >= MAX_ARCHIVE_ENTRIES:
                    raise ArchiveSafetyError("Too many archive entries")
                if not (member.isfile() or member.isdir()):
                    raise ArchiveSafetyError("Archive contains links or special files")
                path = _relative_path(member.name, strip_components)
                entries.append((member, path, member.size, member.isdir()))
            _validate_entries(entries)
            _extract_tar(archive, destination, entries, check, progress)


def _validate_entries(
    entries: list[tuple[object, Path | None, int, bool]]
) -> None:
    """Preflight archive sizes, duplicate names and file/directory collisions."""
    seen: dict[str, bool] = {}
    total = 0
    for _member, relative, size, is_dir in entries:
        if size < 0:
            raise ArchiveSafetyError("Negative archive member size")
        if relative is None:
            if not is_dir:
                raise ArchiveSafetyError("strip_components would hide a file")
            continue
        key = relative.as_posix().casefold()
        if key in seen:
            raise ArchiveSafetyError(f"Duplicate archive path: {relative}")
        seen[key] = is_dir
        if not is_dir:
            total += size
        if total > MAX_UNPACKED_BYTES:
            raise ArchiveSafetyError("Archive extraction size limit exceeded")
    for relative in seen:
        for parent in Path(relative).parents:
            if parent != Path(".") and seen.get(parent.as_posix()) is False:
                raise ArchiveSafetyError("Archive file shadows a directory")


def _extract_zip(
    archive: zipfile.ZipFile,
    destination: Path,
    entries: list[tuple[object, Path | None, int, bool]],
    check: Check,
    progress: Progress,
) -> None:
    """Write validated ZIP members into the staging directory."""
    remaining = MAX_UNPACKED_BYTES
    total = sum(size for _, path, size, is_dir in entries if path is not None and not is_dir)
    done = 0
    def advance(size: int) -> None:
        nonlocal done
        done += size
        progress(done, total)
    for member, relative, _size, is_dir in entries:
        check()
        if relative is None:
            continue
        target = destination / relative
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(member) as source:
            copied = _copy_checked(source, target, min(remaining, _size), check, advance)
            if copied != _size:
                raise ArchiveSafetyError("Archive member size mismatch")
            remaining -= copied


def _extract_tar(
    archive: tarfile.TarFile,
    destination: Path,
    entries: list[tuple[object, Path | None, int, bool]],
    check: Check,
    progress: Progress,
) -> None:
    """Write validated TAR members without using unsafe extractall semantics."""
    remaining = MAX_UNPACKED_BYTES
    total = sum(size for _, path, size, is_dir in entries if path is not None and not is_dir)
    done = 0
    def advance(size: int) -> None:
        nonlocal done
        done += size
        progress(done, total)
    for member, relative, _size, is_dir in entries:
        check()
        if relative is None:
            continue
        target = destination / relative
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = archive.extractfile(member)
        if source is None:
            raise ArchiveSafetyError("Unreadable archive file")
        with source:
            copied = _copy_checked(source, target, min(remaining, _size), check, advance)
            if copied != _size:
                raise ArchiveSafetyError("Archive member size mismatch")
            remaining -= copied
        if stat.S_IMODE(member.mode) & 0o111:
            target.chmod(target.stat().st_mode | (stat.S_IMODE(member.mode) & 0o111))
