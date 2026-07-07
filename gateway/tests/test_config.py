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
