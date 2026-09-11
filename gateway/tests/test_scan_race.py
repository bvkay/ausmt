"""The inline-scan / poll-loop race on a freshly received submission.

A submit inserts its row at RECEIVED and THEN scans it inline, so for the duration of that scan the
row looks exactly like one held at RECEIVED because clamd was down. The poll loop's retry pass reads
RECEIVED rows, so it could scan and advance the row first; the inline path then tried
RECEIVED -> SCANNED on a row already at SCANNED, which the state machine correctly refuses -
IllegalTransition out of POST /gateway/submit as a 500, and jobs.write_pending run twice for one
submission.

The scan seam is gated on an asyncio.Event here, so the interleaving is exact rather than hopeful.
"""
from __future__ import annotations

import asyncio

import pytest

from gateway import clamd, db, jobs, states
from gateway.tests.conftest import app_client, good_package_zip, run, scanner_clean, submit_zip


def _gated_scanner(first_call_started: asyncio.Event, release: asyncio.Event, calls: list[int]):
    """A clean scanner whose FIRST call parks until `release` is set. The first call is the inline
    one (the submit handler), so the test can hold it open, run a whole poll pass underneath it, and
    then let it finish into a row the loop has already advanced."""
    async def _scan(data: bytes):
        calls.append(1)
        if len(calls) == 1:
            first_call_started.set()
            await release.wait()
        return clamd.ScanResult(clean=True, signature=None)
    return _scan


def test_poll_loop_scan_during_inline_scan_does_not_break_submit(tmp_path):
    # The race itself: the loop advances the row while the inline scan is still in flight.
    # Proven failing before the fix: the submit raised
    # db.IllegalTransition("illegal transition SCANNED -> SCANNED") out of the handler.
    async def _body():
        started, release, calls = asyncio.Event(), asyncio.Event(), []
        async with app_client(tmp_path, scanner=_gated_scanner(started, release, calls)) as (
                client, _app, gw, _cfg):
            pending = gw.cfg.jobs_dir / "pending"
            submit = asyncio.create_task(submit_zip(client, good_package_zip()))
            await asyncio.wait_for(started.wait(), 5)   # row is RECEIVED, inline scan parked
            await gw.poll_once()
            release.set()
            resp = await submit
            assert resp.status_code == 201
            sid = resp.json()["submission_id"]
            assert gw.db.get(sid).state == states.SCANNED
            # Exactly one advance in the audit trail: the opening RECEIVED row plus one SCANNED row.
            rows = gw.db.transitions_for(sid)
            assert [r["to_state"] for r in rows] == [states.RECEIVED, states.SCANNED], rows
            assert [p.name for p in sorted(pending.glob("*.json"))] == [f"{sid}.json"]
    run(_body())


def test_inline_scan_in_flight_is_not_rescanned_by_the_loop(tmp_path):
    # The in-flight set is what keeps the loop off a row the submit handler is already scanning:
    # one submission, one scan. Proven failing before the fix: two scan calls (inline + loop).
    async def _body():
        started, release, calls = asyncio.Event(), asyncio.Event(), []
        async with app_client(tmp_path, scanner=_gated_scanner(started, release, calls)) as (
                client, _app, gw, _cfg):
            submit = asyncio.create_task(submit_zip(client, good_package_zip()))
            await asyncio.wait_for(started.wait(), 5)
            await gw.poll_once()
            assert len(calls) == 1, "the poll loop rescanned a submission whose inline scan is live"
            release.set()
            await submit
    run(_body())


def test_write_pending_runs_once_per_submission(tmp_path, monkeypatch):
    # The job file is written by whichever scanner advances the row, and only by that one: a second
    # write_pending would re-queue an already-queued submission for the runner.
    # Proven failing before the fix: 2 calls (loop then inline, the inline one after the 500).
    async def _body():
        started, release, calls = asyncio.Event(), asyncio.Event(), []
        written: list[str] = []
        real_write_pending = jobs.write_pending

        def _counting_write_pending(jobs_dir, submission_id, zip_path, quarantine_dir):
            written.append(submission_id)
            return real_write_pending(jobs_dir, submission_id, zip_path, quarantine_dir)

        monkeypatch.setattr(jobs, "write_pending", _counting_write_pending)
        async with app_client(tmp_path, scanner=_gated_scanner(started, release, calls)) as (
                client, _app, gw, _cfg):
            submit = asyncio.create_task(submit_zip(client, good_package_zip()))
            await asyncio.wait_for(started.wait(), 5)
            await gw.poll_once()
            release.set()
            resp = await submit
            sid = resp.json()["submission_id"]
            assert written == [sid], written
    run(_body())


def test_scan_and_advance_is_idempotent_on_an_already_advanced_row(tmp_path):
    # The state check standing on its own, independent of the in-flight set: a second
    # _scan_and_advance on a row that has already left RECEIVED skips, rather than raising.
    # Proven failing before the fix: db.IllegalTransition SCANNED -> SCANNED on the second call.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip())
            sid = r.json()["submission_id"]
            assert gw.db.get(sid).state == states.SCANNED
            before = len(gw.db.transitions_for(sid))
            await gw._scan_and_advance(sid, cfg.incoming_dir / f"{sid}.zip")
            assert gw.db.get(sid).state == states.SCANNED
            assert len(gw.db.transitions_for(sid)) == before  # no second audit row
    run(_body())


def test_a_genuinely_held_row_is_still_retried_by_the_loop(tmp_path):
    # The retry pass the in-flight set must not disable: a row held at RECEIVED because clamd was
    # down at upload still advances once the scanner is back. Guards against "fix" the race by
    # letting the loop skip RECEIVED rows wholesale.
    async def _body():
        async with app_client(tmp_path, scanner=_never_reached_scanner()) as (
                client, _app, gw, _cfg):
            r = await submit_zip(client, good_package_zip())
            sid = r.json()["submission_id"]
            assert gw.db.get(sid).state == states.RECEIVED
            assert gw._scanning == set(), "the inline scan released its in-flight marker"
            gw._scan_bytes = scanner_clean()
            await gw.poll_once()
            assert gw.db.get(sid).state == states.SCANNED
            assert (gw.cfg.jobs_dir / "pending" / f"{sid}.json").exists()
    run(_body())


def _never_reached_scanner():
    async def _scan(data: bytes):
        raise clamd.ScanError("fake: clamd down")
    return _scan


def test_scan_error_still_holds_at_received(tmp_path):
    # Fail-closed is unchanged by the in-flight bookkeeping: a ScanError leaves the row at RECEIVED
    # with no job queued and no in-flight marker left behind.
    async def _body():
        async with app_client(tmp_path, scanner=_never_reached_scanner()) as (
                client, _app, gw, _cfg):
            r = await submit_zip(client, good_package_zip())
            assert r.status_code == 201
            sid = r.json()["submission_id"]
            assert gw.db.get(sid).state == states.RECEIVED
            assert not (gw.cfg.jobs_dir / "pending" / f"{sid}.json").exists()
            assert gw._scanning == set()
    run(_body())


def test_illegal_transition_is_still_raised_for_a_real_bug(tmp_path):
    # The idempotent skip must be a state check, not a swallowed exception: an illegal move that is
    # NOT the benign already-advanced case still raises out of db.transition.
    database = db.Database(tmp_path / "gateway.sqlite")
    sid = db.new_id()
    database.insert_submission(
        submission_id=sid, zip_sha256="a" * 64, zip_bytes=10, submitter_name="N",
        submitter_email="e@x.org", submitter_orcid=None, token_hash="h" * 64,
    )
    with pytest.raises(db.IllegalTransition):
        database.transition(sid, states.VALIDATED, actor="test", reason="skip")
    database.close()
