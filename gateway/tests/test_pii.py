"""PII containment (design §0/§8, house rule). The submitter email fixture must appear NOWHERE in
the gw/ tree, the job files, or the rendered status HTML — only inside the SQLite DB file.

This is the load-bearing privacy test: it greps real bytes on disk (an independent observable), not
metadata self-consistency. If any code path ever writes the email into a job file, report, or
status page, this fails.

Proven-failing-first: with the status template echoing submitter_email, the email appeared in the
rendered HTML captured below -> the "zero hits outside sqlite" assertion failed.
"""
from __future__ import annotations

from pathlib import Path

from gateway import jobs, states
from gateway.tests.conftest import (
    app_client, good_package_zip, run, scanner_clean, submit_zip,
)

UNIQUE_EMAIL = "pii-canary-8471@example.test"
UNIQUE_NAME = "Piicanary Uniquesubmitter"
UNIQUE_ORCID = "0000-0002-1825-0097"


def _grep_tree_for(root: Path, needles: list[bytes]) -> list[tuple[str, bytes]]:
    """Return (relpath, needle) for every file under root (EXCLUDING *.sqlite*) that contains any
    needle. The sqlite DB is the ONE sanctioned PII home, so it is excluded by design."""
    hits: list[tuple[str, bytes]] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.startswith(".sqlite") or ".sqlite" in p.name:
            continue
        data = p.read_bytes()
        for needle in needles:
            if needle in data:
                hits.append((str(p.relative_to(root)), needle))
    return hits


def test_pii_only_in_sqlite_after_full_flow(tmp_path):
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, gw, cfg):
            r = await submit_zip(client, good_package_zip(), name=UNIQUE_NAME, email=UNIQUE_EMAIL,
                                 orcid=UNIQUE_ORCID)
            assert r.status_code == 201
            sid = r.json()["submission_id"]

            # Render the status page (a rendered-HTML surface the design calls out explicitly).
            page = await client.get(r.json()["status_url"])
            (cfg.state_dir / "rendered-status.html").write_text(page.text, encoding="utf-8")

            # Drive a validated done-file through ingest so job/report files exist on disk too.
            done_dir = cfg.jobs_dir / "done"
            done_dir.mkdir(parents=True, exist_ok=True)
            import json
            (done_dir / f"{sid}.json").write_text(
                json.dumps({"submission_id": sid, "outcome": jobs.OUTCOME_VALIDATED,
                            "reason": "ok", "report_refs": {"slug": "mysurvey"}}),
                encoding="utf-8")
            await gw.poll_once()
            assert gw.db.get(sid).state == states.VALIDATED

            needles = [UNIQUE_EMAIL.encode(), UNIQUE_NAME.encode(), UNIQUE_ORCID.encode()]
            hits = _grep_tree_for(cfg.data_dir, needles)
            assert hits == [], f"PII leaked outside sqlite: {hits}"

            # And prove the DB genuinely DOES hold it (else the test would pass vacuously by the PII
            # never being stored at all).
            sub = gw.db.get(sid)
            assert sub.submitter_email == UNIQUE_EMAIL
            assert sub.submitter_name == UNIQUE_NAME
    run(_body())


def test_pii_absent_from_pending_job(tmp_path):
    # The pending job file is written before any scan; assert it is PII-free on its own (design §5).
    async def _body():
        async with app_client(tmp_path, scanner=scanner_clean()) as (client, _app, _gw, cfg):
            await submit_zip(client, good_package_zip(), name=UNIQUE_NAME, email=UNIQUE_EMAIL)
            for p in (cfg.jobs_dir / "pending").glob("*.json"):
                data = p.read_bytes()
                assert UNIQUE_EMAIL.encode() not in data
                assert UNIQUE_NAME.encode() not in data
    run(_body())
