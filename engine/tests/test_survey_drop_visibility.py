"""Every survey-granularity drop is machine-visible, and verify.py refuses the build (D20's rule
extended to the whole class).

Eight paths drop a survey with rc=0. Recording only the validator skip leaves verify.py's
loud-skip gate passed a build that silently lost a survey to an unreadable survey.yaml, an invalid
coordinate policy or station_ids block, a zero-station parse, or an unserialisable SMETA - exactly
the swap D20 exists to prevent. build_report.json now carries `surveys_dropped` (present and empty
on a clean build), fed by one recorder across discover_work and main's loop, and verify.py FAILs on
any entry.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _good_pkg(base, slug, name, edi):
    sys.path.insert(0, str(HERE))
    from _fixtures import EXAMPLE_SURVEY as ex
    import shutil
    y = ex.joinpath("survey.yaml").read_text(encoding="utf-8")
    y = (y.replace("slug: example-survey", f"slug: {slug}")
           .replace('project_name: "Example MT Survey 2026"', f'project_name: "{name}"')
           .replace('name: "Example MT Survey 2026"', f'name: "{name}"'))
    d = base / slug
    (d / "transfer_functions" / "edi").mkdir(parents=True)
    shutil.copy(edi, d / "transfer_functions" / "edi" / edi.name)
    (d / "survey.yaml").write_text(y)


def test_a_dropped_survey_is_recorded_and_verify_refuses_the_build(tmp_path):
    sys.path.insert(0, str(HERE))
    from _fixtures import example_edis
    edis = example_edis()
    base = tmp_path / "surveys"
    _good_pkg(base, "good-2017", "Good Survey 2017", edis[0])
    broken = base / "broken-2018"
    (broken / "transfer_functions" / "edi").mkdir(parents=True)
    (broken / "survey.yaml").write_text("- this is a list, not a mapping\n")

    out = tmp_path / "out"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal",
                       "--surveys", str(base), "--out", str(out), "--no-validate"],
                      cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr   # survey granularity: the corpus still builds

    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    dropped = rep.get("surveys_dropped")
    assert dropped is not None, "build_report.json must always carry surveys_dropped"
    assert len(dropped) == 1 and dropped[0]["survey"] == "broken-2018", dropped
    assert "mapping" in dropped[0]["reason"], dropped
    mt = json.loads((out / "mtcat.json").read_text(encoding="utf-8"))
    assert len(mt["surveys"]) == 1, "the rest of the corpus builds"

    v = subprocess.run([sys.executable, "scripts/verify.py", "--data-dir", str(out)],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert v.returncode != 0, "verify.py must refuse a build that dropped a survey:\n" + v.stdout + v.stderr
    assert "broken-2018" in (v.stdout + v.stderr), v.stdout + v.stderr


def test_a_clean_build_carries_an_empty_drop_list(tmp_path):
    sys.path.insert(0, str(HERE))
    from _fixtures import example_edis
    base = tmp_path / "surveys"
    _good_pkg(base, "good-2017", "Good Survey 2017", example_edis()[0])
    out = tmp_path / "out"
    subprocess.run([sys.executable, "-m", "extract.build_portal",
                    "--surveys", str(base), "--out", str(out), "--no-validate"],
                   cwd=str(ROOT), check=True, capture_output=True)
    rep = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    assert rep.get("surveys_dropped") == [], rep.get("surveys_dropped")
