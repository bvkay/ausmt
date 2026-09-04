"""CONTRIBUTOR-CREDIT-SPEC (§6, the ausmt-side editor typed rows): creators[] and contributors[] are
modelled LIST_SECTION widgets that must round-trip AND save end-to-end.

Three failure modes this pins:
  1. The EDITABLE_LISTS gap (the SAME bug the related_identifiers workflow shipped with): the widget assembles
     a creators/contributors patch that the runner then REJECTS on save as a non-editable field, because
     the key was missing from gateway.runner.edit.EDITABLE_LISTS. The end-to-end assertions below drive a
     real merge and assert the save is ACCEPTED - RED before creators/contributors join the allow-list.
  2. Byte-clean round-trip: an unchanged creators/contributors list (org creator with ror-but-no-orcid,
     person creator with orcid-but-no-ror) reassembles to its snapshot -> _OMIT, so an unrelated edit
     never blanks or re-quotes a credit list the curator did not touch.
  3. INFERRED-REVIEW adjudication: the RATIFIED migration marks a
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


def test_people_name_type_is_fail_closed():
    """A hand-crafted out-of-vocab name_type on a unified People & credit row is a SectionError (fail-
    closed at the form, keyed "people"), like relation/identifies. Role is now a fixed checkbox SET
    (l_people_<i>_role_<Token>) so an out-of-vocab role token is not selectable through the panel - a
    bogus role checkbox is simply IGNORED (never assembled), and the role vocab stays pinned to the
    surveys validator by test_editor_form.test_credit_vocab_matches_surveys_validator."""
    bad_nt = {"l_people_0_name": "X", "l_people_0_name_type": "robot"}
    _, e1 = ef.build_section_patch(bad_nt)
    assert any(getattr(x, "section", "") == "people" for x in e1), e1

    # A bogus role checkbox contributes nothing (no error, no contributors entry) - the panel can only
    # ever tick a ratified role.
    bogus_role = {"l_people_0_name": "X", "l_people_0_name_type": "person",
                  "l_people_0_role_Wizard": "1", **_snap("creators", []), **_snap("contributors", [])}
    patch, errs = ef.build_section_patch(bogus_role)
    assert not errs, errs
    assert "contributors" not in patch and "creators" not in patch


def _snap(key, value):
    """The hidden o_<list> round-trip anchor (canonical JSON) the People panel emits for creators /
    contributors, matching curatorpage._canon_json (sort_keys)."""
    return {f"o_{key}": json.dumps(value, sort_keys=True, ensure_ascii=False)}


def _people_form(rows, creators_snap=None, contributors_snap=None, **extra):
    """Build a People & credit form POST from a list of unified-row dicts (name, name_type, orcid?,
    ror?, cited?, roles?), with the o_ anchors defaulting to empty lists."""
    form = {}
    form.update(_snap("creators", creators_snap if creators_snap is not None else []))
    form.update(_snap("contributors", contributors_snap if contributors_snap is not None else []))
    for i, r in enumerate(rows):
        form[f"l_people_{i}_name"] = r["name"]
        form[f"l_people_{i}_name_type"] = r.get("name_type", "person")
        if r.get("orcid"):
            form[f"l_people_{i}_orcid"] = r["orcid"]
        if r.get("ror"):
            form[f"l_people_{i}_ror"] = r["ror"]
        if r.get("cited"):
            form[f"l_people_{i}_cited"] = "1"
        for role in r.get("roles", []):
            form[f"l_people_{i}_role_{role}"] = "1"
    form.update(extra)
    return form


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
from gateway.tests.conftest import require_validator_dir  # noqa: E402


def test_people_panel_creators_save_is_accepted_by_the_runner(tmp_path):
    """The unified People & credit panel decomposes its rows into creators[] and both keys must be
    patchable (EDITABLE_LISTS gate). Two CITED rows (a person + an organisation) become creators[] in
    display order; the merge is ACCEPTED and the list lands in the YAML. RED if creators is not in
    EDITABLE_LISTS (run_merge_job would raise 'patch contains non-editable field(s): creators')."""
    form = _people_form([
        {"name": "Thiel, Stephan", "name_type": "person", "cited": True},
        {"name": "Geological Survey of South Australia", "name_type": "organisation",
         "ror": "https://ror.org/03yghzc09", "cited": True},
    ])
    patch, errors = ef.build_section_patch(form)
    assert not errors, errors
    assert "creators" in patch and patch["creators"][0]["name"] == "Thiel, Stephan"

    pkg = _merge_pkg(tmp_path, b"name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n")
    res = edit.run_merge_job(pkg, patch=patch, bump="minor", note="add creators",
                             today="2026-07-26", validator_path="", scratch_dir=tmp_path / "scratch")
    assert res["ok"] is True
    assert "creators" in res["changed"]
    assert "name_type: organisation" in res["new_yaml"]
    assert "ror: https://ror.org/03yghzc09" in res["new_yaml"]


def test_people_panel_contributors_save_is_accepted_by_the_runner(tmp_path):
    """The contributors sibling of the EDITABLE_LISTS gate, through the unified panel: an organisation
    row with the DataCollector role ticked decomposes to a contributors[] entry the runner accepts."""
    form = _people_form([
        {"name": "Zonge Engineering", "name_type": "organisation", "roles": ["DataCollector"]},
    ])
    patch, errors = ef.build_section_patch(form)
    assert not errors, errors
    assert "contributors" in patch and "creators" not in patch  # not cited -> no creators entry
    pkg = _merge_pkg(tmp_path, b"name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n")
    res = edit.run_merge_job(pkg, patch=patch, bump="minor", note="add contributor",
                             today="2026-07-26", validator_path="", scratch_dir=tmp_path / "scratch")
    assert res["ok"] is True
    assert "contributors" in res["changed"]
    assert "role: DataCollector" in res["new_yaml"]


# ---- INFERRED-REVIEW detection + save-strips-the-marker adjudication -----------------------------

# GROUND TRUTH (hermetic): the BYTE-EXACT output of the ratified credit migration
#  on a survey carrying legacy
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


def test_people_panel_chips_carry_the_migration_flags_labelled_by_source(tmp_path):
    """§6.2 CHIPS CARRY. The runner's review_flags (indices into the ORIGINAL creators[]/contributors[])
    map onto the MERGED unified rows and each seeded row carries a 'needs review' chip labelled which
    underlying list seeded it (Creators / Contributors). Drives the People panel with the read-job's own
    flags for the comment-above fixture and asserts a chip on the two creator rows and the contributor
    row - never on an unflagged row."""
    from gateway import curatorpage as cp
    pkg = _merge_pkg(tmp_path, _SEEDED_YAML)
    res = edit.run_read_job(pkg)
    flags = res["review_flags"]
    assert flags == {"creators": [0, 1], "contributors": [0]}
    fields = {**res["fields"]}
    html = cp._people_credit_inner("demo", fields, None, {}, review_flags=flags)
    # Three seeded rows -> three chips (Thiel + GSSA from creators, Kay from contributors); each labels
    # its source list.
    assert html.count("data-review-chip") == 3, html
    assert "seeded from the migrated Creators list" in html
    assert "seeded from the migrated Contributors list" in html


def test_people_panel_chips_absent_on_a_clean_survey(tmp_path):
    """No INFERRED-REVIEW markers -> no chips (no false 'needs review')."""
    from gateway import curatorpage as cp
    fields = {"creators": [{"name": "A", "name_type": "person"}],
              "contributors": [{"name": "B", "name_type": "person", "role": "DataCurator"}]}
    html = cp._people_credit_inner("demo", fields, None, {}, review_flags={})
    assert "data-review-chip" not in html


# ---- unified merge/decompose + round-trip + legacy convert ---------------------------------------

def _canonical_form(fields):
    """Build the People & credit form POST that an UNCHANGED load of `fields` (its creators[] +
    contributors[]) would submit: merge to unified rows, then emit l_people_* + the cited/role ticks +
    the o_ anchors. Used to prove the no-op round-trip is byte-stable."""
    rows = ef.merge_people(fields.get("creators") or [], fields.get("contributors") or [])
    tick_rows = []
    for r in rows:
        tick_rows.append({"name": r["name"], "name_type": r["name_type"], "orcid": r["orcid"],
                          "ror": r["ror"], "cited": r["cited"], "roles": r["roles"]})
    return _people_form(tick_rows, creators_snap=fields.get("creators") or [],
                        contributors_snap=fields.get("contributors") or [])


def test_merge_people_keys_by_orcid_url_form_then_name():
    """LOAD MERGE. A creator and a contributor for the SAME person merge into ONE row when their ORCID
    matches even across URL forms (bare vs https://orcid.org/...); a person with no ORCID keys by exact
    name+name_type. An organisation and a person sharing a name never collide (different name_type key)."""
    creators = [{"name": "Thiel, Stephan", "name_type": "person", "orcid": "0000-0002-1825-0097"},
                {"name": "Kapunda", "name_type": "organisation"}]
    contributors = [
        {"name": "Thiel, Stephan", "name_type": "person", "role": "ProjectLeader",
         "orcid": "https://orcid.org/0000-0002-1825-0097"},   # URL form -> same person as the creator
        {"name": "Kapunda", "name_type": "person", "role": "DataCurator"},  # person, NOT the org above
    ]
    rows = ef.merge_people(creators, contributors)
    assert len(rows) == 3, [(r["name"], r["name_type"]) for r in rows]
    thiel = rows[0]
    assert thiel["cited"] and thiel["roles"] == ["ProjectLeader"]     # merged by ORCID across URL form
    assert rows[1]["name"] == "Kapunda" and rows[1]["name_type"] == "organisation" and rows[1]["cited"]
    assert rows[2]["name"] == "Kapunda" and rows[2]["name_type"] == "person"   # name-keyed, distinct


def test_people_multi_role_decomposition_in_ratified_order():
    """SAVE. One person with several ticked roles decomposes to one contributors[] entry per role,
    ordered by the RATIFIED role order (not tick/checkbox order). A cited tick adds a creators[] entry."""
    form = _people_form([{"name": "Kay, Ben", "name_type": "person", "cited": True,
                          "roles": ["DataCurator", "ProjectLeader"]}])  # deliberately reverse order
    patch, errs = ef.build_section_patch(form)
    assert not errs, errs
    assert [c["role"] for c in patch["contributors"]] == ["ProjectLeader", "DataCurator"]
    assert patch["creators"] == [{"name": "Kay, Ben", "name_type": "person"}]


def test_people_citation_order_is_among_cited_rows_only():
    """SAVE. creators[] is the CITED rows in display order; a non-cited row in between never enters
    creators[] and never shifts the citation order. contributors[] follows ROW order."""
    form = _people_form([
        {"name": "First", "name_type": "person", "cited": True, "roles": ["ProjectMember"]},
        {"name": "Middle", "name_type": "person", "cited": False, "roles": ["ProjectMember"]},
        {"name": "Last", "name_type": "person", "cited": True, "roles": ["ProjectMember"]},
    ])
    patch, errs = ef.build_section_patch(form)
    assert not errs, errs
    assert [c["name"] for c in patch["creators"]] == ["First", "Last"]     # cited-only, in order
    assert [c["name"] for c in patch["contributors"]] == ["First", "Middle", "Last"]  # row order


def test_people_no_op_round_trip_is_byte_stable():
    """ROUND-TRIP IDENTITY. Loading a canonical survey's creators[]+contributors[] into unified rows and
    saving with UNCHANGED ticks decomposes back to the identical lists -> both _OMIT -> NOT in the patch,
    so an unrelated edit never rewrites a credit list the curator did not touch. Proven on a canonical
    fixture: a cited person creator (orcid), a cited org creator (ror), and a multi-role contributor
    consistent with its creator entry."""
    fields = {
        "creators": [
            {"name": "Thiel, Stephan", "name_type": "person", "orcid": "0000-0002-1825-0097"},
            {"name": "Geological Survey of South Australia", "name_type": "organisation",
             "ror": "https://ror.org/03yghzc09"},
        ],
        "contributors": [
            {"name": "Thiel, Stephan", "name_type": "person", "role": "ProjectLeader",
             "orcid": "0000-0002-1825-0097"},
            {"name": "Thiel, Stephan", "name_type": "person", "role": "DataCurator",
             "orcid": "0000-0002-1825-0097"},
            {"name": "Zonge Engineering", "name_type": "organisation", "role": "DataCollector"},
        ],
    }
    form = _canonical_form(fields)
    patch, errs = ef.build_section_patch(form)
    assert not errs, errs
    assert "creators" not in patch, patch.get("creators")
    assert "contributors" not in patch, patch.get("contributors")


def test_people_no_op_round_trip_is_a_runner_no_op(tmp_path):
    """The byte-stable no-op holds through the REAL runner: a canonical survey re-saved unchanged has an
    empty effective patch, so run_merge_job refuses with 'no changes' (no diff, no version bump)."""
    yaml_bytes = (
        b'name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n'
        b'creators:\n'
        b'  - name: "Thiel, Stephan"\n    name_type: person\n    orcid: 0000-0002-1825-0097\n'
        b'  - name: "Geological Survey of South Australia"\n    name_type: organisation\n'
        b'    ror: https://ror.org/03yghzc09\n'
        b'contributors:\n'
        b'  - name: "Zonge Engineering"\n    name_type: organisation\n    role: DataCollector\n')
    pkg = _merge_pkg(tmp_path, yaml_bytes)
    fields = edit.run_read_job(pkg)["fields"]
    form = _canonical_form(fields)
    patch, errs = ef.build_section_patch(form)
    assert not errs, errs
    assert "creators" not in patch and "contributors" not in patch
    with pytest.raises(edit.EditError, match="no changes"):
        edit.run_merge_job(pkg, patch=patch, bump="patch", note="noop",
                           today="2026-07-26", validator_path="", scratch_dir=tmp_path / "scratch")


# ==================================================================================================
# The legacy Convert flow and its _delete_keys directive are GONE
#and the three ratified curated homes plus the designation mapping round-trip end to end.
# ==================================================================================================

def test_the_legacy_convert_surface_is_gone(tmp_path):
    """With the corpus migration run and the retired keys deleted, there is nothing left to
    convert. The people_convert submit, the hidden legacy payload fields and the _delete_keys patch
    directive are all removed, so a hand-crafted convert POST contributes NOTHING and the runner has
    no delete surface at all. FAILS IF any part of the retired mechanism still functions."""
    assert not hasattr(ef, "DELETE_DIRECTIVE") and not hasattr(ef, "convert_requested")
    assert not hasattr(edit, "DELETE_DIRECTIVE") and not hasattr(edit, "_DELETABLE_LEGACY_KEYS")
    form = _people_form([], people_convert="lead_investigator",
                        people_legacy_lead_name="Heinson, Graham",
                        people_legacy_lead_orcid="0000-0002-1825-0097")
    patch, errs = ef.build_section_patch(form)
    assert not errs, errs
    assert patch == {}, patch
    pkg = _merge_pkg(tmp_path, b'name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n')
    with pytest.raises(edit.EditError, match="non-editable"):
        edit.run_merge_job(pkg, patch={"_delete_keys": ["organisation"]}, bump="minor",
                           note="hostile", today="2026-07-26", validator_path="",
                           scratch_dir=tmp_path / "scratch")


def test_an_unmodelled_retired_key_is_byte_preserved_through_an_unrelated_save(tmp_path):
    """A pre-migration survey that STILL carries a retired flat credit key is simply an unmodelled
    key now: the editor never reads or patches it, so an unrelated edit leaves it byte-for-byte
    alone. This is what lets the ausmt wave run clean against BOTH corpora."""
    patch = {"region": "Renamed Region"}
    pkg = _merge_pkg(tmp_path, b'name: Demo\nversion: 1.0.0\nregion: Old\n'
                               b'lead_investigator:\n  name: "Heinson, Graham"\n'
                               b'  orcid: 0000-0002-1825-0097\n')
    res = edit.run_merge_job(pkg, patch=patch, bump="minor", note="rename region",
                             today="2026-07-26", validator_path="", scratch_dir=tmp_path / "scratch")
    assert res["ok"] is True
    assert "lead_investigator" in res["new_yaml"], res["new_yaml"]
    assert "Heinson, Graham" in res["new_yaml"]
    assert "lead_investigator" not in res["changed"], res["changed"]


# ---- the three curated homes + the designation mapping, end to end ------------------------------

_MTCAT20_SECTION_FORM = {
    "s_citation_preferred_text": "GSSA (2016). AusLAMP South Australia. [Data set].",
    "s_citation_text_source": "source_provided",
    "s_citation_preferred_identifier_scheme": "DOI",
    "s_citation_preferred_identifier_identifier": "10.25914/abc",
    "s_identity_classification_case": "case_a",
    "l_identity_classification_represents_0_scheme": "DOI",
    "l_identity_classification_represents_0_identifier": "10.25914/abc",
    "l_organisations_0_name": "Geological Survey of South Australia",
    "l_organisations_0_ror": "https://ror.org/04y8k6r48",
    "c_organisations_0_custodian": "1",
    "c_organisations_primary": "0",
    "l_acknowledgements_0_text": "Data supplied by the Geological Survey of South Australia.",
    "l_acknowledgements_0_type": "custodian",
}


def test_the_new_sections_are_editable_and_save_through_the_runner(tmp_path):
    """THE EDITABLE_KEYS GATE (the exact gap the related_identifiers and credit workflows each shipped
    with): the editor assembles citation / identity_classification / organisations / acknowledgements,
    so all four MUST be patchable or run_merge_job refuses the curator's save as a non-editable field.
    RED before they join EDITABLE_MAPS/EDITABLE_LISTS."""
    patch, errs = ef.build_section_patch(_MTCAT20_SECTION_FORM)
    assert not errs, errs
    pkg = _merge_pkg(tmp_path, b'name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n')
    res = edit.run_merge_job(pkg, patch=patch, bump="minor", note="curate the citation homes",
                             today="2026-07-26", validator_path="", scratch_dir=tmp_path / "scratch")
    assert res["ok"] is True
    for key in ("citation", "identity_classification", "organisations", "acknowledgements"):
        assert key in res["changed"], res["changed"]
    out = res["new_yaml"]
    assert "preferred_identifier:" in out and "scheme: DOI" in out
    assert "roles:" in out and "custodian" in out and "primary_custodian: true" in out
    assert "Data supplied by the Geological Survey of South Australia." in out


def test_the_new_sections_no_op_round_trip_is_byte_stable(tmp_path):
    """ROUND-TRIP IDENTITY for the three new panels + the designation mapping: re-submitting a
    survey's stored values UNCHANGED assembles to _OMIT for every one of them, so an unrelated edit
    never rewrites, reorders or re-quotes a section the curator did not touch."""
    yaml_bytes = (
        b'name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n'
        b'citation:\n  preferred_text: "GSSA (2016). AusLAMP South Australia."\n'
        b'  text_source: source_provided\n'
        b'  preferred_identifier:\n    scheme: DOI\n    identifier: 10.25914/abc\n'
        b'identity_classification:\n  case: case_a\n'
        b'  represents:\n    - scheme: DOI\n      identifier: 10.25914/abc\n'
        b'organisations:\n  - name: "Geological Survey of South Australia"\n'
        b'    ror: https://ror.org/04y8k6r48\n    roles:\n      - custodian\n'
        b'    primary_custodian: true\n'
        b'acknowledgements:\n  - text: "Data supplied by the GSSA."\n    type: custodian\n')
    pkg = _merge_pkg(tmp_path, yaml_bytes)
    fields = edit.run_read_job(pkg)["fields"]
    form = {
        "s_citation_preferred_text": fields["citation"]["preferred_text"],
        "s_citation_text_source": fields["citation"]["text_source"],
        "s_citation_preferred_identifier_scheme":
            fields["citation"]["preferred_identifier"]["scheme"],
        "s_citation_preferred_identifier_identifier":
            fields["citation"]["preferred_identifier"]["identifier"],
        "o_citation": json.dumps(fields["citation"], sort_keys=True),
        "s_identity_classification_case": fields["identity_classification"]["case"],
        "l_identity_classification_represents_0_scheme":
            fields["identity_classification"]["represents"][0]["scheme"],
        "l_identity_classification_represents_0_identifier":
            fields["identity_classification"]["represents"][0]["identifier"],
        "o_identity_classification": json.dumps(fields["identity_classification"], sort_keys=True),
        "l_organisations_0_name": fields["organisations"][0]["name"],
        "l_organisations_0_ror": fields["organisations"][0]["ror"],
        "c_organisations_0_custodian": "1",
        "c_organisations_primary": "0",
        "o_organisations": json.dumps(fields["organisations"], sort_keys=True),
        "l_acknowledgements_0_text": fields["acknowledgements"][0]["text"],
        "l_acknowledgements_0_type": fields["acknowledgements"][0]["type"],
        "l_acknowledgements_0_source": "",
        "o_acknowledgements": json.dumps(fields["acknowledgements"], sort_keys=True),
    }
    patch, errs = ef.build_section_patch(form)
    assert not errs, errs
    for key in ("citation", "identity_classification", "organisations", "acknowledgements"):
        assert key not in patch, (key, patch.get(key))
    with pytest.raises(edit.EditError, match="no changes"):
        edit.run_merge_job(pkg, patch=patch, bump="patch", note="noop",
                           today="2026-07-26", validator_path="", scratch_dir=tmp_path / "scratch")


# ---- INFERRED-REVIEW handling extended to the two new marked lists ------------------------------

_ORG_SEEDED_YAML = (
    b'name: Demo\nversion: 1.0.0\norganisation:\n  name: Uni\n'
    b'creators:\n'
    b'  # INFERRED-REVIEW: confirm citation authorship\n'
    b'  - name: "Thiel, Stephan"\n    name_type: person\n'
    b'organisations:\n'
    b'  # INFERRED-REVIEW: custodian seeded from the essential organisation; confirm roles\n'
    b'  - name: "Geological Survey of South Australia"\n'
    b'    roles:\n      - custodian\n    primary_custodian: true\n')


def test_read_job_surfaces_organisations_review_flags(tmp_path):
    """The corpus-wide custodian seeding marks every organisations row it writes, so the runner
    read job must surface organisations markers exactly as it does creators/contributors. RED before
    organisations joins _CREDIT_LIST_KEYS and the read job's loop: the chip would never appear and the
    curator would never be asked to confirm the seeded roles."""
    pkg = _merge_pkg(tmp_path, _ORG_SEEDED_YAML)
    res = edit.run_read_job(pkg)
    assert res["review_flags"] == {"creators": [0], "organisations": [0]}


def test_saving_organisations_strips_its_marker_and_leaves_creators(tmp_path):
    """Per-LIST-SECTION marker stripping (no per-row stripping): editing organisations clears ITS
    marker (the adjudication) and leaves the untouched creators marker alone."""
    form = {
        "l_organisations_0_name": "Geological Survey of South Australia",
        "l_organisations_0_ror": "",
        "c_organisations_0_custodian": "1",
        "c_organisations_0_publisher": "1",
        "c_organisations_primary": "0",
        "o_organisations": json.dumps([{"name": "Geological Survey of South Australia",
                                        "roles": ["custodian"], "primary_custodian": True}]),
    }
    patch, errs = ef.build_section_patch(form)
    assert not errs, errs
    assert "organisations" in patch
    data = edit._load_bytes(_ORG_SEEDED_YAML)
    edit.apply_patch(data, patch)
    out = edit._dump_bytes(data).decode("utf-8")
    assert "custodian seeded from the essential organisation" not in out, out
    assert "confirm citation authorship" in out, out


# ---- the entry gate: an inconsistent citation save is refused with the validator's message -------

_VALIDATOR_DIR = str(require_validator_dir())


def _package_for_validation(tmp_path, extra_yaml: bytes = b""):
    pkg = tmp_path / "surveys" / "demo-survey-2026"
    (pkg / "transfer_functions" / "edi").mkdir(parents=True)
    (pkg / "survey.yaml").write_bytes(
        b'schema_version: "0.3"\nname: Demo\nproject_name: Demo\nslug: demo-survey-2026\n'
        b'version: 1.0.0\ncountry: Australia\nlicense: CC-BY-4.0\n'
        b'organisation:\n  name: Uni\naccess:\n  level: open\n'
        b'related_identifiers:\n  - identifier: 10.25914/abc\n    identifier_type: DOI\n'
        b'    identifies: entire\n    relation: IsVariantFormOf\n' + extra_yaml)
    # A parseable stub EDI: the validator's edi_parse check needs real LAT/LONG in HEAD, and the
    # coordinates must sit inside the Australian bounding box it defaults to.
    (pkg / "transfer_functions" / "edi" / "S01.edi").write_text(
        ">HEAD\n  DATAID=S01\n  LAT=-34:55:00\n  LONG=138:36:00\n  ELEV=50\n"
        ">FREQ NFREQ=1 // 1\n  1.0\n>END\n", encoding="utf-8")
    (pkg / "README.md").write_text("# demo\n", encoding="utf-8")
    (pkg / "LICENSE.md").write_text("# Licence\n\n**CC-BY-4.0**\n", encoding="utf-8")
    return pkg


def test_preferred_identifier_without_its_designation_is_refused_by_the_merge(tmp_path):
    """ENTRY-GATE GUARD (D18 / emitter D20): the editor CAN write citation.preferred_identifier, and
    the validator FAILs a pair that no designation matches. The merge surfaces that FAIL verbatim, so
    an inconsistent curator save can never reach the engine. RED if the editor writes the pair and
    nothing refuses it."""
    patch, errs = ef.build_section_patch({
        "s_citation_preferred_text": "GSSA (2016).",
        "s_citation_text_source": "source_provided",
        "s_citation_preferred_identifier_scheme": "DOI",
        "s_citation_preferred_identifier_identifier": "10.25914/abc",
    })
    assert not errs, errs
    assert patch["citation"]["preferred_identifier"] == {"scheme": "DOI",
                                                         "identifier": "10.25914/abc"}
    pkg = _package_for_validation(tmp_path)
    res = edit.run_merge_job(pkg, patch=patch, bump="minor", note="prefer this identifier",
                             today="2026-07-26", validator_path=_VALIDATOR_DIR,
                             scratch_dir=tmp_path / "scratch")
    assert res["has_fail"] is True, res["validator"]
    fails = [i for i in res["validator"]["items"] if i["level"] == "FAIL"]
    assert any(i["check"] == "citation" and "designated identifier" in i["message"] for i in fails), \
        fails


def test_preferred_identifier_with_its_designation_is_accepted_by_the_merge(tmp_path):
    """The other half of the gate: the SAME pair, designated through identity_classification.represents
    (which must itself match a related_identifiers row), validates clean and the save is accepted."""
    patch, errs = ef.build_section_patch({
        "s_citation_preferred_text": "GSSA (2016).",
        "s_citation_text_source": "source_provided",
        "s_citation_preferred_identifier_scheme": "DOI",
        "s_citation_preferred_identifier_identifier": "10.25914/abc",
        "s_identity_classification_case": "case_a",
        "l_identity_classification_represents_0_scheme": "DOI",
        "l_identity_classification_represents_0_identifier": "10.25914/abc",
    })
    assert not errs, errs
    pkg = _package_for_validation(tmp_path)
    res = edit.run_merge_job(pkg, patch=patch, bump="minor", note="prefer this identifier",
                             today="2026-07-26", validator_path=_VALIDATOR_DIR,
                             scratch_dir=tmp_path / "scratch")
    assert res["has_fail"] is False, [i for i in res["validator"]["items"] if i["level"] == "FAIL"]
