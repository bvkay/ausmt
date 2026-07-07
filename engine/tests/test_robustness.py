"""Build robustness on a hostile/atypical contributor survey.yaml (pre-push hostile audit, must-fix #2).
One malformed or oddly-shaped survey.yaml must NOT crash the whole all-or-nothing build with a raw
traceback and deny publication to every other survey.

Each test states its failure criterion:
- test_read_yaml_malformed_returns_none: FAILS if _read_yaml lets a yaml.YAMLError escape (was a raw crash).
- test_extent_of_coerces_and_rejects: FAILS if a quoted bound isn't coerced to float, or a garbage/missing
  bound isn't treated as absent (a non-float bound -> str < float TypeError in qc_pass).
- test_build_skips_malformed_survey: FAILS if the build aborts instead of dropping the one bad package.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "extract"))
import build_portal as bp  # noqa: E402


def test_read_yaml_malformed_returns_none(tmp_path):
    (tmp_path / "bad.yaml").write_text('name: "unclosed string\n  bad: [1, 2')
    assert bp._read_yaml(tmp_path / "bad.yaml") is None   # warned + dropped, not raised


def test_extent_of_coerces_and_rejects():
    assert bp._extent_of({"geographic_extent": {"west": "136.97", "east": "137", "south": "-30", "north": "-29"}}) \
        == (136.97, 137.0, -30.0, -29.0)                                                  # quoted-numeric coerces
    assert bp._extent_of({"geographic_extent": {"west": "x", "east": 1, "south": 2, "north": 3}}) is None  # garbage -> absent
    assert bp._extent_of({"geographic_extent": {"west": 1, "east": 2, "south": 3}}) is None                # missing bound -> absent


def test_near_duplicate_collection_ids_flags_case_whitespace_typos():
    # FAILS if a case/whitespace-only id variant (a likely typo that silently splits one collection into two)
    # is NOT grouped, or if genuinely distinct ids ARE grouped (false positive).
    groups = bp._near_duplicate_collection_ids(["auslamp", "AusLAMP", " auslamp ", "musgraves"])
    assert len(groups) == 1 and set(groups[0]) == {"auslamp", "AusLAMP", " auslamp "}
    assert bp._near_duplicate_collection_ids(["auslamp", "musgraves", "ccmt"]) == []


def test_build_skips_malformed_survey_instead_of_crashing(tmp_path):
    bad = tmp_path / "surveys" / "broken"
    (bad / "transfer_functions" / "edi").mkdir(parents=True)
    (bad / "survey.yaml").write_text('name: "unclosed\n bad: [1, 2')
    (bad / "transfer_functions" / "edi" / "a.edi").write_text('>HEAD\nLAT=-30:0:0\nLONG=136:0:0\n>END\n')
    rc = bp.main(["--surveys", str(tmp_path / "surveys"), "--out", str(tmp_path / "out"),
                  "--allow-empty", "--no-validate"])
    assert rc == 0   # the malformed package is skipped; the build empties cleanly rather than tracebacking
