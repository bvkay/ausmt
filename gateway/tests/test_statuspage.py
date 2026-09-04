"""Status-page rendering (design §6, review #8/#11). The validator table renders from the REAL
validator JSON shape ({"items":[...]}), and every rendered surface — validator rows, preview values,
AV note — is absolute-path-stripped and html.escaped.
"""
from __future__ import annotations

from gateway import states, statuspage


def test_validator_table_renders_from_items():
    # The real validator writes {"items":[{level,name,message}, ...]}. proven failing:
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
    # AV note get. A warning echoing a build path would leak it. proven failing: the raw
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
    # The decision/AV note must not render for ANY state with a truthy note,
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


# The >INFO pre-flight advisory arrives as a LIST of plain sentences written for a geophysicist.
# Before the pre-flight workflow the `warnings` key only ever held a 2-4 item build-failure list, or the
# empty list `_summarise_preview` hardcodes, so nobody noticed the cell renders `str(the_list)`.

_ADVISORY = [
    "EDI pre-flight: 246 of 312 files need AusMT's >INFO repair to be read at all",
    'S01.edi (station 1_001): magnetic declination is scraped as "5," so a stock reader refuses it',
    "None of the above blocks this submission.",
]


def test_preview_warnings_render_as_a_list_not_a_python_repr():
    # Proven failing on abc82d2: the whole advisory arrived in ONE table cell as a Python
    # list repr, a single unbroken 4,027-character run beginning `[&quot;EDI pre-flight: ...` with
    # the sentences separated by `&#x27;, &#x27;` and the quote style flipping mid-list wherever a
    # sentence contained a double quote. Prose written for a geophysicist, delivered as a debug dump.
    # Failure criterion: fails if a list value is stringified instead of becoming list items.
    page = statuspage.render(submission_id="01ABC", state=states.VALIDATED, updated_utc="t",
                             preview_summary={"station_count": 312, "warnings": _ADVISORY})
    assert page.count("<li>") == len(_ADVISORY), "each sentence must be its own list item"
    assert "[&quot;" not in page and "[&#x27;" not in page, "still a Python list repr"
    assert "&#x27;, &#x27;" not in page, "sentences separated by repr punctuation, not by markup"
    # Escaping is unchanged: the >INFO in the sentence is still inert.
    assert "&gt;INFO repair" in page
    assert "magnetic declination is scraped as &quot;5,&quot;" in page


def test_preview_warning_items_are_still_escaped_and_path_stripped():
    # The list rendering must not become a hole in either §6 control. Failure criterion: fails if a
    # hostile warning renders live markup, or if a build path survives inside a list item.
    page = statuspage.render(
        submission_id="01ABC", state=states.VALIDATED, updated_utc="t",
        preview_summary={"warnings": ["<script>alert(1)</script>",
                                      "build wrote /srv/ausmt/gateway/quarantine/01/reports"]})
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    assert "/srv/ausmt/gateway" not in page
    assert "[path]" in page


def test_a_non_list_preview_value_still_renders_as_a_plain_cell():
    # The control for the two tests above: everything that is not a list is unchanged, so the fix
    # cannot go green by turning every preview value into a bullet list.
    page = statuspage.render(submission_id="01ABC", state=states.VALIDATED, updated_utc="t",
                             preview_summary={"station_count": 3, "warnings": "one plain string"})
    assert "one plain string" in page
    assert "<li>" not in page
