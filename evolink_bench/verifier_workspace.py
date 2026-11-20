"""Check existing workspace inputs in the verifier's own user/mount namespace."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Any


def workspace_input_manifest(workspace: Path, bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fingerprint existing inputs only; an absent submission remains a task failure."""
    root = workspace.resolve()
    paths = {root}
    absent = set()
    for binding in bindings:
        if binding.get("source") != "workspace":
            continue
        relative = PurePosixPath(str(binding.get("path", "")))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("workspace verifier binding must stay under its workspace")
        parts = relative.parts[1:] if relative.parts[0] == "agent_workspace" else relative.parts
        source = root.joinpath(*parts)
        if not source.exists():
            if source.is_symlink():
                raise ValueError("workspace verifier input is a broken symlink")
            absent.add(source)
            continue
        if source.is_symlink() and not source.resolve().is_relative_to(root):
            raise ValueError("workspace verifier binding resolves outside workspace")
        paths.add(source)
        if source.is_dir() and not source.is_symlink():
            paths.update(source.rglob("*"))
    manifest = []
    for path in sorted(paths):
        # Dependency trees commonly contain links to the container's runtime.
        # Compare the link itself across namespaces; never read its host target.
        if path.is_symlink():
            manifest.append({"path": path.relative_to(root).as_posix(),
                             "kind": "symlink", "target": os.readlink(path)})
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError("workspace verifier input escapes its workspace")
        entry = {"path": path.relative_to(root).as_posix()}
        if path.is_dir():
            entry.update(kind="directory", children=sorted(item.name for item in path.iterdir()))
        elif path.is_file():
            entry.update(kind="file", sha256=_sha256(path))
        else:
            raise ValueError("workspace verifier input is not a file or directory")
        manifest.append(entry)
    manifest.extend({"path": path.relative_to(root).as_posix(), "kind": "absent"}
                    for path in sorted(absent))
    return manifest


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def bind_workspace_user(workspace: Path) -> str | None:
    """Container root with cap-drop ALL cannot traverse another owner's 0700 dir."""
    if os.name != "posix":
        return None
    metadata = workspace.stat()
    return f"{metadata.st_uid}:{metadata.st_gid}"


# Embedded because the runtime source tree is not mounted into the verifier.
# Inputs are fingerprints, never private source contents. The real verifier runs
# only after visibility is established in this same container and process UID.
WORKSPACE_GUARD = r'''
import hashlib, io, json, os, pathlib, runpy, sys
envelope = json.load(sys.stdin)
failure = None
for item in envelope['workspace_manifest']:
    path = pathlib.Path(os.environ.get('L2_VERIFIER_WORKSPACE', '/workspace')) / item['path']
    try:
        if item['kind'] == 'absent':
            if os.path.lexists(path):
                raise OSError('input absent on host exists in verifier mount')
        elif item['kind'] == 'symlink':
            if not path.is_symlink() or os.readlink(path) != item['target']:
                raise OSError('symbolic link differs from host snapshot')
        elif item['kind'] == 'directory':
            if not path.is_dir():
                raise OSError('expected directory is not visible')
            with os.scandir(path) as entries:
                actual_children = sorted(entry.name for entry in entries)
            if 'children' in item and actual_children != item['children']:
                raise OSError('directory entries differ from host snapshot')
        else:
            with path.open('rb') as stream:
                actual = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != item['sha256']:
                raise OSError('input content differs from host snapshot')
    except OSError as exc:
        failure = {'path': item['path'], 'type': type(exc).__name__, 'errno': exc.errno}
        break
if failure is not None:
    print(json.dumps({
        'schema_version': 'l2_native_verifier_result/1.0',
        'verifier_id': envelope['verifier_id'], 'status': 'error', 'score': None,
        'error': 'workspace input is not visible or differs in the verifier',
        'public_summary': {'result_category': 'error', 'observable_deficiencies': []},
        'private_diagnostics': {'reason': 'workspace_input_visibility_error',
                                'uid': getattr(os, 'getuid', lambda: None)(), 'gid': getattr(os, 'getgid', lambda: None)(), **failure},
    }))
else:
    print('TRIEVO_WORKSPACE_GUARD ' + json.dumps({
        'uid': getattr(os, 'getuid', lambda: None)(), 'gid': getattr(os, 'getgid', lambda: None)(),
        'checked_entries': len(envelope['workspace_manifest']),
    }), file=sys.stderr, flush=True)
    entrypoint = sys.argv[1]
    sys.argv = [entrypoint]
    sys.path.insert(0, str(pathlib.Path(entrypoint).parent))
    sys.stdin = io.StringIO(json.dumps(envelope['request'], ensure_ascii=False))
    runpy.run_path(entrypoint, run_name='__main__')
'''
