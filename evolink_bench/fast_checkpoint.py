"""Opt-in, byte-preserving workspace snapshots using ordinary standalone ZIPs."""
from __future__ import annotations

import hashlib
import ctypes
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time
import uuid
import zipfile


def _signature(path: Path) -> tuple:
    s = path.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_mode)


class FileDigests:
    """Hash contents without trusting filesystem timestamp granularity."""

    def digest(self, path: Path) -> str:
        before = _signature(path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if _signature(path) != before:
            raise RuntimeError("workspace changed while computing checkpoint digest")
        return digest


DIGESTS = FileDigests()


def workspace_digest(workspace: Path) -> dict[str, str]:
    return {p.relative_to(workspace).as_posix(): DIGESTS.digest(p)
            for p in workspace.rglob("*")
            if p.is_file() and not p.is_symlink() and ".l2_state" not in p.parts}


def _files(source: Path) -> list[Path]:
    return sorted(p for p in source.rglob("*") if p.is_file() and not p.is_symlink())


def _clone_common_blocks(previous: Path, fresh: Path) -> int | None:
    """Share APFS extents while keeping a complete, independent standard ZIP."""
    if sys.platform != "darwin" or not previous.is_file():
        return None
    cloned = fresh.with_suffix(".clone")
    libc = ctypes.CDLL(None, use_errno=True)
    clone = libc.clonefile
    clone.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
    clone.restype = ctypes.c_int
    if clone(os.fsencode(previous), os.fsencode(cloned), 0):
        return None
    changed = 0
    try:
        os.chmod(cloned, 0o600)
        with fresh.open("rb") as new, cloned.open("r+b") as target:
            offset = 0
            while chunk := new.read(4096):
                old = target.read(len(chunk))
                if old != chunk:
                    target.seek(offset)
                    target.write(chunk)
                    changed += len(chunk)
                offset += len(chunk)
            target.truncate(offset)
        with fresh.open("rb") as a, cloned.open("rb") as b:
            if hashlib.file_digest(a, "sha256").digest() != hashlib.file_digest(b, "sha256").digest():
                raise RuntimeError("cloned checkpoint byte verification failed")
        cloned.replace(fresh)
        return changed
    finally:
        cloned.unlink(missing_ok=True)


def archive_tree(source: Path, archive: Path, store: Path) -> dict:
    if os.name != "posix":
        raise NotImplementedError("fast checkpoint archives require a POSIX filesystem")
    started = time.monotonic()
    source, store = source.resolve(), store.resolve()
    if source == store or source in store.parents:
        raise ValueError("checkpoint store must be private and outside the workspace")
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(store, 0o700)
    files = _files(source)
    signatures = {p: _signature(p) for p in files}
    digests = {p: DIGESTS.digest(p) for p in files}
    manifest = [(p.relative_to(source).as_posix(), signatures[p][3],
                 stat.S_IMODE(signatures[p][5]), signatures[p][2], digests[p]) for p in files]

    def verify_source() -> None:
        if _files(source) != files or any(
            _signature(p) != signatures[p] or DIGESTS.digest(p) != digests[p] for p in files
        ):
            raise RuntimeError("workspace changed while creating checkpoint")

    key = hashlib.sha256(("fast_zip/3:" + json.dumps(manifest, ensure_ascii=False)).encode()).hexdigest()
    canonical = store / key[:2] / (key + ".zip")
    canonical.parent.mkdir(exist_ok=True)
    cache_hit = canonical.is_file()
    changed_bytes = None
    previous_pointer = store / ("previous-" + hashlib.sha256(os.fsencode(source)).hexdigest() + ".json")
    temporary = canonical.parent / ("." + uuid.uuid4().hex + ".zip")
    try:
        if not cache_hit:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
                # Large stable dependencies first improve APFS block sharing
                # when small task outputs change between adjacent snapshots.
                for path in sorted(files, key=lambda p: (-p.stat().st_size, p.relative_to(source).as_posix())):
                    bundle.write(path, arcname=path.relative_to(source).as_posix())
            # Validate the archive bytes as well as the current source. A file
            # might have been edited and restored during zipfile.write().
            with zipfile.ZipFile(temporary) as bundle:
                for path in files:
                    with bundle.open(path.relative_to(source).as_posix()) as entry:
                        if hashlib.file_digest(entry, "sha256").hexdigest() != digests[path]:
                            raise RuntimeError("workspace changed while creating checkpoint")
            if previous_pointer.is_file():
                previous = store / json.loads(previous_pointer.read_text())["archive"]
                changed_bytes = _clone_common_blocks(previous, temporary)
            verify_source()
            os.chmod(temporary, 0o444)
            # Publication is atomic; independent workers never replace a cache
            # object already linked into a committed checkpoint.
            try:
                os.link(temporary, canonical)
            except FileExistsError:
                cache_hit = True
        else:
            verify_source()
        archive.parent.mkdir(parents=True, exist_ok=True)
        destination = archive.parent / ("." + uuid.uuid4().hex + ".zip")
        try:
            try:
                os.link(canonical, destination)
                transport = "hardlink"
            except OSError:
                shutil.copyfile(canonical, destination)
                transport = "copy"
            destination.replace(archive)
        finally:
            destination.unlink(missing_ok=True)
        pointer = store / (".previous-" + uuid.uuid4().hex)
        try:
            pointer.write_text(json.dumps({"archive": str(canonical.relative_to(store))}))
            pointer.replace(previous_pointer)
        finally:
            pointer.unlink(missing_ok=True)
    finally:
        temporary.unlink(missing_ok=True)
    event = {"stage": "checkpoint", "cache_hit": cache_hit, "transport": transport,
             "files": len(files), "zip_bytes": archive.stat().st_size,
             "elapsed_seconds": time.monotonic() - started, "manifest_sha256": key}
    event["apfs_changed_bytes"] = changed_bytes
    fd = os.open(store / "timings.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(event) + "\n").encode())
    finally:
        os.close(fd)
    return event
