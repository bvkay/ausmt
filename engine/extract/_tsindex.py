#!/usr/bin/env python3
"""The verified-resource register a survey package carries beside survey.yaml.

    surveys/<slug>/ts-index.yaml
        ts_index:
          SA104A:
            - level: raw_packed              # one of the five D8 tokens
              url_path: "my80/.../SA104A.zip"  # the archive's own string, stored VERBATIM
              filename: "SA104A.zip"
              bytes: 1042000000
              verified: "2026-08-24"         # the day the crawler read a 200, and the day the
              match_method: rule:sa-pad      #   published fieldnote names (D18)
              review: verified               # only `verified` ever projects

Rule 14: this is read OFFLINE. The crawler (_tools/crawl_ts_index.py, ausmt-surveys) is the only
thing that talks to the archive; `--ts-index` is what makes a build consume its file. The build
never reaches the network, so cache.py's byte-reproducibility invariant survives contact with a
remote archive, and no build can honestly claim to have verified anything itself.

FAIL-CLOSED, for the run-id store's reason and one more: this file is the ONLY record of which
remote file belongs to which station, and what it publishes is a ROUTE a reader will follow. A
malformed register stops the build rather than projecting the rows it happened to be able to parse.

UNKNOWN ROW KEYS ARE TOLERATED and carried through (`data_size` was added to the shape after the
first crawl), so the register can gain a field without every reader having to be taught it in the
same commit. Unknown TOP-LEVEL keys are not: the file has one block and a second one means the
curator wrote something this reader is silently ignoring.
"""
from __future__ import annotations

import re
from pathlib import Path

STORE_NAME = "ts-index.yaml"

# The three closed vocabularies, restated from _validation/validate_survey.py (TS_INDEX_LEVELS /
# TS_INDEX_REVIEW / TS_INDEX_MATCH_METHODS) because the build must not depend on a sibling checkout.
# Restated, so pinned: tests/test_ts_index_register.py holds the content, and the two copies are
# reconciled when the vendored validator is resynced after merge.
# LEVELS and REVIEW are GATES here; the match-method pair is the RECONCILIATION ANCHOR only. The
# build does not judge a match method (see _row) - the validator's WARNING is its whole severity -
# but the tokens still have to agree across the two copies, so they are stated and pinned here.
LEVELS = ("raw_packed", "level0", "level1_mth5", "level1_netcdf", "level2")
REVIEW = ("verified", "pending", "retired")
MATCH_METHODS = ("exact", "curator")
_MATCH_RULE = re.compile(r"^rule:[a-z0-9-]+$")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TsIndexError(Exception):
    """The register exists but cannot be read as a record of verified remote files."""


def _text(value) -> str:
    return str(value).strip() if value not in (None, "") else ""


def load(index_root, package, known_ids) -> dict:
    """{published station id: [ordered rows]} for one survey package, {} where `index_root` holds no
    register for it (a partial register is legal: the flag names a ROOT, not a file).

    KEYED ON THE PACKAGE DIRECTORY NAME, never the declared slug, which is the run-id store's rule
    and for its reason: two packages may legitimately declare one slug, and the register belongs to
    the directory it sits in. Pointing --ts-index at the --surveys root therefore reads each
    package's own file.

    `known_ids` is the set of station ids THIS BUILD published for the package. A row outside it is
    a hard error rather than a dropped row: the register's whole job is to say which remote file
    belongs to which station, so a row nothing matched would publish a route under an identifier
    this build never assigned."""
    path = Path(index_root) / str(package) / STORE_NAME
    if not path.exists():
        return {}
    try:
        import yaml  # noqa: PLC0415
    except ModuleNotFoundError:
        raise TsIndexError(
            f"{STORE_NAME} needs PyYAML to be read (pip install PyYAML). The stdlib fallback parser "
            f"returns a PARTIAL map, which would publish some stations' routes and silently drop "
            f"the rest") from None
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise TsIndexError(f"{path} is not valid YAML ({e})") from None
    if not isinstance(doc, dict):
        raise TsIndexError(f"{path} must be a mapping carrying a `ts_index` block")
    unknown = sorted(k for k in doc if k != "ts_index")
    if unknown:
        raise TsIndexError(f"{path} has unknown top-level key(s) {unknown}; only `ts_index` is defined")
    stations = doc.get("ts_index")
    if not isinstance(stations, dict):
        raise TsIndexError(f"{path} carries no `ts_index` mapping of {{station id: [rows]}}")
    out: dict = {}
    for station, rows in stations.items():
        sid = str(station)
        if sid not in known_ids:
            raise TsIndexError(
                f"{path} names station {sid!r}, which this survey does not publish. The register "
                f"states which remote file belongs to which station, so a row nothing in the corpus "
                f"matches would publish a route under an identifier this build never assigned")
        if not isinstance(rows, (list, tuple)) or not rows:
            raise TsIndexError(f"{path}: station {sid!r} has no rows. A row states one verified "
                               f"file; to register none, remove the station")
        clean: list = []
        for idx, row in enumerate(rows):
            clean.append(_row(path, sid, idx, row, clean))
        out[sid] = clean
    return out


def _row(path, sid, idx, row, taken) -> dict:
    """One validated row, unknown keys intact. `taken` is the rows already accepted for this
    station, which is what the one-file-per-(station, level) rule is checked against."""
    label = f"{path}: {sid}[{idx}]"
    if not isinstance(row, dict):
        raise TsIndexError(f"{label} must be a mapping, got {type(row).__name__}")
    level = _text(row.get("level"))
    if level not in LEVELS:
        raise TsIndexError(f"{label}.level {level!r} is not one of {list(LEVELS)}; the token is what "
                           f"a route, a chooser button and a drawer row key off")
    if level in {r["level"] for r in taken}:
        raise TsIndexError(f"{path}: two rows claim station {sid!r} at level {level!r}; one "
                           f"(station, level) names one file, so a second row leaves nothing able "
                           f"to choose between them")
    review = _text(row.get("review"))
    if review not in REVIEW:
        raise TsIndexError(f"{label}.review {review!r} is not one of {list(REVIEW)}; only "
                           f"'verified' publishes, and an out-of-vocab state reads as 'not verified' "
                           f"to one reader and 'unknown' to the next")
    if review == "retired" and not (_text(row.get("retired")) and _text(row.get("retired_reason"))):
        raise TsIndexError(f"{label} is retired without `retired` and `retired_reason`; retirement "
                           f"is a dated curator act, not a deletion, and the row stays as evidence")
    # match_method is provenance, not a gate: a row stands or falls on `review`, and its severity
    # is the surveys validator's WARNING (S1's ratified FAIL list does not name it). Raising here
    # hard-stopped builds on registers that passed surveys CI green. Carried through verbatim.
    url_path = _text(row.get("url_path"))
    if not url_path:
        raise TsIndexError(f"{label} has no url_path; that string IS the remote file's identity, "
                           f"stored verbatim, and is never rebuilt by joining catalog segments")
    verified = _text(row.get("verified"))
    if not _ISO_DATE.match(verified):
        raise TsIndexError(f"{label}.verified {verified!r} is not an ISO date (YYYY-MM-DD); that day "
                           f"is what the published fieldnote names")
    size = row.get("bytes")
    if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size <= 0):
        raise TsIndexError(f"{label}.bytes {size!r} is not a positive integer; the figure is "
                           f"published beside the file, so a wrong one is a wrong claim")
    return dict(row, level=level, review=review, url_path=url_path, verified=verified)
