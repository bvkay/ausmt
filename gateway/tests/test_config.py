"""Config + fail-closed startup guard (design §3/§7). The server refuses to start on a missing or
short submit key; config logging redacts the key.
"""
from __future__ import annotations

import pytest

from gateway.config import DEFAULT_MAX_UPLOAD_MB, fail_closed_startup, load_config
from gateway.tests.conftest import make_config


def test_missing_key_aborts_startup(tmp_path):
    # proven failing 2026-07-05: an empty AUSMT_SUBMIT_KEY was accepted and the app bound a port —
    # fail_closed_startup returned instead of raising SystemExit.
    cfg = make_config(tmp_path, submit_key="")
    with pytest.raises(SystemExit):
        fail_closed_startup(cfg)


def test_short_key_aborts_startup(tmp_path):
    cfg = make_config(tmp_path, submit_key="short")  # < 16 chars
    with pytest.raises(SystemExit):
        fail_closed_startup(cfg)


def test_adequate_key_starts(tmp_path):
    cfg = make_config(tmp_path, submit_key="a-sufficiently-long-key-1234")
    fail_closed_startup(cfg)  # no raise


def test_redacted_items_omit_key(tmp_path):
    # The startup config dump must never carry the key value (design §7).
    cfg = make_config(tmp_path, submit_key="super-secret-key-value-9999")
    items = dict(cfg.redacted_items())
    assert "super-secret-key-value-9999" not in items.values()
    assert items["AUSMT_SUBMIT_KEY"] == "<redacted>"


def test_env_defaults():
    cfg = load_config({"AUSMT_SUBMIT_KEY": "x" * 20})
    assert cfg.max_upload_mb == DEFAULT_MAX_UPLOAD_MB  # M2: the ONE default, not a re-typed 250
    assert cfg.max_inflight == 8
    assert cfg.max_per_day == 25
    assert cfg.job_timeout_s == 900
    assert cfg.clamd_host == "clamd"
    assert cfg.clamd_port == 3310


def test_default_upload_cap_is_250_mb():
    # The one place the CONCRETE 250 value is asserted, so a deliberate change to the operator-facing
    # default is a visible one-line test edit here (not silently spread across config + runner).
    # FAILS IF the shared default is changed without updating this pin.
    assert DEFAULT_MAX_UPLOAD_MB == 250


# --------------------------------------------------------------------------------------------------
# G7: numeric floors. A zero or negative knob is a typo, never an operator intent, and every one of
# them fails INVISIBLY at runtime: the health surfaces stay green while the gateway serves a wall of
# 413/429 or bounces every curator login. The floor belongs at startup for the same reason the key
# guard does: loud and early, before the port binds.
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("knob,value", [
    ("max_upload_mb", 0),          # reproduced: every submission 413 "upload exceeds size limit"
    ("max_inflight", 0),           # reproduced: every submission 429
    ("max_per_day", 0),
    ("job_timeout_s", 0),
    ("session_ttl_s", 0),          # reproduced: login 303s to the queue, the queue 303s back - lockout
    ("login_max_attempts", 0),
    ("login_window_s", 0),
    ("edit_timeout_s", 0),
    ("clamd_port", 0),
    ("smtp_port", 0),
    ("key_request_per_email_daily", 0),
    ("key_request_per_ip_daily", 0),
    ("key_request_global_daily", 0),   # reproduced: issuance silently off behind the neutral 202
    ("email_verified_key_expiry_days", 0),
    ("email_verified_key_allowance", 0),
    ("max_upload_mb", -1),
    ("session_ttl_s", -1),
    ("clamd_port", 65536),         # out the top end: not a port
    ("smtp_port", 70000),
])
def test_out_of_range_knob_aborts_startup(tmp_path, knob, value):
    """Every numeric knob whose zero/negative value can never be legitimate must abort the process at
    startup, and the abort message must name the knob so the operator can fix the env var.

    Scope: config.fail_closed_startup range checks. FAILS IF a knob is dropped from the guard or its
    floor is wrong. RED against the pre-guard config: fail_closed_startup validated only the submit
    key, so every case here returned None and the app went on to bind a port.
    """
    cfg = make_config(tmp_path, **{knob: value})
    with pytest.raises(SystemExit) as excinfo:
        fail_closed_startup(cfg)
    assert knob in str(excinfo.value), f"the abort must name the knob: {excinfo.value}"


def test_in_range_knobs_start(tmp_path):
    # The floors are floors, not narrowings: the shipped defaults and the tight-but-legitimate edge
    # (a 1 MB cap, one in-flight submit, a 1-second session) all still start.
    fail_closed_startup(make_config(tmp_path))
    fail_closed_startup(make_config(tmp_path, max_upload_mb=1, max_inflight=1, session_ttl_s=1,
                                    clamd_port=65535, smtp_port=1))
    fail_closed_startup(load_config({"AUSMT_SUBMIT_KEY": "x" * 20}))


def test_startup_guard_reports_the_key_first(tmp_path):
    # The key guard is the design §3 abort and must keep its own message: a config that is BOTH
    # key-less and out of range still fails on the key, so the operator's first fix is the secret.
    cfg = make_config(tmp_path, submit_key="", max_inflight=0)
    with pytest.raises(SystemExit) as excinfo:
        fail_closed_startup(cfg)
    assert "AUSMT_SUBMIT_KEY" in str(excinfo.value)
