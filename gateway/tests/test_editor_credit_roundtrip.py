"""CONTRIBUTOR-CREDIT-SPEC (§6, the ausmt-side editor typed rows): creators[] and contributors[] are
modelled LIST_SECTION widgets that must round-trip AND save end-to-end.

Three failure modes this pins:
  1. The EDITABLE_LISTS gap (the SAME bug the related_identifiers lane shipped with): the widget assembles
     a creators/contributors patch that the runner then REJECTS on save as a non-editable field, because
     the key was missing from gateway.runner.edit.EDITABLE_LISTS. The end-to-end assertions below drive a
     real merge and assert the save is ACCEPTED - RED before creators/contributors join the allow-list.
  2. Byte-clean round-trip: an unchanged creators/contributors list (org creator with ror-but-no-orcid,
     person creator with orcid-but-no-ror) reassembles to its snapshot -> _OMIT, so an unrelated edit
     never blanks or re-quotes a credit list the curator did not touch.
  3. INFERRED-REVIEW adjudication: the RATIFIED migration (surveys origin/main, hardened 2026-07-25) marks a
     seeded row with a COMMENT-ABOVE INFERRED-REVIEW note (its own line directly above `- name:`), NOT an
     inline comment. ruamel re-homes that above-comment onto a NEIGHBOUR (row 0 -> the parent list key;
     row i>0 -> the previous row's trailing comment), so the runner detector (inferred_review_indices) reads
     it via the parent-key comment + a next-row attribution rule, and stays tolerant of a hand-edited INLINE
     marker too. EDITING the list clears its markers (the adjudication) - which for the comment-above row 0
     needs an EXPLICIT strip because it rides the parent key and survives a wholesale replace - while an
     UNTOUCHED list keeps its marker. The baked fixture is the migration's byte-exact output (hermetic).
"""
from __future__ import annotations

import json

import pytest

from gateway import editor_form as ef


def _merge_pkg(tmp_path, yaml_bytes: bytes):
    """Materialise a minimal package under tmp and return its package_root (survey.yaml + one EDI)."""
    pkg = tmp_path / "surveys" / "demo"
    (pkg / "transfer_functions" / "edi").mkdir(parents=True)
    (pkg / "survey.yaml").write_bytes(yaml_bytes)
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(">HEAD\n", encoding="utf-8")
    return pkg


# ---- unit: vocab + optional-key round-trip (no ruamel needed) -----------------------------------

def test_creators_and_contributors_are_modelled_list_sections():
    """The typed rows are registered so build_section_patch assembles them. RED if either is unmodelled."""
    assert "creators" in ef.LIST_SECTIONS
    assert "contributors" in ef.LIST_SECTIONS
    assert "creators" in ef.WIDGET_SECTIONS
    assert "contributors" in ef.WIDGET_SECTIONS


def test_name_type_and_role_are_fail_closed():
    """An out-of-vocab name_type or role is a SectionError (fail-closed at the form), like relation."""
    bad_nt = {"l_creators_0_name": "X", "l_creators_0_name_type": "robot"}
    _, e1 = ef.build_section_patch(bad_nt)
    assert any(getattr(x, "section", "") == "creators" for x in e1), e1

    bad_role = {"l_contributors_0_name": "X", "l_contributors_0_name_type": "person",
                "l_contributors_0_role": "Wizard"}
    _, e2 = ef.build_section_patch(bad_role)
    assert any(getattr(x, "section", "") == "contributors" for x in e2), e2


def test_org_creator_without_orcid_round_trips_to_omit():
    """An org creator {name, name_type: organisation, ror} (no orcid) reassembles to its snapshot -> _OMIT.
    RED if orcid/ror are not optional (an empty orcid would be written as null and break the round-trip)."""
    stored = [{"name": "Geological Survey of South Australia", "name_type": "organisation",
               "ror": "https://ror.org/03yghzc09"}]
    form = {"o_creators": json.dumps(stored)}
    for sk, *_ in ef.LIST_SECTIONS["creators"]:
        v = stored[0].get(sk)
        form[f"l_creators_0_{sk}"] = "" if v is None else str(v)
    assert ef.assemble_section(form, "creators") is ef._OMIT


def test_person_contributor_without_ror_round_trips_to_omit():
    stored = [{"name": "Thiel, Stephan", "name_type": "person", "role": "ProjectLeader",
               "orcid": "0000-0002-1825-0097"}]
    form = {"o_contributors": json.dumps(stored)}
    for sk, *_ in ef.LIST_SECTIONS["contributors"]:
        v = stored[0].get(sk)
        form[f"l_contributors_0_{sk}"] = "" if v is None else str(v)
    assert ef.assemble_section(form, "contributors") is ef._OMIT


def test_creators_assembled_order_follows_row_index():
    """creators is ORDERED (the citation author order). The assembler reads rows in NUMERIC index order,
    so the client-side reorder (which renumbers the row indices) persists through save. Row 1 renumbered
    below row 0's index proves the order is index-driven, not form-key order."""
    form = {
        # deliberately out of natural key order; index 0 must come first
        "l_creators_1_name": "Second", "l_creators_1_name_type": "person",
        "l_creators_0_name": "First", "l_creators_0_name_type": "organisation",
    }
    out = ef.assemble_section(form, "creators")
    assert [r["name"] for r in out] == ["First", "Second"]


# ---- end-to-end through the REAL runner merge (the EDITABLE_LISTS gate) --------------------------

ruamel = pytest.importorskip("ruamel.yaml")

from gateway.runner import edit  # noqa: E402  (only importable where ruamel is installed)


def test_creators_save_is_accepted_by_the_runner(tmp_path):
    """RED before creators joins EDITABLE_LISTS: run_merge_job raises EditError('patch contains
    non-editable field(s): creators'). GREEN after: the merge is ACCEPTED and the list lands in the YAML."""
    form = {
        "l_creators_0_name": "Thiel, Stephan", "l_creators_0_name_type": "person",
        "l_creators_1_name": "Geological Survey of South Australia",
        "l_creators_1_name_type": "organisation", "l_creators_1_ror": "https://ror.org/03yghzc09",
    }
    patch, errors = ef.build_section_patch(form)
    assert not errors, errors
    assert "creators" in patch

    pkg = _merge_pkg(tmp_path, b"name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n")
    res = edit.run_merge_job(pkg, patch=patch, bump="minor", note="add creators",
                             today="2026-07-26", validator_path="", scratch_dir=tmp_path / "scratch")
    assert res["ok"] is True
    assert "creators" in res["changed"]
    assert "name_type: organisation" in res["new_yaml"]
    assert "ror: https://ror.org/03yghzc09" in res["new_yaml"]


def test_contributors_save_is_accepted_by_the_runner(tmp_path):
    """The contributors sibling of the EDITABLE_LISTS gate. RED before contributors joins the allow-list."""
    form = {"l_contributors_0_name": "Zonge Engineering", "l_contributors_0_name_type": "organisation",
            "l_contributors_0_role": "DataCollector"}
    patch, errors = ef.build_section_patch(form)
    assert not errors, errors
    pkg = _merge_pkg(tmp_path, b"name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n")
    res = edit.run_merge_job(pkg, patch=patch, bump="minor", note="add contributor",
                             today="2026-07-26", validator_path="", scratch_dir=tmp_path / "scratch")
    assert res["ok"] is True
    assert "contributors" in res["changed"]
    assert "role: DataCollector" in res["new_yaml"]


# ---- INFERRED-REVIEW detection + save-strips-the-marker adjudication -----------------------------

# GROUND TRUTH (hermetic): the BYTE-EXACT output of the ratified credit migration
# (_tools/migrate_credit.py at surveys origin/main, hardened 2026-07-25) on a survey carrying legacy
# principal_investigators (-> two person creators) + lead_investigator (-> one ProjectLeader contributor).
# The INFERRED-REVIEW note rides its OWN comment line directly ABOVE each `- name:` row (comment-ABOVE) -
# the ratified format, because an inline comment after a quoted scalar tripped the vendored mini parser.
# Reproduced literally here so the test carries NO sibling-repo dependency. Captured verbatim by running
# the migration against a minimal fixture and copying its emitted bytes.
_SEEDED_YAML = (
    b'name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n'
    b'creators:\n'
    b'  # INFERRED-REVIEW: confirm citation authorship\n'
    b'  - name: "Thiel, Stephan"\n'
    b'    name_type: person\n'
    b'    orcid: 0000-0002-1825-0097\n'
    b'  # INFERRED-REVIEW: confirm citation authorship\n'
    b'  - name: "Geological Survey of South Australia"\n'
    b'    name_type: person\n'
    b'\n'
    b'contributors:\n'
    b'  # INFERRED-REVIEW: was lead_investigator; confirm role\n'
    b'  - name: "Kay, Ben"\n'
    b'    name_type: person\n'
    b'    role: ProjectLeader\n'
    b'    orcid: 0000-0002-9738-7277\n'
)

# The already-live `identifies:`-style INLINE placement (hand-edited or a legacy marker), kept passing so
# the detector is robust to BOTH placements - the marker sits on the annotated row's own `- name:` line.
_INLINE_SEEDED_YAML = (
    b'name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n'
    b'creators:\n'
    b'  - name: "Thiel, Stephan"  # INFERRED-REVIEW: confirm citation authorship\n'
    b'    name_type: person\n'
    b'  - name: "Clean, Curated"\n'
    b'    name_type: person\n'
)


def _parent_comment(data, key):
    parent_ca = getattr(getattr(data, "ca", None), "items", None) or {}
    return parent_ca.get(key)


def test_inferred_review_indices_detects_comment_above_rows(tmp_path):
    """GROUND TRUTH: the migration marks EVERY seeded row with a comment-ABOVE INFERRED-REVIEW note, so
    both creators rows (0 AND 1) and the single contributors row (0) are flagged. RED against the pre-fix
    detector, which read the wrong nodes: it returned creators [0] (missing row 1) and contributors []
    (the silent-zero failure - a single seeded row surfaced NO chip on the exact data the feature exists
    for)."""
    data = edit._load_bytes(_SEEDED_YAML)
    assert edit.inferred_review_indices(
        data["creators"], parent_comment=_parent_comment(data, "creators")) == [0, 1]
    assert edit.inferred_review_indices(
        data["contributors"], parent_comment=_parent_comment(data, "contributors")) == [0]


def test_inferred_review_indices_still_detects_inline_marker(tmp_path):
    """The detector stays tolerant of the INLINE placement (a hand-edited / identifies-style marker on the
    row's own line): row 0 marked, the clean row 1 not."""
    data = edit._load_bytes(_INLINE_SEEDED_YAML)
    assert edit.inferred_review_indices(
        data["creators"], parent_comment=_parent_comment(data, "creators")) == [0]


def test_inferred_review_indices_empty_for_a_plain_list(tmp_path):
    """A curated list with no markers flags nothing (no false chips)."""
    plain = (b'name: Demo\nversion: 1.0.0\ncreators:\n'
             b'  - name: "A"\n    name_type: person\n  - name: "B"\n    name_type: person\n')
    data = edit._load_bytes(plain)
    assert edit.inferred_review_indices(
        data["creators"], parent_comment=_parent_comment(data, "creators")) == []


def test_read_job_returns_review_flags_for_comment_above(tmp_path):
    """run_read_job surfaces review_flags for the migration's comment-above output so the editor chips the
    seeded rows. RED against the pre-fix read job: it returned {'creators': [0]} - dropping creators row 1
    and surfacing ZERO contributors chips on the exact migrated data."""
    pkg = _merge_pkg(tmp_path, _SEEDED_YAML)
    res = edit.run_read_job(pkg)
    assert res["review_flags"] == {"creators": [0, 1], "contributors": [0]}


def test_editing_creators_strips_the_comment_above_marker_but_leaves_contributors(tmp_path):
    """Saving a CHANGE to creators rewrites the list WITHOUT its INFERRED-REVIEW markers (the adjudication).
    A wholesale replace drops the per-row markers with the old items, but row 0's comment-ABOVE marker rides
    the PARENT list key and SURVIVES the replace - apply_patch strips it explicitly. The UNTOUCHED
    contributors list keeps its marker and is still flagged on the next read."""
    # A curator confirms the citation order (renames the split), leaving contributors untouched.
    form = {
        "l_creators_0_name": "Thiel, S.", "l_creators_0_name_type": "person",
        "l_creators_1_name": "Geological Survey of South Australia",
        "l_creators_1_name_type": "organisation",
        "o_creators": json.dumps([{"name": "Thiel, Stephan", "name_type": "person"},
                                  {"name": "Geological Survey of South Australia",
                                   "name_type": "organisation"}]),
    }
    patch, errors = ef.build_section_patch(form)
    assert not errors, errors
    assert "creators" in patch and "contributors" not in patch

    data = edit._load_bytes(_SEEDED_YAML)
    edit.apply_patch(data, patch)
    out = edit._dump_bytes(data).decode("utf-8")
    assert "confirm citation authorship" not in out, out          # BOTH creators markers cleared
    assert "was lead_investigator; confirm role" in out, out      # contributors marker preserved
    # and the untouched contributors row is still flagged on the next read; creators is clean.
    assert edit.inferred_review_indices(
        data["contributors"], parent_comment=_parent_comment(data, "contributors")) == [0]
    assert edit.inferred_review_indices(
        data["creators"], parent_comment=_parent_comment(data, "creators")) == []


def test_review_flags_chip_the_right_rendered_rows(tmp_path):
    """The review_flags indices flow through to the rendered editor: chipping the exact rows the runner
    flagged. Drives the curatorpage list panel with the read-job's own flags for the comment-above fixture
    (creators [0,1]) and asserts a 'needs review' chip on rows 0 and 1 - and NONE on an unflagged row."""
    from gateway import curatorpage as cp
    pkg = _merge_pkg(tmp_path, _SEEDED_YAML)
    res = edit.run_read_job(pkg)
    flags = res["review_flags"]["creators"]
    assert flags == [0, 1]
    fields = {"creators": [{"name": "Thiel, Stephan", "name_type": "person"},
                           {"name": "Geological Survey of South Australia", "name_type": "person"},
                           {"name": "Later, Curated", "name_type": "person"}]}
    html = cp._list_section_panel("creators", "Creators", fields, None, {}, review_indices=flags)
    # exactly the two flagged rows carry the chip; the third (unflagged) row does not.
    assert html.count("data-review-chip") == 2, html
    # the chip sits inside rows 0 and 1 but not row 2: the row-2 name input follows the last chip.
    assert 'name="l_creators_0_name"' in html and 'name="l_creators_1_name"' in html
    last_chip = html.rfind("data-review-chip")
    row2_input = html.find('name="l_creators_2_name"')
    assert row2_input > last_chip, "row 2 must render after the last chip (no chip on the curated row)"
