"""systemd nightly-backup unit (deploy/systemd/ausmt-backup.service) — Documentation= path pin (#16).

The unit's `Documentation=` hardcoded `file:///home/<operator>/ausmt-code/deploy/README.md` — a literal
`<operator>` that the install sed never touched (it only rewrites `__DEPLOY_DIR__`/`__ENV_FILE__` in
ExecStart/EnvironmentFile/WorkingDirectory), so the installed unit pointed at a path that never existed.
The fix uses the same `__DEPLOY_DIR__` placeholder as ExecStart, which the install sed resolves to the
operator's real deploy/ — whose README.md IS the runbook.

This pin RESOLVES the Documentation target against THIS repo (substituting `__DEPLOY_DIR__` -> the repo's
deploy/ dir, exactly as the install sed does) and asserts the file exists AND carries no unresolved
`<placeholder>`. Runs everywhere (pure text + path resolution, no sh/git/docker needed). RED against the
shipped stale value (the `<operator>` path does not resolve to an existing file); GREEN after the fix.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_UNIT = _REPO / "deploy" / "systemd" / "ausmt-backup.service"
_DEPLOY_DIR = _REPO / "deploy"


def _documentation_uris() -> list[str]:
    """Every whitespace-separated URI on the unit's `Documentation=` line(s)."""
    uris: list[str] = []
    for line in _UNIT.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("Documentation="):
            uris.extend(s[len("Documentation="):].split())
    return uris


def _resolve_file_uri(uri: str) -> str:
    """`file://…` -> a filesystem path, with `__DEPLOY_DIR__` substituted to THIS repo's deploy/ dir
    (what the install sed does). Non-file: URIs are returned unchanged (the caller skips them)."""
    if not uri.startswith("file://"):
        return uri
    path = uri[len("file://"):]
    return path.replace("__DEPLOY_DIR__", _DEPLOY_DIR.as_posix())


def test_backup_unit_documentation_resolves_to_an_existing_runbook():
    """The backup unit's Documentation= must resolve to an existing runbook file in this repo, with no
    unresolved <placeholder>. FAILS IF: it carries a literal `<operator>` (the shipped stale value), or
    it points at a path that does not exist once `__DEPLOY_DIR__` is resolved."""
    uris = _documentation_uris()
    assert uris, "ausmt-backup.service has no Documentation= line"
    file_uris = [u for u in uris if u.startswith("file://")]
    assert file_uris, f"expected a file:// Documentation= URI; got {uris}"
    for uri in file_uris:
        assert "<" not in uri and ">" not in uri, (
            f"Documentation= carries an unresolved <placeholder> the install sed never fills: {uri!r}")
        resolved = _resolve_file_uri(uri)
        assert Path(resolved).is_file(), (
            f"Documentation= must resolve to an existing runbook; {uri!r} -> {resolved!r} does not exist")

    # And it must point at the deploy README (the actual runbook), not some unrelated file.
    assert any(_resolve_file_uri(u).endswith("deploy/README.md") for u in file_uris), (
        f"the backup runbook is deploy/README.md; Documentation= points elsewhere: {file_uris}")
