"""Guard the cross-platform build: when PyYAML is absent (e.g. a fresh Windows/conda env), the build
falls back to the stdlib ``_mini_yaml`` parser. This test asserts that parser yields the SAME survey
metadata projection as PyYAML on the structured ``survey.yaml`` schema — so a no-PyYAML build produces
the same portal data as a PyYAML build. Skips when PyYAML is not installed (nothing to compare to)."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from extract import build_portal as bp   # noqa: E402
from _fixtures import EXAMPLE_SURVEY      # noqa: E402


def _survey_yaml_text():
    return (EXAMPLE_SURVEY / "survey.yaml").read_text(encoding="utf-8")


def test_mini_yaml_matches_pyyaml_on_survey_schema():
    yaml = pytest.importorskip("yaml")
    text = _survey_yaml_text()
    smeta_pyyaml = bp.survey_meta_from_yaml(yaml.safe_load(text) or {})
    smeta_mini = bp.survey_meta_from_yaml(bp._mini_yaml(text))
    assert smeta_mini == smeta_pyyaml


def test_mini_yaml_parses_structured_lists():
    """Directly exercise the fallback on the schema's list shapes (no PyYAML needed)."""
    parsed = bp._mini_yaml(_survey_yaml_text())
    assert isinstance(parsed.get("data_types"), list)            # block sequence of scalars
    assert parsed.get("funding") == []                            # inline empty list, NOT the string "[]"
    instruments = parsed.get("instruments")
    assert isinstance(instruments, list) and instruments and isinstance(instruments[0], dict)
    assert instruments[0].get("manufacturer") == "Phoenix"        # block sequence of maps
    org = parsed.get("organisation")
    assert isinstance(org, dict) and org.get("name")              # nested map


def test_mini_yaml_matches_pyyaml_on_pid_chain_fields():
    """The mini-yaml fallback must agree with PyYAML on organisation.ror,
    identifiers.project_raid and time_series.collection_pid too: the new SMETA
    fields this contract adds, all of which are declared (non-null) in the pid-survey fixture.
    The retired lead_investigator key is still ON DISK in the fixture and is read by NEITHER
    parser path, so the two SMETAs agree by both ignoring it."""
    yaml = pytest.importorskip("yaml")
    text = (HERE / "fixtures" / "pid-survey" / "survey.yaml").read_text(encoding="utf-8")
    smeta_pyyaml = bp.survey_meta_from_yaml(yaml.safe_load(text) or {})
    smeta_mini = bp.survey_meta_from_yaml(bp._mini_yaml(text))
    assert smeta_mini == smeta_pyyaml
    # sanity: the fields under test are actually populated (not both-None trivially matching)
    assert "investigators" not in smeta_pyyaml and "investigators" not in smeta_mini
    assert smeta_pyyaml["org_ror"] == "https://ror.org/00892tw58"
    assert smeta_pyyaml["raid"] == "https://raid.org/10.12345/AB1234"
    assert smeta_pyyaml["ts_pid"] == "10.25914/pid-survey-ts"


def test_survey_meta_never_crashes_on_bad_shapes():
    """Defensive: odd funder/instrument shapes must be tolerated, never raise."""
    bad = {"name": "X", "slug": "x", "organisation": "Org", "license": "CC-BY-4.0",
           "funding": ["not-a-dict", {"organisation": "AuScope"}],
           "instruments": ["nope", {"manufacturer": "Phoenix", "model": "MTU-5C"}]}
    sm = bp.survey_meta_from_yaml(bad)
    assert any(f.get("name") == "AuScope" for f in sm["funders"])  # dict kept, string dropped
    assert "Phoenix MTU-5C" in (sm["instrument_model"] or "")


def test_parity_comment_after_quoted_scalar():
    """An inline comment after a QUOTED scalar must strip like PyYAML strips it; a hash
    inside the quotes is data. The credit migration's review notes exposed the divergence."""
    import yaml
    from extract.build_portal import _mini_yaml
    text = ('name: "Stephan Thiel"  # a trailing note\n'
            "single: 'a value'  # note\n"
            'inside: "keep # this"\n')
    assert _mini_yaml(text) == yaml.safe_load(text)
    # Escaped inner quotes: only pin that the trailing comment is gone (the mini unquoter's
    # lack of backslash UNescaping is a pre-existing, separate limitation).
    esc = _mini_yaml('escaped: "say \\"hi\\""  # note\n')["escaped"]
    assert "note" not in esc


def test_parity_quoted_mapping_keys():
    """Station-id override: a QUOTED mapping key must parse like PyYAML parses it.
    Filenames with spaces/parentheses are only expressible quoted, and the fallback once dropped
    such keys entirely. The same alternation must NOT turn a quoted list-item SCALAR that contains a
    colon into a one-key map, so both shapes are pinned here against PyYAML."""
    import yaml
    from extract.build_portal import _mini_yaml
    text = ('bare: 1\n'
            'quoted:\n'
            '  "49R stage 1.edi": "RD18-049-S1"\n'
            "  '53(RR).edi': RD18-053\n"
            '  plain.key: value\n'
            'items:\n'
            '  - "a: b"\n'
            "  - 'c: d'\n"
            '  - plain\n')
    assert _mini_yaml(text) == yaml.safe_load(text)


def test_parity_comment_on_key_line_before_nested_block():
    """A trailing comment on a KEY line whose value is a nested block
    ('data_types:  # pick one' followed by indented items) must parse like PyYAML parses it. The
    fallback once read the comment as the key's scalar VALUE, then bailed out of the nested block,
    truncating every later top-level key (block sequences) or flattening children into the parent
    (nested maps). The shipped _template/_example both carry this shape, so a no-PyYAML box failed
    the reference package against its own validator."""
    import yaml
    from extract.build_portal import _mini_yaml
    text = ('data_types:  # select all that apply\n'
            '  - BBMT\n'
            '  - LPMT\n'
            'organisation:  # who ran it\n'
            '  name: GSSA\n'
            'license: CC-BY-4.0\n')
    assert _mini_yaml(text) == yaml.safe_load(text)
    # The list-item sibling-key form of the same defect, plus a block-scalar indicator with a
    # trailing comment (legal YAML: the comment follows the '>' header).
    text2 = ('instruments:\n'
            '  - manufacturer: LEMI  # vendor\n'
            '    model: LEMI-423\n'
            'abstract: >  # folded\n'
            '  Two lines\n'
            '  folded to one.\n')
    assert _mini_yaml(text2) == yaml.safe_load(text2)


def test_parity_collection_prose_map_of_paragraph_lists():
    """`collection.prose` is the only place in the schema that nests a MAP OF LISTS two levels under
    a top-level key, and the only field whose values may begin with '#' (the subheading sigil) or
    carry a mid-string colon (the classification lines). Each of those is a live hazard for the
    tokeniser: a '#'-leading line is dropped as a comment, and an unquoted colon splits a scalar
    into a mapping. All three are safe only because the paragraphs are QUOTED scalars in a block
    sequence, which is exactly what this pins.

    FAILS IF a no-PyYAML box would parse the collection prose differently from a PyYAML box, which
    would serve two different collection pages from one corpus."""
    import yaml
    from extract.build_portal import _mini_yaml
    text = ('collection:\n'
            '  id: australia-legacy-gds\n'
            '  status: completed\n'
            '  description: "One flat paragraph, the discovery text."\n'
            '  prose:\n'
            '    about:\n'
            '      - "The collection brings together historical surveys."\n'
            '      - "# Preservation and reprocessing"\n'
            "      - \"Variations in the Earth's magnetic field.\"\n"
            '    members_after:\n'
            '      - "Where appropriate, surveys may be identified as:"\n'
            '      - "Reprocessed: transfer functions newly estimated."\n'
            '    organisations:\n'
            '      - "The organisations represented include institutions."\n')
    assert _mini_yaml(text) == yaml.safe_load(text)

    prose = _mini_yaml(text)["collection"]["prose"]
    assert prose["about"][1] == "# Preservation and reprocessing", \
        "a quoted '#' paragraph must survive the tokeniser's comment strip"
    assert prose["members_after"][1] == "Reprocessed: transfer functions newly estimated.", \
        "a mid-string colon must stay in the scalar, not split it into a mapping"
    assert prose["about"][2].endswith("Earth's magnetic field."), \
        "an ASCII apostrophe inside a double-quoted scalar survives both parsers"
    assert [type(v) for v in prose.values()] == [list, list, list], \
        "every prose section is a list of paragraphs, never a bare string"
