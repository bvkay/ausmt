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
    """C7: the mini-yaml fallback must agree with PyYAML on lead_investigator.orcid,
    organisation.ror, identifiers.project_raid and time_series.collection_pid too — the new SMETA
    fields this contract adds, all of which are declared (non-null) in the pid-survey fixture."""
    yaml = pytest.importorskip("yaml")
    text = (HERE / "fixtures" / "pid-survey" / "survey.yaml").read_text(encoding="utf-8")
    smeta_pyyaml = bp.survey_meta_from_yaml(yaml.safe_load(text) or {})
    smeta_mini = bp.survey_meta_from_yaml(bp._mini_yaml(text))
    assert smeta_mini == smeta_pyyaml
    # sanity: the fields under test are actually populated (not both-None trivially matching)
    assert smeta_pyyaml["investigators"] == [{"name": "A. Researcher", "orcid": "0000-0002-1825-0097"}]
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
