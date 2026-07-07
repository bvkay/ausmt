"""Status-page rendering (design §6, review #8/#11). The validator table renders from the REAL
validator JSON shape ({"items":[...]}), and every rendered surface — validator rows, preview values,
AV note — is absolute-path-stripped and html.escaped.
"""
from __future__ import annotations

from gateway import states, statuspage


def test_validator_table_renders_from_items():
    # The real validator writes {"items":[{level,name,message}, ...]}. proven failing 2026-07-06:
    # _validator_section read only "checks"/"rows", so a real {"items":...} report rendered an EMPTY
    # table (the whole §6 validator feature silently absent).
    report = {"items": [
        {"level": "PASS", "name": "slug-matches-folder", "message": "ok"},
        {"level": "WARN", "name": "coord-precision", "message": "low precision"},
        {"level": "FAIL", "name": "licence-recognised", "message": "unknown licence"},
    ]}
    html = statuspage.render(submission_id="01ABC", state=states.QUARANTINED,
                             updated_utc="2026-07-06T00:00:00Z", validator_report=report)
    assert "slug-matches-folder" in html
    assert "coord-precision" in html
    assert "licence-recognised" in html
    assert "PASS" in html and "WARN" in html and "FAIL" in html


def test_validator_rows_strip_absolute_paths():
    # A validator message that echoes a server path must NOT leak it (design §6). Keeping the strip on
    # the items rows is why fixing the key (#8) does not re-open the path leak (#11 sibling concern).
    report = {"items": [
        {"level": "FAIL", "name": "x", "message": "failed reading /srv/ausmt/gateway/quarantine/01ABC/package/survey.yaml"},
    ]}
    html = statuspage.render(submission_id="01ABC", state=states.QUARANTINED,
                             updated_utc="t", validator_report=report)
    assert "/srv/ausmt/gateway" not in html
    assert "[path]" in html


def test_preview_values_strip_absolute_paths():
    # review #11: preview values were rendered WITHOUT the abs-path strip that validator rows and the
    # AV note get. A warning echoing a build path would leak it. proven failing 2026-07-06: the raw
    # C:\... / /srv/... path appeared verbatim in the preview panel.
    summary = {"station_count": 3, "warnings": "build wrote /srv/ausmt/gateway/quarantine/01/reports"}
    html = statuspage.render(submission_id="01ABC", state=states.VALIDATED,
                             updated_utc="t", preview_summary=summary)
    assert "/srv/ausmt/gateway" not in html
    assert "[path]" in html
    assert "station_count" in html


def test_status_page_never_has_script_or_raw_html_injection():
    # A hostile validator message with markup must be escaped (defence-in-depth; reviewer cleared
    # html.escape at every sink — this pins it stays true after the #8 key change).
    report = {"items": [{"level": "FAIL", "name": "x", "message": "<script>alert(1)</script>"}]}
    html = statuspage.render(submission_id="01ABC", state=states.QUARANTINED,
                             updated_utc="t", validator_report=report)
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_note_renders_only_for_submitter_intended_states():
    # Review finding 2 (C11b): the decision/AV note used to render for ANY state with a truthy note,
    # so the PII-ACK audit reason — curator-only by C11b §2 — leaked onto the public page during the
    # PUBLISHING window (and raw curator notes / internal git failure text leaked in
    # PUBLISHING/PUBLISH_FAILED). The note renders ONLY for states where it is intended for the
    # submitter: QUARANTINED, REJECTED_AV, RETURNED, REJECTED. Failure criterion: fails if a note
    # renders in any publish-cycle/pre-review state, or stops rendering in an allowed one (over-gate).
    note = "PII-ACK (1 file(s): mysurvey/S01.edi): private curator note"
    shown = (states.QUARANTINED, states.REJECTED_AV, states.RETURNED, states.REJECTED)
    hidden = (states.RECEIVED, states.SCANNED, states.VALIDATED,
              states.PUBLISHING, states.PUBLISHED, states.PUBLISH_FAILED)
    for st in shown:
        html = statuspage.render(submission_id="01ABC", state=st, updated_utc="t", note=note)
        assert "private curator note" in html, f"note missing for {st} (over-gated)"
    for st in hidden:
        html = statuspage.render(submission_id="01ABC", state=st, updated_utc="t", note=note)
        assert "PII-ACK" not in html and "private curator note" not in html, (
            f"curator/audit note leaked publicly for state {st}")
