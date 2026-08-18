"""The published-URL id freeze (path-URL contract commit 3, owner ruling 2026-08-18).

/surveys/<slug>, /stations/<ausmt_id> and /collections/<id> are PUBLISHED URL contracts, so the id
VOCABULARY behind them is frozen in a checked-in registry (portal/data/url_registry.json): every
survey slug, station ausmt_id and collection id currently published. The freeze rule:

  * an ADDED id is fine and is auto-recorded (--check appends it; a brand-new survey publishes new
    URLs, it breaks none);
  * a REMOVED or CHANGED id is a violation: a published URL id moved - add a redirect entry and a
    dated registry note, never rename silently. (A rename surfaces as a removal beside an
    addition; the removal is what fails.)
  * the sitemap can never advertise an unpinned id: every entity id in sitemap.xml must appear in
    the registry, so nothing reaches the published surface without first being frozen.

WHERE THE IDS COME FROM (regeneration reads the BUILT products, mtcat.json, deliberately: the
engine's own id derivations are the single authority, and re-deriving ids from raw inputs here
would be a second derivation, the exact divergence risk build_portal.py refuses elsewhere):

  * survey slug   = mtcat surveys[].survey_id: declared in survey.yaml (`slug:`, defaulting to the
    package folder name), sanitised by safe_component. NOT derived from the display name in
    --surveys builds. (--raw bulk-seed mode DOES slugify display labels; rebrand-fragile, flagged
    as an owner item in the lane report.)
  * station ausmt_id = mtcat stations[].station_id: au.<survey-slug>.<station-id[.variant]>, the
    station id being the transfer function's own declared DATAID (sanitised), with a processing
    variant tag only when one survey holds the same station twice.
  * collection id = mtcat collections[].collection_id: declared VERBATIM in each member
    survey.yaml's collection.id (grouping is an exact string match; the build warns on
    near-duplicate ids; the Add Survey form autofills known ids from collections.json).

CLI (module form, like the other engine tools):

    python -m extract.url_registry --data <built-portal-data-dir> [--registry <path>] --check
    python -m extract.url_registry --data <built-portal-data-dir> [--registry <path>] --update

--check: exits non-zero on any removed/changed id or any unpinned sitemap id; additions are
auto-recorded into the registry and reported. --update: seeds or extends the registry (additions
only; it refuses to bless a removal). The registry's `_meta.redirects` map plus a dated
`_meta.notes` entry is where a genuinely moved id is recorded when the owner decides one.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

KINDS = ("surveys", "stations", "collections")

# The prescribed freeze-failure message (path-URL contract commit 3). Tests pin it verbatim.
MOVED_MSG = ("a published URL id moved - add a redirect entry and a dated registry note, "
             "never rename silently.")

_REPO = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = _REPO / "portal" / "data" / "url_registry.json"

# Path-form sitemap ids: <base>/surveys/<id> etc. The legacy fragment forms (#/survey/<id>) are
# ALSO parsed so a regression to fragment emission cannot smuggle an unpinned id past the pin.
_PATH_RE = {
    "surveys": re.compile(r"/surveys/([^/?#]+)"),
    "stations": re.compile(r"/stations/([^/?#]+)"),
    "collections": re.compile(r"/collections/([^/?#]+)"),
}
_FRAG_RE = {
    "surveys": re.compile(r"#/survey/([^/?#]+)"),
    "stations": re.compile(r"#/station/([^/?#]+)"),
    "collections": re.compile(r"#/collection/([^/?#]+)"),
}


def ids_from_mtcat(mtcat: dict) -> dict[str, list[str]]:
    """{kind: sorted ids} from a built mtcat.json document (the id authority of the built
    product). Malformed rows are skipped rather than crashing: the freeze compares SETS, and a row
    with no id publishes no URL."""
    out = {k: set() for k in KINDS}
    if isinstance(mtcat, dict):
        for row in mtcat.get("surveys") or []:
            if isinstance(row, dict) and isinstance(row.get("survey_id"), str) and row["survey_id"]:
                out["surveys"].add(row["survey_id"])
        for row in mtcat.get("stations") or []:
            if isinstance(row, dict) and isinstance(row.get("station_id"), str) and row["station_id"]:
                out["stations"].add(row["station_id"])
        for row in mtcat.get("collections") or []:
            if isinstance(row, dict) and isinstance(row.get("collection_id"), str) and row["collection_id"]:
                out["collections"].add(row["collection_id"])
    return {k: sorted(v) for k, v in out.items()}


def ids_from_data_dir(data_dir: Path) -> dict[str, list[str]]:
    mtcat_path = Path(data_dir) / "mtcat.json"
    return ids_from_mtcat(json.loads(mtcat_path.read_text(encoding="utf-8")))


def sitemap_entity_ids(xml_text: str) -> dict[str, list[str]]:
    """{kind: sorted ids} advertised by a sitemap.xml text, path form AND legacy fragment form."""
    out = {k: set() for k in KINDS}
    for loc in re.findall(r"<loc>([^<]+)</loc>", xml_text):
        for kind in KINDS:
            for rx in (_PATH_RE[kind], _FRAG_RE[kind]):
                for m in rx.findall(loc):
                    out[kind].add(m)
    return {k: sorted(v) for k, v in out.items()}


def _empty_registry() -> dict:
    return {
        "_meta": {
            "contract": ("path-URL contract (owner ruling 2026-08-18): /surveys/<slug>, "
                         "/stations/<ausmt_id> and /collections/<id> are published URL contracts; "
                         "the ids below are FROZEN. " + MOVED_MSG),
            "derivation": [
                "survey slug: declared in survey.yaml (slug:, defaulting to the package folder "
                "name), sanitised by safe_component; not derived from the display name in "
                "--surveys builds (raw bulk-seed mode slugifies labels; rebrand-fragile, owner "
                "item).",
                "station ausmt_id: au.<survey-slug>.<station-id[.variant]>; the station id is the "
                "transfer function's declared DATAID (sanitised), variant only for same-station "
                "reprocessings.",
                "collection id: declared verbatim in each member survey.yaml's collection.id "
                "(exact-string grouping; near-duplicate ids warn at build; the Add Survey form "
                "autofills known ids).",
            ],
            "notes": [],
            "redirects": {},
        },
        "surveys": [], "stations": [], "collections": [],
    }


def load_registry(path: Path) -> dict:
    reg = json.loads(Path(path).read_text(encoding="utf-8"))
    for kind in KINDS:
        reg.setdefault(kind, [])
    return reg


def save_registry(path: Path, registry: dict) -> None:
    for kind in KINDS:
        registry[kind] = sorted(set(registry.get(kind) or []))
    Path(path).write_text(json.dumps(registry, indent=1, ensure_ascii=False) + "\n",
                          encoding="utf-8")


def check_freeze(registry: dict, current: dict[str, list[str]]) -> tuple[list[str], dict[str, list[str]]]:
    """(violations, additions). A registry id missing from the current build is a violation (a
    removed or renamed PUBLISHED id); a current id missing from the registry is an addition
    (fine, to be auto-recorded)."""
    violations: list[str] = []
    additions: dict[str, list[str]] = {}
    for kind in KINDS:
        reg_ids = set(registry.get(kind) or [])
        cur_ids = set(current.get(kind) or [])
        for gone in sorted(reg_ids - cur_ids):
            violations.append(
                f"{kind}: id '{gone}' is in the registry but absent from the current build: "
                + MOVED_MSG)
        added = sorted(cur_ids - reg_ids)
        if added:
            additions[kind] = added
    return violations, additions


def check_sitemap(registry: dict, sitemap_ids: dict[str, list[str]]) -> list[str]:
    """Violations for every sitemap-advertised entity id that the registry does not pin: the
    sitemap can never advertise an unpinned id."""
    violations: list[str] = []
    for kind in KINDS:
        reg_ids = set(registry.get(kind) or [])
        for sid in sitemap_ids.get(kind) or []:
            if sid not in reg_ids:
                violations.append(
                    f"{kind}: the sitemap advertises id '{sid}' that is not pinned in the "
                    f"registry (the sitemap can never advertise an unpinned id) - record it "
                    f"with --update before publishing.")
    return violations


def merge_additions(registry: dict, additions: dict[str, list[str]]) -> dict:
    for kind, ids in additions.items():
        registry[kind] = sorted(set(registry.get(kind) or []) | set(ids))
    return registry


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True,
                    help="built portal data dir (mtcat.json; sitemap.xml checked when present)")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY),
                    help=f"the checked-in registry file [default: {DEFAULT_REGISTRY}]")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true",
                      help="fail on removed/changed or unpinned-in-sitemap ids; auto-record additions")
    mode.add_argument("--update", action="store_true",
                      help="seed or extend the registry (additions only; refuses removals)")
    a = ap.parse_args(argv)

    data_dir = Path(a.data)
    reg_path = Path(a.registry)
    current = ids_from_data_dir(data_dir)

    if reg_path.is_file():
        registry = load_registry(reg_path)
    else:
        if a.check:
            print(f"url_registry: ERROR: no registry at {reg_path} - seed it with --update first.",
                  file=sys.stderr)
            return 2
        registry = _empty_registry()

    violations, additions = check_freeze(registry, current)
    sitemap_path = data_dir / "sitemap.xml"
    if sitemap_path.is_file():
        violations += check_sitemap(
            merge_additions(json.loads(json.dumps(registry)), additions),
            sitemap_entity_ids(sitemap_path.read_text(encoding="utf-8")))

    if violations:
        for v in violations:
            print(f"url_registry: FAIL: {v}", file=sys.stderr)
        if a.update:
            print("url_registry: --update refuses to bless a removed/changed published id.",
                  file=sys.stderr)
        return 1

    if additions:
        merge_additions(registry, additions)
        save_registry(reg_path, registry)
        for kind, ids in sorted(additions.items()):
            print(f"url_registry: recorded {len(ids)} new {kind} id(s): {', '.join(ids)}")
    elif a.update and not reg_path.is_file():
        save_registry(reg_path, registry)

    counts = ", ".join(f"{len(registry.get(k) or [])} {k}" for k in KINDS)
    print(f"url_registry: OK ({counts}) - registry {reg_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
