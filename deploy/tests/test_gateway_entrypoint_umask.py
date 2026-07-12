"""Gateway entrypoint umask seam (deploy/docker/gateway-entrypoint.sh) — #16, incident 2026-07-11.

The gateway runs as uid 10002 and opens its sqlite state DB in WAL mode, minting `-wal`/`-shm` sidecars
fresh on every container recreate. The nightly HOST backup runs as the operator in the shared group
10002 and needs group-WRITE on those sidecars (opening a WAL DB writes to its dir even for a read).
The default umask 022 dropped the group-write bit, so a `docker compose up -d` left the fresh sidecars
operator-unwritable and the backup FAILED two nights running until a manual `chmod g+rw`. The durable
fix is `umask 0002` at the process-spawn seam, so every file the gateway (and its git subprocesses)
creates is group-writable.

This is an EXECUTABLE pin, not a string grep: it runs the REAL gateway-entrypoint.sh with a stub
`python` on PATH (so `exec python -m gateway` lands in the stub) that (a) records the umask it INHERITED
across the exec and (b) creates a file. FAILS IF: the exec'd process does not see umask 0002 (the line
is missing/wrong), or — on POSIX — the created file is not group-writable. RED (proven by removing the
`umask 0002` line): the stub inherits the harness's preset umask 022 and the file is 0644 (no g+w).

PLATFORM: ubuntu-only (skipif nt). POSIX mode bits are not meaningful on a Windows/MSYS filesystem
(a file always reports 0666), AND `exec python` on Windows resolves to python.exe rather than a
PATH-placed shell stub, so the entrypoint cannot be exercised there. It RUNS on the gateway-ci ubuntu
lane with nothing skipped — where the incident's group-write bit is a real, checkable observable.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_ENTRYPOINT = _REPO / "deploy" / "docker" / "gateway-entrypoint.sh"
_SH = shutil.which("sh") or shutil.which("bash")

pytestmark = [
    pytest.mark.skipif(os.name == "nt",
                       reason="POSIX umask/mode bits not meaningful and `python` unstubbable on Windows"),
    pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run the entrypoint"),
]


def _run_entrypoint(tmp_path: Path) -> tuple[str, int]:
    """Run the real entrypoint with a stub `python` on PATH that records its inherited umask and creates
    a file. The harness presets umask 022 (preexec) so the entrypoint's `umask 0002` is what changes it.
    Returns (recorded_umask_string, created_file_mode)."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    umask_out = tmp_path / "seen_umask"
    file_out = tmp_path / "created_file"
    stub = bindir / "python"
    stub.write_text(
        "#!/bin/sh\n"
        # Ignore the `-m gateway` args; record the umask we inherited across the entrypoint's exec, then
        # create a file whose mode reflects that umask.
        f'umask > "{umask_out.as_posix()}"\n'
        f': > "{file_out.as_posix()}"\n',
        encoding="utf-8")
    stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    subprocess.run(
        [_SH, str(_ENTRYPOINT)], env=env, capture_output=True, text=True,
        preexec_fn=lambda: os.umask(0o022),  # noqa: PLW1509 -- POSIX-only test, sets a known baseline
    )
    recorded = umask_out.read_text(encoding="utf-8").strip() if umask_out.exists() else ""
    mode = file_out.stat().st_mode & 0o777 if file_out.exists() else -1
    return recorded, mode


def test_entrypoint_applies_umask_0002_group_writable(tmp_path):
    """The gateway entrypoint sets umask 0002 so files it (and its subprocesses) create are group-
    writable. FAILS IF: the exec'd process inherits a umask other than 0002 (the fix line is absent),
    or the file it creates lacks the group-write bit (0002 would give 0664; the pre-fix 022 gave 0644,
    the exact sidecar-lockout the nightly backup hit)."""
    recorded, mode = _run_entrypoint(tmp_path)
    assert recorded in ("0002", "002", "00002"), (
        f"the entrypoint must set umask 0002; the exec'd process saw {recorded!r}")
    assert mode != -1, "the stub python did not run (entrypoint exec chain broken)"
    assert mode & 0o020, (
        f"a file created under the entrypoint's umask must be group-writable (0002 => 0664); got {oct(mode)}")
