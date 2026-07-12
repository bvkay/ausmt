"""Unit tests for the structured metadata-editor form assembly (gateway/editor_form.py) — the
2026-07-08 "hostile JSON" fix that replaces the raw-JSON textareas with per-section widgets.

These are pure-function tests of the SERVER-SIDE half: the widget form fields <-> section dicts
mapping, the advanced-JSON override precedence, per-field format validation, repeatable-row
handling, and the round-trip anchor (an unchanged submit reassembles to the original snapshot and
contributes NOTHING to the patch, so the yaml diff is empty).

Failure criterion is in each test name/docstring (Invariant 10). No app/HTTP surface here — the
end-to-end round-trip through the real gateway seam lives in test_metadata_edit.py.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from gateway import editor_form as ef


def _snap(section: str, value) -> dict:
    """A form fragment carrying only the hidden original-snapshot for `section`."""
    return {f"o_{section}": json.dumps(value)}


# The REAL engine coordinate-access parser, loaded from its file by path (engine-truth). engine/ is
# NOT a package (no __init__.py; build_portal imports `_coordaccess` flat off sys.path), so we load the
# module standalone via importlib — no sys.path pollution, no shadowing. It only imports pathlib, so it
# loads cleanly in the stack-less gateway test env. Used by the KEY-PARITY pin: the editor's assembled
# access block must be read back by THIS function as the intended policy.
_ENGINE_COORDACCESS_PY = Path(__file__).resolve().parents[2] / "engine" / "extract" / "_coordaccess.py"


def _load_engine_coordaccess():
    spec = importlib.util.spec_from_file_location("_ausmt_engine_coordaccess_ro", _ENGINE_COORDACCESS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---- map sections: assembly + round-trip --------------------------------------------------------

def test_map_section_assembles_from_named_inputs():
    """organisation {name, ror} assembles from s_organisation_* inputs. FAILS IF the widget names are
    not read into the section dict."""
    form = {
        "s_organisation_name": "University of Example",
        "s_organisation_ror": "https://ror.org/03yghzc09",
        **_snap("organisation", {"name": "old", "ror": None}),
    }
    assert ef.assemble_section(form, "organisation") == {
        "name": "University of Example", "ror": "https://ror.org/03yghzc09"}


def test_unchanged_map_round_trips_to_omit():
    """Submitting a map section UNCHANGED (widgets equal the original) contributes nothing to the
    patch. FAILS IF an unchanged submit emits a section (which would produce a spurious yaml diff —
    the CRITICAL round-trip invariant)."""
    original = {"name": "University of Example", "ror": None}
    form = {
        "s_organisation_name": "University of Example",
        "s_organisation_ror": "",  # ror was null -> empty input round-trips to None
        **_snap("organisation", original),
    }
    assert ef.assemble_section(form, "organisation") is ef._OMIT


def test_empty_input_for_present_key_clears_to_none():
    """Emptying a sub-field that WAS present sets it to null (a real edit). FAILS IF clearing a
    present key silently drops it instead of nulling it."""
    form = {
        "s_organisation_name": "University of Example",
        "s_organisation_ror": "",
        **_snap("organisation", {"name": "University of Example", "ror": "https://ror.org/x"}),
    }
    # name unchanged, ror cleared from a real value -> a change, ror becomes None
    assert ef.assemble_section(form, "organisation") == {
        "name": "University of Example", "ror": None}


def test_absent_key_left_empty_is_omitted():
    """A sub-key the original section did NOT carry, left empty, is not introduced. FAILS IF the
    assembler adds an empty key the source lacked (breaking round-trip on subset-map surveys)."""
    # identifiers originally only carried dataset_doi + project_raid (a real subset case).
    original = {"dataset_doi": None, "project_raid": None}
    form = {
        "s_identifiers_dataset_doi": "",
        "s_identifiers_related_publication": "",
        "s_identifiers_related_publication_doi": "",
        "s_identifiers_project": "",
        "s_identifiers_project_raid": "",
        **_snap("identifiers", original),
    }
    # Unchanged subset -> OMIT (round-trip), never a full 5-key dict of nulls.
    assert ef.assemble_section(form, "identifiers") is ef._OMIT


def test_organisation_bare_string_round_trips():
    """organisation may be a BARE STRING (0.1 flat form). An unchanged submit re-emits the string, so
    it round-trips. FAILS IF a string organisation is force-upgraded to a map on an unchanged submit
    (a spurious diff)."""
    form = {
        "s_organisation_name": "AusMT CI",
        "s_organisation_ror": "",
        **_snap("organisation", "AusMT CI"),
    }
    assert ef.assemble_section(form, "organisation") is ef._OMIT


def test_organisation_bare_string_upgrades_when_ror_added():
    """Adding a ROR to a bare-string organisation upgrades it to a map. FAILS IF the ror is dropped
    because the original was a string."""
    form = {
        "s_organisation_name": "AusMT CI",
        "s_organisation_ror": "https://ror.org/03yghzc09",
        **_snap("organisation", "AusMT CI"),
    }
    assert ef.assemble_section(form, "organisation") == {
        "name": "AusMT CI", "ror": "https://ror.org/03yghzc09"}


# ---- access: select + date ----------------------------------------------------------------------

def test_access_level_and_embargo_assemble():
    """access assembles level (select) + embargo_until (date) + contact. FAILS IF the select/date
    widget names are not read."""
    form = {
        "s_access_level": "embargoed",
        "s_access_embargo_until": "2027-01-01",
        "s_access_contact": "release@example.org",
        **_snap("access", {"level": "open", "embargo_until": None, "contact": None}),
    }
    assert ef.assemble_section(form, "access") == {
        "level": "embargoed", "embargo_until": "2027-01-01", "contact": "release@example.org"}


def test_bad_access_level_errors():
    """A level outside the enum surfaces a per-field error. FAILS IF a bad level is accepted."""
    form = {"s_access_level": "public", **_snap("access", {"level": "open"})}
    with pytest.raises(ef.SectionError) as ei:
        ef.assemble_section(form, "access")
    assert ei.value.section == "access"


def test_bad_embargo_date_errors():
    """A malformed embargo date surfaces a per-field error. FAILS IF a non-ISO date is accepted."""
    form = {"s_access_level": "embargoed", "s_access_embargo_until": "next year",
            **_snap("access", {"level": "open"})}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "access")


# ---- access.coordinates (C42 survey-level coordinate-access policy) ------------------------------

def test_coordinate_policy_key_and_vocab_match_engine():
    """The editor's declared key + vocab are IDENTICAL to what the engine consumes: the sub-key is
    'coordinates' (the one parse_coordinate_policy reads) and COORDINATE_POLICIES equals the engine's.
    FAILS IF the editor offers a value the engine would reject, or reads/writes a different key (the
    labels-vs-slugs silent-no-op class)."""
    coordacc = _load_engine_coordaccess()
    # the sub-field the editor renders/assembles under access is exactly 'coordinates'.
    assert any(sub == "coordinates" for (sub, *_rest) in ef.MAP_SECTIONS["access"])
    assert ef.COORDINATE_POLICIES == coordacc.COORDINATE_POLICIES


def test_coordinate_policy_key_parity_through_real_engine_parser():
    """KEY-PARITY PIN (the important one): every policy the editor ASSEMBLES for access.coordinates is
    read back by the ENGINE's real parse_coordinate_policy as that same policy — engine-truth, not a
    hand-typed expectation. FAILS IF a key/spelling mismatch makes the editor's setting a silent no-op
    (the engine would fall back to 'exact')."""
    coordacc = _load_engine_coordaccess()
    for policy in ef.COORDINATE_POLICIES:
        form = {
            "s_access_level": "open",
            "s_access_coordinates": policy,
            **_snap("access", {"level": "open"}),
        }
        assembled = ef.assemble_section(form, "access")
        # the engine parses the SAME block the editor emits.
        default, overrides = coordacc.parse_coordinate_policy(assembled)
        assert default == policy, (
            f"editor-assembled {assembled!r} parsed by the engine to {default!r}, not the intended "
            f"{policy!r} — a key/spelling mismatch would make the policy a silent no-op")
        assert overrides == {}  # survey-level lane only; no per-station overrides written here


def test_coordinate_policy_unset_round_trips_to_omit():
    """DIFF-MINIMALITY (zero-change promise): a survey with NO access.coordinates, submitted with the
    blank/default select, contributes NOTHING to the patch. FAILS IF the editor writes
    access.coordinates for a survey that never set it (a spurious diff on every existing survey)."""
    original = {"level": "embargoed", "embargo_until": "2027-01-01", "contact": "x@e.org"}
    form = {
        "s_access_level": "embargoed",
        "s_access_coordinates": "",  # blank/default option -> unset
        "s_access_embargo_until": "2027-01-01",
        "s_access_contact": "x@e.org",
        **_snap("access", original),
    }
    assert ef.assemble_section(form, "access") is ef._OMIT
    # And the engine reads that untouched block as the default 'exact' (byte-unchanged == exact).
    coordacc = _load_engine_coordaccess()
    assert coordacc.parse_coordinate_policy(original) == ("exact", {})


def test_setting_coordinate_policy_adds_only_that_key():
    """DIFF-MINIMALITY: setting the policy on a survey that LACKED it yields a block adding ONLY
    access.coordinates. FAILS IF it touches any other access key (the Stage-1 minimality property)."""
    original = {"level": "embargoed", "embargo_until": "2027-01-01", "contact": "x@e.org"}
    form = {
        "s_access_level": "embargoed",
        "s_access_coordinates": "withheld",
        "s_access_embargo_until": "2027-01-01",
        "s_access_contact": "x@e.org",
        **_snap("access", original),
    }
    assert ef.assemble_section(form, "access") == {**original, "coordinates": "withheld"}


def test_changing_coordinate_policy_touches_only_that_key():
    """DIFF-MINIMALITY: changing an existing policy touches ONLY access.coordinates. FAILS IF another
    key moves (e.g. an absent embargo gets introduced as null)."""
    original = {"level": "open", "coordinates": "exact", "contact": "x@e.org"}
    form = {
        "s_access_level": "open",
        "s_access_coordinates": "generalised",
        "s_access_contact": "x@e.org",
        **_snap("access", original),
    }
    assert ef.assemble_section(form, "access") == {
        "level": "open", "coordinates": "generalised", "contact": "x@e.org"}


def test_unchanged_coordinate_policy_round_trips_to_omit():
    """DIFF-MINIMALITY: a survey that ALREADY has a policy, resubmitted unchanged, is a no-op. FAILS IF
    an unchanged coordinates value re-emits the section (a spurious diff)."""
    original = {"level": "open", "coordinates": "generalised", "contact": "x@e.org"}
    form = {
        "s_access_level": "open",
        "s_access_coordinates": "generalised",
        "s_access_contact": "x@e.org",
        **_snap("access", original),
    }
    assert ef.assemble_section(form, "access") is ef._OMIT


def test_bad_coordinate_policy_errors():
    """A coordinates value outside the vocab surfaces a per-field error (fail-closed at the form), so
    the form never accepts a value the engine would reject at build. FAILS IF a bad policy is accepted."""
    form = {"s_access_level": "open", "s_access_coordinates": "fuzzy",
            **_snap("access", {"level": "open"})}
    with pytest.raises(ef.SectionError) as ei:
        ef.assemble_section(form, "access")
    assert ei.value.section == "access"
    assert "coordinate" in ei.value.message.lower()


def test_coordinate_and_level_selects_validate_independently():
    """Both access selects validate against their OWN vocab: a valid coordinates value must not trip
    the level check, and a valid level must not trip the coordinates check. FAILS IF the shared
    'select' branch cross-rejects (e.g. 'generalised' rejected as a bad access level)."""
    # a valid coordinates value + valid level assembles cleanly (no cross-rejection).
    form = {"s_access_level": "open", "s_access_coordinates": "generalised",
            **_snap("access", {"level": "open"})}
    out = ef.assemble_section(form, "access")
    assert out["coordinates"] == "generalised" and out["level"] == "open"
    # a bad LEVEL still errors on the level (coordinates being valid must not mask it).
    bad = {"s_access_level": "public", "s_access_coordinates": "exact",
           **_snap("access", {"level": "open"})}
    with pytest.raises(ef.SectionError) as ei:
        ef.assemble_section(bad, "access")
    assert "access level" in ei.value.message.lower()


# ---- time_series levels checkboxes --------------------------------------------------------------

def test_time_series_levels_checkboxes():
    """levels_available assembles from the checked c_time_series_levels_available_* boxes in canonical
    order. FAILS IF checkbox names are not read or order is not canonical."""
    form = {
        "s_time_series_collection_pid": "10.25914/abc",
        "c_time_series_levels_available_level1": "on",
        "c_time_series_levels_available_raw_packed": "on",
        **_snap("time_series", {"collection_pid": None, "levels_available": []}),
    }
    out = ef.assemble_section(form, "time_series")
    assert out["collection_pid"] == "10.25914/abc"
    assert out["levels_available"] == ["raw_packed", "level1"]  # canonical order, not form order


# ---- list sections: repeatable rows -------------------------------------------------------------

def test_list_rows_assemble_and_blank_rows_dropped():
    """principal_investigators assembles filled rows; an all-empty spare row is dropped. FAILS IF a
    blank spare row lands in the yaml as a row of nulls (the no-JS degradation must be inert)."""
    form = {
        "l_principal_investigators_0_name": "Alice Example",
        "l_principal_investigators_0_orcid": "0000-0002-1825-0097",
        "l_principal_investigators_1_name": "",   # blank spare row
        "l_principal_investigators_1_orcid": "",
        **_snap("principal_investigators", []),
    }
    out = ef.assemble_section(form, "principal_investigators")
    assert out == [{"name": "Alice Example", "orcid": "0000-0002-1825-0097"}]


def test_list_partial_row_kept_with_nulls():
    """A partially-filled row is kept with the empty sub-fields as null. FAILS IF a partial row is
    dropped (losing curator input)."""
    form = {
        "l_instruments_0_manufacturer": "Phoenix",
        "l_instruments_0_model": "",
        "l_instruments_0_pid": "",
        **_snap("instruments", []),
    }
    out = ef.assemble_section(form, "instruments")
    assert out == [{"manufacturer": "Phoenix", "model": None, "pid": None}]


def test_list_bad_orcid_row_errors():
    """A bad ORCID in a PI row surfaces a per-field error. FAILS IF a bad ORCID slips through."""
    form = {
        "l_principal_investigators_0_name": "Alice",
        "l_principal_investigators_0_orcid": "0000-0000-0000-0000",  # bad checksum
        **_snap("principal_investigators", []),
    }
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "principal_investigators")


def test_list_bad_doi_row_errors():
    """A publication DOI without a '10.' prefix surfaces a per-field error. FAILS IF a non-DOI is
    accepted in a DOI field."""
    form = {
        "l_publications_0_title": "Some paper",
        "l_publications_0_doi": "not-a-doi",
        **_snap("publications", []),
    }
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "publications")


# ---- advanced-JSON override precedence ----------------------------------------------------------

def test_advanced_json_overrides_widgets():
    """A non-empty j_<section> raw-JSON textarea OVERRIDES the widget inputs for that section. FAILS
    IF the widgets win over the advanced fallback (the documented precedence would be violated)."""
    form = {
        "s_access_level": "open",  # widget says open
        "j_access": '{"level": "embargoed", "embargo_until": "2030-01-01", "contact": null}',
        **_snap("access", {"level": "open"}),
    }
    assert ef.assemble_section(form, "access") == {
        "level": "embargoed", "embargo_until": "2030-01-01", "contact": None}


def test_advanced_json_malformed_errors():
    """A malformed advanced-JSON blob surfaces a per-section error (not a silent drop). FAILS IF bad
    JSON is swallowed."""
    form = {"j_identifiers": "{not json", **_snap("identifiers", {})}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "identifiers")


# ---- build_section_patch: collect-all errors ----------------------------------------------------

def test_build_section_patch_collects_multiple_errors():
    """build_section_patch collects EVERY section error rather than failing on the first. FAILS IF
    only the first bad field is reported (the curator would fix one, resubmit, hit the next)."""
    form = {
        "s_lead_investigator_orcid": "0000-0000-0000-0000",  # bad orcid
        "s_access_level": "nope",                             # bad level
        **_snap("lead_investigator", {"name": None, "orcid": None}),
        **_snap("access", {"level": "open"}),
    }
    patch, errors = ef.build_section_patch(form)
    sections = {e.section for e in errors}
    assert "lead_investigator" in sections and "access" in sections


def test_build_section_patch_empty_form_is_empty_patch():
    """An empty form (no widget inputs, no snapshots) yields an empty patch and no errors. FAILS IF a
    bare form invents sections."""
    patch, errors = ef.build_section_patch({})
    assert patch == {} and errors == []
