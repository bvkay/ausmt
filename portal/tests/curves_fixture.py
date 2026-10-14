"""The per-survey curve layout the engine emits, for the tests that build a portal data dir by hand.

A survey's transfer-function rows are served as data/tf/<slug>.json, in catalogue order, and the
survey's surveys.json entry names that file (tf_url). The portal fetches the file when one of the
survey's stations opens, so a fixture that writes only tf.json gives the drawer no curves at all.
"""
import json
from pathlib import Path

COLS = json.loads((Path(__file__).resolve().parents[2] / "contract" / "columns.json")
                  .read_text(encoding="utf-8"))
SURVEY_COL = COLS["catalogue"].index("survey")


def curve_files(catalogue, tf_rows, surveys):
    """{relative path: rows} for every survey the catalogue holds, and set each survey's tf_url in
    `surveys` (mutated in place)."""
    files = {}
    for row, tf in zip(catalogue, tf_rows):
        label = row[SURVEY_COL]
        rel = f"tf/{surveys[label]['slug']}.json"
        surveys[label]["tf_url"] = rel
        files.setdefault(rel, []).append(tf)
    return files


def write_curves(data_dir, catalogue, tf_rows, surveys):
    """Write the curve files under `data_dir` and name each in `surveys` (mutated in place); the
    caller writes surveys.json afterwards."""
    for rel, rows in curve_files(catalogue, tf_rows, surveys).items():
        p = Path(data_dir) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rows), encoding="utf-8")


def datamap_curves(catalogue, tf_rows, surveys):
    """The same files as entries of a probe's url -> body map (keys "data/tf/<slug>.json")."""
    return {"data/" + rel: rows for rel, rows in curve_files(catalogue, tf_rows, surveys).items()}
