"""Per-survey transfer-function curve files: data/tf/<slug>.json.

The portal fetches one survey's curves when a station of that survey opens, so the whole-corpus
tf.json is not part of first paint. Each per-survey file holds that survey's tf.json rows in
catalogue order. tf.json is still written beside them, and these pins hold the two in step:

  * every catalogue row has exactly one row in its survey's file, at the same position among that
    survey's rows, and the row is BYTE-equal to the matching tf.json row (an embargoed survey's
    withheld rows included, so the split cannot leak curves the access gate emptied);
  * surveys.json names each survey's file (tf_url), so the portal resolves it from a document it
    already holds at first paint;
  * manifest.json lists every file with its size and sha256, recomputed here from the bytes;
  * verify.py --data-dir fails when a survey file is missing or holds fewer rows than the survey
    has in the catalogue, even when the manifest has been made to agree with the damaged file.

Two surveys are built so the catalogue holds more than one group: the open sample survey and an
embargoed copy of it under its own slug.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

pytest.importorskip("mt_metadata")
pytest.importorskip("mth5")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SAMPLE = ROOT / "data" / "sample-survey"
COLS = json.loads((ROOT.parent / "contract" / "columns.json").read_text(encoding="utf-8"))
SURVEY_COL = COLS["catalogue"].index("survey")


def _row_bytes(row):
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _stage(tmp_path):
    root = tmp_path / "surveys"
    shutil.copytree(SAMPLE, root / "sample-survey")
    emb = root / "sample-embargoed"
    shutil.copytree(SAMPLE, emb)
    y = emb / "survey.yaml"
    until = (date.today() + timedelta(days=365)).isoformat()
    swap = {"slug:": "slug: sample-embargoed", "name:": 'name: "CI Sample Survey Embargoed"',
            "access:": f"access: {{ level: embargoed, embargo_until: {until} }}"}
    lines = [next((v for k, v in swap.items() if ln.strip().startswith(k)), ln)
             for ln in y.read_text(encoding="utf-8").splitlines()]
    y.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("tfsplit")
    surveys = _stage(tmp)
    out = tmp / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys),
                        "--out", str(out), "--bundle-edi", "--no-validate"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _load(out, name):
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_every_catalogue_row_has_one_byte_equal_row_in_its_survey_file(built):
    cat, tf, smeta = _load(built, "catalogue.json"), _load(built, "tf.json"), _load(built, "surveys.json")
    labels = [row[SURVEY_COL] for row in cat]
    assert len(set(labels)) == 2, f"fixture sanity: two surveys expected, got {sorted(set(labels))}"
    assert len(tf) == len(cat)
    files = {}
    for label in dict.fromkeys(labels):
        url = smeta[label].get("tf_url")
        assert url == f"tf/{smeta[label]['slug']}.json", (
            f"surveys.json must name {label!r}'s curve file as tf/<slug>.json, got {url!r}")
        assert (built / url).is_file(), f"{url} was not written"
        files[label] = _load(built, url)
    taken = {label: 0 for label in files}
    for i, label in enumerate(labels):
        k = taken[label]
        assert k < len(files[label]), f"{label!r} file is short: catalogue row {i} has no curve row"
        assert _row_bytes(files[label][k]) == _row_bytes(tf[i]), (
            f"catalogue row {i} ({label!r}, position {k} in its survey) differs from tf.json row {i}")
        taken[label] = k + 1
    for label, rows in files.items():
        assert taken[label] == len(rows), (
            f"{label!r} file holds {len(rows)} rows for {taken[label]} catalogue rows")
    emb = [lbl for lbl in files if smeta[lbl].get("access") == "embargoed"]
    assert emb and all(all(series == [] for series in row) for row in files[emb[0]]), (
        "the embargoed survey's file must carry the withheld rows tf.json carries")


def test_the_survey_file_is_the_compact_dump_of_its_rows(built):
    smeta = _load(built, "surveys.json")
    for label, m in smeta.items():
        text = (built / m["tf_url"]).read_text(encoding="utf-8")
        rows = json.loads(text)
        assert text == "[" + ",".join(_row_bytes(r) for r in rows) + "]", (
            f"{m['tf_url']} must be written in the same compact form as tf.json")


def test_the_tf_directory_holds_exactly_the_catalogue_surveys(built):
    smeta = _load(built, "surveys.json")
    want = sorted(f"{m['slug']}.json" for m in smeta.values())
    assert sorted(p.name for p in (built / "tf").iterdir()) == want


def test_the_manifest_lists_every_curve_file_with_its_digest(built):
    man, smeta, cat = _load(built, "manifest.json"), _load(built, "surveys.json"), _load(built, "catalogue.json")
    rows = man.get("curves")
    assert isinstance(rows, list), "manifest.json must carry a curves[] list"
    by_url = {r["url"]: r for r in rows}
    assert sorted(by_url) == sorted(m["tf_url"] for m in smeta.values())
    for label, m in smeta.items():
        r = by_url[m["tf_url"]]
        data = (built / r["url"]).read_bytes()
        assert r["survey"] == label and r["slug"] == m["slug"], r
        assert r["size"] == len(data) and r["sha256"] == hashlib.sha256(data).hexdigest(), r
        assert r["n_stations"] == sum(1 for row in cat if row[SURVEY_COL] == label), r
    assert man["generated_count"] == len(man["files"]) + len(man["bundles"]), (
        "the curve files are not downloadable artifacts and must not change generated_count")


def test_the_manifest_with_curves_validates_against_its_schema(built):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((ROOT / "schema" / "manifest.schema.json").read_text(encoding="utf-8"))
    assert "curves" in schema["properties"], "the manifest schema must describe curves[]"
    jsonschema.validate(_load(built, "manifest.json"), schema)


def _verify(out):
    return subprocess.run([sys.executable, "scripts/verify.py", "--data-dir", str(out)],
                          cwd=str(ROOT), capture_output=True, text=True)


def _copy(built, tmp_path):
    out = tmp_path / "data"
    shutil.copytree(built, out)
    return out


def _restamp(out, url, data):
    """Rewrite one curve file and make the manifest agree with the new bytes, so only the row-count
    gate can see the damage."""
    man = _load(out, "manifest.json")
    if data is None:
        (out / url).unlink()
        man["curves"] = [r for r in man["curves"] if r["url"] != url]
    else:
        (out / url).write_bytes(data)
        for r in man["curves"]:
            if r["url"] == url:
                r["size"], r["sha256"] = len(data), hashlib.sha256(data).hexdigest()
    (out / "manifest.json").write_text(json.dumps(man, separators=(",", ":")), encoding="utf-8")


def test_verify_passes_the_intact_build(built, tmp_path):
    r = _verify(_copy(built, tmp_path))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "curves:" in r.stdout, "verify.py must report the curve-file gate:\n" + r.stdout


def test_verify_fails_a_missing_survey_file(built, tmp_path):
    out = _copy(built, tmp_path)
    url = _load(out, "surveys.json")["CI Sample Survey"]["tf_url"]
    _restamp(out, url, None)
    r = _verify(out)
    assert r.returncode != 0, "a survey with no curve file must fail verify:\n" + r.stdout
    assert "curves:" in r.stdout and "FAIL" in r.stdout.split("curves:")[1].splitlines()[0], r.stdout


def test_verify_fails_a_short_survey_file(built, tmp_path):
    out = _copy(built, tmp_path)
    url = _load(out, "surveys.json")["CI Sample Survey"]["tf_url"]
    rows = _load(out, url)
    assert len(rows) >= 2, "fixture sanity: the sample survey has two stations"
    _restamp(out, url, json.dumps(rows[:-1], separators=(",", ":")).encode("utf-8"))
    r = _verify(out)
    assert r.returncode != 0, "a survey file with fewer rows than the catalogue must fail verify:\n" + r.stdout
    assert "curves:" in r.stdout and "FAIL" in r.stdout.split("curves:")[1].splitlines()[0], r.stdout
