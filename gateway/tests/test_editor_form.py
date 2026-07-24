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


# ---- access.coordinate_overrides (C43 Stage-4 per-station coordinate-access overrides) -----------
#
# The stations-panel fieldset (exact / generalised / withheld + inherit) assembles a
# {BASE_station_id: policy} map and submits it as the ONE field s_access_coordinate_overrides
# (canonical JSON, keys built ONLY from real served station records). A station left at INHERIT is
# ABSENT from the map (it follows the survey default); an explicit policy is written verbatim (even if
# equal to the current default — an explicit override pins intent against later default changes). An
# EMPTY map writes NO coordinate_overrides key (the record's byte-unchanged promise). These pins feed
# the editor-ASSEMBLED block through the REAL engine parser AND validator (engine-truth), so a
# key/vocab drift can never pass silently.

def _override_records():
    """Realistic engine station records [(path, record), ...] the way build_portal's parsed +
    _disambiguate'd records look — enough to exercise validate_overrides / station_policy honestly:
      * a DATAID-differs-from-stem station (file stem 'ALPHA', station id 'CP1L04' from the DATAID);
      * a processing-variant PAIR (one physical site 'MBV20' processed twice -> ids MBV20.a / MBV20.b
        with variant tags 'a'/'b', base id 'MBV20');
      * a plain station whose id equals its stem ('CP1L10')."""
    return [
        (Path("ALPHA.edi"), {"id": "CP1L04", "variant": None, "ausmt_id": "au.s.cp1l04"}),
        (Path("MBV20_lemi.edi"), {"id": "MBV20.a", "variant": "a", "ausmt_id": "au.s.mbv20.a"}),
        (Path("MBV20_ohmega.edi"), {"id": "MBV20.b", "variant": "b", "ausmt_id": "au.s.mbv20.b"}),
        (Path("CP1L10.edi"), {"id": "CP1L10", "variant": None, "ausmt_id": "au.s.cp1l10"}),
    ]


def test_coordinate_overrides_key_parity_through_real_engine():
    """KEY-PARITY PIN (load-bearing): the editor-assembled access block WITH per-station overrides
    round-trips through the REAL parse_coordinate_policy AND validate_overrides — every written key is
    accepted AND EFFECTIVE (changes at least one record's resolved policy; no silent no-op). A
    base-id override (MBV20) covers ALL its variant records. FAILS IF a key/vocab drift makes an
    override silently absent or a validated-but-inert no-op (matcher divergence)."""
    coordacc = _load_engine_coordaccess()
    records = _override_records()
    overrides_in = {"CP1L04": "withheld", "MBV20": "generalised"}
    form = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps(overrides_in),
        **_snap("access", {"level": "open"}),
    }
    assembled = ef.assemble_section(form, "access")
    default, overrides = coordacc.parse_coordinate_policy(assembled)
    assert default == "exact"
    assert overrides == overrides_in, (
        f"engine parsed overrides {overrides!r}, not the editor-assembled {overrides_in!r} "
        f"— a key/spelling drift would make the per-station policy a silent no-op")
    # every key validates against the REAL records (no raise) ...
    coordacc.validate_overrides(overrides, records)
    # ... and is EFFECTIVE: each key changes at least one record's resolved policy vs the bare default.
    for key, pol in overrides.items():
        hits = [r for (_p, r) in records
                if coordacc.station_policy(default, overrides, r.get("id"), r.get("variant")) == pol
                and coordacc.station_policy(default, {}, r.get("id"), r.get("variant")) != pol]
        assert hits, (f"override {key!r}={pol!r} matched no record — a validated-but-inert key "
                      f"(the matcher-divergence class)")


def test_coordinate_overrides_bad_vocab_rejected_fail_closed():
    """FAIL-CLOSED POST: an override VALUE outside COORDINATE_POLICIES is rejected at the editor
    (mirrors the #53 survey-level select vocab check). FAILS IF the editor assembles an unknown policy
    the engine would refuse to build."""
    form = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps({"CP1L04": "fuzzy"}),
        **_snap("access", {"level": "open"}),
    }
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "access")


def test_coordinate_overrides_unknown_key_rejected_by_engine():
    """FAIL-CLOSED POST: an override key naming NO real base station id is rejected by the REAL engine
    validator over the editor-assembled block (engine-truth; the gateway is content-blind so the
    authoritative key gate is the engine/validator). FAILS IF a mis-keyed override validates."""
    coordacc = _load_engine_coordaccess()
    records = _override_records()
    form = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps({"NOSUCH": "withheld"}),
        **_snap("access", {"level": "open"}),
    }
    assembled = ef.assemble_section(form, "access")
    _default, overrides = coordacc.parse_coordinate_policy(assembled)
    assert overrides == {"NOSUCH": "withheld"}  # the editor assembled it; the ENGINE is the key gate
    with pytest.raises(coordacc.CoordinatePolicyError):
        coordacc.validate_overrides(overrides, records)


def test_coordinate_overrides_variant_suffixed_key_rejected_by_engine():
    """FAIL-CLOSED POST: a FULL variant-suffixed id (MBV20.a) is NOT a valid key — overrides key the
    BASE id (MBV20), which covers all its processing variants. FAILS IF a sibling variant could be
    keyed directly (the probe-e / variant class: a sibling serving the physical site's true position)."""
    coordacc = _load_engine_coordaccess()
    records = _override_records()
    form = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps({"MBV20.a": "withheld"}),
        **_snap("access", {"level": "open"}),
    }
    assembled = ef.assemble_section(form, "access")
    _default, overrides = coordacc.parse_coordinate_policy(assembled)
    assert overrides == {"MBV20.a": "withheld"}
    with pytest.raises(coordacc.CoordinatePolicyError):
        coordacc.validate_overrides(overrides, records)


def test_coordinate_overrides_empty_and_inherit_omit_the_key():
    """INHERIT / EMPTY-MAP: a station set to inherit is absent from the submitted map; an EMPTY map
    (or the absent field) writes NO coordinate_overrides key — a survey that never used overrides stays
    byte-unchanged. A NON-empty map ADDS exactly the keyed stations. FAILS IF an empty map introduces
    the key, or the assembly path never emits it."""
    # empty map on a survey that never had overrides -> the key is not written (and, nothing else
    # changed, the whole section is a no-op).
    form_empty = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps({}),
        **_snap("access", {"level": "open"}),
    }
    assert ef.assemble_section(form_empty, "access") is ef._OMIT
    # the absent field (no JS / never touched) behaves identically.
    form_absent = {"s_access_level": "open", **_snap("access", {"level": "open"})}
    assert ef.assemble_section(form_absent, "access") is ef._OMIT
    # a NON-empty map ADDS exactly the keyed station (proves the assembly path emits the key).
    form_add = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps({"CP1L04": "withheld"}),
        **_snap("access", {"level": "open"}),
    }
    assert ef.assemble_section(form_add, "access") == {
        "level": "open", "coordinate_overrides": {"CP1L04": "withheld"}}


def test_coordinate_overrides_inherit_removes_a_present_key():
    """INHERIT removes a previously-pinned station: original had {CP1L04: withheld}; resubmitting an
    empty map yields an access block that no longer carries coordinate_overrides, so apply_patch's
    surgical map-merge DELETES the key (byte-clean removal). FAILS IF a removed override lingers."""
    original = {"level": "open", "coordinate_overrides": {"CP1L04": "withheld"}}
    form = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps({}),
        **_snap("access", original),
    }
    # resubmitting the SAME override is a no-op (the assembly recognises the existing key).
    same = {"s_access_level": "open",
            "s_access_coordinate_overrides": json.dumps({"CP1L04": "withheld"}),
            **_snap("access", original)}
    assert ef.assemble_section(same, "access") is ef._OMIT
    out = ef.assemble_section(form, "access")
    assert out is not ef._OMIT
    assert "coordinate_overrides" not in out


def test_coordinate_overrides_unchanged_round_trips_to_omit():
    """DIFF-MINIMALITY: an UNCHANGED overrides map (resubmitted identically) contributes nothing to
    the patch. FAILS IF a no-op submit re-emits the section (a spurious diff on a policy-bearing
    survey)."""
    original = {"level": "open",
                "coordinate_overrides": {"CP1L04": "withheld", "MBV20": "generalised"}}
    form = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps(
            {"CP1L04": "withheld", "MBV20": "generalised"}),
        **_snap("access", original),
    }
    assert ef.assemble_section(form, "access") is ef._OMIT


def test_coordinate_overrides_malformed_payload_rejected():
    """FAIL-CLOSED: a malformed overrides payload (not a JSON object of str->str) fail-closes at the
    editor rather than silently dropping the curator's intent. FAILS IF a non-mapping payload is
    accepted."""
    with pytest.raises(ef.SectionError):
        ef.assemble_section({"s_access_level": "open",
                             "s_access_coordinate_overrides": "not json",
                             **_snap("access", {"level": "open"})}, "access")
    with pytest.raises(ef.SectionError):
        ef.assemble_section({"s_access_level": "open",
                             "s_access_coordinate_overrides": json.dumps(["a", "b"]),
                             **_snap("access", {"level": "open"})}, "access")


# ---- C42 coordinate-privacy: an ordinary access edit must PRESERVE the overrides map --------------
#
# The Metadata-tab per-section access form models only the four access scalars (level / coordinates /
# embargo_until / contact) — it does NOT render s_access_coordinate_overrides. So an ordinary access
# edit (change embargo, contact, or level) submits WITHOUT that field. The assembler distinguishes the
# ABSENT field (this form: PRESERVE the survey's existing overrides from the o_access snapshot) from an
# explicit EMPTY map (the stations panel: DELETE the key — set-all-to-inherit). Before this fix an
# absent field collapsed to {} exactly like an explicit clear, so apply_patch's surgical merge deleted
# the whole coordinate_overrides map, silently reverting every withheld/generalised station to the
# survey default (usually exact) — its TRUE coordinates served on the next build (a C42 leak).

def test_ordinary_access_edit_preserves_existing_coordinate_overrides():
    """C42 LEAK PIN (RED on pre-fix HEAD dfa5bab): a Metadata-tab access edit that changes ONLY
    embargo_until — submitting NO s_access_coordinate_overrides field, exactly what that form posts —
    must PRESERVE the survey's existing coordinate_overrides map. FAILS IF an unrelated access edit
    drops a withheld/generalised station back to the survey default (the silent un-masking)."""
    original = {"level": "open", "embargo_until": "2026-01-01", "contact": "data@example.org",
                "coordinate_overrides": {"SITE1": "withheld", "SITE2": "generalised"}}
    form = {
        "s_access_level": "open",
        "s_access_coordinates": "",                 # the <select>'s default-blank, round-tripped
        "s_access_embargo_until": "2027-06-30",     # the ONLY curator change
        "s_access_contact": "data@example.org",
        # NOTE: no s_access_coordinate_overrides — the Metadata-tab access form never renders it.
        **_snap("access", original),
    }
    out = ef.assemble_section(form, "access")
    assert out is not ef._OMIT
    assert out["embargo_until"] == "2027-06-30"
    assert out["coordinate_overrides"] == {"SITE1": "withheld", "SITE2": "generalised"}, \
        "an embargo-only access edit dropped the coordinate_overrides map (C42 coordinate-privacy leak)"


def test_access_edit_with_absent_overrides_and_no_original_stays_omit():
    """The absent-field PRESERVE path must NOT introduce a key on a survey that never had overrides: an
    unchanged access submit with no original map and no overrides field is still a no-op (_OMIT). FAILS
    IF the fix fabricates an empty coordinate_overrides key (a spurious diff / broken byte-unchanged
    promise)."""
    original = {"level": "open", "embargo_until": "2026-01-01", "contact": "data@example.org"}
    form = {
        "s_access_level": "open",
        "s_access_coordinates": "",
        "s_access_embargo_until": "2026-01-01",
        "s_access_contact": "data@example.org",
        **_snap("access", original),
    }
    assert ef.assemble_section(form, "access") is ef._OMIT


def test_stations_panel_clear_all_removes_overrides_despite_original_map():
    """OVER-PRESERVATION GUARD: field PRESENT + explicit EMPTY map (the stations-panel set-all-to-
    inherit) must still DELETE the key even when the original carried a map and a sibling scalar also
    changed. This is the OTHER side of the absent/present distinction — the fix must not over-preserve
    a map the curator explicitly cleared. FAILS IF the clear-all no longer removes the key."""
    original = {"level": "open", "contact": "old@example.org",
                "coordinate_overrides": {"SITE1": "withheld"}}
    form = {
        "s_access_level": "open",
        "s_access_contact": "new@example.org",      # a real sibling change (so the section is not _OMIT)
        "s_access_coordinate_overrides": json.dumps({}),   # explicit clear-all (present, empty)
        **_snap("access", original),
    }
    out = ef.assemble_section(form, "access")
    assert out is not ef._OMIT
    assert "coordinate_overrides" not in out, \
        "an explicit clear-all did not remove the coordinate_overrides key (over-preservation regression)"


def test_survey_level_coordinates_default_survives_sibling_scalar_edit():
    """C42 sibling-scalar class (the survey-level policy, one level up from the per-station map): editing
    a SIBLING access scalar (embargo) must not drop the survey-level `coordinates` policy. The Metadata
    form round-trips the coordinates <select>, so it is re-posted verbatim and the assembler keeps it.
    FAILS IF a sibling-only edit drops access.coordinates (the same silent un-mask, survey-granularity)."""
    original = {"level": "open", "coordinates": "withheld", "embargo_until": "2026-01-01"}
    form = {
        "s_access_level": "open",
        "s_access_coordinates": "withheld",         # round-tripped by the <select>
        "s_access_embargo_until": "2027-06-30",     # the only change
        **_snap("access", original),
    }
    out = ef.assemble_section(form, "access")
    assert out is not ef._OMIT
    assert out["coordinates"] == "withheld", \
        "a sibling-scalar access edit dropped the survey-level coordinate policy"


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
    order. FAILS IF checkbox names are not read or order is not canonical. IDCONS D2: collection_pid is
    RETIRED from the editor UI, so a stray s_time_series_collection_pid input is IGNORED (not assembled);
    a stored collection_pid instead ROUND-TRIPS verbatim via the unmodelled-key carry-forward."""
    form = {
        "s_time_series_collection_pid": "10.25914/ignored",   # retired input — must NOT be assembled
        "c_time_series_levels_available_level1": "on",
        "c_time_series_levels_available_raw_packed": "on",
        **_snap("time_series", {"collection_pid": "10.25914/abc", "levels_available": []}),
    }
    out = ef.assemble_section(form, "time_series")
    assert out["collection_pid"] == "10.25914/abc"  # carried from the snapshot, NOT the retired input
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
    dropped (losing curator input). IDCONS D2: instruments[].pid is RETIRED from the row widgets, so a
    stray l_instruments_0_pid input is IGNORED — the assembled row carries only the modelled sub-keys."""
    form = {
        "l_instruments_0_manufacturer": "Phoenix",
        "l_instruments_0_model": "",
        "l_instruments_0_pid": "10.ignored/x",   # retired input — must NOT be assembled
        **_snap("instruments", []),
    }
    out = ef.assemble_section(form, "instruments")
    assert out == [{"manufacturer": "Phoenix", "model": None}]


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


# ---- C46: attribution (map) + sources (list) capture --------------------------------------------

# The GENERATED engine contract seam, loaded by path (engine-truth). _contract.py is a stdlib-only
# generated constants file (no heavy stack), so it loads cleanly in the stack-less gateway test env.
# The gateway APP image is CONTENT-BLIND (ships only gateway/), so editor_form BAKES the licence vocab;
# this test PINS that baked copy to the contract the same way the coordinate-policy test pins its copy.
_ENGINE_CONTRACT_PY = Path(__file__).resolve().parents[2] / "engine" / "extract" / "_contract.py"

# The REAL surveys validator, loaded from the VENDORED copy that ships with the gateway (the same copy
# the F7 oracles use). The C46-W1c key-parity pin feeds an editor-assembled patch through THIS validator
# and asserts zero unknown-key warnings — cross-repo engine-truth, not a hand-typed expectation.
_VENDORED_VALIDATOR_PY = (Path(__file__).resolve().parent / "fixtures" / "vendored_validation"
                          / "validate_survey.py")


def _load_by_path(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_license_vocab_matches_engine_contract():
    """PARITY PIN: editor_form.LICENSE_IDS is the full recognised vocab (redistributable ∪
    recognised_only) from the generated engine contract seam, in order. FAILS IF the baked copy drifts
    from contract/licenses.json (an id added there but not here). This is the 'not hand-copied' guard
    the content-blind gateway needs — it cannot import the seam at runtime, so the test pins it."""
    contract = _load_by_path(_ENGINE_CONTRACT_PY, "_ausmt_engine_contract_ro")
    expected = tuple(contract.LICENSES["redistributable"]) + tuple(contract.LICENSES["recognised_only"])
    assert ef.LICENSE_IDS == expected, "editor LICENSE_IDS drifted from the generated contract"
    assert ef.LICENSE_REDISTRIBUTABLE == tuple(contract.LICENSES["redistributable"]), \
        "editor LICENSE_REDISTRIBUTABLE grouping drifted from the contract"
    assert len(ef.LICENSE_IDS) == 19


def _survey_meta_with(patch: dict) -> dict:
    """A minimal schema-0.3 survey metadata dict carrying an editor-assembled patch fragment."""
    return {
        "schema_version": "0.3", "slug": "paritytest", "project_name": "Parity Test",
        "country": "Australia", "organisation": {"name": "Org", "ror": None},
        "access": {"level": "open"}, "license": "CC-BY-4.0", **patch,
    }


def _write_survey(folder: Path, meta: dict) -> None:
    import yaml
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "survey.yaml").write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    (folder / "README.md").write_text("# x\n", encoding="utf-8")
    (folder / "LICENSE.md").write_text("# Licence\n\n**CC-BY-4.0**\n", encoding="utf-8")


# D-L3 (SPEC §9.3): the acquisition fields (title/licence/retrieved/statement/profile) that used to live
# on a sources[] row now ride a related_identifiers row (identifies: entire). Same SOURCE_KEYS allow-list
# at the validator, so the key-parity pin now feeds the merged row.
_C46_FORM = {
    "s_attribution_custodian": "Geological Survey of South Australia",
    "s_attribution_custodian_ror": "https://ror.org/04y8k6r48",
    "s_attribution_statement": "Cite as GSSA (2016)",
    "s_attribution_changes_made": "1",
    "s_attribution_changes_summary": "EMTF XML + MTH5 regenerated from custodian EDIs",
    "s_attribution_declared_by": "A. Curator",
    "s_attribution_declared_date": "2026-07-13",
    "l_related_identifiers_0_identifies": "entire",
    "l_related_identifiers_0_identifier": "10.25914/abc",
    "l_related_identifiers_0_identifier_type": "DOI",
    "l_related_identifiers_0_custodian": "NCI / AuScope",
    "l_related_identifiers_0_title": "AusLAMP SA – NCI/AuScope archive",
    "l_related_identifiers_0_licence": "CC-BY-3.0-AU",
    "l_related_identifiers_0_retrieved": "2016",
    "l_related_identifiers_0_statement": "Cite the AusLAMP SA archive",
}


def test_key_parity_editor_patch_through_real_validator(tmp_path):
    """KEY-PARITY PIN (the important one): an editor-assembled attribution + related_identifiers patch
    (the row carrying the MERGED acquisition fields, D-L3), written to a survey.yaml and read back by the
    REAL vendored surveys validator, produces ZERO unknown-key warnings — the editor's FROZEN section keys
    equal the validator's ATTRIBUTION_KEYS / SOURCE_KEYS (the C42-editor key-parity lesson, cross-repo).
    MUTATION-PROOF below (rename one key -> red)."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_validate")
    patch, errors = ef.build_section_patch(_C46_FORM)
    assert not errors, errors
    assert set(patch) == {"attribution", "related_identifiers"}, patch
    # the relation DERIVED from identifies: entire (D-L2) and the acquisition fields round-tripped onto the row
    assert patch["related_identifiers"][0]["relation"] == "IsVariantFormOf"
    assert patch["related_identifiers"][0]["title"] == "AusLAMP SA – NCI/AuScope archive"

    folder = tmp_path / "paritytest"
    _write_survey(folder, _survey_meta_with(patch))
    rep = vv.validate(folder)
    unknown = [i for i in rep.items if i["check"] in ("attribution", "related_identifiers")
               and "not a recognised" in i["message"]]
    assert not unknown, f"editor keys the validator does not recognise: {unknown}"
    # the merged acquisition keys + derived relation are accepted (no related_identifiers WARN/FAIL)
    assert not [i for i in rep.items if i["check"] == "related_identifiers"
                and i["level"] in ("WARNING", "FAIL")]


def test_key_parity_mutation_proof(tmp_path):
    """NON-VACUOUS proof for the key-parity pin: renaming ONE frozen key in the assembled block makes
    the REAL validator flag it as unrecognised. FAILS IF the validator's allow-list would silently
    accept a drifted key (which would make the parity test above vacuous)."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_validate2")
    patch, _ = ef.build_section_patch(_C46_FORM)
    attr = dict(patch["attribution"])
    attr["custodianX"] = attr.pop("custodian")          # a drifted attribution key
    patch = {**patch, "attribution": attr}
    folder = tmp_path / "mutant"
    _write_survey(folder, _survey_meta_with(patch))
    rep = vv.validate(folder)
    assert any(i["check"] == "attribution" and "custodianX" in i["message"] for i in rep.items), \
        "validator did not flag a drifted attribution key — the parity pin would be vacuous"


def test_attribution_bool_and_round_trip():
    """attribution assembles changes_made from the checkbox (present => True); an unchanged submit
    round-trips to _OMIT. FAILS IF the bool checkbox is not read, or an unchanged submit emits a diff."""
    form = {
        "s_attribution_custodian": "GSSA", "s_attribution_changes_made": "1",
        "s_attribution_declared_date": "2026-07-13",
        **_snap("attribution", {"custodian": "GSSA", "changes_made": True, "declared_date": "2026-07-13"}),
    }
    assert ef.assemble_section(form, "attribution") is ef._OMIT
    # unticking a previously-true flag is a real change to False (not a silent drop)
    form2 = {"s_attribution_custodian": "GSSA",
             **_snap("attribution", {"custodian": "GSSA", "changes_made": True})}
    assert ef.assemble_section(form2, "attribution") == {"custodian": "GSSA", "changes_made": False}


def test_attribution_bad_declared_date_errors():
    """attribution.declared_date is a date-kind field: a malformed date surfaces a per-field error."""
    form = {"s_attribution_declared_date": "soon", **_snap("attribution", {})}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "attribution")


def test_related_identifiers_acquisition_licence_and_profile_vocab_enforced():
    """D-L3: the acquisition fields merged onto a related_identifiers row keep the fail-closed vocab
    discipline the retired sources[] row had — licence against the contract vocab, profile against
    ga|generic. A valid pair assembles; an out-of-vocab value fail-closes at the form. FAILS IF the merged
    row would accept a value the validator/engine would reject."""
    ok = {"l_related_identifiers_0_identifies": "entire", "l_related_identifiers_0_identifier": "10.1/x",
          "l_related_identifiers_0_licence": "CC-BY-4.0", "l_related_identifiers_0_profile": "ga",
          **_snap("related_identifiers", [])}
    out = ef.assemble_section(ok, "related_identifiers")
    assert out[0]["licence"] == "CC-BY-4.0" and out[0]["profile"] == "ga"
    with pytest.raises(ef.SectionError):
        ef.assemble_section({"l_related_identifiers_0_identifier": "10.1/x",
                             "l_related_identifiers_0_licence": "NOT-A-LICENCE",
                             **_snap("related_identifiers", [])}, "related_identifiers")
    with pytest.raises(ef.SectionError):
        ef.assemble_section({"l_related_identifiers_0_identifier": "10.1/x",
                             "l_related_identifiers_0_profile": "mystery",
                             **_snap("related_identifiers", [])}, "related_identifiers")


# ---- §2a/§2b: related_identifiers (typed list) + identifiers.instrument_pid ----------------------

def test_related_identifiers_vocab_matches_vendored_validator():
    """PARITY PIN: the editor's baked RELATION_TYPES / IDENTIFIER_TYPES equal the surveys validator's
    frozen vocabularies (loaded from the VENDORED copy — the content-blind gateway cannot import the
    sibling at runtime, so the test pins it). FAILS IF a vocab is extended in the validator but not
    mirrored here — the exact drift the shared _check_typed_relation seam exists to prevent."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_relvocab")
    assert set(ef.RELATION_TYPES) == set(vv.RELATION_TYPES), "editor RELATION_TYPES drifted from the validator"
    assert set(ef.IDENTIFIER_TYPES) == set(vv.IDENTIFIER_TYPES), "editor IDENTIFIER_TYPES drifted from the validator"


# The vulcan-2022 demo shape: the four keys the editor row models (identifier, identifier_type,
# relation, AND custodian — custodian is modelled so a stored entry that carries it round-trips).
_RELID_ROW = {
    "l_related_identifiers_0_identifier": "10.25914/sv5r-zw68",
    "l_related_identifiers_0_identifier_type": "DOI",
    "l_related_identifiers_0_relation": "IsDerivedFrom",
    "l_related_identifiers_0_custodian": "NCI",
}
_RELID_VALUE = [{"identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI",
                 "relation": "IsDerivedFrom", "custodian": "NCI"}]


def test_related_identifiers_row_assembles_and_round_trips():
    """A related_identifiers row assembles through the SAME per-section list flow, carrying the typed
    trio PLUS custodian. A blank spare row is dropped; an unchanged submit round-trips to _OMIT. FAILS
    IF the widget silently drops the custodian field (round-trip data loss) or emits a diff unchanged."""
    form = {**_RELID_ROW,
            "l_related_identifiers_1_identifier": "",   # blank spare row -> dropped
            "l_related_identifiers_1_identifier_type": "",
            "l_related_identifiers_1_relation": "",
            "l_related_identifiers_1_custodian": "",
            **_snap("related_identifiers", [])}
    assert ef.assemble_section(form, "related_identifiers") == _RELID_VALUE
    same = {**_RELID_ROW, **_snap("related_identifiers", _RELID_VALUE)}
    assert ef.assemble_section(same, "related_identifiers") is ef._OMIT


def test_related_identifiers_bad_relation_and_type_rejected():
    """FAIL-CLOSED: an out-of-vocab relation or identifier_type is rejected at the form (SectionError),
    the same posture as access.coordinates. FAILS IF the editor would accept a value the validator
    hard-FAILs — a wrong/ambiguous provenance claim must never assemble."""
    with pytest.raises(ef.SectionError):
        ef.assemble_section({"l_related_identifiers_0_identifier": "10.25914/x",
                             "l_related_identifiers_0_relation": "IsBogusOf",
                             **_snap("related_identifiers", [])}, "related_identifiers")
    with pytest.raises(ef.SectionError):
        ef.assemble_section({"l_related_identifiers_0_identifier": "10.25914/x",
                             "l_related_identifiers_0_identifier_type": "MAGNET",
                             **_snap("related_identifiers", [])}, "related_identifiers")


def test_related_identifiers_key_parity_through_real_validator(tmp_path):
    """KEY-PARITY PIN: an editor-assembled related_identifiers patch, read back by the REAL vendored
    validator, produces ZERO related_identifiers items (no unknown-key warning, no vocab FAIL) — the
    row's keys are a subset of SOURCE_KEYS and its vocab values are accepted. The non-vacuous proof
    below (a bogus relation -> a validator FAIL) keeps this meaningful."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_relid")
    patch, errors = ef.build_section_patch({**_RELID_ROW, **_snap("related_identifiers", [])})
    assert not errors, errors
    assert patch == {"related_identifiers": _RELID_VALUE}, patch
    folder = tmp_path / "relid"
    _write_survey(folder, _survey_meta_with(patch))
    rep = vv.validate(folder)
    flagged = [i for i in rep.items if i["check"] == "related_identifiers"]
    assert not flagged, f"validator flagged the editor-assembled related_identifiers: {flagged}"


def test_related_identifiers_validator_fails_bad_relation_non_vacuous(tmp_path):
    """NON-VACUOUS proof: a related_identifiers entry with an out-of-vocab relation is a HARD FAIL at
    the real validator — so the vocab pin is not vacuous (the validator does not accept any relation)."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_relid_mut")
    meta = _survey_meta_with({"related_identifiers": [
        {"identifier": "10.25914/x", "identifier_type": "DOI", "relation": "IsBogusOf"}]})
    folder = tmp_path / "relidmut"
    _write_survey(folder, meta)
    rep = vv.validate(folder)
    assert any(i["check"] == "related_identifiers" and i["level"] == "FAIL" for i in rep.items), \
        "validator did not FAIL a bogus relation — the vocab pin would be vacuous"


def test_identifies_out_of_vocab_is_fail_closed():
    """D-L1: `identifies` is a fail-closed vocab (like relation/identifier_type) — an out-of-vocab level
    is a SectionError, because a mis-typed level auto-derives a WRONG relation and must block, not ship."""
    with pytest.raises(ef.SectionError):
        ef.assemble_section({"l_related_identifiers_0_identifier": "10.25914/x",
                             "l_related_identifiers_0_identifies": "level9",
                             **_snap("related_identifiers", [])}, "related_identifiers")
    # every ratified level is accepted
    for lvl in ef.IDENTIFIES_LEVELS:
        out = ef.assemble_section({"l_related_identifiers_0_identifier": "10.25914/x",
                                   "l_related_identifiers_0_identifier_type": "DOI",
                                   "l_related_identifiers_0_identifies": lvl,
                                   **_snap("related_identifiers", [])}, "related_identifiers")
        assert out[0]["identifies"] == lvl


def test_relation_auto_derives_from_identifies_server_side():
    """D-L2: when a row states `identifies`, the DataCite relation DERIVES from it server-side — the form
    carries NO explicit relation (the control is hidden on an identifies row), and the assembler writes the
    derived value. Every level maps to its ratified relation. FAILS IF a level does not derive its relation."""
    expected = {"collection": "IsPartOf", "raw_packed": "IsDerivedFrom", "level0": "IsDerivedFrom",
                "level1": "IsDerivedFrom", "level2": "IsVariantFormOf", "level3": "IsSourceOf",
                "entire": "IsVariantFormOf"}
    for lvl, rel in expected.items():
        out = ef.assemble_section({"l_related_identifiers_0_identifier": "10.25914/x",
                                   "l_related_identifiers_0_identifier_type": "DOI",
                                   "l_related_identifiers_0_identifies": lvl,
                                   # NO l_related_identifiers_0_relation posted (the control is hidden)
                                   **_snap("related_identifiers", [])}, "related_identifiers")
        assert out[0]["relation"] == rel, f"{lvl} did not derive {rel}: {out}"


def test_legacy_relation_row_without_identifies_is_preserved():
    """D-L2 back-compat: a legacy row that carries an explicit relation but NO identifies keeps its relation
    exactly (no derivation, no identifies key introduced) — an unchanged submit round-trips to _OMIT. FAILS
    IF the merge clobbers a legacy relation or sprays a null identifies onto the row."""
    legacy = [{"identifier": "10.25914/legacy", "identifier_type": "DOI", "relation": "Cites",
               "custodian": "GA"}]
    form: dict = {"o_related_identifiers": json.dumps(legacy)}
    for subkey, *_ in ef.LIST_SECTIONS["related_identifiers"]:
        val = legacy[0].get(subkey)
        form[f"l_related_identifiers_0_{subkey}"] = "" if val is None else str(val)
    assert ef.assemble_section(form, "related_identifiers") is ef._OMIT


def test_identifies_row_derives_even_when_no_explicit_relation_field_present():
    """The exact render shape of an identifies row (the relation <select> is OMITTED, so the form has no
    relation field at all): the derived relation is still written. FAILS IF the assembler needs an explicit
    (empty) relation input to fire the derivation."""
    stored = [{"identifier": "10.25914/coll", "identifies": "raw_packed", "identifier_type": "DOI",
               "relation": "IsDerivedFrom", "custodian": "NCI"}]
    form = {"o_related_identifiers": json.dumps(stored),
            "l_related_identifiers_0_identifier": "10.25914/coll",
            "l_related_identifiers_0_identifies": "raw_packed",
            "l_related_identifiers_0_identifier_type": "DOI",
            "l_related_identifiers_0_custodian": "NCI"}   # NO _relation key (control hidden)
    assert ef.assemble_section(form, "related_identifiers") is ef._OMIT


def test_instrument_pid_persists_and_round_trips():
    """identifiers.instrument_pid (§2b, wave-1 EXPAND) assembles from its input and round-trips to
    _OMIT when unchanged. FAILS IF the new field is not read, or an unchanged submit emits a diff. It
    is additive/WARNING-only at the validator, so the editor never blocks on its format (plain text)."""
    form = {"s_identifiers_dataset_doi": "10.5281/zenodo.1",
            "s_identifiers_instrument_pid": "10.82388/abc",
            **_snap("identifiers", {"dataset_doi": "10.5281/zenodo.1"})}
    out = ef.assemble_section(form, "identifiers")
    assert out["instrument_pid"] == "10.82388/abc"
    assert out["dataset_doi"] == "10.5281/zenodo.1"
    same = {"s_identifiers_dataset_doi": "10.5281/zenodo.1",
            "s_identifiers_instrument_pid": "10.82388/abc",
            **_snap("identifiers", {"dataset_doi": "10.5281/zenodo.1", "instrument_pid": "10.82388/abc"})}
    assert ef.assemble_section(same, "identifiers") is ef._OMIT
