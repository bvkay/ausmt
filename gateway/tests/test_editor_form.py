"""Unit tests for the structured metadata-editor form assembly (gateway/editor_form.py) - the "hostile JSON" fix that replaces the raw-JSON textareas with per-section widgets.

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
from gateway.tests.conftest import require_validator_dir, resolve_validator_dir


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
    # identifiers carries only dataset_doi + project_raid (a real subset case).
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
        assert overrides == {}  # survey level only; no per-station overrides written here


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
    """INHERIT removes a pinned station: the original carries {CP1L04: withheld}; resubmitting an
    empty map yields an access block that carries no coordinate_overrides, so apply_patch's
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
    """LEAK PIN (RED on pre-fix HEAD dfa5bab): a Metadata-tab access edit that changes ONLY
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
    a map the curator explicitly cleared. FAILS IF the clear-all does not remove the key."""
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
    """Sibling-scalar class (the survey-level policy, one level up from the per-station map): editing
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
    order. FAILS IF checkbox names are not read or order is not canonical. IDCONS collection_pid is
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
    """A list section assembles filled rows; an all-empty spare row is dropped. FAILS IF a blank spare
    row lands in the yaml as a row of nulls (the no-JS degradation must be inert). retargeted off
    the retired principal_investigators section onto publications, an all-scalar list of the same shape
    (creators/contributors are assembled by the unified People panel, not this generic path)."""
    form = {
        "l_publications_0_author": "Alice Example",
        "l_publications_0_doi": "10.1234/x",
        "l_publications_1_author": "",   # blank spare row
        "l_publications_1_doi": "",
        **_snap("publications", []),
    }
    out = ef.assemble_section(form, "publications")
    assert out == [{"author": "Alice Example", "year": None, "title": None,
                    "journal": None, "doi": "10.1234/x"}]


def test_list_partial_row_kept_with_nulls():
    """A partially-filled row is kept with the empty sub-fields as null. FAILS IF a partial row is
    dropped (losing curator input). IDCONS instruments[].pid is RETIRED from the row widgets, so a
    stray l_instruments_0_pid input is IGNORED - the assembled row carries only the modelled sub-keys."""
    form = {
        "l_instruments_0_manufacturer": "Phoenix",
        "l_instruments_0_model": "",
        "l_instruments_0_pid": "10.ignored/x",   # retired input — must NOT be assembled
        **_snap("instruments", []),
    }
    out = ef.assemble_section(form, "instruments")
    assert out == [{"manufacturer": "Phoenix", "model": None}]


def test_list_bad_orcid_row_errors():
    """A bad ORCID in a credit row surfaces a per-field error. FAILS IF a bad ORCID slips through."""
    form = {
        "l_creators_0_name": "Alice",
        "l_creators_0_name_type": "person",
        "l_creators_0_orcid": "0000-0000-0000-0000",  # bad checksum
        **_snap("creators", []),
    }
    with pytest.raises(ef.SectionError):
        ef._assemble_list(form, "creators")


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
        "s_citation_preferred_text": "GSSA (2016).",
        "s_citation_text_source": "guessed",                  # bad text_source vocab
        "s_access_level": "nope",                             # bad level
        **_snap("citation", {}),
        **_snap("access", {"level": "open"}),
    }
    patch, errors = ef.build_section_patch(form)
    sections = {e.section for e in errors}
    assert "citation" in sections and "access" in sections


def test_build_section_patch_empty_form_is_empty_patch():
    """An empty form (no widget inputs, no snapshots) yields an empty patch and no errors. FAILS IF a
    bare form invents sections."""
    patch, errors = ef.build_section_patch({})
    assert patch == {} and errors == []


# --- Attribution (map) + sources (list) capture --------------------------------------------

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


# SPEC §9.3: the acquisition fields (title/licence/retrieved/statement/profile) that would otherwise live
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
    # unticking a flag the original set true is a real change to False (not a silent drop)
    form2 = {"s_attribution_custodian": "GSSA",
             **_snap("attribution", {"custodian": "GSSA", "changes_made": True})}
    assert ef.assemble_section(form2, "attribution") == {"custodian": "GSSA", "changes_made": False}


def test_attribution_bad_declared_date_errors():
    """attribution.declared_date is a date-kind field: a malformed date surfaces a per-field error."""
    form = {"s_attribution_declared_date": "soon", **_snap("attribution", {})}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "attribution")


def test_related_identifiers_acquisition_licence_and_profile_vocab_enforced():
    """The acquisition fields merged onto a related_identifiers row keep the fail-closed vocab
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
    """PARITY PIN: the editor's baked RELATION_TYPES / IDENTIFIER_TYPES / identifies vocab equal the surveys
    validator's frozen vocabularies (loaded from the VENDORED copy — the content-blind gateway cannot import
    the sibling at runtime, so the test pins it). FAILS IF a vocab is extended in the validator but not
    mirrored here — the exact drift the shared _check_typed_relation seam exists to prevent.

    The identifies pin is the load-bearing one for D-L: an editor level token that drifts from the
    validator would auto-derive a WRONG DataCite relation (or fail-close a level the validator accepts).
    Pins the level set, the IDENTIFIES_RELATION mapping byte-for-byte, and per-level derived_relation
    parity so the editor and validator can never disagree on what a level derives to."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_relvocab")
    assert set(ef.RELATION_TYPES) == set(vv.RELATION_TYPES), "editor RELATION_TYPES drifted from the validator"
    assert set(ef.IDENTIFIER_TYPES) == set(vv.IDENTIFIER_TYPES), "editor IDENTIFIER_TYPES drifted from the validator"
    # the identifies vocab (validator exports the membership set as IDENTIFIES_TYPES = frozenset(IDENTIFIES_LEVELS))
    assert set(ef.IDENTIFIES_LEVELS) == set(vv.IDENTIFIES_TYPES), "editor IDENTIFIES_LEVELS drifted from the validator"
    # the level -> DataCite relation mapping is identical byte-for-byte
    assert ef.IDENTIFIES_RELATION == vv.IDENTIFIES_RELATION, "editor IDENTIFIES_RELATION drifted from the validator"
    # and every level derives the SAME relation through both derived_relation implementations
    for lvl in ef.IDENTIFIES_LEVELS:
        assert ef.derived_relation(lvl) == vv.derived_relation(lvl), \
            f"editor/validator derived_relation disagree for identifies={lvl!r}"


def _load_credit_validator():
    """The surveys validator this pin compares against, resolved through conftest's ONE resolver so the
    credit vocab is read from the SAME arm as every other cross-repo oracle: the live sibling checkout on
    a dev box, the committed vendored copy in CI. Hand-rolling a candidate order here (vendored first)
    inverted the resolver and kept this pin off the live validator entirely. None when the resolved
    validator predates the credit vocab, which today means an old sibling checkout: the vendored copy is
    committed and carries it."""
    vv = _load_by_path(require_validator_dir() / "validate_survey.py", "_ausmt_creditvocab")
    if hasattr(vv, "NAME_TYPES") and hasattr(vv, "CONTRIBUTOR_ROLES"):
        return vv
    return None


def test_credit_vocab_matches_surveys_validator():
    """PARITY PIN (CONTRIBUTOR-CREDIT-SPEC §6): the editor's baked NAME_TYPES / CONTRIBUTOR_ROLES equal the
    surveys validator's FROZEN credit vocabularies, read from the arm conftest resolves. Skipped only when
    that validator predates the credit vocab - a stale sibling checkout, since the vendored copy carries
    it; that skip is deliberately NOT on gateway-ci's allow-list, so a CI run that lost the vocab reds the
    workflow instead of passing quietly. Where it runs it FAILS IF the editor vocab drifts from the validator vocab - a mis-typed name_type/role would mis-classify an actor or publish a wrong provenance
    claim, so the two must never disagree."""
    vv = _load_credit_validator()
    if vv is None:
        pytest.skip(f"the resolved validator {require_validator_dir()} predates the credit vocab")
    assert set(ef.NAME_TYPES) == set(vv.NAME_TYPES), "editor NAME_TYPES drifted from the validator"
    assert set(ef.CONTRIBUTOR_ROLES) == set(vv.CONTRIBUTOR_ROLES), \
        "editor CONTRIBUTOR_ROLES drifted from the validator"
    # the ordered tuple must match the validator's order too (creators/contributors selects
    # present the roles in the spec's §3.1 order).
    assert tuple(ef.CONTRIBUTOR_ROLES) == tuple(vv.CONTRIBUTOR_ROLES_ORDERED), \
        "editor CONTRIBUTOR_ROLES order drifted from the validator's ratified order"


def test_credit_vocab_pin_reads_the_resolved_validator_arm(monkeypatch):
    """The credit-vocab pin must read the SAME validator arm as every other cross-repo oracle in this
    suite, i.e. whatever conftest.resolve_validator_dir returns. FAILS IF this pin re-derives its own
    candidate order and prefers the vendored copy: that inversion shipped, so on every dev box the
    vocab was compared against a snapshot while the live sibling went unread. Both arms are
    asserted because they resolve to the same file in CI, where only the vendored copy exists."""
    for forced in (None, "1"):
        if forced is None:
            monkeypatch.delenv("AUSMT_FORCE_VENDORED_VALIDATOR", raising=False)
        else:
            monkeypatch.setenv("AUSMT_FORCE_VENDORED_VALIDATOR", forced)
        resolved = resolve_validator_dir()
        assert resolved is not None, "no validator resolved at all: a broken checkout, not a drift"
        expected = resolved / "validate_survey.py"
        vv = _load_credit_validator()
        assert vv is not None, f"the resolved validator {expected} carries no credit vocab"
        assert Path(vv.__file__) == expected, (
            f"credit-vocab pin read {vv.__file__} while the oracles resolve {expected}")


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
    """`identifies` is a fail-closed vocab (like relation/identifier_type) - an out-of-vocab level
    is a SectionError, because a mis-typed level auto-derives a WRONG relation and must block, not ship."""
    with pytest.raises(ef.SectionError):
        ef.assemble_section({"l_related_identifiers_0_identifier": "10.25914/x",
                             "l_related_identifiers_0_identifies": "level9",
                             **_snap("related_identifiers", [])}, "related_identifiers")
    # every level is accepted
    for lvl in ef.IDENTIFIES_LEVELS:
        out = ef.assemble_section({"l_related_identifiers_0_identifier": "10.25914/x",
                                   "l_related_identifiers_0_identifier_type": "DOI",
                                   "l_related_identifiers_0_identifies": lvl,
                                   **_snap("related_identifiers", [])}, "related_identifiers")
        assert out[0]["identifies"] == lvl


def test_relation_auto_derives_from_identifies_server_side():
    """When a row states `identifies`, the DataCite relation DERIVES from it server-side - the form
    carries NO explicit relation (the control is hidden on an identifies row), and the assembler writes the
    derived value. Every level maps to its relation. FAILS IF a level does not derive its relation."""
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
    """identifiers.instrument_pid (§2b, additive) assembles from its input and round-trips to
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


# ==================================================================================================
# The retired flat credit keys leave the editor, and the
# MTCAT 2.0 curated homes arrive - citation{}, organisations[], acknowledgements[] and the
# identity_classification designation mapping. Every vocab is pinned to the vendored surveys
# validator (the fail-closed parity discipline), and the key-parity pin feeds a fully assembled
# patch through the REAL validator so an editor key the validator does not recognise is caught
# cross-repo rather than by a hand-typed expectation.
# ==================================================================================================

def test_retired_flat_credit_keys_are_no_longer_editor_sections():
    """Lead_investigator and principal_investigators are GONE from the editor registries,
    and with them the legacy Convert surface (_LEGACY_CREDIT_KEYS / convert_requested /
    _apply_legacy_convert / DELETE_DIRECTIVE). FAILS IF any of them survives - a curator control that
    edits a key the migration deleted and the engine does not read."""
    assert "lead_investigator" not in ef.MAP_SECTIONS
    assert "principal_investigators" not in ef.LIST_SECTIONS
    for gone in ("_LEGACY_CREDIT_KEYS", "convert_requested", "_apply_legacy_convert",
                 "DELETE_DIRECTIVE"):
        assert not hasattr(ef, gone), f"{gone} survived the retirement"
    patch, errors = ef.build_section_patch({"people_convert": "lead_investigator",
                                            "people_legacy_lead_name": "Heinson, Graham"})
    assert patch == {} and errors == [], (patch, errors)


# ---- citation{} (interface contract section 3) ---------------------------------------------------

def test_citation_assembles_preferred_text_and_text_source():
    """citation{preferred_text, text_source} assembles from the flat s_citation_* inputs. FAILS IF the
    widget names are not read, or text_source is not vocab-checked."""
    form = {"s_citation_preferred_text": "GSSA (2016). AusLAMP South Australia.",
            "s_citation_text_source": "source_provided",
            **_snap("citation", {})}
    assert ef.assemble_section(form, "citation") == {
        "preferred_text": "GSSA (2016). AusLAMP South Australia.",
        "text_source": "source_provided"}


def test_citation_text_source_out_of_vocab_fails_closed():
    """text_source is a FAIL-CLOSED provenance claim at the validator, so an out-of-vocab POST is
    rejected at the form. FAILS IF a hand-crafted value is assembled."""
    form = {"s_citation_preferred_text": "X", "s_citation_text_source": "guessed",
            **_snap("citation", {})}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "citation")


def test_citation_text_source_without_preferred_text_fails_closed():
    """Text_source states where preferred_text came from, so it is meaningless without one.
    FAILS IF a bare text_source assembles (it would claim provenance for wording that is not there)."""
    form = {"s_citation_preferred_text": "", "s_citation_text_source": "source_provided",
            **_snap("citation", {})}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "citation")


def test_citation_preferred_identifier_assembles_as_a_nested_pair():
    """The editor writes citation.preferred_identifier ONLY as the NESTED
    {scheme, identifier} pair. FAILS IF flat scheme/identifier sub-keys land on citation (the
    validator WARNs them as unrecognised keys) or the pair is not nested."""
    form = {"s_citation_preferred_text": "GSSA (2016).",
            "s_citation_text_source": "source_provided",
            "s_citation_preferred_identifier_scheme": "DOI",
            "s_citation_preferred_identifier_identifier": "10.25914/abc",
            **_snap("citation", {})}
    out = ef.assemble_section(form, "citation")
    assert out["preferred_identifier"] == {"scheme": "DOI", "identifier": "10.25914/abc"}
    assert "scheme" not in out and "identifier" not in out


def test_citation_preferred_identifier_is_both_or_neither():
    """A half-declared pair cannot anchor the citation invariant, so the editor fail-closes on one
    half. FAILS IF a lone scheme (or a lone identifier) is assembled and shipped to the validator."""
    for half in ({"s_citation_preferred_identifier_scheme": "DOI",
                  "s_citation_preferred_identifier_identifier": ""},
                 {"s_citation_preferred_identifier_scheme": "",
                  "s_citation_preferred_identifier_identifier": "10.25914/abc"}):
        with pytest.raises(ef.SectionError):
            ef.assemble_section({**half, **_snap("citation", {})}, "citation")


def test_citation_preferred_identifier_both_empty_writes_no_key():
    """Both halves blank on a citation that never carried the pair writes NO key (never an empty
    mapping). FAILS IF an empty preferred_identifier is introduced."""
    form = {"s_citation_preferred_text": "GSSA (2016).",
            "s_citation_preferred_identifier_scheme": "",
            "s_citation_preferred_identifier_identifier": "",
            **_snap("citation", {})}
    assert ef.assemble_section(form, "citation") == {"preferred_text": "GSSA (2016)."}


def test_citation_additional_and_preferred_identifier_survive_a_preferred_text_edit():
    """CARRY-FORWARD (the load-bearing one, editor_form._assemble_map): additional[] is not modelled by
    any widget and preferred_identifier is not rendered by this form, so BOTH must ride the snapshot
    through an edit that only touches preferred_text. FAILS IF either is dropped - apply_patch's
    surgical map merge DELETES a sub-key the assembled map lacks."""
    stored = {"preferred_text": "Old wording", "text_source": "source_provided",
              "preferred_identifier": {"scheme": "DOI", "identifier": "10.25914/abc"},
              "additional": [{"identifier": {"scheme": "DOI", "identifier": "10.1/other"},
                              "reason": "derived_product"}]}
    form = {"s_citation_preferred_text": "New wording",
            "s_citation_text_source": "source_provided",
            **_snap("citation", stored)}   # NO s_citation_preferred_identifier_* keys rendered
    out = ef.assemble_section(form, "citation")
    assert out["preferred_text"] == "New wording"
    assert out["preferred_identifier"] == {"scheme": "DOI", "identifier": "10.25914/abc"}
    assert out["additional"] == stored["additional"]


def test_citation_unchanged_round_trips_to_omit():
    """An unchanged citation submit contributes nothing to the patch (no spurious diff)."""
    stored = {"preferred_text": "GSSA (2016).", "text_source": "source_provided",
              "preferred_identifier": {"scheme": "DOI", "identifier": "10.25914/abc"}}
    form = {"s_citation_preferred_text": "GSSA (2016).",
            "s_citation_text_source": "source_provided",
            "s_citation_preferred_identifier_scheme": "DOI",
            "s_citation_preferred_identifier_identifier": "10.25914/abc",
            **_snap("citation", stored)}
    assert ef.assemble_section(form, "citation") is ef._OMIT


# ---- organisations[] (survey scope section 3) ----------------------------------------------------

def test_organisations_row_assembles_roles_from_the_checkbox_group():
    """organisations[] rows carry roles[] assembled from the c_organisations_<i>_<role> checkbox group
    (:624 is scalar-only, so a plain list section cannot express this). FAILS IF roles is written as a
    scalar or the ticked boxes are not collected into a list."""
    form = {"l_organisations_0_name": "Geological Survey of South Australia",
            "l_organisations_0_ror": "https://ror.org/04y8k6r48",
            "c_organisations_0_custodian": "1",
            "c_organisations_0_publisher": "1",
            "c_organisations_primary": "0",
            **_snap("organisations", [])}
    out = ef.assemble_section(form, "organisations")
    assert out == [{"name": "Geological Survey of South Australia",
                    "ror": "https://ror.org/04y8k6r48",
                    "roles": ["publisher", "custodian"],
                    "primary_custodian": True}], out


def test_organisations_unknown_role_fails_closed():
    """An organisation role is a FAIL-CLOSED vocab at the validator (a mis-typed role publishes a wrong
    claim about who holds/publishes/collected the data), so a hand-crafted out-of-vocab checkbox is
    rejected at the form. FAILS IF the unknown token is silently dropped or assembled."""
    form = {"l_organisations_0_name": "Org", "c_organisations_0_owner": "1",
            **_snap("organisations", [])}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "organisations")


def test_organisations_primary_custodian_requires_a_custodian_row():
    """validate_survey.py: primary_custodian selects AMONG custodial rows, so the radio is refused on a
    row that does not tick custodian. FAILS IF the editor can assemble a primary non-custodian row."""
    form = {"l_organisations_0_name": "Org", "c_organisations_0_publisher": "1",
            "c_organisations_primary": "0", **_snap("organisations", [])}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "organisations")


def test_organisations_ror_is_omitted_when_blank_never_null():
    """The ror key is OMITTED when blank, never written as ror: null (schema 108-112). FAILS IF a blank
    ror lands as a null key - the exact shape the corpus migration is careful never to write."""
    form = {"l_organisations_0_name": "Org", "l_organisations_0_ror": "",
            "c_organisations_0_custodian": "1", **_snap("organisations", [])}
    assert ef.assemble_section(form, "organisations") == [
        {"name": "Org", "roles": ["custodian"]}]
    cleared = {"l_organisations_0_name": "Org", "l_organisations_0_ror": "",
               "c_organisations_0_custodian": "1",
               **_snap("organisations", [{"name": "Org", "ror": "https://ror.org/04y8k6r48",
                                          "roles": ["custodian"]}])}
    assert ef.assemble_section(cleared, "organisations") == [
        {"name": "Org", "roles": ["custodian"]}]


def test_organisations_unchanged_round_trips_to_omit_and_keeps_role_order():
    """An unchanged organisations submit contributes nothing to the patch, INCLUDING when the stored
    row lists its roles in a non-canonical order (the assembler preserves the stored order for roles
    still ticked). FAILS IF re-canonicalising the order manufactures a diff on an untouched row."""
    stored = [{"name": "GSSA", "roles": ["custodian", "publisher"], "primary_custodian": True}]
    form = {"l_organisations_0_name": "GSSA", "l_organisations_0_ror": "",
            "c_organisations_0_custodian": "1", "c_organisations_0_publisher": "1",
            "c_organisations_primary": "0", **_snap("organisations", stored)}
    assert ef.assemble_section(form, "organisations") is ef._OMIT


def test_organisations_primary_flag_cleared_removes_the_key():
    """Unselecting the primary radio REMOVES primary_custodian from the row (never primary_custodian:
    false). FAILS IF the flag is written false, which the validator reads as 'not primary' but the
    corpus never carries."""
    stored = [{"name": "GSSA", "roles": ["custodian"], "primary_custodian": True}]
    form = {"l_organisations_0_name": "GSSA", "l_organisations_0_ror": "",
            "c_organisations_0_custodian": "1", **_snap("organisations", stored)}
    assert ef.assemble_section(form, "organisations") == [
        {"name": "GSSA", "roles": ["custodian"]}]


# ---- acknowledgements[] (interface contract section 3: plural, verbatim) -------------------------

def test_acknowledgements_rows_assemble_with_optional_keys_omitted():
    """acknowledgements[] rows {text, type?, source?}: the optional keys are written back only when
    filled or already present. FAILS IF a text-only row gains null type/source keys (round-trip noise
    on a block whose whole payload is verbatim wording)."""
    form = {"l_acknowledgements_0_text": "Data supplied by GSSA under licence.",
            "l_acknowledgements_0_type": "", "l_acknowledgements_0_source": "",
            **_snap("acknowledgements", [])}
    assert ef.assemble_section(form, "acknowledgements") == [
        {"text": "Data supplied by GSSA under licence."}]


def test_acknowledgements_type_vocab_is_warn_only_not_fail_closed():
    """The acknowledgement type vocabulary is the contract's CANDIDATE list, validated against real
    holdings before freeze, so the validator WARNs rather than blocks. The editor MIRRORS that posture:
    a stored out-of-vocab type must round-trip rather than lock the curator out of the section. FAILS
    IF the editor fail-closes on a vocab the validator itself only warns about."""
    form = {"l_acknowledgements_0_text": "Wording", "l_acknowledgements_0_type": "legacy_type",
            **_snap("acknowledgements", [])}
    assert ef.assemble_section(form, "acknowledgements") == [
        {"text": "Wording", "type": "legacy_type"}]


# ---- identity_classification (survey-metadata workflow D12; the designation home) --------------------

def test_identity_classification_assembles_case_and_represents_rows():
    """The designation mapping {case, represents[] | own_identifiers[]} assembles from the case select
    plus its pair rows. FAILS IF the rows are not read (the citation chain then has nothing to
    match) or the retired scalar-string form is emitted."""
    form = {"s_identity_classification_case": "case_a",
            "l_identity_classification_represents_0_scheme": "DOI",
            "l_identity_classification_represents_0_identifier": "10.25914/abc",
            "l_identity_classification_represents_1_scheme": "",
            "l_identity_classification_represents_1_identifier": "",
            **_snap("identity_classification", {})}
    assert ef.assemble_section(form, "identity_classification") == {
        "case": "case_a",
        "represents": [{"scheme": "DOI", "identifier": "10.25914/abc"}]}


def test_identity_classification_case_out_of_vocab_fails_closed():
    form = {"s_identity_classification_case": "case_c",
            **_snap("identity_classification", {})}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "identity_classification")


def test_identity_classification_half_pair_row_fails_closed():
    """A designated identifier is a COMPLETE {scheme, identifier} pair; half a row cannot anchor the
    chain. FAILS IF a half row is assembled and left for the validator to reject at merge."""
    form = {"s_identity_classification_case": "case_a",
            "l_identity_classification_represents_0_scheme": "DOI",
            "l_identity_classification_represents_0_identifier": "",
            **_snap("identity_classification", {})}
    with pytest.raises(ef.SectionError):
        ef.assemble_section(form, "identity_classification")


def test_identity_classification_absent_rows_preserve_the_stored_designation():
    """ABSENT-vs-EMPTY (the coordinate_overrides precedent, editor_form._resolve_coordinate_overrides):
    a form that does NOT render the pair rows must PRESERVE the stored designation; a form that renders
    them empty DELETES it. FAILS IF an unrelated case edit silently un-designates the survey's
    identifiers (which would turn citation.preferred_identifier into a validator FAIL)."""
    stored = {"case": "case_a", "represents": [{"scheme": "DOI", "identifier": "10.25914/abc"}]}
    absent = {"s_identity_classification_case": "case_b",
              **_snap("identity_classification", stored)}
    assert ef.assemble_section(absent, "identity_classification") == {
        "case": "case_b", "represents": [{"scheme": "DOI", "identifier": "10.25914/abc"}]}
    emptied = {"s_identity_classification_case": "case_a",
               "l_identity_classification_represents_0_scheme": "",
               "l_identity_classification_represents_0_identifier": "",
               **_snap("identity_classification", stored)}
    assert ef.assemble_section(emptied, "identity_classification") == {"case": "case_a"}


# ---- vocab parity pins against the vendored surveys validator ------------------------------------

def test_mtcat20_vocabs_match_the_vendored_validator():
    """PARITY PIN: the editor's baked ORG_ROLES_ORDERED / ACKNOWLEDGEMENT_TYPES /
    CITATION_TEXT_SOURCES / IDENTITY_CLASSIFICATIONS equal the surveys validator's FROZEN
    vocabularies, and the modelled section keys equal its row allow-lists. FAILS IF a vocab or key set
    is extended surveys-side and not mirrored here - the drift that publishes an unrecognised key or
    fail-closes a value the validator accepts."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_mtcat20vocab")
    assert set(ef.ORG_ROLES_ORDERED) == set(vv.ORG_ROLES), "editor ORG_ROLES drifted"
    assert tuple(ef.ORG_ROLES_ORDERED) == tuple(vv.ORG_ROLES_ORDERED), "editor ORG_ROLES order drifted"
    assert set(ef.ACKNOWLEDGEMENT_TYPES) == set(vv.ACKNOWLEDGEMENT_TYPES), \
        "editor ACKNOWLEDGEMENT_TYPES drifted"
    assert set(ef.CITATION_TEXT_SOURCES) == set(vv.CITATION_TEXT_SOURCES), \
        "editor CITATION_TEXT_SOURCES drifted"
    assert tuple(ef.IDENTITY_CLASSIFICATIONS) == tuple(vv.IDENTITY_CLASSIFICATIONS), \
        "editor IDENTITY_CLASSIFICATIONS drifted"
    # the modelled row/section key sets equal the validator's allow-lists
    assert {sk for sk, *_ in ef.LIST_SECTIONS["organisations"]} == set(vv.ORGANISATION_ROW_KEYS)
    assert {sk for sk, *_ in ef.LIST_SECTIONS["acknowledgements"]} == set(vv.ACKNOWLEDGEMENT_KEYS)
    assert {sk for sk, *_ in ef.MAP_SECTIONS["citation"]} | {"preferred_identifier", "additional"} \
        == set(vv.CITATION_KEYS)
    assert {sk for sk, *_ in ef.MAP_SECTIONS["identity_classification"]} \
        | {"represents", "own_identifiers"} == set(vv.IDENTITY_CLASSIFICATION_KEYS)


_MTCAT20_FORM = {
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
    "l_organisations_1_name": "Geoscience Australia",
    "l_organisations_1_ror": "",
    "c_organisations_1_publisher": "1",
    "l_acknowledgements_0_text": "Data supplied by the Geological Survey of South Australia.",
    "l_acknowledgements_0_type": "custodian",
    "l_acknowledgements_0_source": "GSSA licence deed",
    "l_related_identifiers_0_identifies": "entire",
    "l_related_identifiers_0_identifier": "10.25914/abc",
    "l_related_identifiers_0_identifier_type": "DOI",
}


def test_key_parity_mtcat20_patch_through_real_validator(tmp_path):
    """KEY-PARITY PIN (the important one): an editor-assembled citation + identity_classification +
    organisations + acknowledgements patch, written to a survey.yaml and read back by the REAL vendored
    surveys validator, produces ZERO unknown-key warnings AND ZERO FAILs - the editor's frozen section
    keys equal the validator's allow-lists and the assembled citation chain is internally consistent.
    MUTATION-PROOF below."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_mtcat20")
    patch, errors = ef.build_section_patch(_MTCAT20_FORM)
    assert not errors, errors
    assert {"citation", "identity_classification", "organisations",
            "acknowledgements"} <= set(patch), sorted(patch)
    folder = tmp_path / "paritytest"          # the validator pins folder name == slug
    _write_survey(folder, _survey_meta_with(patch))
    rep = vv.validate(folder)
    checks = ("citation", "identity_classification", "organisations", "acknowledgements")
    unknown = [i for i in rep.items if i["check"] in checks and "not a recognised" in i["message"]]
    assert not unknown, f"editor keys the validator does not recognise: {unknown}"
    # No WARNING or FAIL at all on the four curated homes (the assembled citation chain is consistent).
    noisy = [i for i in rep.items if i["check"] in checks and i["level"] in ("WARNING", "FAIL")]
    assert not noisy, noisy


def test_key_parity_mtcat20_mutation_proof(tmp_path):
    """NON-VACUOUS proof: dropping the designation (identity_classification) makes the REAL validator
    FAIL the assembled citation.preferred_identifier - the D20 citation-chain rule this module relies on
    to refuse an inconsistent curator save. FAILS IF the validator would accept an undesignated
    preferred_identifier (which would make the parity pin above vacuous)."""
    vv = _load_by_path(_VENDORED_VALIDATOR_PY, "_ausmt_vendored_mtcat20_mut")
    patch, _ = ef.build_section_patch(_MTCAT20_FORM)
    patch.pop("identity_classification")
    folder = tmp_path / "paritytest"
    _write_survey(folder, _survey_meta_with(patch))
    rep = vv.validate(folder)
    assert any(i["check"] == "citation" and i["level"] == "FAIL"
               and "designated identifier" in i["message"] for i in rep.items), \
        "validator did not FAIL an undesignated preferred_identifier - the parity pin would be vacuous"


def test_gateway_carries_no_retired_credit_key_outside_tests():
    """GREP PIN: no retired flat credit key is read anywhere in the gateway package outside the
    test tree and the vendored validator copy. The legitimate needles are the PII fixture in
    test_intake_files.py and the round-trip fixture in test_edit_runner.py, both under tests/.
    FAILS IF a reader, a registry entry or a rendered control survives the retirement."""
    gateway_dir = Path(__file__).resolve().parents[1]
    offenders = []
    for path in sorted(gateway_dir.rglob("*.py")):
        rel = path.relative_to(gateway_dir)
        if rel.parts and rel.parts[0] == "tests":
            continue
        text = path.read_text(encoding="utf-8")
        if "lead_investigator" in text or "principal_investigators" in text:
            offenders.append(str(rel))
    assert not offenders, f"retired credit keys still referenced: {offenders}"


# ---- G1 (section-3 review): the CARE panel must reach the patch ---------------------------------

def test_care_json_edit_reaches_the_patch():
    """The CARE governance panel renders as j_care on both editing surfaces under 'leave blank to
    leave unchanged' - so a non-blank j_care MUST become a care patch. FAILS IF build_section_patch
    never reads j_care (earlier: 'care' was in neither MAP_SECTIONS nor LIST_SECTIONS, so a
    curator's Indigenous data-governance edit was silently discarded with no diff and no error)."""
    edited = {"traditional_owner_acknowledgement": "NEW WORDING",
              "land_access": {"permission_obtained": True},
              "restrictions_requested": True}
    form = {"j_care": json.dumps(edited),
            **_snap("care", {"traditional_owner_acknowledgement": "OLD"})}
    patch, errors = ef.build_section_patch(form)
    assert errors == []
    assert patch.get("care") == edited


def test_care_untouched_submit_contributes_nothing():
    """The panel PREFILLS j_care with the stored value, so an untouched submit posts JSON equal to
    the o_care snapshot and must round-trip to no patch (the byte-clean discipline every widget
    section follows). FAILS IF an untouched save rewrites the care block."""
    stored = {"traditional_owner_acknowledgement": "OLD", "restrictions_requested": False}
    form = {"j_care": json.dumps(stored), **_snap("care", stored)}
    patch, errors = ef.build_section_patch(form)
    assert errors == [] and "care" not in patch


def test_care_blank_leaves_unchanged_and_bad_json_refuses():
    """Blank j_care means unchanged (the panel's own copy); malformed JSON is a SectionError that
    refuses the save rather than guessing. FAILS IF blank invents a patch or bad JSON passes."""
    patch, errors = ef.build_section_patch({"j_care": "", **_snap("care", {"x": 1})})
    assert errors == [] and "care" not in patch
    patch, errors = ef.build_section_patch({"j_care": "{not json", **_snap("care", {"x": 1})})
    assert any(e.section == "care" for e in errors) and "care" not in patch
