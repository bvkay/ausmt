"""External alerting agent (deploy/scripts/alert.sh) — dead-man ping / check-logic tests.

alert.sh is POSIX sh, tested as a BLACK BOX through `sh` over a fabricated data tree under tmp_path:
a gateway state dir with a reconcile-status.json, a backups dir with a snapshot, and a fake code dir
holding a compose.yaml. The two external commands the script shells out to — `docker compose` and
`curl` — are replaced by SH SHIMS via the script's own override hooks (AUSMT_ALERT_COMPOSE /
AUSMT_ALERT_CURL), the same shim pattern backup.sh's AUSMT_BACKUP_SQLITE uses. The curl shim RECORDS
every invocation (argv + the --data-raw body) to a file, so every assertion is an INDEPENDENT
OBSERVABLE: whether curl was called at all, the exact URL it was called with ($URL vs $URL/fail), the
failure text in the body, and the process exit code — never the script's own self-report.

The `docker compose ps` output is fabricated by the compose shim (it ignores its args and prints the
JSONL we want the script to see), so each service-health case is driven deterministically without a
docker daemon. The disk case shims `df` via PATH.

Each test names its failure criterion in the docstring (Invariant 10). No test skips on this stack —
sh, python (this interpreter), and coreutils are all present on the CI runner and the dev box, so the
whole file runs on the gateway-ci lane with no skip-tripwire allow-list entry needed.
"""
from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "deploy" / "scripts" / "alert.sh"

_SH = shutil.which("sh") or shutil.which("bash")
pytestmark = pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run alert.sh")

_URL = "https://hc.example/check-uuid"


def _now_iso() -> str:
    """The exact ISO-8601 UTC format reconcile.sh writes into last_run (%Y-%m-%dT%H:%M:%SZ)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compose_shim(tmp_path: Path, jsonl: str) -> Path:
    """A stand-in for `docker compose`: it ignores every argument and prints the given compose-ps JSONL
    on stdout. The script invokes it as `<shim> --profile gateway ps --format json --all`; the shim
    does not parse args, it just emits the fabricated ps output the test wants the script to read."""
    shim = tmp_path / "compose_shim.sh"
    # The JSONL is embedded via a quoted heredoc so no shell expansion mangles the JSON.
    shim.write_text(
        "#!/bin/sh\n"
        "cat <<'COMPOSE_JSON'\n"
        f"{jsonl}\n"
        "COMPOSE_JSON\n",
        encoding="utf-8")
    shim.chmod(0o755)
    return shim


def _curl_shim(tmp_path: Path, *, fail: bool = False) -> tuple[Path, Path]:
    """A stand-in for `curl`. It APPENDS one line per invocation to a record file: the full argv joined
    by spaces (so a test can see the URL, the /fail suffix, and the --data-raw body). When fail=True it
    also exits non-zero (rc=7) to simulate an unreachable monitor. Returns (shim_path, record_path)."""
    record = tmp_path / "curl_calls.log"
    shim = tmp_path / "curl_shim.sh"
    body = (
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> "{record.as_posix()}"\n'
    )
    if fail:
        body += "exit 7\n"
    shim.write_text(body, encoding="utf-8")
    shim.chmod(0o755)
    return shim, record


# A compose ps JSONL where every monitored service is running + healthy (gw-runner has no healthcheck,
# so its Health is legitimately empty). This is the ALL-OK baseline; individual tests mutate one line.
_ALL_OK_JSONL = "\n".join([
    '{"Service":"portal","State":"running","Health":"healthy"}',
    '{"Service":"gateway","State":"running","Health":"healthy"}',
    '{"Service":"clamd","State":"running","Health":"healthy"}',
    '{"Service":"gw-runner","State":"running","Health":""}',
])


def _make_tree(tmp_path: Path, *, compose_jsonl: str = _ALL_OK_JSONL,
               reconcile_action: str = "noop", reconcile_last_run: str | None = None,
               backup_age_days: float = 0.0, curl_fail: bool = False) -> dict:
    """Build the data tree + shims and return the env alert.sh runs under.

    - a gateway state dir with a reconcile-status.json (fresh + action=noop by default),
    - a backups dir with ONE snapshot dir (mtime = now by default; older when backup_age_days > 0),
    - a code dir holding deploy/compose.yaml (so the AUSMT_CODE_DIR service check proceeds),
    - a compose shim emitting compose_jsonl and a recording curl shim.
    """
    data = tmp_path / "data"
    state = data / "gateway" / "state"
    state.mkdir(parents=True, exist_ok=True)
    if reconcile_last_run is None:
        reconcile_last_run = _now_iso()
    (state / "reconcile-status.json").write_text(
        '{"last_run":"%s","action":"%s"}' % (reconcile_last_run, reconcile_action),
        encoding="utf-8")

    backups = data / "backups"
    snap = backups / "20260710T032000Z"
    snap.mkdir(parents=True, exist_ok=True)
    if backup_age_days > 0:
        old = datetime.datetime.now().timestamp() - backup_age_days * 86400
        os.utime(snap, (old, old))

    code = tmp_path / "code"
    (code / "deploy").mkdir(parents=True, exist_ok=True)
    (code / "deploy" / "compose.yaml").write_text("services: {}\n", encoding="utf-8")

    compose = _compose_shim(tmp_path, compose_jsonl)
    curl, record = _curl_shim(tmp_path, fail=curl_fail)

    env = dict(os.environ)
    env["AUSMT_ALERT_URL"] = _URL
    env["AUSMT_DATA_DIR"] = str(data)
    env["AUSMT_CODE_DIR"] = str(code)
    env["AUSMT_ALERT_COMPOSE"] = f"sh {compose.as_posix()}"
    env["AUSMT_ALERT_CURL"] = f"sh {curl.as_posix()}"
    # A working python on PATH for the JSON parses (this interpreter's dir).
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    return {"data": data, "state": state, "backups": backups, "code": code,
            "curl_record": record, "env": env}


def _run(tree: dict, env_extra: dict | None = None,
         path_prepend: str | None = None) -> subprocess.CompletedProcess:
    env = dict(tree["env"])
    if env_extra:
        env.update(env_extra)
    if path_prepend:
        env["PATH"] = path_prepend + os.pathsep + env["PATH"]
    return subprocess.run([_SH, str(_SCRIPT)], capture_output=True, text=True, env=env)


def _curl_calls(tree: dict) -> list[str]:
    rec = tree["curl_record"]
    if not rec.exists():
        return []
    return [ln for ln in rec.read_text(encoding="utf-8").splitlines() if ln.strip()]


# --------------------------------------------------------------------------------------------------
# (a) unset AUSMT_ALERT_URL -> exit 0 + loud "not configured" note + NO curl invocation.
# --------------------------------------------------------------------------------------------------

def test_unconfigured_url_exits_zero_with_note_and_no_ping(tmp_path):
    """With AUSMT_ALERT_URL unset/empty, the script prints ONE loud 'not configured' note and exits 0
    WITHOUT ever invoking curl (it must never fake a ping or break the timer). FAILS IF: the exit code
    is nonzero, the note is absent, OR curl was called at all (the shim recorded any invocation)."""
    tree = _make_tree(tmp_path)
    r = _run(tree, env_extra={"AUSMT_ALERT_URL": ""})
    assert r.returncode == 0, r.stderr
    assert "not configured" in r.stderr.lower(), "must print the loud not-configured note"
    assert _curl_calls(tree) == [], "must NOT ping when unconfigured (no fake beat)"


# --------------------------------------------------------------------------------------------------
# (b) all-OK -> exactly ONE curl to $URL (not /fail), exit 0.
# --------------------------------------------------------------------------------------------------

def test_all_ok_sends_exactly_one_success_ping(tmp_path):
    """When every check passes, the script sends EXACTLY ONE curl to the bare $URL (the success beat)
    and exits 0. FAILS IF: zero or >1 curl calls, the call goes to $URL/fail instead of $URL, or the
    exit code is nonzero."""
    tree = _make_tree(tmp_path)
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    calls = _curl_calls(tree)
    assert len(calls) == 1, f"expected exactly one ping, got {calls}"
    assert _URL in calls[0], "the success ping must go to the ping URL"
    assert "/fail" not in calls[0], "an all-OK run must NOT hit the /fail endpoint"


# --------------------------------------------------------------------------------------------------
# (c) each failure class -> curl to $URL/fail with the failure text in the body + nonzero exit.
# --------------------------------------------------------------------------------------------------

def _assert_fail_ping(tree: dict, r: subprocess.CompletedProcess, needle: str) -> None:
    """Shared failure-criterion: rc!=0, exactly one curl call, it targets $URL/fail, and the failure
    `needle` appears in the recorded argv (which includes the --data-raw body)."""
    assert r.returncode != 0, f"a failed check must exit nonzero; stderr={r.stderr}"
    calls = _curl_calls(tree)
    assert len(calls) == 1, f"expected exactly one fail ping, got {calls}"
    assert f"{_URL}/fail" in calls[0], f"a failed check must ping $URL/fail; got {calls[0]}"
    assert needle in calls[0], f"the fail body must name the failure ({needle!r}); got {calls[0]}"


def test_unhealthy_service_pings_fail(tmp_path):
    """A healthchecked service reporting Health=unhealthy => a fail ping naming that service, nonzero
    exit. FAILS IF: the unhealthy service is not detected, the ping does not hit /fail, or the body
    does not name the service."""
    jsonl = _ALL_OK_JSONL.replace(
        '{"Service":"portal","State":"running","Health":"healthy"}',
        '{"Service":"portal","State":"running","Health":"unhealthy"}')
    tree = _make_tree(tmp_path, compose_jsonl=jsonl)
    r = _run(tree)
    _assert_fail_ping(tree, r, "portal")


def test_crashlooping_gw_runner_pings_fail(tmp_path):
    """The healthcheck-LESS gw-runner in State=restarting (the 2026-07-06 'stuck at SCANNED' crash-loop)
    => a fail ping naming gw-runner, nonzero exit. This is the headline silent-stall mode; gw-runner has
    no Health, so it must be caught by STATE. FAILS IF: a restarting gw-runner is treated as healthy
    (no fail ping) or the body does not name it."""
    jsonl = _ALL_OK_JSONL.replace(
        '{"Service":"gw-runner","State":"running","Health":""}',
        '{"Service":"gw-runner","State":"restarting","Health":""}')
    tree = _make_tree(tmp_path, compose_jsonl=jsonl)
    r = _run(tree)
    _assert_fail_ping(tree, r, "gw-runner")


def test_disk_over_threshold_pings_fail(tmp_path):
    """Disk usage over AUSMT_ALERT_DISK_PCT => a fail ping with the number, nonzero exit. Forced by
    shimming `df` on PATH to report 99%. FAILS IF: an over-threshold disk is not flagged, or the body
    lacks the percentage."""
    tree = _make_tree(tmp_path)
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "df").write_text(
        "#!/bin/sh\n"
        'echo "Filesystem 1024-blocks Used Available Capacity Mounted on"\n'
        'echo "/dev/fake 100 99 1 99% /"\n',
        encoding="utf-8")
    (fakebin / "df").chmod(0o755)
    r = _run(tree, path_prepend=str(fakebin))
    _assert_fail_ping(tree, r, "99%")


def test_reconcile_action_failed_pings_fail(tmp_path):
    """reconcile-status.json with action=failed (a build/verify failure) => a fail ping quoting it,
    nonzero exit. FAILS IF: an action=failed status is not flagged, or the body does not say failed."""
    tree = _make_tree(tmp_path, reconcile_action="failed")
    r = _run(tree)
    _assert_fail_ping(tree, r, "action=failed")


def test_reconcile_stale_pings_fail(tmp_path):
    """reconcile-status.json whose last_run is older than AUSMT_ALERT_RECONCILE_MAX_MIN (the timer
    stalled) => a fail ping saying stale, nonzero exit. Forced with a 2020 last_run. FAILS IF: a stale
    reconcile is treated as fresh (no fail ping) or the body does not flag staleness."""
    tree = _make_tree(tmp_path, reconcile_last_run="2020-01-01T00:00:00Z")
    r = _run(tree)
    _assert_fail_ping(tree, r, "stale")


def test_stale_backup_pings_fail(tmp_path):
    """The newest backup snapshot older than AUSMT_ALERT_BACKUP_MAX_H (default 26h) => a fail ping,
    nonzero exit. Forced by ageing the snapshot dir's mtime 5 days back. FAILS IF: a stale backup is not
    flagged, or the body does not name the snapshot/age."""
    tree = _make_tree(tmp_path, backup_age_days=5)
    r = _run(tree)
    _assert_fail_ping(tree, r, "older than")


# --------------------------------------------------------------------------------------------------
# (d) curl itself failing -> nonzero exit, no crash-hide.
# --------------------------------------------------------------------------------------------------

def test_curl_failure_on_success_path_exits_nonzero(tmp_path):
    """When all checks pass but the success ping cannot be delivered (curl exits non-zero — the box
    could not reach the monitor), the script exits NONZERO with a loud message rather than swallowing
    the error. FAILS IF: the script exits 0 despite the failed ping, or crashes without a message.
    (The monitor's own absent-ping timeout is the ultimate backstop — asserted only via the message.)"""
    tree = _make_tree(tmp_path, curl_fail=True)
    r = _run(tree)
    assert r.returncode != 0, "a failed success-ping must surface as a nonzero exit, not be hidden"
    assert _curl_calls(tree), "curl must have been attempted"
    assert "ping" in r.stderr.lower(), "a failed ping must produce a loud message"


# ==================================================================================================
# (e) C43 S2b-i: alert.sh ALSO writes ops-status.json for the curator ops floor (record D8/D15).
# The producer half of the serve-state operations floor. Same shim/black-box posture — every
# assertion reads the emitted ops-status.json (an independent on-disk observable), never the script's
# self-report. All run on the gateway-ci lane (sh + python + git present); no skip-tripwire entry.
# ==================================================================================================
_OPS_TOP_KEYS = ("generated_at", "timer_period_min", "reconcile", "backups", "alerts", "box",
                 "freshness", "builds", "logs")


def _ops_doc(tree: dict) -> dict:
    return json.loads((tree["state"] / "ops-status.json").read_text(encoding="utf-8"))


def _add_retained_build(tree: dict, dir_name: str = "20260710T032000Z", *,
                        provenance_cache: dict | None = None, serving: bool = True) -> Path:
    """Materialise a site-data/builds/<dir_name>/ retained build the ops writer inventories:
    build.json (identity) + build_report.json (stations) + build_provenance.json (the C18-A4 cache
    block) + a build log; optionally the `current` symlink (best-effort — no-op where symlinks are
    unprivileged, e.g. Windows, so the serving marker just does not match)."""
    site = tree["data"] / "site-data"
    bdir = site / "builds" / dir_name
    bdir.mkdir(parents=True, exist_ok=True)
    (site / "logs").mkdir(parents=True, exist_ok=True)
    (bdir / "build.json").write_text(json.dumps(
        {"build_id": "abc1234-def5678-2026-07-10T03:20:00Z", "engine_commit": "abc1234",
         "source_commit": "def5678"}), encoding="utf-8")
    (bdir / "build_report.json").write_text(json.dumps(
        {"surveys": {"s1": {"stations_built": 3}, "s2": {"stations_built": 5}}}), encoding="utf-8")
    if provenance_cache is None:
        provenance_cache = {"enabled": True, "mode": "rw", "salt_fp": "deadbeef0000",
                            "write_errors": 0, "read_errors": 0, "hits": 6, "misses": 0}
    (bdir / "build_provenance.json").write_text(json.dumps({"cache": provenance_cache}),
                                                encoding="utf-8")
    (site / "logs" / f"{dir_name}.build.log").write_text("line1\nBUILD OK\n", encoding="utf-8")
    if serving:
        cur = site / "current"
        try:
            if cur.is_symlink() or cur.exists():
                cur.unlink()
            cur.symlink_to(Path("builds") / dir_name)
        except OSError:
            pass
    return bdir


def test_ops_status_emitted_schema_valid_atomic_ping_unchanged(tmp_path):
    """EMISSION PIN (B6). One alert.sh pass writes a schema-valid ops-status.json into the state dir
    ATOMICALLY (no surviving .tmp), AND the dead-man ping behaviour is UNCHANGED — an all-OK run still
    sends EXACTLY ONE success beat to $URL (never /fail). FAILS IF: ops-status.json is absent, is not
    valid JSON, is missing any required top-level block, a .tmp orphan survives, OR the ping call
    count/target changed (the ping and the ops-write must stay independent)."""
    tree = _make_tree(tmp_path)
    _add_retained_build(tree)
    r = _run(tree)
    # dead-man ping UNCHANGED: exactly one success beat, to $URL, not /fail.
    assert r.returncode == 0, r.stderr
    calls = _curl_calls(tree)
    assert len(calls) == 1 and _URL in calls[0] and "/fail" not in calls[0], calls
    # ops-status.json: present, valid, complete.
    ops = tree["state"] / "ops-status.json"
    assert ops.exists(), "ops-status.json must be written each run"
    doc = json.loads(ops.read_text(encoding="utf-8"))
    for key in _OPS_TOP_KEYS:
        assert key in doc, f"ops-status.json missing top-level {key!r}: {sorted(doc)}"
    assert doc["generated_at"].endswith("Z") and "T" in doc["generated_at"], doc["generated_at"]
    assert set(doc["freshness"]) == {"code", "surveys_live"}, "freshness must cover BOTH repos"
    assert isinstance(doc["builds"], list) and doc["builds"], "retained-build inventory must be listed"
    # atomic: no orphan tmp left behind.
    assert list(tree["state"].glob("ops-status.json.tmp*")) == [], "atomic write left a tmp orphan"


def test_ops_status_builds_carry_a4_cache_forensics_producer_truth(tmp_path):
    """PRODUCER-TRUTH PIN (B4). The C18-A4 cache forensics (salt_fp / write_errors / read_errors) are
    produced by engine.extract.cache.BuildCache.counters() and land in build_provenance.json's
    TOP-LEVEL `cache` block — NOT in build.json or build_report.json (verified against
    build_portal.py). alert.sh must lift them from that exact file into ops-status.json builds[].cache.
    Driven by the REAL cache producer (constructed here, not a hand-typed block), so a field rename in
    the engine reds this pin. FAILS IF: alert.sh reads the counters from the wrong file, drops one, or
    the producer's field names drift out from under the reader.

    Uses the real producer's counters() rather than a full engine sample-survey build (which would
    need mt_metadata + the allow-listed skip): the direct construction exercises the SAME producer
    that writes build_provenance.json and runs on every lane, so the field contract is pinned without
    a stack dependency."""
    import sys as _sys
    eng = str(Path(__file__).resolve().parents[2] / "engine" / "extract")
    _sys.path.insert(0, eng)
    try:
        import cache as cache_mod
    finally:
        if eng in _sys.path:
            _sys.path.remove(eng)
    bc = cache_mod.BuildCache(tmp_path / "cachedir", engine_commit="testpin", lib_versions={},
                              contract_digest="contract-x", disabled_reason="producer-truth pin")
    real_cache = bc.counters()
    for k in ("salt_fp", "write_errors", "read_errors"):
        assert k in real_cache, f"engine cache.counters() no longer exposes {k!r}: {real_cache}"
    tree = _make_tree(tmp_path)
    _add_retained_build(tree, provenance_cache=real_cache)
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    doc = _ops_doc(tree)
    assert doc["builds"], "the retained-build inventory must list the build"
    got = doc["builds"][0]["cache"]
    assert got["salt_fp"] == real_cache["salt_fp"], (got, real_cache)
    assert got["write_errors"] == real_cache["write_errors"], (got, real_cache)
    assert got["read_errors"] == real_cache["read_errors"], (got, real_cache)


def test_ops_status_written_when_alerting_unconfigured(tmp_path):
    """The ops floor is INDEPENDENT of the external monitor: ops-status.json is written even when
    AUSMT_ALERT_URL is unset (and NO ping is sent — the dead-man behaviour is untouched, matching the
    (a) test). FAILS IF: an unconfigured box writes no ops-status.json, a ping was sent, or
    alerts.installed does not reflect the missing URL."""
    tree = _make_tree(tmp_path)
    r = _run(tree, env_extra={"AUSMT_ALERT_URL": ""})
    assert r.returncode == 0, r.stderr
    assert _curl_calls(tree) == [], "no ping when unconfigured (dead-man behaviour untouched)"
    ops = tree["state"] / "ops-status.json"
    assert ops.exists(), "ops-status.json must be written even on an unconfigured box"
    assert _ops_doc(tree)["alerts"]["installed"] is False, "alerts.installed must reflect no URL"


def test_ops_status_sync_failed_streak_increments_across_runs(tmp_path):
    """INCIDENT-AS-TEST, producer side (record D15). A reconcile action=sync_failed that persists must
    be visible as a GROWING streak (count + a stable `since`), not a silent single line — the
    2026-07-11 incident where a sync_failed hid for 4 h. FAILS IF: the streak does not accumulate
    across passes, or `since` is not carried forward from the first failing pass."""
    tree = _make_tree(tmp_path, reconcile_action="sync_failed")   # fresh last_run
    _run(tree)
    d1 = _ops_doc(tree)
    assert d1["reconcile"]["sync_failed"] is True, d1["reconcile"]
    assert d1["reconcile"]["sync_failed_streak"] == 1, d1["reconcile"]
    since1 = d1["reconcile"]["sync_failed_since"]
    assert since1, "the first failing pass must record a sync_failed_since"
    _run(tree)   # still failing -> streak grows, since preserved
    d2 = _ops_doc(tree)
    assert d2["reconcile"]["sync_failed_streak"] == 2, d2["reconcile"]
    assert d2["reconcile"]["sync_failed_since"] == since1, d2["reconcile"]
