"""Numeric-knob range enforcement at the TWO consumers of the numeric floors (deploy review section 5).

gateway/config.py::_RANGES pins 15 numeric knobs whose zero/out-of-range value breaks the gateway
SILENTLY (a zeroed cap serves a wall of 413/429 while healthz stays green). They are enforced at
gateway container start (fail_closed_startup). This suite pins the two gaps that review found:

  1. PREFLIGHT (deploy/scripts/preflight.sh) now range-checks the SAME _RANGES before `docker compose
     up`, so `make preflight PROFILE=gateway` names a bad numeric override EARLY instead of leaving the
     operator to debug a crash-loop. Driven as a black box through `sh`, asserting the specific range
     FAIL/PASS line (an independent observable), never the overall exit code - preflight legitimately
     fails other legs (docker, images) in this env. It shells out to the REAL gateway.config._RANGES, so
     preflight and the app share one source of truth. AUSMT_PREFLIGHT_PYTHON points it at this venv's
     interpreter (config.py is stdlib-only, so it imports fine).

  2. THE RUNNER (gateway/runner/runner.py::RunnerConfig.from_env) reads AUSMT_JOB_TIMEOUT_S and
     AUSMT_MAX_UPLOAD_MB - the same knobs the gateway floors - but historically int'd them with no
     floor, so a zero was accepted where the gateway rejects it. from_env now fails closed (SystemExit)
     on a sub-1 value, identically to the gateway.

RED-first proof: against the pre-fix tree the preflight tests found no range leg (no PASS/FAIL line) and
from_env({"AUSMT_JOB_TIMEOUT_S": "0"}) returned a config instead of raising.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
from gateway.runner.runner import RunnerConfig  # noqa: E402 - path insert above must precede this

_SCRIPT = _REPO / "deploy" / "scripts" / "preflight.sh"
_SH = shutil.which("sh") or shutil.which("bash")


# ------------------------------------------------------------------------------------------------
# 1. Preflight range leg (black box through sh)
# ------------------------------------------------------------------------------------------------
_RANGE_FAIL_NEEDLE = "out of range"
_RANGE_PASS_NEEDLE = "within range"


def _run_preflight(extra_env: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess:
    """Run gateway-profile preflight with a deliberately-broken (or valid) numeric override. Other legs
    (docker, images, ownership) FAIL harmlessly; we only read the numeric-range line."""
    env = dict(os.environ)
    # Point the range leg at THIS interpreter (guaranteed present + can import gateway.config).
    env["AUSMT_PREFLIGHT_PYTHON"] = sys.executable
    env["AUSMT_PROFILE"] = "gateway"
    env["AUSMT_DATA_DIR"] = str(tmp_path / "data")   # nonexistent tree -> other legs fail, harmless
    # Clear any inherited knob so the case under test is the only override in play.
    for knob in ("AUSMT_MAX_UPLOAD_MB", "AUSMT_SESSION_TTL_S", "AUSMT_JOB_TIMEOUT_S",
                 "AUSMT_CLAMD_PORT", "AUSMT_MAX_INFLIGHT"):
        env.pop(knob, None)
    env.update(extra_env)
    return subprocess.run([_SH, str(_SCRIPT), "gateway"], capture_output=True, text=True, env=env)


@pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run preflight.sh")
def test_preflight_reds_on_zeroed_numeric_knob(tmp_path):
    """RED PIN. A zeroed AUSMT_MAX_UPLOAD_MB (a universal 413 that the gateway crash-loops on) must make
    gateway-profile preflight FAIL with a line that NAMES the knob and its allowed range. FAILS IF the
    range leg is absent (the shipped-blind state) or does not name the offending knob."""
    r = _run_preflight({"AUSMT_MAX_UPLOAD_MB": "0"}, tmp_path)
    out = r.stdout + r.stderr
    assert _RANGE_FAIL_NEEDLE in out, f"preflight did not range-check the numeric knobs - output:\n{out}"
    assert "AUSMT_MAX_UPLOAD_MB" in out and "FAIL" in out, (
        f"the range FAIL must NAME the offending knob - output:\n{out}")


@pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run preflight.sh")
def test_preflight_reds_on_non_integer_knob(tmp_path):
    """RED PIN (parse arm). A non-integer numeric override (int would ValueError inside config) must
    also be caught by name, not surface as a traceback. FAILS IF a garbage value passes the range leg."""
    r = _run_preflight({"AUSMT_SESSION_TTL_S": "abc"}, tmp_path)
    out = r.stdout + r.stderr
    assert "AUSMT_SESSION_TTL_S" in out and ("integer" in out or _RANGE_FAIL_NEEDLE in out), (
        f"a non-integer knob must be flagged by name - output:\n{out}")


@pytest.mark.skipif(_SH is None, reason="no POSIX sh/bash to run preflight.sh")
def test_preflight_passes_on_valid_and_unset_knobs(tmp_path):
    """GREEN PIN. With a valid override (AUSMT_MAX_UPLOAD_MB=500) and every other knob unset (config
    falls back to in-range defaults), the range leg PASSES and the range FAIL line is absent - proving
    the red pins above are non-vacuous (the same leg passes once the knobs are sane). FAILS IF a valid
    override still trips the range FAIL."""
    r = _run_preflight({"AUSMT_MAX_UPLOAD_MB": "500"}, tmp_path)
    out = r.stdout + r.stderr
    assert _RANGE_PASS_NEEDLE in out, f"the range PASS line must render for valid knobs - output:\n{out}"
    assert _RANGE_FAIL_NEEDLE not in out, f"a valid knob must not trip the range FAIL - output:\n{out}"


# ------------------------------------------------------------------------------------------------
# 2. Runner floor (RunnerConfig.from_env) - fail closed identically to the gateway
# ------------------------------------------------------------------------------------------------
def test_runner_from_env_reds_on_zeroed_timeout():
    """RED PIN. A zeroed AUSMT_JOB_TIMEOUT_S (every job times out instantly) must make from_env fail
    closed (SystemExit) naming the knob, not silently build a runner that quarantines everything."""
    with pytest.raises(SystemExit) as exc:
        RunnerConfig.from_env({"AUSMT_JOB_TIMEOUT_S": "0"})
    assert "AUSMT_JOB_TIMEOUT_S" in str(exc.value)


def test_runner_from_env_reds_on_zeroed_upload():
    """RED PIN. A zeroed AUSMT_MAX_UPLOAD_MB (a zero extraction byte-cap) must make from_env fail closed
    naming the knob - the same value the gateway rejects at startup."""
    with pytest.raises(SystemExit) as exc:
        RunnerConfig.from_env({"AUSMT_MAX_UPLOAD_MB": "0"})
    assert "AUSMT_MAX_UPLOAD_MB" in str(exc.value)


def test_runner_from_env_reds_on_negative_knob():
    """RED PIN. A negative override is out of range too (the floor is >= 1)."""
    with pytest.raises(SystemExit):
        RunnerConfig.from_env({"AUSMT_JOB_TIMEOUT_S": "-5"})


def test_runner_from_env_accepts_valid_and_default_knobs():
    """GREEN PIN. Valid overrides construct, and an empty env lands on the in-range defaults - proving
    the floor does not reject legitimate config (non-vacuous red pins above)."""
    cfg = RunnerConfig.from_env({"AUSMT_JOB_TIMEOUT_S": "120", "AUSMT_MAX_UPLOAD_MB": "500"})
    assert cfg.timeout_s == 120
    assert cfg.max_upload_bytes == 500 * 1024 * 1024
    default_cfg = RunnerConfig.from_env({})
    assert default_cfg.timeout_s >= 1 and default_cfg.max_upload_bytes > 0
