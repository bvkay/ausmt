"""C45 systemd units for the usage-analytics aggregator (deploy/systemd/ausmt-stats.{service,timer}).

Config-level pins over the shipped unit files (record D4/D5 — the established oneshot+timer pattern):
the service is a oneshot run as the OPERATOR uid via the __DEPLOY_DIR__/__ENV_FILE__ placeholder idiom
(NEVER a literal <operator> path — the 2026-07 backup-unit Documentation bug), and the timer fires
DAILY and is Persistent. Runs everywhere (pure text + path resolution — no systemd, sh, or git needed),
so it never trips the CI skip tripwire. FAILS if a unit drifts from the pattern the operator runbook
documents.
"""
from __future__ import annotations

from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SYSTEMD = _REPO / "deploy" / "systemd"
_SERVICE = _SYSTEMD / "ausmt-stats.service"
_TIMER = _SYSTEMD / "ausmt-stats.timer"
_DEPLOY_DIR = _REPO / "deploy"


def _lines(path: Path, key: str) -> list[str]:
    return [ln.strip()[len(key):] for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip().startswith(key)]


def test_stats_service_is_oneshot_operator_uid_with_placeholder_paths():
    """The aggregator service must be a Type=oneshot run as a NON-root, non-container operator uid, with
    the __ENV_FILE__/__DEPLOY_DIR__ placeholder paths the install sed resolves. FAILS IF it drops
    oneshot, runs as root or a container uid (10001/10002), or hardcodes a real path instead of the
    placeholder (breaking the documented install flow)."""
    text = _SERVICE.read_text(encoding="utf-8")
    assert _lines(_SERVICE, "Type=") == ["oneshot"], "the aggregator must be a oneshot"
    users = _lines(_SERVICE, "User=")
    assert users and users[0] not in ("root", "10001", "10002"), (
        f"the aggregator must run as the operator uid, not root/container uid: {users}")
    envfiles = _lines(_SERVICE, "EnvironmentFile=")
    assert envfiles == ["__ENV_FILE__"], f"EnvironmentFile must be the __ENV_FILE__ placeholder: {envfiles}"
    assert _lines(_SERVICE, "WorkingDirectory=") == ["__DEPLOY_DIR__"]
    execs = _lines(_SERVICE, "ExecStart=")
    assert execs and "aggregate_stats.py" in execs[0], f"ExecStart must run aggregate_stats.py: {execs}"
    assert "__DEPLOY_DIR__/scripts/aggregate_stats.py" in execs[0]
    # A synced clock is wanted for date bucketing (like the backup/alert units).
    assert "time-sync.target" in text


def test_stats_service_documentation_resolves_to_the_runbook():
    """The service Documentation= must resolve (after the install sed substitutes __DEPLOY_DIR__) to an
    existing runbook file, with no unresolved <placeholder> — the exact bug the backup unit hit. FAILS
    IF it carries a literal <...> or points at a non-existent file."""
    uris: list[str] = []
    for line in _SERVICE.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith("Documentation="):
            uris.extend(s[len("Documentation="):].split())
    file_uris = [u for u in uris if u.startswith("file://")]
    assert file_uris, f"expected a file:// Documentation= URI; got {uris}"
    for uri in file_uris:
        assert "<" not in uri and ">" not in uri, (
            f"Documentation= carries an unresolved <placeholder> the install sed never fills: {uri!r}")
        resolved = uri[len("file://"):].replace("__DEPLOY_DIR__", _DEPLOY_DIR.as_posix())
        assert Path(resolved).is_file(), (
            f"Documentation= must resolve to an existing runbook; {uri!r} -> {resolved!r} does not exist")
    assert any(u[len("file://"):].replace("__DEPLOY_DIR__", _DEPLOY_DIR.as_posix()).endswith(
        "deploy/README.md") for u in file_uris), f"Documentation= must point at deploy/README.md: {file_uris}"


def test_stats_timer_is_daily_and_persistent():
    """The timer must fire DAILY (an OnCalendar day cadence) and be Persistent (catch up a missed run).
    FAILS IF it uses a sub-daily OnUnitActiveSec cadence (the aggregator folds COMPLETE days — running
    more than daily just re-writes the same file) or drops Persistent."""
    cal = _lines(_TIMER, "OnCalendar=")
    assert cal, f"the timer must set OnCalendar for a daily fire: {cal}"
    # A once-a-day calendar spec: '*-*-* HH:MM:SS' (a fixed daily time), NOT a sub-daily interval.
    assert any(c.startswith("*-*-*") for c in cal), f"expected a daily OnCalendar spec: {cal}"
    assert _lines(_TIMER, "OnUnitActiveSec=") == [], "the aggregator is daily, not an interval timer"
    assert _lines(_TIMER, "Persistent=") == ["true"], "the timer must be Persistent (catch up a missed day)"
    assert _lines(_TIMER, "WantedBy=") == ["timers.target"]
