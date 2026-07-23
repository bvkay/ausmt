"""IDCONS D2 (identifier-consolidation, SPEC §3) — the retired flat identifier keys must SURVIVE an edit
to an UNRELATED section, byte-preserved on disk.

dataset_doi, time_series.collection_pid, and instruments[].pid are RETIRED from the editor UI (their
input widgets are gone from editor_form.MAP_SECTIONS / LIST_SECTIONS) but the schema keys stay READABLE —
the engine keeps its flat-key fallback reads until the corpus migration lands (SPEC §3/§6). So a survey
that still carries an un-migrated dataset_doi (or collection_pid, or per-row instrument pid) must not have
it silently dropped the next time a curator saves an unrelated change. The fix is the unmodelled-key
carry-forward in editor_form._assemble_map / _assemble_list: a key the widget no longer models is re-
emitted verbatim, so the assembled section still equals its o_<section> round-trip anchor (-> _OMIT) and
the section never enters the patch, leaving apply_patch to touch nothing.

This mirrors test_editor_sources_typed_roundtrip.py — it builds the form fields the way the render does,
straight from the REAL (post-retirement) MAP_SECTIONS / LIST_SECTIONS subfields, so it is RED before the
carry-forward (the retired keys are unmodelled -> never posted -> the truncated section overwrites the
stored one) and GREEN after. The end-to-end half applies through a REAL ruamel round-trip doc; it runs
wherever ruamel is installed (CI runner job + dev), skipped otherwise like the sibling end-to-end pins.
"""
from __future__ import annotations

import json

import pytest

from gateway import editor_form as ef


def _map_fields(section: str, stored: dict) -> dict:
    """Simulate what the render POSTs for a MAP section: one s_<section>_<subkey> field per MODELLED
    sub-key, prefilled from the stored value (curatorpage._sub_value). A retired (unmodelled) key is
    simply never posted — its survival is exactly what the carry-forward closes."""
    form: dict = {}
    for subkey, _label, _ph, _kind in ef.MAP_SECTIONS[section]:
        val = stored.get(subkey)
        form[f"s_{section}_{subkey}"] = "" if val is None else str(val)
    return form


def _list_row_fields(section: str, stored: list) -> dict:
    """Simulate the render's per-row POST for a LIST section: l_<section>_<i>_<subkey> for each MODELLED
    sub-key, prefilled from the stored row (curatorpage._list_section_panel)."""
    form: dict = {}
    for i, item in enumerate(stored):
        for subkey, *_ in ef.LIST_SECTIONS[section]:
            val = item.get(subkey)
            form[f"l_{section}_{i}_{subkey}"] = "" if val is None else str(val)
    return form


# A stored identifiers block that carries BOTH the retired dataset_doi AND the still-modelled project_raid
# + instrument_pid — the exact un-migrated shape the corpus holds until the migration script runs.
_STORED_IDENTIFIERS = {"dataset_doi": "10.25914/bzd5-n780", "project_raid": "https://raid.org/10.1/AB1",
                       "instrument_pid": "10.82388/plat-1"}
_STORED_TIME_SERIES = {"collection_pid": "10.25914/bzd5-n780", "levels_available": ["raw_packed", "level1"]}
_STORED_INSTRUMENTS = [{"manufacturer": "Phoenix", "model": "MTU-5C", "pid": "10.25914/inst-1"}]


def test_retired_dataset_doi_unchanged_section_round_trips_to_omit():
    """An identifiers section submitted UNCHANGED (project_raid + instrument_pid ride along; dataset_doi is
    retired so never posted) must reassemble to the snapshot and contribute NOTHING to the patch. RED before
    the carry-forward (the truncated {project_raid, instrument_pid} != the stored 3-key dict -> emitted)."""
    form = {**_map_fields("identifiers", _STORED_IDENTIFIERS),
            "o_identifiers": json.dumps(_STORED_IDENTIFIERS)}
    assert ef.assemble_section(form, "identifiers") is ef._OMIT


def test_retired_collection_pid_and_instrument_pid_round_trip_to_omit():
    """The same invariant for time_series.collection_pid and instruments[].pid — an unchanged submit of
    each retired-key-bearing section drops from the patch."""
    ts = {**_list_and_levels("time_series", _STORED_TIME_SERIES),
          "o_time_series": json.dumps(_STORED_TIME_SERIES)}
    assert ef.assemble_section(ts, "time_series") is ef._OMIT
    inst = {**_list_row_fields("instruments", _STORED_INSTRUMENTS),
            "o_instruments": json.dumps(_STORED_INSTRUMENTS)}
    assert ef.assemble_section(inst, "instruments") is ef._OMIT


def _list_and_levels(section: str, stored: dict) -> dict:
    """time_series map fields incl. the levels checkboxes the render posts for a stored levels list."""
    form = _map_fields(section, stored)
    for lv in stored.get("levels_available", []):
        form[f"c_{section}_levels_available_{lv}"] = "1"
    return form


def test_retired_keys_are_not_editable_from_their_stray_inputs():
    """Defence in depth: even if a hostile POST carries the retired inputs, they are IGNORED (unmodelled),
    and the stored values still round-trip from the snapshot — the retired surface cannot be driven."""
    form = {**_map_fields("identifiers", _STORED_IDENTIFIERS),
            "s_identifiers_dataset_doi": "10.9999/attacker",   # retired -> ignored
            "o_identifiers": json.dumps(_STORED_IDENTIFIERS)}
    assert ef.assemble_section(form, "identifiers") is ef._OMIT


ruamel = pytest.importorskip("ruamel.yaml")

from gateway.runner import edit  # noqa: E402  (only importable where ruamel is installed)


_SURVEY_YAML = (
    "name: Demo survey\nversion: 1.0.0\n"
    "processing:\n  software: BIRRP\n  notes: original note\n"
    "identifiers:\n"
    "  dataset_doi: 10.25914/bzd5-n780\n"
    "  project_raid: https://raid.org/10.1/AB1\n"
    "  instrument_pid: 10.82388/plat-1\n"
    "time_series:\n"
    "  collection_pid: 10.25914/bzd5-n780\n"
    "  levels_available:\n    - raw_packed\n    - level1\n"
    "instruments:\n"
    "  - manufacturer: Phoenix\n    model: MTU-5C\n    pid: 10.25914/inst-1\n"
)


def test_retired_identifier_keys_survive_unrelated_edit_end_to_end():
    """RED before the carry-forward, GREEN after. A curator edits ONLY processing.notes; the identifiers /
    time_series / instruments sections ride along prefilled from the REAL (retirement-trimmed) widgets.
    Apply the assembled patch to a REAL ruamel round-trip doc and assert every retired flat key SURVIVES,
    byte-for-byte, in the emitted YAML. FAILS IF an unrelated edit blanks an un-migrated dataset_doi /
    collection_pid / instruments[].pid."""
    form = {
        # the unrelated edit
        "o_processing": json.dumps({"software": "BIRRP", "notes": "original note"}),
        "s_processing_software": "BIRRP", "s_processing_version": "",
        "s_processing_remote_reference": "", "s_processing_notes": "revised note",
        # the retired-key-bearing sections ride along, prefilled from the real widgets
        **_map_fields("identifiers", _STORED_IDENTIFIERS),
        "o_identifiers": json.dumps(_STORED_IDENTIFIERS),
        **_list_and_levels("time_series", _STORED_TIME_SERIES),
        "o_time_series": json.dumps(_STORED_TIME_SERIES),
        **_list_row_fields("instruments", _STORED_INSTRUMENTS),
        "o_instruments": json.dumps(_STORED_INSTRUMENTS),
    }
    patch, errors = ef.build_section_patch(form)
    assert not errors, errors
    # the retired-key sections must NOT be in the patch at all (they round-tripped to _OMIT)
    assert "identifiers" not in patch, patch
    assert "time_series" not in patch, patch
    assert "instruments" not in patch, patch

    data = edit._load_bytes(_SURVEY_YAML.encode("utf-8"))
    edit.apply_patch(data, patch)
    out_yaml = edit._dump_bytes(data).decode("utf-8")

    assert data["processing"]["notes"] == "revised note"
    assert "dataset_doi: 10.25914/bzd5-n780" in out_yaml, out_yaml
    assert "collection_pid: 10.25914/bzd5-n780" in out_yaml, out_yaml
    assert "pid: 10.25914/inst-1" in out_yaml, out_yaml
    # the retired keys are byte-identical to the source (no re-quoting / reordering)
    assert data["identifiers"]["dataset_doi"] == "10.25914/bzd5-n780"
    assert data["time_series"]["collection_pid"] == "10.25914/bzd5-n780"
    assert data["instruments"][0]["pid"] == "10.25914/inst-1"


def test_unknown_legacy_key_in_modelled_section_survives_unrelated_edit():
    """The generalisation the carry-forward buys: an UNKNOWN key the editor never modelled (here a made-up
    identifiers.legacy_ref) also survives an unrelated edit, rather than being dropped by the wholesale
    map merge. FAILS IF the assembler only preserves the specifically-retired keys."""
    stored = {**_STORED_IDENTIFIERS, "legacy_ref": "ARC-LP-2019"}
    form = {**_map_fields("identifiers", stored), "o_identifiers": json.dumps(stored)}
    assert ef.assemble_section(form, "identifiers") is ef._OMIT
