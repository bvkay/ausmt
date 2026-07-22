"""§2a (identifiers design — the related-identifiers model) FOLLOWUP, end-to-end (the reviewer's exact
drop path): a sources[] entry that carries the typed keys (relation / identifier_type) must SURVIVE an
edit to an UNRELATED section.

The sources[] widget row models a fixed set of sub-fields (editor_form.LIST_SECTIONS["sources"]); the
render prefills each existing row with ONLY those sub-keys (curatorpage._list_section_panel:
`{sk: item.get(sk) for sk, *_ in subfields}`), and the assembler (_assemble_list) reads back ONLY those
same sub-keys. So when the sources[] row does NOT model relation/identifier_type, a stored entry carrying
them re-assembles WITHOUT them; because the truncated value differs from the o_sources round-trip anchor,
assemble_section emits the truncated list into the patch, and apply_patch (LISTs replace wholesale) writes
it over the stored list — the typed keys are dropped on disk.

This test builds the sources form fields the way the render does — straight from the REAL
LIST_SECTIONS["sources"] subfields — so it is RED before the fix (the two keys are not modelled, so the
simulated POST lacks them and they drop) and GREEN after (they are modelled, prefilled, and round-trip).

ruamel.yaml is a runner (engine-image) dependency; this test runs wherever ruamel is installed (CI runner
job + dev). Skipped otherwise, exactly like the sibling end-to-end pins in test_edit_runner.py."""
from __future__ import annotations

import json

import pytest

ruamel = pytest.importorskip("ruamel.yaml")

from gateway import editor_form
from gateway.runner import edit


# A stored survey whose sources[] entry carries the typed keys (the vulcan-2022 demo shape: a DOI-typed
# IsDerivedFrom relation to an NCI-custodied upstream dataset), alongside an unrelated `processing`
# section the curator is about to edit.
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


def _sources_row_fields(stored: list) -> dict:
    """Simulate what the render POSTs for the sources[] rows: for each stored entry, one
    l_sources_<i>_<subkey> field per MODELLED sub-key, prefilled from the stored value — exactly
    curatorpage._list_section_panel's `{sk: item.get(sk) for sk, *_ in subfields}` prefill. Using the
    REAL LIST_SECTIONS subfields is the crux: an unmodelled key is simply never posted (its drop is what
    the fix closes), so this helper needs no edit when the fix lands."""
    subfields = editor_form.LIST_SECTIONS["sources"]
    form: dict = {}
    for i, item in enumerate(stored):
        for subkey, *_ in subfields:
            val = item.get(subkey)
            form[f"l_sources_{i}_{subkey}"] = "" if val is None else str(val)
    return form


def test_sources_typed_keys_survive_unrelated_edit_end_to_end():
    """RED before the fix (relation/identifier_type not modelled -> dropped on the round-trip), GREEN
    after. Assemble the patch a curator posts when editing ONLY processing.notes (the sources[] rows ride
    along, prefilled from the stored entry), apply it to a REAL ruamel round-trip doc, and assert the
    emitted YAML still carries the typed keys. FAILS IF an unrelated edit drops sources[].relation /
    .identifier_type."""
    form = {
        # the unrelated edit: processing.notes changes (its o_ anchor + the four modelled scalars)
        "o_processing": json.dumps({"software": "BIRRP", "notes": "original note"}),
        "s_processing_software": "BIRRP", "s_processing_version": "",
        "s_processing_remote_reference": "", "s_processing_notes": "revised note",
        # the sources[] round-trip anchor (carries the typed keys) + the rendered rows
        "o_sources": json.dumps(_STORED_SOURCES),
        **_sources_row_fields(_STORED_SOURCES),
    }
    patch, errors = editor_form.build_section_patch(form)
    assert not errors, errors

    data = edit._load_bytes(_SURVEY_YAML.encode("utf-8"))
    edit.apply_patch(data, patch)
    out_yaml = edit._dump_bytes(data).decode("utf-8")

    # the unrelated edit landed
    assert data["processing"]["notes"] == "revised note"
    # the typed provenance keys survived, in the emitted YAML and in the doc
    assert "identifier_type: DOI" in out_yaml, \
        "an unrelated edit dropped sources[].identifier_type in the emitted YAML:\n" + out_yaml
    assert "relation: IsDerivedFrom" in out_yaml, \
        "an unrelated edit dropped sources[].relation in the emitted YAML:\n" + out_yaml
    assert data["sources"][0]["identifier_type"] == "DOI"
    assert data["sources"][0]["relation"] == "IsDerivedFrom"


def test_unchanged_sources_with_typed_keys_round_trips_to_omit():
    """The tighter invariant: a submit that changes NOTHING in a FULLY-modelled sources[] entry (every
    sub-key populated, typed keys included) must reassemble to the original snapshot and contribute
    NOTHING to the patch — otherwise the value leaks into every edit. A full entry is used because
    _assemble_list normalises every modelled sub-key to None (a pre-existing list-section trait), so only
    a fully-populated entry is a true no-op. FAILS (pre-fix) because the reassembled row lacks
    relation/identifier_type, so value != o_sources -> the section is emitted."""
    full = [{"title": "AusLAMP SA — NCI/AuScope archive", "custodian": "NCI",
             "identifier": "10.25914/sv5r-zw68", "identifier_type": "DOI", "relation": "IsDerivedFrom",
             "licence": "CC-BY-4.0", "retrieved": "2022", "statement": "Sourced from the NCI archive.",
             "profile": "generic"}]
    form = {"o_sources": json.dumps(full), **_sources_row_fields(full)}
    assert editor_form.assemble_section(form, "sources") is editor_form._OMIT


def test_sources_relation_is_fail_closed_on_out_of_vocab_post():
    """Byte-identical posture to the related_identifiers section: an out-of-vocab relation on a sources[]
    row is a SectionError (a hand-crafted POST cannot ship a mis-typed provenance claim). FAILS IF the
    sources[] relation is not wired through the fail-closed select plumbing."""
    form = {"l_sources_0_identifier": "10.1/x", "l_sources_0_relation": "NotARelation"}
    with pytest.raises(editor_form.SectionError):
        editor_form.assemble_section(form, "sources")
