"""Upload-path guards through the HTTP seam (design §4/§8). Every hostile shape is rejected at upload
with a distinct reason AND leaves nothing under quarantine/; capacity/auth/oversize/duplicate guards;
the clamd verdicts (clean/EICAR/down) drive the right state.

Proven-failing-first: evidence recorded per-test. The upload rejections were confirmed to genuinely
gate by asserting a rejected upload leaves NOTHING under quarantine — a real observable, not the
response code echoing itself.
"""
from __future__ import annotations

import asyncio

import pytest

from gateway import states
from gateway.tests.conftest import (
    SUBMIT_KEY, app_client, eicar_package_zip, good_package_zip, make_zip, ratio_bomb_zip,
    run, scanner_clean, scanner_down, scanner_eicar_aware, submit_zip,
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
    (lambda: make_zip({"mysurvey/survey.yaml": b"s", "mysurvey/README.md": b"hi"}), "no .edi"),
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
