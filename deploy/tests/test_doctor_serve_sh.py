"""The serving-replica doctor (deploy/nectar/doctor-serve.sh).

Black box over `sh` with a real site-data tree and stubs for docker, curl, mountpoint and the front
door's own doctor, the pattern test_box_doctor_sh.py uses. The pins: one labelled PASS / WARN / FAIL
line per check, a non-zero exit exactly when a check FAILs, and each serve-role fault reported by
name: a container down, a loopback listener silent, the public wall open, current not resolving,
build.json unreadable, the replica not fed through the publish path, the front door unhealthy, or
the data tree sitting on the root disk instead of its volume.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_DOCTOR = _REPO / "deploy" / "nectar" / "doctor-serve.sh"
_SH = shutil.which("sh")

pytestmark = [
    pytest.mark.skipif(_SH is None, reason="no POSIX sh to run doctor-serve.sh"),
    pytest.mark.skipif(os.name == "nt", reason="POSIX sh stubs are not meaningful here"),
]

TS = "20260930T010203Z"

# The deploy compose file answers with the portal and the front-door compose file with the edge;
# PORTAL_DOWN / FRONTDOOR_DOWN empty the matching answer.
_DOCKER_STUB = """#!/bin/sh
case "$*" in
  *frontdoor*"ps --status running --services") [ -n "${FRONTDOOR_DOWN:-}" ] || echo frontdoor ;;
  *"ps --status running --services") [ -n "${PORTAL_DOWN:-}" ] || echo portal ;;
  *"ps -q portal") [ -n "${PORTAL_DOWN:-}" ] || echo cid-portal ;;
  *"ps -q frontdoor") [ -n "${FRONTDOOR_DOWN:-}" ] || echo cid-frontdoor ;;
  "image inspect"*"sha256:img-portal") echo "ghcr.io/example/ausmt-portal@sha256:${PORTAL_DIGEST:-1111}" ;;
  "image inspect"*"sha256:img-frontdoor") echo "caddy@sha256:2222" ;;
  "inspect"*"cid-portal") echo sha256:img-portal ;;
  "inspect"*"cid-frontdoor") echo sha256:img-frontdoor ;;
esac
exit 0
"""
_CURL_STUB = """#!/bin/sh
[ -n "${CURL_LOG:-}" ] && printf '%s\\n' "$*" >> "$CURL_LOG"
for a in "$@"; do url="$a"; done
case "$url" in
  *":8443/") echo "${PORTAL_CODE:-200}" ;;
  *":8445/gateway/curator/queue") echo "${CURATOR_CODE:-404}" ;;
  *"/gateway/healthz") echo "${HEALTHZ_CODE:-200}" ;;
  *":8445/") echo "${READER_CODE:-200}" ;;
  *) echo 200 ;;
esac
"""
_FRONTDOOR_STUB = """#!/bin/sh
if [ "${FRONTDOOR_RC:-0}" != 0 ]; then
  echo "FAIL tls: no certificate for ausmt.auscope.org.au"
  echo "RESULT: FAIL (1 failed, 0 warned)"
  exit 1
fi
echo "PASS container: frontdoor is running"
echo "RESULT: PASS"
exit 0
"""
_MOUNTPOINT_STUB = '#!/bin/sh\nexit "${MOUNT_RC:-0}"\n'
# Runs its arguments as the log account would: CADDYLOG_DENIED stands for a file the account's ACL
# does not reach.
_AS_CADDYLOG_STUB = '#!/bin/sh\n[ -z "${CADDYLOG_DENIED:-}" ] || exit 1\nexec "$@"\n'


def _tree(tmp_path: Path, *, published_ts: str | None = TS, sender: str | None = None) -> Path:
    data = tmp_path / "data"
    site = data / "site-data"
    build = site / "builds" / TS
    build.mkdir(parents=True)
    (build / "build.json").write_text(json.dumps(
        {"build_id": "bid-1", "source_commit": "abc1234"}), encoding="utf-8")
    os.symlink(f"builds/{TS}", site / "current")
    if published_ts is not None:
        record = {"ts": published_ts, "source_commit": "abc1234", "build_id": "bid-1",
                  "received_at": "2026-09-30T01:20:00Z"}
        if sender is not None:
            record["sender"] = sender
        (site / "published.json").write_text(json.dumps(record), encoding="utf-8")
    return data


_GATEWAY = "http://ausmt-box:8445"


def _env(tmp_path: Path, data: Path, *, gateway: str | None = _GATEWAY, **extra: str) -> dict:
    b = tmp_path / "bin"
    b.mkdir(exist_ok=True)
    for name, body in (("docker", _DOCKER_STUB), ("curl", _CURL_STUB),
                       ("frontdoor-doctor", _FRONTDOOR_STUB), ("mountpoint", _MOUNTPOINT_STUB),
                       ("as-caddylog", _AS_CADDYLOG_STUB)):
        p = b / name
        p.write_text(body, encoding="utf-8")
        p.chmod(0o755)
    envf = tmp_path / ".env"
    envf.write_text(f"AUSMT_DATA_DIR={data}\nOWNER=example\nTAG=latest\n", encoding="utf-8")
    fdenv = tmp_path / "frontdoor.env"
    fd_lines = ["AUSMT_PUBLIC_NAME=ausmt.auscope.org.au",
                "AUSMT_BOX_READER_UPSTREAM=http://127.0.0.1:8445"]
    if gateway is not None:
        fd_lines.append(f"AUSMT_GATEWAY_UPSTREAM={gateway}")
    fdenv.write_text("\n".join(fd_lines) + "\n", encoding="utf-8")
    caddy_log = tmp_path / "access-frontdoor.json"
    caddy_log.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    env.update({
        "AUSMT_DOCTOR_CADDY_LOG": str(caddy_log),
        "AUSMT_DOCTOR_AS_CADDYLOG": str(b / "as-caddylog"),
        "AUSMT_DOCTOR_ENV": str(envf),
        "AUSMT_DOCTOR_FRONTDOOR_ENV": str(fdenv),
        "CURL_LOG": str(tmp_path / "curl.log"),
        "AUSMT_DOCTOR_DOCKER": str(b / "docker"),
        "AUSMT_DOCTOR_CURL": str(b / "curl"),
        "AUSMT_DOCTOR_FRONTDOOR": str(b / "frontdoor-doctor"),
        "AUSMT_DOCTOR_MOUNTPOINT": str(b / "mountpoint"),
        "AUSMT_DOCTOR_COMPOSE": str(tmp_path / "compose.yaml"),
        "AUSMT_DOCTOR_FRONTDOOR_COMPOSE": str(tmp_path / "frontdoor" / "compose.yaml"),
    })
    env.update(extra)
    return env


def _run(env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([_SH, str(_DOCTOR)], capture_output=True, text=True, env=env)


def _lines(r: subprocess.CompletedProcess, label: str) -> list[str]:
    return [ln for ln in r.stdout.splitlines() if ln.startswith(label + " ")]


def test_a_healthy_replica_is_labelled_and_exits_zero(tmp_path):
    data = _tree(tmp_path)
    r = _run(_env(tmp_path, data))
    assert r.returncode == 0, r.stdout + r.stderr
    assert not _lines(r, "FAIL"), r.stdout
    body = [ln for ln in r.stdout.splitlines()
            if ln and not ln.startswith(("=", "AusMT", "RESULT"))]
    for ln in body:
        assert ln.split(" ", 1)[0] in ("PASS", "WARN", "FAIL", "INFO"), f"unlabelled line: {ln!r}"
    out = r.stdout
    assert f"current -> builds/{TS}" in out
    assert any("published" in ln for ln in _lines(r, "PASS")), out
    assert any("frontdoor" in ln for ln in _lines(r, "PASS")), out


def test_the_gateway_leg_probes_healthz_through_the_front_door(tmp_path):
    """The four public gateway routes leave this host through the front door to the curation host,
    so the leg asks the front door itself, by the public name pinned to loopback, never the local
    reader (which has no gateway behind it). FAILS IF the probe skips the front door or a healthy
    curation host is not a PASS."""
    data = _tree(tmp_path)
    env = _env(tmp_path, data)
    r = _run(env)
    assert r.returncode == 0, r.stdout
    assert any(ln.startswith("PASS gateway") for ln in r.stdout.splitlines()), r.stdout
    calls = [ln for ln in Path(env["CURL_LOG"]).read_text(encoding="utf-8").splitlines()
             if "/gateway/healthz" in ln]
    assert len(calls) == 1, calls
    assert "--resolve ausmt.auscope.org.au:443:127.0.0.1" in calls[0], calls[0]
    assert calls[0].endswith("https://ausmt.auscope.org.au/gateway/healthz"), calls[0]


def test_an_unreachable_curation_host_is_a_warning_that_names_the_routes(tmp_path):
    """The curation host down or off the tailnet takes the submission routes down and nothing else:
    the readers are served here. So it WARNs, naming the four routes, and never fails the run.
    FAILS IF it FAILs, passes, or leaves the routes unnamed."""
    data = _tree(tmp_path)
    for code in ("502", "000"):
        (tmp_path / code).mkdir()
        r = _run(_env(tmp_path / code, data, HEALTHZ_CODE=code))
        assert r.returncode == 0, r.stdout
        warn = [ln for ln in _lines(r, "WARN") if ln.startswith("WARN gateway")]
        assert warn, r.stdout
        for route in ("POST /gateway/submit", "POST /gateway/request-key", "GET /gateway/healthz",
                      "GET /gateway/status/*"):
            assert route in warn[0], (route, warn[0])
        assert "readers are unaffected" in warn[0], warn[0]
        assert not any(ln.startswith("FAIL gateway") for ln in r.stdout.splitlines()), r.stdout


def test_an_unset_gateway_upstream_warns_by_name(tmp_path):
    """Unset, the front door sends the four routes to this host's own reader, which has no gateway
    behind it. The WARN names the variable to set. FAILS IF the gap is reported without its fix."""
    data = _tree(tmp_path)
    for gateway in (None, ""):
        root = tmp_path / ("none" if gateway is None else "empty")
        root.mkdir()
        r = _run(_env(root, data, gateway=gateway, HEALTHZ_CODE="502"))
        assert r.returncode == 0, r.stdout
        assert any(ln.startswith("WARN gateway") and "AUSMT_GATEWAY_UPSTREAM" in ln
                   for ln in r.stdout.splitlines()), r.stdout


def test_a_current_that_is_not_a_symlink_fails(tmp_path):
    data = _tree(tmp_path)
    cur = data / "site-data" / "current"
    cur.unlink()
    cur.mkdir()
    r = _run(_env(tmp_path, data))
    assert r.returncode != 0
    assert any(ln.startswith("FAIL current") for ln in r.stdout.splitlines()), r.stdout


def test_an_unreadable_build_json_fails(tmp_path):
    data = _tree(tmp_path)
    (data / "site-data" / "builds" / TS / "build.json").write_text("{not json", encoding="utf-8")
    r = _run(_env(tmp_path, data))
    assert r.returncode != 0
    assert any("build.json" in ln for ln in _lines(r, "FAIL")), r.stdout


def test_a_current_the_publish_path_did_not_put_there_warns(tmp_path):
    """published.json names another build than current: current was swapped by hand."""
    data = _tree(tmp_path, published_ts="20260101T000000Z")
    r = _run(_env(tmp_path, data))
    assert any("published" in ln for ln in _lines(r, "WARN")), r.stdout


def test_a_replica_never_fed_by_a_publish_warns(tmp_path):
    data = _tree(tmp_path, published_ts=None)
    r = _run(_env(tmp_path, data))
    assert any("published.json" in ln for ln in _lines(r, "WARN")), r.stdout


def test_an_unhealthy_front_door_fails(tmp_path):
    data = _tree(tmp_path)
    r = _run(_env(tmp_path, data, FRONTDOOR_RC="1"))
    assert r.returncode != 0
    assert any("frontdoor" in ln and "no certificate" in ln for ln in _lines(r, "FAIL")), r.stdout


def test_an_open_public_wall_fails(tmp_path):
    data = _tree(tmp_path)
    r = _run(_env(tmp_path, data, CURATOR_CODE="200"))
    assert r.returncode != 0
    assert any("WALL 2 BREACH" in ln for ln in _lines(r, "FAIL")), r.stdout


def test_a_silent_loopback_listener_fails(tmp_path):
    for var in ("PORTAL_CODE", "READER_CODE"):
        data = _tree(tmp_path / var)
        r = _run(_env(tmp_path / var, data, **{var: "000"}))
        assert r.returncode != 0, var
        assert _lines(r, "FAIL"), (var, r.stdout)


def test_a_stopped_container_fails(tmp_path):
    for var in ("PORTAL_DOWN", "FRONTDOOR_DOWN"):
        data = _tree(tmp_path / var)
        r = _run(_env(tmp_path / var, data, **{var: "1"}))
        assert r.returncode != 0, var
        assert any("containers" in ln for ln in _lines(r, "FAIL")), (var, r.stdout)


def test_a_data_dir_that_is_not_its_own_volume_fails(tmp_path):
    """A tree on the root disk fills the flavour's disk and vanishes behind the volume when it is
    mounted later."""
    data = _tree(tmp_path)
    r = _run(_env(tmp_path, data, MOUNT_RC="1"))
    assert r.returncode != 0
    assert any("volume" in ln for ln in _lines(r, "FAIL")), r.stdout


def test_a_build_directory_without_a_sidecar_warns(tmp_path):
    """A directory with no sidecar is a transfer that never completed. The receiver's prune never
    takes one, so it stays until someone removes it; the doctor names it. FAILS IF it goes unreported
    or is reported as a failure of the serving path."""
    data = _tree(tmp_path)
    (data / "site-data" / "builds" / "20260801T000000Z").mkdir()
    r = _run(_env(tmp_path, data))
    assert r.returncode == 0, r.stdout
    assert any("20260801T000000Z" in ln and "sidecar" in ln for ln in _lines(r, "WARN")), r.stdout


_SHELLS = [s for s in (_SH, shutil.which("dash")) if s]


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root reads a mode-000 file, so unreadability cannot be staged")
@pytest.mark.parametrize("shell", _SHELLS, ids=lambda s: Path(s).name)
@pytest.mark.parametrize("which", ["AUSMT_DOCTOR_ENV", "AUSMT_DOCTOR_FRONTDOOR_ENV"])
def test_an_unreadable_env_file_fails_by_name_and_points_at_sudo(tmp_path, shell, which):
    """Provisioning writes both .env files root-only, and dash dies on the `.` of a file it cannot
    read, so a doctor run without sudo must report that rather than abort before its first check.
    FAILS IF the run stops short of its summary, exits zero, or the FAIL line names neither the
    file nor sudo."""
    data = _tree(tmp_path)
    env = _env(tmp_path, data)
    target = Path(env[which])
    target.chmod(0)
    try:
        r = subprocess.run([shell, str(_DOCTOR)], capture_output=True, text=True, env=env)
    finally:
        target.chmod(0o600)
    assert "RESULT: FAIL" in r.stdout, r.stdout + r.stderr
    assert r.returncode != 0
    assert any(str(target) in ln and "sudo" in ln for ln in _lines(r, "FAIL")), r.stdout


def test_the_published_line_reports_age_and_lag(tmp_path):
    """published.json carries the receive time and the build's own timestamp names when it was
    built, so the line states how long ago the replica swapped and how long the publish took."""
    data = _tree(tmp_path)
    r = _run(_env(tmp_path, data))
    line = [ln for ln in _lines(r, "PASS") if ln.startswith("PASS published")]
    assert line and "age" in line[0] and "lag" in line[0], r.stdout


def _installed(tmp_path: Path) -> Path:
    """The doctor as provisioning installs it: a lone copy under /usr/local/bin, outside the
    checkout and outside the data volume."""
    b = tmp_path / "usr" / "local" / "bin"
    b.mkdir(parents=True)
    copy = b / "ausmt-doctor-serve"
    shutil.copy(_DOCTOR, copy)
    return copy


def test_the_installed_copy_finds_the_checkout_on_the_data_volume(tmp_path):
    """FAILS IF the copy outside the checkout cannot find deploy/.env and deploy/frontdoor/.env
    under the data root's checkout, and so reports a healthy replica as unconfigured."""
    data = _tree(tmp_path)
    env = _env(tmp_path, data)
    deploy = data / "code" / "deploy"
    (deploy / "frontdoor").mkdir(parents=True)
    shutil.copy(env.pop("AUSMT_DOCTOR_ENV"), deploy / ".env")
    shutil.copy(env.pop("AUSMT_DOCTOR_FRONTDOOR_ENV"), deploy / "frontdoor" / ".env")
    env["AUSMT_DATA_DIR"] = str(data)
    r = subprocess.run([_SH, str(_installed(tmp_path))], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"current -> builds/{TS}" in r.stdout, r.stdout
    assert any(ln.startswith("PASS gateway") for ln in r.stdout.splitlines()), r.stdout


def test_with_the_volume_absent_the_installed_copy_fails_its_volume_line(tmp_path):
    """The checkout and both .env files live on the volume, so a boot without it leaves the
    installed copy with nothing to read and nothing in its environment. It must still name the
    default data root's volume. FAILS IF it stops at the missing configuration without a volume
    line, or exits zero."""
    env = _env(tmp_path, tmp_path / "unused", MOUNT_RC="1")
    for name in ("AUSMT_DOCTOR_ENV", "AUSMT_DOCTOR_FRONTDOOR_ENV", "AUSMT_DATA_DIR", "AUSMT_CODE_DIR"):
        env.pop(name, None)
    r = subprocess.run([_SH, str(_installed(tmp_path))], capture_output=True, text=True, env=env)
    assert r.returncode != 0, r.stdout
    assert "RESULT: FAIL" in r.stdout, r.stdout + r.stderr
    assert any(ln.startswith("FAIL volume") and "/srv/ausmt" in ln
               for ln in r.stdout.splitlines()), r.stdout


def test_the_running_images_are_named_by_digest(tmp_path):
    """A replica that stopped pulling serves new builds through an old SPA, and only the image
    digest tells the two hosts apart, since the tags move. The line is information, never a
    verdict. FAILS IF the portal's RepoDigest is not printed as an INFO line, or a stopped
    portal makes the image line a FAIL of its own."""
    data = _tree(tmp_path)
    r = _run(_env(tmp_path, data, PORTAL_DIGEST="abcd"))
    info = [ln for ln in _lines(r, "INFO") if "ghcr.io/example/ausmt-portal@sha256:abcd" in ln]
    assert info, r.stdout
    assert any("caddy@sha256:2222" in ln for ln in _lines(r, "INFO")), r.stdout
    (tmp_path / "down").mkdir()
    r = _run(_env(tmp_path / "down", data, PORTAL_DOWN="1"))
    assert not any("image" in ln for ln in _lines(r, "FAIL")), r.stdout


def test_the_log_account_can_read_the_live_access_log(tmp_path):
    """The curation host pulls the masked access log as caddylog, whose read rests on a default
    ACL that a 0600 log file masks to nothing. FAILS IF a readable log is not a PASS, an unreadable
    one is anything but a FAIL naming the file and the fix, or a log Caddy has not created yet
    fails the run."""
    data = _tree(tmp_path)
    r = _run(_env(tmp_path, data))
    assert any(ln.startswith("PASS caddylog") for ln in r.stdout.splitlines()), r.stdout
    (tmp_path / "denied").mkdir()
    r = _run(_env(tmp_path / "denied", data, CADDYLOG_DENIED="1"))
    assert r.returncode != 0, r.stdout
    line = [ln for ln in _lines(r, "FAIL") if ln.startswith("FAIL caddylog")]
    assert line and "access-frontdoor.json" in line[0] and "0640" in line[0], r.stdout
    (tmp_path / "absent").mkdir()
    env = _env(tmp_path / "absent", data)
    Path(env["AUSMT_DOCTOR_CADDY_LOG"]).unlink()
    r = _run(env)
    assert r.returncode == 0, r.stdout
    assert any(ln.startswith("WARN caddylog") for ln in r.stdout.splitlines()), r.stdout


def _expect_sender(env: dict, sender: str) -> dict:
    with open(env["AUSMT_DOCTOR_ENV"], "a", encoding="utf-8") as fh:
        fh.write(f"AUSMT_PUBLISH_SENDER={sender}\n")
    return env


def test_a_record_without_a_sender_is_information_not_a_warning(tmp_path):
    """published.json carries no sender until the receiver records one, so its absence says
    nothing about a second publisher. FAILS IF it WARNs, even with an expected sender set, or goes
    unmentioned."""
    data = _tree(tmp_path)
    r = _run(_expect_sender(_env(tmp_path, data), "100.64.0.7"))
    assert r.returncode == 0, r.stdout
    assert any(ln.startswith("INFO sender") for ln in r.stdout.splitlines()), r.stdout
    assert not any(ln.startswith("WARN sender") for ln in r.stdout.splitlines()), r.stdout


def test_the_recorded_sender_is_named_and_matched_against_the_expected_one(tmp_path):
    """Two hosts publishing to one replica swap the public build every tick and each pass reports
    publish=ok, so only the replica can see it: the sender recorded on the last receive differs
    from the one this host expects. FAILS IF the sender goes unnamed, a match is not a PASS, or a
    mismatch is anything but a WARN naming both addresses."""
    data = _tree(tmp_path, sender="100.64.0.7")
    r = _run(_env(tmp_path, data))
    assert "100.64.0.7" in r.stdout, r.stdout
    assert not any(ln.startswith("WARN sender") for ln in r.stdout.splitlines()), r.stdout
    (tmp_path / "same").mkdir()
    r = _run(_expect_sender(_env(tmp_path / "same", data), "100.64.0.7"))
    assert any(ln.startswith("PASS sender") for ln in r.stdout.splitlines()), r.stdout
    (tmp_path / "other").mkdir()
    r = _run(_expect_sender(_env(tmp_path / "other", data), "100.64.0.9"))
    assert r.returncode == 0, r.stdout
    warn = [ln for ln in _lines(r, "WARN") if ln.startswith("WARN sender")]
    assert warn and "100.64.0.7" in warn[0] and "100.64.0.9" in warn[0], r.stdout


def test_the_serve_env_template_offers_the_expected_sender_as_optional():
    """FAILS IF the template omits AUSMT_PUBLISH_SENDER or gives it a value that provisioning
    would stop on."""
    example = (_REPO / "deploy" / "nectar" / "serve.env.example").read_text(encoding="utf-8")
    lines = [ln for ln in example.splitlines() if ln.startswith("AUSMT_PUBLISH_SENDER=")]
    assert lines == ["AUSMT_PUBLISH_SENDER="], lines
    para = example.split("\nAUSMT_PUBLISH_SENDER=")[0].rsplit("\n\n", 1)[-1]
    assert "published.json" in para and "optional" in para.lower(), para
