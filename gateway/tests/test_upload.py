"""Upload-path guards through the HTTP seam (design §4/§8). Every hostile shape is rejected at upload
with a distinct reason AND leaves nothing under quarantine/; capacity/auth/oversize/duplicate guards;
the clamd verdicts (clean/EICAR/down) drive the right state.

Proven-failing-first: evidence recorded per-test. The upload rejections were confirmed to genuinely
gate by asserting a rejected upload leaves NOTHING under quarantine — a real observable, not the
response code echoing itself.
"""
from __future__ import annotations

import asyncio
import tempfile

import pytest
from starlette.formparsers import MultiPartParser
from starlette.requests import Request

from gateway import states
from gateway.tests.conftest import (
    SUBMIT_KEY, FakeGit, app_client, csrf_for_session, curator_login, eicar_package_zip,
    good_package_zip, make_zip, ratio_bomb_zip, run, scanner_clean, scanner_down,
    scanner_eicar_aware, settle_publish, submit_zip,
)


def _multipart_body(file_bytes: bytes, *, boundary: bytes = b"----ausmttestboundary") -> tuple[bytes, str]:
    """Build a minimal multipart/form-data body (file + the two required text fields)."""
    parts = []
    parts.append(b"--" + boundary + b"\r\n")
    parts.append(b'Content-Disposition: form-data; name="submitter_name"\r\n\r\nCI\r\n')
    parts.append(b"--" + boundary + b"\r\n")
    parts.append(b'Content-Disposition: form-data; name="submitter_email"\r\n\r\nci@example.test\r\n')
    parts.append(b"--" + boundary + b"\r\n")
    parts.append(b'Content-Disposition: form-data; name="file"; filename="p.zip"\r\n'
                 b"Content-Type: application/zip\r\n\r\n")
    parts.append(file_bytes)
    parts.append(b"\r\n--" + boundary + b"--\r\n")
    body = b"".join(parts)
    return body, f"multipart/form-data; boundary={boundary.decode()}"


def _quarantine_empty(cfg) -> bool:
    q = cfg.quarantine_dir
    return not q.exists() or not any(q.iterdir())


def test_missing_key_unauthorized(tmp_path):
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, cfg):
            r = await submit_zip(client, good_package_zip(), key=None)
            assert r.status_code == 401
            assert _quarantine_empty(cfg)
    run(_body())


def test_wrong_key_unauthorized(tmp_path):
    # proven failing 2026-07-05: with the hmac check stubbed to True, this returned 201 not 401.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, cfg):
            r = await submit_zip(client, good_package_zip(), key="wrong-key-but-long-enough")
            assert r.status_code == 401
    run(_body())


def test_good_upload_scans_clean_and_queues(tmp_path):
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip())
            assert r.status_code == 201, r.text
            body = r.json()
            assert body["status_url"].startswith("/gateway/status/")
            sub = gw.db.get(body["submission_id"])
            assert sub.state == states.SCANNED
            # A pending job was queued with NO PII in it.
            pending = list((cfg.jobs_dir / "pending").glob("*.json"))
            assert len(pending) == 1
            text = pending[0].read_text(encoding="utf-8")
            assert "tester@example.org" not in text
            assert "Test Tester" not in text
    run(_body())


@pytest.mark.parametrize("zip_factory,needle", [
    (lambda: make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/../evil.edi": b"x"}), "parent-directory"),
    (lambda: make_zip({"mysurvey/survey.yaml": b"s", "/etc/evil.edi": b"x"}), "absolute path"),
    (lambda: make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/inner.zip": b"PK", "mysurvey/S.edi": b"e"}), "nested archive"),
    (lambda: make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/README.md": b"hi"}),
     "no transfer-function members"),
    (lambda: make_zip({"a/survey.yaml": b"s", "a/S.edi": b"e", "b/x.txt": b"y"}), "top-level"),
])
def test_hostile_zip_rejected_nothing_quarantined(tmp_path, zip_factory, needle):
    # proven failing 2026-07-05: before wiring zipsafety.inspect() into handle_submit, a hostile zip
    # returned 201 and the .zip landed in incoming/ (quarantine still empty, but the row advanced) —
    # the "distinct reason" assert failed and the state was SCANNED.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, cfg):
            r = await submit_zip(client, zip_factory())
            assert r.status_code == 400, r.text
            assert needle in r.json()["detail"]
            assert _quarantine_empty(cfg)
            # No incoming .zip promoted, no DB row created.
            assert not any(cfg.incoming_dir.glob("*.zip"))
    run(_body())


def test_ratio_bomb_rejected_at_upload(tmp_path):
    # The ratio-bomb fixture is ~2 MiB (compress_size must exceed the 1-MiB ratio gate), so it needs
    # an upload cap above that to reach the zip inspection rather than the size guard. max_upload_mb=8
    # gives a 32-MiB uncompressed ceiling (4x) that the 400-MiB LYING file_size still blows past —
    # the ratio guard fires first (per-member, inside the loop) with a "ratio" reason.
    # proven failing 2026-07-05: with the ratio guard disabled the upload returned 201, state SCANNED.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean(), max_upload_mb=8) as (client, _app, _gw, cfg):
            r = await submit_zip(client, ratio_bomb_zip())
            assert r.status_code == 400, r.text
            assert "ratio" in r.json()["detail"]
            assert _quarantine_empty(cfg)
            assert not any(cfg.incoming_dir.glob("*.zip"))
    run(_body())


def test_oversize_aborts_and_leaves_no_part_file(tmp_path):
    # max_upload_mb=1 (conftest); send > 1 MiB. proven failing 2026-07-05: without the mid-stream
    # cap, the whole 2-MiB body was written and a .part file remained after the 413.
    async def _body():
        big = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/S.edi": b"A" * (2 * 1024 * 1024)})
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, cfg):
            r = await submit_zip(client, big)
            assert r.status_code == 413
            assert not any(cfg.incoming_dir.glob("*.part"))
            assert not any(cfg.incoming_dir.glob("*.zip"))
    run(_body())


def test_midstream_cap_when_content_length_passes_gate(tmp_path):
    # A file part ~1.5 MiB with max_upload_mb=1: the total body (~1.5 MiB) is under the
    # Content-Length gate (cap + 1 MiB overhead = 2 MiB), so it reaches the streaming loop — where
    # the mid-stream byte count (1.5 MiB > 1 MiB cap) aborts with 413 and deletes the .part file.
    # This exercises the AUTHORITATIVE cap (not the declared-length gate), proving a body that lies
    # its way past Content-Length still cannot exceed the cap on disk.
    # proven failing 2026-07-05: with the mid-stream cap removed, the 1.5-MiB part was written whole
    # and promoted to a .zip.
    async def _body():
        payload = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/S.edi": b"A" * (1536 * 1024)})
        assert len(payload) < 2 * 1024 * 1024  # sanity: under the CL gate for max_upload_mb=1
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, cfg):
            r = await submit_zip(client, payload)
            assert r.status_code == 413
            assert not any(cfg.incoming_dir.glob("*.part"))
            assert not any(cfg.incoming_dir.glob("*.zip"))
    run(_body())


def test_bad_orcid_rejected(tmp_path):
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, _cfg):
            r = await submit_zip(client, good_package_zip(), orcid="0000-0002-1825-0098")
            assert r.status_code == 400
            assert "orcid" in r.json()["detail"].lower()
    run(_body())


def test_good_orcid_accepted(tmp_path):
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, _cfg):
            r = await submit_zip(client, good_package_zip(), orcid="0000-0002-1825-0097")
            assert r.status_code == 201
    run(_body())


def test_duplicate_sha_conflicts(tmp_path):
    # Same bytes, still non-terminal -> 409 pointing at the first (design §4.4).
    # proven failing 2026-07-05: without the sha lookup, the second upload got its own 201.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_down()) as (client, _app, _gw, _cfg):
            # scanner_down keeps the first at RECEIVED (non-terminal) so the dup check has a live row.
            z = good_package_zip()
            r1 = await submit_zip(client, z)
            assert r1.status_code == 201
            r2 = await submit_zip(client, z)
            assert r2.status_code == 409
            assert r2.json()["submission_id"] == r1.json()["submission_id"]
    run(_body())


def _materialise_curation_artifacts(cfg, sid: str, slug: str) -> None:
    """The package tree + reports the gw-runner leaves behind, so the curator checklist, the PII
    sweep and the publish stage have something real to read. Written here rather than reusing
    seed_validated because these tests need the artifacts to belong to a submission that came in
    through the REAL upload path (its own zip_sha256), not to a row inserted beside it."""
    import json

    pkg = cfg.quarantine_dir / sid / "package" / slug
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "survey.yaml").write_text("survey:\n  slug: %s\n" % slug, encoding="utf-8")
    reports = cfg.quarantine_dir / sid / "reports"
    (reports / "preview-data").mkdir(parents=True, exist_ok=True)
    (reports / "validate.json").write_text(
        json.dumps({"items": [{"level": "PASS", "name": "structure", "message": "ok"}]}),
        encoding="utf-8")
    (reports / "preview-summary.json").write_text(
        json.dumps({"station_count": 1, "types": ["MT"], "coord_flags": [], "warnings": []}),
        encoding="utf-8")
    (reports / "preview-data" / "index.html").write_text(
        "<!doctype html><title>preview</title><p>preview shell</p>", encoding="utf-8")


def test_duplicate_sha_conflicts_after_the_first_was_approved_and_published(tmp_path):
    """The duplicate-content guard is about CONTENT, not liveness: bytes the archive has already
    ingested and PUBLISHED must not buy a second scan + validate + preview cycle, nor a second
    publish of the identical package under a fresh submission id.

    This is the exact sequence deploy-images.yml's curator-e2e drives (submit the fixture, approve
    it, then submit the byte-identical zip again) and the 409 that job's reject leg names.

    FAILS IF the second submit of identical bytes is accepted. Proven failing 2026-08-04 against
    find_active_by_sha: PUBLISHED is a TERMINAL state, so the lookup skipped the first row entirely
    and the resubmit got its own 201 with a new submission id.
    """
    async def _body():
        git = FakeGit()
        async with app_client(tmp_path, scanner=scanner_clean(), git_runner=git) as (
                client, _app, gw, cfg):
            z = good_package_zip()
            r1 = await submit_zip(client, z)
            assert r1.status_code == 201
            sid = r1.json()["submission_id"]
            assert gw.db.get(sid).state == states.SCANNED

            # What the runner does in production: VALIDATED plus the artifacts on disk.
            gw.db.transition(sid, states.VALIDATED, actor="runner", reason="validated",
                             slug="mysurvey")
            _materialise_curation_artifacts(cfg, sid, "mysurvey")

            await curator_login(client)
            approved = await client.post(
                f"/gateway/curator/submission/{sid}/approve",
                data={"note": "approved by the test", "csrf_token": csrf_for_session(client)},
                follow_redirects=False)
            assert approved.status_code == 303, approved.text
            await settle_publish(gw, sid)
            assert gw.db.get(sid).state == states.PUBLISHED

            r2 = await submit_zip(client, z, email="someone-else@example.org", name="Someone Else")
            assert r2.status_code == 409, (
                "identical bytes were accepted again after the first copy was published: "
                f"{r2.status_code} {r2.text}")
            assert r2.json()["submission_id"] == sid
            # Refused at the door: no second row, and nothing promoted into incoming/.
            assert len(gw.db.ids_in_state(states.SCANNED)) == 0
            assert not any(cfg.incoming_dir.glob("*.part"))
    run(_body())


def test_duplicate_sha_conflicts_after_the_first_was_rejected_by_the_scanner(tmp_path):
    """The same rule at the other terminal state, and the cheap one to reason about: bytes clamd
    already called a virus are still that virus on the second upload. A fresh 201 would mean an
    attacker can make the gateway re-scan and re-log the same payload without limit.

    FAILS IF the resubmit of an already REJECTED_AV package is accepted. Proven failing 2026-08-04:
    REJECTED_AV is terminal, so the second upload got its own 201 and its own audit trail.
    """
    async def _body():
        async with app_client(tmp_path, scanner=scanner_eicar_aware()) as (client, _app, gw, _cfg):
            z = eicar_package_zip()
            r1 = await submit_zip(client, z)
            assert r1.status_code == 201
            sid = r1.json()["submission_id"]
            assert gw.db.get(sid).state == states.REJECTED_AV

            r2 = await submit_zip(client, z)
            assert r2.status_code == 409, (
                f"identical infected bytes were accepted again: {r2.status_code} {r2.text}")
            assert r2.json()["submission_id"] == sid
    run(_body())


def test_eicar_upload_rejected_av_and_zip_deleted(tmp_path):
    # proven failing 2026-07-05: with the FOUND branch not deleting the zip, the file remained in
    # incoming/ after REJECTED_AV.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_eicar_aware()) as (client, _app, gw, cfg):
            r = await submit_zip(client, eicar_package_zip())
            assert r.status_code == 201
            sub = gw.db.get(r.json()["submission_id"])
            assert sub.state == states.REJECTED_AV
            assert not any(cfg.incoming_dir.glob("*.zip"))  # raw zip deleted immediately (design §2)
    run(_body())


def test_clamd_down_holds_at_received_then_advances(tmp_path):
    # clamd down at upload -> RECEIVED (fail closed). A later poll pass with clamd back -> SCANNED.
    # proven failing 2026-07-05: an early version advanced on ScanError (treating it as clean) —
    # the state was SCANNED right after upload with clamd down.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_down()) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip())
            assert r.status_code == 201
            sid = r.json()["submission_id"]
            assert gw.db.get(sid).state == states.RECEIVED
            assert (cfg.incoming_dir / f"{sid}.zip").exists()  # kept for retry
            # clamd comes back: swap the scanner and drive one poll pass.
            gw._scan_bytes = scanner_clean()
            await gw.poll_once()
            assert gw.db.get(sid).state == states.SCANNED
    run(_body())


def test_capacity_inflight_cap(tmp_path):
    # proven failing 2026-07-05: without the inflight gate the 2nd upload got 201 at max_inflight=1.
    async def _body():
        async with app_client(tmp_path, scanner=scanner_down(), max_inflight=1) as (client, _app, _gw, _cfg):
            r1 = await submit_zip(client, good_package_zip())
            assert r1.status_code == 201  # held at RECEIVED (non-terminal) -> inflight=1
            r2 = await submit_zip(client, make_zip({"mysurvey/survey.yaml": b"s2", "mysurvey/S.edi": b"e2"}))
            assert r2.status_code == 429
    run(_body())


def test_chunked_oversize_rejected_no_content_length(tmp_path):
    # A Transfer-Encoding: chunked upload carries NO Content-Length, so the old declared-length gate
    # never fired; the capped stream must reject it as bytes arrive. max_upload_mb=1 (conftest), send
    # a ~3 MiB body via a streaming generator (httpx omits Content-Length -> chunked).
    # proven failing 2026-07-05 (before the capped-stream intake): the old code buffered the whole
    # 3-MiB chunked body into request.form()'s spool and returned 400 (missing/oversize part) only
    # after buffering, or 201 — never a clean 413 pre-buffer.
    async def _body():
        big_zip = make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/S.edi": b"B" * (3 * 1024 * 1024)})
        body, content_type = _multipart_body(big_zip)

        async def _gen():
            # Yield in chunks; httpx sends this as chunked transfer-encoding (no Content-Length).
            for i in range(0, len(body), 64 * 1024):
                yield body[i:i + 64 * 1024]

        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, cfg):
            r = await client.post(
                "/gateway/submit", content=_gen(),
                headers={"X-AusMT-Submit-Key": SUBMIT_KEY, "Content-Type": content_type},
            )
            assert "content-length" not in {k.lower() for k in r.request.headers}  # was chunked
            assert r.status_code == 413, r.text
            assert not any(cfg.incoming_dir.glob("*.part"))
            assert not any(cfg.incoming_dir.glob("*.zip"))
            # Nothing spooled to /tmp either: the intake pins the spool to incoming/. No stray temp
            # files should linger under incoming (the .part is cleaned; SpooledTemporaryFile unlinks).
            assert not any(p.name.startswith("tmp") for p in cfg.incoming_dir.iterdir())
    run(_body())


def test_concurrent_submits_respect_inflight_cap(tmp_path):
    # Cap TOCTOU: fire 8 concurrent submits at max_inflight=3. The scanner is held open so any row
    # that gets inserted stays RECEIVED (non-terminal, i.e. in-flight) for the whole race; a barrier
    # inside the body-parse holds EVERY handler after its capacity check but before its insert, so
    # all 8 have passed the gate with durable count_inflight()==0 — only the in-memory reservation
    # can hold the cap. proven failing 2026-07-05 (reservation disabled): 8/8 returned 201.
    from gateway import upload as upload_intake

    async def _body():
        gate_release = asyncio.Event()
        real_parse = upload_intake.parse_capped

        async def barrier_parse(request, max_bytes, spool_dir):
            # Runs AFTER the capacity check (which is synchronous, at the top of handle_submit) and
            # BEFORE insert_submission — exactly the TOCTOU window. Hold here so every handler has
            # passed the gate before any inserts, then do the real parse.
            await gate_release.wait()
            return await real_parse(request, max_bytes, spool_dir)

        upload_intake.parse_capped = barrier_parse  # type: ignore[assignment]
        try:
            async with app_client(tmp_path, scanner=scanner_down(), max_inflight=3) as (client, _app, _gw, _cfg):
                zips = [make_zip({"mysurvey/survey.yaml": bytes([i]), "mysurvey/S.edi": bytes([i, 9])})
                        for i in range(8)]
                tasks = [asyncio.ensure_future(submit_zip(client, z)) for z in zips]
                await asyncio.sleep(0.05)  # let all 8 reach the barrier (all past the gate)
                gate_release.set()
                results = await asyncio.gather(*tasks)
        finally:
            upload_intake.parse_capped = real_parse  # type: ignore[assignment]
        codes = sorted(r.status_code for r in results)
        accepted = sum(1 for c in codes if c == 201)
        rejected = sum(1 for c in codes if c == 429)
        assert accepted <= 3, f"cap bypassed: {codes}"
        assert rejected >= 5, f"expected >=5 rejections: {codes}"
    run(_body())


# --------------------------------------------------------------------------------------------------
# The intake's spool pinning under concurrency. max_inflight defaults to 8, so two parses overlapping
# is a supported mode, not a hypothetical, and a spool that escapes to the OS tempdir defeats the
# only headroom gate the upload path has (_free_bytes(incoming_dir) in handle_submit).
# --------------------------------------------------------------------------------------------------
def _queued_request(content_type: str) -> tuple[Request, asyncio.Queue]:
    """A REAL starlette Request whose body arrives from a queue the test controls, so two parses can
    be interleaved deterministically instead of raced."""
    queue: asyncio.Queue = asyncio.Queue()
    scope = {"type": "http", "method": "POST", "path": "/gateway/submit",
             "headers": [(b"content-type", content_type.encode("latin-1"))]}
    return Request(scope, queue.get), queue


async def _feed(queue: asyncio.Queue, body: bytes, chunk: int = 64 * 1024) -> None:
    for i in range(0, len(body), chunk):
        await queue.put({"type": "http.request", "body": body[i:i + chunk], "more_body": True})
    await queue.put({"type": "http.request", "body": b"", "more_body": False})


def test_concurrent_parses_never_spool_outside_the_spool_dir(tmp_path, monkeypatch):
    """Two overlapping parse_capped calls must EACH spool onto their own measured volume. A rolled-over
    SpooledTemporaryFile is unlinked the instant it is created, so the observable used here is the OS
    tempdir pointed at a path that does not exist: a part that rolls over anywhere but spool_dir cannot
    be created at all, and a part that honours spool_dir reads back whole.

    Scope: gateway.upload.parse_capped's spool pinning under concurrency, plus the invariant that the
    parse leaves starlette's module namespace exactly as it found it. FAILS IF the pinning is
    per-process rather than per-parse. RED against the module-global monkeypatch: parse B raised
    "FileNotFoundError: [Errno 2] No such file or directory: '<missing>/tmp...'" because parse A's
    finally had already restored the real stdlib factory, and starlette.formparsers.SpooledTemporaryFile
    was left holding parse A's leaked closure afterwards.
    """
    from gateway import upload as upload_intake
    import starlette.formparsers as fp

    # Any rollover that is NOT pinned to a spool_dir lands here, and this directory never exists.
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "unmeasured-os-tmpdir"))
    spool_a, spool_b = tmp_path / "incoming-a", tmp_path / "incoming-b"
    # Each part must exceed the parser's in-memory spool budget so it genuinely rolls over to disk.
    assert MultiPartParser.spool_max_size <= 1024 * 1024
    payload_a = b"A" * (1536 * 1024)
    payload_b = b"B" * (1536 * 1024)
    cap = 8 * 1024 * 1024

    async def _body():
        body_a, ctype_a = _multipart_body(payload_a)
        body_b, ctype_b = _multipart_body(payload_b, boundary=b"----ausmtsecondboundary")
        req_a, queue_a = _queued_request(ctype_a)
        req_b, queue_b = _queued_request(ctype_b)

        task_a = asyncio.ensure_future(upload_intake.parse_capped(req_a, cap, spool_a))
        task_b = asyncio.ensure_future(upload_intake.parse_capped(req_b, cap, spool_b))
        await asyncio.sleep(0.05)  # both parses are now inside parse_capped, blocked on their stream

        # A runs to completion while B is still mid-parse: the window where a per-process pin is torn
        # down under B's feet.
        await _feed(queue_a, body_a)
        form_a = await task_a
        await _feed(queue_b, body_b)
        try:
            form_b = await task_b
        except FileNotFoundError as exc:
            raise AssertionError(
                f"the second concurrent parse spooled outside its spool_dir, into the OS tempdir: {exc}"
            ) from exc

        assert await form_a.file.read() == payload_a
        assert await form_b.file.read() == payload_b
        assert fp.SpooledTemporaryFile is tempfile.SpooledTemporaryFile, \
            "the parse left a factory behind in starlette's module namespace"
    run(_body())
