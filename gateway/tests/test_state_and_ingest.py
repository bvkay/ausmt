"""State machine + done-file ingest (design §2/§5/§8). The property: only legal transitions are
possible, and every transition writes exactly one audit row. Ingest of a forged/unknown done-file
is logged and ignored (no transition).

Proven-failing-first evidence per test.
"""
from __future__ import annotations

import json
import time

import pytest

from gateway import db, jobs, states
from gateway.tests.conftest import (
    app_client, good_package_zip, run, scanner_clean, submit_zip,
)


def _fresh_db(tmp_path):
    return db.Database(tmp_path / "gateway.sqlite")


def _seed_received(database) -> str:
    sid = db.new_id()
    database.insert_submission(
        submission_id=sid, zip_sha256="a" * 64, zip_bytes=10,
        submitter_name="N", submitter_email="e@x.org", submitter_orcid=None, token_hash="h" * 64,
    )
    return sid


def test_illegal_transition_refused_no_row(tmp_path):
    # RECEIVED -> VALIDATED is not in states.ALLOWED (must pass through SCANNED). The DB must refuse
    # AND leave the audit log untouched.
    # proven failing 2026-07-05: an early transition() wrote the row before checking legality —
    # transitions count went 1 -> 2 on the illegal move.
    database = _fresh_db(tmp_path)
    sid = _seed_received(database)
    before = len(database.transitions_for(sid))
    with pytest.raises(db.IllegalTransition):
        database.transition(sid, states.VALIDATED, actor="test", reason="skip")
    assert database.get(sid).state == states.RECEIVED
    assert len(database.transitions_for(sid)) == before  # no audit row for a refused move
    database.close()


def test_every_legal_transition_writes_exactly_one_row(tmp_path):
    # RECEIVED -> SCANNED -> VALIDATED: 1 opening row + 2 transition rows = 3 total.
    database = _fresh_db(tmp_path)
    sid = _seed_received(database)
    assert len(database.transitions_for(sid)) == 1  # the opening RECEIVED row
    database.transition(sid, states.SCANNED, actor="gateway", reason="clean")
    database.transition(sid, states.VALIDATED, actor="runner", reason="ok")
    rows = database.transitions_for(sid)
    assert len(rows) == 3
    assert [r["to_state"] for r in rows] == [states.RECEIVED, states.SCANNED, states.VALIDATED]
    database.close()


def test_terminal_state_cannot_transition(tmp_path):
    database = _fresh_db(tmp_path)
    sid = _seed_received(database)
    database.transition(sid, states.SCANNED, actor="g", reason="")
    database.transition(sid, states.QUARANTINED, actor="r", reason="")
    with pytest.raises(db.IllegalTransition):
        database.transition(sid, states.VALIDATED, actor="r", reason="")
    database.close()


def test_allowed_set_matches_state_diagram():
    # Guard against silent widening of the state machine: the exact legal set is frozen (C10 §2 +
    # C11 §1). If a future change adds a transition, it must be reflected HERE deliberately.
    assert states.ALLOWED == frozenset({
        (states.RECEIVED, states.SCANNED),
        (states.RECEIVED, states.REJECTED_AV),
        (states.SCANNED, states.VALIDATED),
        (states.SCANNED, states.QUARANTINED),
        (states.VALIDATED, states.PUBLISHING),
        (states.VALIDATED, states.RETURNED),
        (states.VALIDATED, states.REJECTED),
        (states.PUBLISHING, states.PUBLISHED),
        (states.PUBLISHING, states.PUBLISH_FAILED),
        (states.PUBLISH_FAILED, states.PUBLISHING),
    })


def test_validated_is_no_longer_terminal():
    # C11 §1: VALIDATED stops being terminal (curator actions reopen it). PUBLISHING/PUBLISH_FAILED
    # are transient/recoverable, not terminal. proven failing 2026-07-06: with the C10 TERMINAL set
    # (VALIDATED terminal) a VALIDATED->PUBLISHING approve was refused as an illegal transition.
    assert not states.is_terminal(states.VALIDATED)
    assert not states.is_terminal(states.PUBLISHING)
    assert not states.is_terminal(states.PUBLISH_FAILED)
    for terminal in (states.PUBLISHED, states.REJECTED, states.RETURNED,
                     states.QUARANTINED, states.REJECTED_AV):
        assert states.is_terminal(terminal)


def _advance_to_scanned(gw, client):
    async def _do():
        r = await submit_zip(client, good_package_zip())
        return r.json()["submission_id"]
    return _do


def test_ingest_validated_done_advances_and_sweeps(tmp_path):
    # A SCANNED submission + a 'validated' done-file -> VALIDATED (post-unpack sweep clean).
    # proven failing 2026-07-05: without _ingest_done wired into poll_once the state stayed SCANNED.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip())
            sid = r.json()["submission_id"]
            assert gw.db.get(sid).state == states.SCANNED
            # No package on disk -> sweep is a no-op clean pass.
            _write_done(cfg, sid, jobs.OUTCOME_VALIDATED, "ok", {"slug": "mysurvey"})
            await gw.poll_once()
            sub = gw.db.get(sid)
            assert sub.state == states.VALIDATED
            assert sub.slug == "mysurvey"
    run(_body())


def test_ingest_quarantined_done(tmp_path):
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip())
            sid = r.json()["submission_id"]
            _write_done(cfg, sid, jobs.OUTCOME_QUARANTINED, "validator reported FAIL", {})
            await gw.poll_once()
            assert gw.db.get(sid).state == states.QUARANTINED
    run(_body())


def test_forged_done_file_ignored(tmp_path):
    # A done-file with an unknown outcome / unknown submission must NOT drive any transition
    # (design §8). proven failing 2026-07-05: read_done returned a DoneFile for outcome='approve'
    # and _apply_done attempted a transition.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip())
            sid = r.json()["submission_id"]
            done_dir = cfg.jobs_dir / "done"
            done_dir.mkdir(parents=True, exist_ok=True)
            # forged outcome
            (done_dir / f"{sid}.json").write_text(
                json.dumps({"submission_id": sid, "outcome": "approve"}), encoding="utf-8")
            # unknown submission id
            (done_dir / "ghost.json").write_text(
                json.dumps({"submission_id": "GHOST", "outcome": jobs.OUTCOME_VALIDATED}), encoding="utf-8")
            await gw.poll_once()
            assert gw.db.get(sid).state == states.SCANNED  # unchanged
            # both forged files consumed (dropped), not left to loop forever
            assert not list(done_dir.glob("*.json"))
    run(_body())


def test_post_unpack_sweep_hit_quarantines(tmp_path):
    # A 'validated' done-file but the second clamd sweep hits -> QUARANTINED av_post_unpack.
    # proven failing 2026-07-05: without the sweep the submission went VALIDATED despite the hit.
    from gateway import clamd

    async def _body():
        async def scan_found(data: bytes):
            return clamd.ScanResult(clean=False, signature="Eicar-Test-Signature")

        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip())
            sid = r.json()["submission_id"]
            # materialise a package file so the sweep has something to scan
            pkg = cfg.quarantine_dir / sid / "package" / "mysurvey"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "S01.edi").write_bytes(b"content")
            _write_done(cfg, sid, jobs.OUTCOME_VALIDATED, "ok", {})
            gw._scan_bytes = scan_found  # sweep uses the injected scanner
            await gw.poll_once()
            sub = gw.db.get(sid)
            assert sub.state == states.QUARANTINED
            assert "av_post_unpack" in gw.db.transitions_for(sid)[-1]["reason"]
    run(_body())


def test_dead_job_requeued_once_then_quarantined(tmp_path):
    # A running-file older than 2x timeout: first dead pass re-queues it (a pending file reappears);
    # a second dead pass quarantines with 'job died twice' (design §5 crash recovery).
    # proven failing 2026-07-05: without _requeue_dead the stale running-file was never noticed and
    # the submission sat at SCANNED forever.
    import os

    async def _body():
        # job_timeout_s tiny so "2x timeout ago" is trivially in the past for a just-touched file.
        async with app_client(tmp_path, scanner=scanner_clean(), job_timeout_s=0) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip())
            sid = r.json()["submission_id"]
            # Simulate a runner that claimed the job then died: move pending -> running, backdate it.
            pending = cfg.jobs_dir / "pending" / f"{sid}.json"
            running = cfg.jobs_dir / "running" / f"{sid}.json"
            running.parent.mkdir(parents=True, exist_ok=True)
            pending.replace(running)
            old = time.time() - 10
            os.utime(running, (old, old))

            await gw.poll_once()  # first dead pass -> re-queued
            assert (cfg.jobs_dir / "pending" / f"{sid}.json").exists()
            assert gw.db.get(sid).state == states.SCANNED

            # The runner "dies" again: re-claim + backdate, then a second dead pass.
            (cfg.jobs_dir / "pending" / f"{sid}.json").replace(running)
            os.utime(running, (old, old))
            await gw.poll_once()
            assert gw.db.get(sid).state == states.QUARANTINED
            assert "died twice" in gw.db.transitions_for(sid)[-1]["reason"]
    run(_body())


def _write_done(cfg, sid, outcome, reason, refs):
    done_dir = cfg.jobs_dir / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    (done_dir / f"{sid}.json").write_text(
        json.dumps({"submission_id": sid, "outcome": outcome, "reason": reason, "report_refs": refs}),
        encoding="utf-8")


def test_wal_mode_enabled(tmp_path):
    database = _fresh_db(tmp_path)
    mode = database._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    database.close()
