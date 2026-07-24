"""D-L3 (identifiers-by-level, SPEC §9.3): the "Source datasets" (sources) section is RETIRED from the
editor UI. Its acquisition fields (title / licence-as-obtained / retrieved / attribution statement /
attribution profile) are now OPTIONAL keys on a related_identifiers row (identifies: entire); the standalone
sources widget is GONE.

The schema key stays READABLE — the engine keeps reading sources[] until the ausmt follow-up (§9.3 note) —
so a survey that still carries a sources[] list must not have it silently dropped the next time a curator
saves an unrelated change. Because sources is no longer a widget section, build_section_patch never
assembles it, so it is never entered into ANY patch and apply_patch touches nothing: byte-preserved on disk.

This mirrors test_editor_retired_identifiers_roundtrip.py. The two unit assertions are RED before the fix
(sources modelled -> assembled -> in the patch -> wholesale-replaced); the end-to-end half applies through a
REAL ruamel round-trip doc and runs wherever ruamel is installed (CI runner job + dev), skipped otherwise.
"""
from __future__ import annotations

import json

import pytest

from gateway import editor_form as ef


def test_sources_is_not_a_widget_section_anymore():
    """The retirement itself: sources is gone from the editor's modelled sections, so nothing the editor
    assembles can carry it into a patch. FAILS RED if the sources widget is still registered."""
    assert "sources" not in ef.LIST_SECTIONS
    assert "sources" not in ef.MAP_SECTIONS
    assert "sources" not in ef.WIDGET_SECTIONS


def test_a_full_form_never_emits_a_sources_key():
    """A build_section_patch over a form that (hostilely or by stale JS) carries l_sources_* inputs never
    produces a sources key — the section is unmodelled, so its inputs are ignored. FAILS RED if a stray
    sources input could still drive the retired surface."""
    form = {"l_sources_0_title": "AusLAMP SA archive", "l_sources_0_identifier": "10.25914/sv5r-zw68",
            "l_sources_0_licence": "CC-BY-4.0"}
    patch, errors = ef.build_section_patch(form)
    assert not errors, errors
    assert "sources" not in patch


# A stored survey with a sources[] list the engine still reads, alongside an unrelated processing section
# the curator is about to edit. The sources[] entry carries the full acquisition payload.
_STORED_SOURCES = [{"title": "AusLAMP SA — NCI/AuScope archive", "custodian": "NCI",
                    "identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI",
                    "relation": "IsDerivedFrom", "licence": "CC-BY-4.0", "retrieved": "2022"}]
_SURVEY_YAML = (
    "name: Demo survey\nversion: 1.0.0\n"
    "processing:\n  software: BIRRP\n  notes: original note\n"
    "sources:\n"
    "  - title: AusLAMP SA — NCI/AuScope archive\n    custodian: NCI\n"
    "    identifier: 10.25914/sv5r-zw68\n    identifier_type: DOI\n"
    "    relation: IsDerivedFrom\n    licence: CC-BY-4.0\n    retrieved: '2022'\n"
)


def test_related_identifiers_acquisition_fields_round_trip():
    """The MERGED home: an acquisition-bearing related_identifiers row (identifies: entire) round-trips to
    _OMIT when unchanged — the acquisition keys are modelled + prefilled + read back. FAILS RED if the
    merged fields drop on the round-trip (the pre-merge sources[] failure mode, now on the typed row)."""
    full = [{"identifier": "10.25914/sv5r-zw68", "identifies": "entire", "identifier_type": "DOI",
             "relation": "IsVariantFormOf", "custodian": "NCI", "title": "AusLAMP SA — NCI/AuScope archive",
             "licence": "CC-BY-4.0", "retrieved": "2022", "statement": "Sourced from the NCI archive.",
             "profile": "generic"}]
    form: dict = {"o_related_identifiers": json.dumps(full)}
    for subkey, *_ in ef.LIST_SECTIONS["related_identifiers"]:
        val = full[0].get(subkey)
        form[f"l_related_identifiers_0_{subkey}"] = "" if val is None else str(val)
    assert ef.assemble_section(form, "related_identifiers") is ef._OMIT


ruamel = pytest.importorskip("ruamel.yaml")

from gateway.runner import edit  # noqa: E402  (only importable where ruamel is installed)


def test_retired_sources_section_survives_unrelated_edit_end_to_end():
    """RED before the retirement, GREEN after. A curator edits ONLY processing.notes; sources[] is not a
    widget so it never enters the patch. Apply the assembled patch to a REAL ruamel round-trip doc and
    assert sources[] SURVIVES byte-for-byte in the emitted YAML. FAILS IF an unrelated edit blanks a stored
    sources[] the engine still reads."""
    form = {
        "o_processing": json.dumps({"software": "BIRRP", "notes": "original note"}),
        "s_processing_software": "BIRRP", "s_processing_version": "",
        "s_processing_remote_reference": "", "s_processing_notes": "revised note",
    }
    patch, errors = ef.build_section_patch(form)
    assert not errors, errors
    assert "sources" not in patch, patch

    data = edit._load_bytes(_SURVEY_YAML.encode("utf-8"))
    edit.apply_patch(data, patch)
    out_yaml = edit._dump_bytes(data).decode("utf-8")

    assert data["processing"]["notes"] == "revised note"
    # the sources[] list is byte-identical to the source (never re-quoted, reordered, or blanked)
    assert "identifier: 10.25914/sv5r-zw68" in out_yaml, out_yaml
    assert "licence: CC-BY-4.0" in out_yaml, out_yaml
    assert data["sources"][0]["identifier"] == "10.25914/sv5r-zw68"
    assert data["sources"][0]["licence"] == "CC-BY-4.0"
