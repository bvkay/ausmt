#!/usr/bin/env python3
"""AusMT survey-package validator — the submission contract, as runnable code.

Implements Stage-2 automated validation of the submission workflow (see the AusMT docs
operations/submission.md). Emits PASS / WARNING / FAIL
per check and a machine-readable report. A FAIL blocks publication; WARNINGs go to the
human reviewer (Stage 3). This is intentionally dependency-light (stdlib + optional
mt_metadata for deep EDI parsing) so it runs anywhere, including CI.

Usage:
  python validate_survey.py path/to/survey-folder [--json report.json] [--strict]
Exit code 0 if no FAILs (1 if any FAIL, or any WARNING under --strict).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path

LEVELS = {"PASS": 0, "WARNING": 1, "FAIL": 2}


def _norm(s: str) -> str:
    """Normalise raw EDI text: CRLF/CR -> LF and left-strip each line (indented >MARKERS / KEY=).
    Single definition shared with contribute.py so the two tools normalise identically."""
    return "\n".join(ln.lstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


AUS_BBOX = (108.0, 156.0, -45.0, -8.0)  # w,e,s,n — generous; non-AU surveys override in survey.yaml
ALLOWED_TF_EXT = {".edi", ".h5", ".mth5"}   # EDI and MTH5 are first-class TF inputs (Prototype 23)
# EMTF-XML and processing-software formats remain deferred; enable per-deployment with --allow-optin-formats
# (--allow-mth5 is a deprecated alias, kept only for existing CI invocations; same dest, same effect)
OPTIN_TF_EXT = {".xml", ".zmm", ".zrr", ".j"}
DISALLOWED_EXT = {".exe", ".dll", ".bat", ".sh", ".scr", ".js", ".vbs", ".jar", ".com",
                  ".cmd", ".ps1", ".py", ".pl", ".php", ".so", ".dylib"}
ARCHIVE_EXT = {".zip", ".tar", ".gz", ".tgz", ".7z", ".rar", ".bz2", ".xz"}
MAX_FILE_MB = 200          # files larger than this FAIL unless a curator passes --allow-large
# C1 access enum: access.level gates byte DISTRIBUTION in the engine (open serves; metadata_only/embargoed
# withhold bytes but stay discoverable). It is a REQUIRED field, so — unlike licence, which had a legacy
# excuse — an out-of-enum value is a hard FAIL (there is no legacy corpus of bad levels). embargo_until must
# be ISO YYYY-MM-DD when present. These mirror the engine's access_serve_state; keep them behaviourally in sync.
ACCESS_LEVELS = ("open", "metadata_only", "embargoed")
# C42 (owner queue): the SURVEY-LEVEL coordinate-access policy read from access.coordinates. It gates
# how station coordinates are SERVED, so an out-of-enum value is a hard FAIL (no legacy corpus of bad
# values). Absent => exact (the record's zero-change default). Byte-identical spelling to the engine's
# extract/_coordaccess.COORDINATE_POLICIES and gateway.editor_form.COORDINATE_POLICIES.
COORDINATE_POLICIES = ("exact", "generalised", "withheld")
# C46 schema-0.3 capture (design §2.1). schema_version is now VALIDATED (it was carried, never
# checked); only these are known. attribution/sources are the 0.3 fields — present under 0.2 warns to
# bump. The key allow-lists are FROZEN and must stay in EXACT parity with the editor's section keys
# (gateway.editor_form MAP/LIST sections); the C46-W1c key-parity test feeds an editor-assembled patch
# through THIS validator and asserts zero unknown-key warnings (the care-field drift lesson: an
# unvalidated new section rots). SOURCE_PROFILES is the custodian attribution-profile vocab.
SCHEMA_VERSIONS = ("0.2", "0.3")
ATTRIBUTION_KEYS = frozenset({"custodian", "custodian_ror", "statement", "changes_made",
                              "changes_summary", "declared_by", "declared_date"})
SOURCE_KEYS = frozenset({"title", "custodian", "identifier", "licence", "retrieved", "statement",
                         "profile", "relation", "identifier_type"})
SOURCE_PROFILES = frozenset({"ga", "generic"})
# §2a (identifiers design — the related-identifiers model): the model TYPES the C46 sources[] object.
# It adds a `relation` + an `identifier_type` to the untyped upstream-dataset identifier sources[]
# already carries, rather than inventing a parallel structure ("C46 built the object; this types it").
# Both vocabularies are FROZEN and FAIL-CLOSED — an out-of-vocab value is a hard FAIL, mirroring the
# access.coordinates enum — because a mis-typed relation would publish a WRONG provenance claim, so it
# must block rather than ship. RELATION_TYPES is the curated DataCite subset ratified as the editor
# presets (design Decision 3); IDENTIFIER_TYPES is the small set AusMT records against (eCat/SARIG ids
# normalise to URL/DOI). Same vocab-select discipline as SOURCE_PROFILES above.
RELATION_TYPES = frozenset({"IsDerivedFrom", "IsVariantFormOf", "IsSupplementTo", "Cites"})
IDENTIFIER_TYPES = frozenset({"DOI", "Handle", "URL", "RAiD"})
# anti-masquerade: the BINARY TF types must start with their real signature. The text type (.edi) is
# checked separately for binary content (a NUL byte ⇒ a renamed binary or a polyglot) in the loop below.
MAGIC = {
    ".h5": b"\x89HDF\r\n\x1a\n", ".mth5": b"\x89HDF\r\n\x1a\n",
}

# C6 licence allow-list. The validator is deliberately dependency-light and CANNOT import the engine, so
# these tables are a COPY of contract/licenses.json pinned by tests/test_contribute.py::
# test_license_list_parity_with_contract (the same parity-pin pattern that guards parse_angle/_norm). A
# licence must be a RECOGNISED id (redistributable ∪ recognised_only ∪ aliases) — WARNING by default,
# FAIL under --strict (the publication gate). Everything else is an unrecognised licence. Keep in sync by
# editing contract/licenses.json, then mirroring the change here (the parity test fails loudly otherwise).
REDISTRIBUTABLE_LICENSES = [
    "CC0-1.0", "CC-BY-3.0", "CC-BY-3.0-AU", "CC-BY-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0",
    "CC-BY-NC-4.0", "CC-BY-NC-SA-4.0", "CC-BY-ND-4.0", "CC-BY-NC-ND-4.0", "PUBLIC DOMAIN",
    "ODBL-1.0", "ODC-BY-1.0",
]
RECOGNISED_ONLY_LICENSES = [
    "CC-BY-NC-3.0", "CC-BY-NC-SA-3.0", "CC-BY-ND-3.0", "CC-BY-NC-ND-3.0",
    "ALL RIGHTS RESERVED", "COPYRIGHT",
]
LICENSE_ALIASES = {
    "CC0": "CC0-1.0", "CC-BY": "CC-BY-4.0", "CC-BY-SA": "CC-BY-SA-4.0", "CC-BY-NC": "CC-BY-NC-4.0",
    "CC-BY-ND": "CC-BY-ND-4.0", "CC-BY-NC-SA": "CC-BY-NC-SA-4.0", "CC-BY-NC-ND": "CC-BY-NC-ND-4.0",
    "ODBL": "ODBL-1.0", "ODC-BY": "ODC-BY-1.0",
}
_RECOGNISED_UPPER = {s.upper() for s in REDISTRIBUTABLE_LICENSES + RECOGNISED_ONLY_LICENSES}
_ALIASES_UPPER = {k.upper(): v.upper() for k, v in LICENSE_ALIASES.items()}


def canon_license(license_str: str) -> str:
    """Canonical UPPER licence id (trim, collapse internal whitespace, upper, de-alias). Byte-identical
    behaviour to the engine's build_portal._canon_license — pinned by the licence-parity test."""
    s = " ".join((license_str or "").strip().split()).upper()
    return _ALIASES_UPPER.get(s, s)


def is_recognised_license(license_str: str) -> bool:
    """True iff the licence canonicalises to a recognised id (redistributable ∪ recognised_only ∪ aliases)."""
    return canon_license(license_str) in _RECOGNISED_UPPER


_ORCID_RE = re.compile(r"^(?:https?://orcid\.org/)?(\d{4})-(\d{4})-(\d{4})-(\d{3}[\dX])$")
_ROR_RE = re.compile(r"^0[a-hj-km-np-tv-z0-9]{6}[0-9]{2}$")   # the bare-id form (Crockford base32 + 2 check digits)


def orcid_checksum_ok(orcid: str) -> bool:
    """ISO 7064 11-2 check-digit validation, the algorithm ORCID identifiers use: double-add-double
    over the first 15 digits mod 11, expressed as a check digit in 0-9/X. A bare id or a full
    https://orcid.org/... URL are both accepted (the survey.yaml comment shows the bare form)."""
    m = _ORCID_RE.match((orcid or "").strip())
    if not m:
        return False
    digits = "".join(m.groups())            # 16 chars: 15 digits + 1 check char (may be 'X')
    total = 0
    for d in digits[:-1]:
        total = (total + int(d)) * 2
    remainder = total % 11
    result = (12 - remainder) % 11
    check = "X" if result == 10 else str(result)
    return check == digits[-1]


def ror_format_ok(ror: str) -> bool:
    """Format sanity for a ROR id: either the bare 9-char Crockford-base32-ish id, or a full
    https://ror.org/<id> URL. Deliberately light (no registry lookup) — this is a curator hint, not a
    resolvability guarantee, mirroring the RAiD check below."""
    s = (ror or "").strip()
    if s.lower().startswith(("http://ror.org/", "https://ror.org/")):
        s = s.split("/")[-1]
    return bool(_ROR_RE.match(s))


_RAID_RE = re.compile(r"^https?://raid\.org/\S+$", re.I)


def raid_format_ok(raid: str) -> bool:
    """Format sanity for a RAiD (Research Activity Identifier): RAiD is a resolvable URL/handle
    (https://raid.org/<prefix>/<suffix>), not a fixed-charset id like ORCID/ROR — so this is a light
    URL-shape regex only, per the C7 contract note ('RAiD is a URL/handle — light regex only')."""
    return bool(_RAID_RE.match((raid or "").strip()))


# PID-schema: an instrument-system PID (AuScope Instrument Registry). Like RAiD it is a resolvable
# URL/handle rather than a fixed-charset id, so the check is deliberately light and only a curator hint:
# an https:// URL, or a bare handle/DOI (a prefix/suffix pair, optionally an `hdl:` prefix) that the
# portal resolves against the handle/DOI resolver. Rejects whitespace and non-http(s) schemes (the exact
# shapes — javascript:, data:, a bare word — a curator would want flagged before it ships as a link).
_INSTRUMENT_PID_URL_RE = re.compile(r"^https?://[^\s/]+/\S+$", re.I)
_INSTRUMENT_PID_HANDLE_RE = re.compile(r"^(?:hdl:)?\d[\w.]*\/\S+$", re.I)   # e.g. 10.25914/x, 20.500/x, hdl:20.500/x


def instrument_pid_format_ok(pid: str) -> bool:
    """Format sanity for instruments[].pid — an https:// URL OR a bare handle/DOI. Deliberately light
    (no registry lookup), mirroring raid_format_ok: a curator hint, not a resolvability guarantee."""
    s = (pid or "").strip()
    return bool(_INSTRUMENT_PID_URL_RE.match(s) or _INSTRUMENT_PID_HANDLE_RE.match(s))


def _check_typed_relation(r, container: str, idx: int, entry: dict) -> None:
    """§2a: vocab-check the two TYPED fields the related-identifiers model adds to a source/relation
    entry — `relation` (the curated DataCite subset) and `identifier_type` (the small mint set).
    FAIL-CLOSED, byte-identically to the access.coordinates enum check: an out-of-vocab value would
    publish a wrong/ambiguous provenance claim, so it blocks. Absent/blank values are silent — the
    check validates the VALUE, not its presence (a typed source may legitimately omit either). Shared
    by the sources[] and related_identifiers[] loops so the two can never drift."""
    rel = entry.get("relation")
    if rel not in (None, "") and str(rel).strip() not in RELATION_TYPES:
        r.add("FAIL", container,
              f"{container}[{idx}].relation '{rel}' is not one of {tuple(sorted(RELATION_TYPES))} — a "
              f"typed provenance relation must use the ratified vocabulary (a mis-typed relation "
              f"publishes a wrong claim; an out-of-enum value cannot ship)")
    it = entry.get("identifier_type")
    if it not in (None, "") and str(it).strip() not in IDENTIFIER_TYPES:
        r.add("FAIL", container,
              f"{container}[{idx}].identifier_type '{it}' is not one of {tuple(sorted(IDENTIFIER_TYPES))}")


def parse_angle(tok: str):
    tok = (tok or "").strip().strip('"')
    if not tok:
        return None
    try:
        if ":" in tok:
            p = tok.split(":")
            sign = -1.0 if tok.lstrip().startswith("-") else 1.0
            mag = abs(float(p[0])) + (abs(float(p[1])) / 60 if len(p) > 1 and p[1] else 0) \
                + (abs(float(p[2])) / 3600 if len(p) > 2 and p[2] else 0)
            return sign * mag
        return float(tok)
    except ValueError:
        return None


class Report:
    def __init__(self):
        self.items = []
        self.manifest = []

    def add(self, level, check, msg):
        self.items.append({"level": level, "check": check, "message": msg})

    def worst(self):
        return max((LEVELS[i["level"]] for i in self.items), default=0)

    def counts(self):
        c = {"PASS": 0, "WARNING": 0, "FAIL": 0}
        for i in self.items:
            c[i["level"]] += 1
        return c


def _load_yaml(path: Path):
    try:
        import yaml  # noqa: PLC0415
        return yaml.safe_load(path.read_text())
    except ModuleNotFoundError:
        return _mini_yaml(path.read_text())  # tolerant fallback for CI without pyyaml


# >>> BEGIN generated _mini_yaml (vendored from ausmt engine; sync_validator_mini_yaml.py) >>>
# DO NOT EDIT BY HAND. This function is VENDORED verbatim from the ausmt engine's
# build_portal.py (engine/tests/test_mini_yaml_parity.py pins IT against PyYAML). Refresh with
#   python _validation/sync_validator_mini_yaml.py --write
# from a checkout with the ausmt monorepo beside this repo. MINI_YAML_PIN records the source
# commit + sha256; the surveys test-suite asserts this block matches the PIN (no silent drift).
def _mini_yaml(text: str) -> dict:
    """Small YAML-subset parser used only when PyYAML is unavailable, sufficient for AusMT
    `survey.yaml`. Handles nested maps, block sequences (of scalars and of maps), inline ``[]`` /
    ``{}`` and simple flow collections, block scalars (``>`` / ``|`` collapsed to one line), quotes,
    booleans/numbers, and ``#`` comments. It is NOT a general YAML parser; the build also accepts
    PyYAML and the two agree on the AusMT schema (guarded by ``tests/test_mini_yaml_parity.py``).
    Keep it in step with the survey.yaml schema."""
    import re

    def _strip_comment(v: str) -> str:
        if not v or v[0] in "\"'":
            return v.strip()
        i = v.find(" #")
        return (v[:i] if i >= 0 else v).strip()

    def _flow_split(s: str):
        out, depth, cur = [], 0, ""
        for ch in s:
            if ch in "[{":
                depth += 1; cur += ch
            elif ch in "]}":
                depth -= 1; cur += ch
            elif ch == "," and depth == 0:
                out.append(cur); cur = ""
            else:
                cur += ch
        if cur.strip():
            out.append(cur)
        return [x.strip() for x in out]

    def _scalar(v):
        v = _strip_comment(v)
        if v == "":
            return None
        if (v[0] == '"' and v[-1:] == '"') or (v[0] == "'" and v[-1:] == "'"):
            return v[1:-1]
        if v == "[]":
            return []
        if v == "{}":
            return {}
        if v[0] == "[" and v[-1:] == "]":
            inner = v[1:-1].strip()
            return [_scalar(x) for x in _flow_split(inner)] if inner else []
        if v[0] == "{" and v[-1:] == "}":
            d = {}
            for part in _flow_split(v[1:-1]):
                if ":" in part:
                    kk, _, vv = part.partition(":")
                    d[kk.strip()] = _scalar(vv)
            return d
        low = v.lower()
        if low in ("true", "false"):
            return low == "true"
        if low in ("null", "~"):
            return None
        try:
            return int(v)
        except ValueError:
            try:
                return float(v)
            except ValueError:
                return v

    toks = []
    for ln in text.splitlines():
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        toks.append((len(ln) - len(ln.lstrip(" ")), ln.strip()))
    n = len(toks)
    pos = [0]
    key_re = re.compile(r"^([\w.\-]+):\s*(.*)$")

    def _block_scalar(min_indent, style=">"):
        buf = []
        while pos[0] < n and toks[pos[0]][0] >= min_indent:
            buf.append(toks[pos[0]][1]); pos[0] += 1
        joiner = "\n" if style[0] == "|" else " "       # | literal keeps newlines; > folds to spaces
        text_out = joiner.join(buf)
        if not style.endswith("-") and text_out:        # clip (default) keeps one trailing newline
            text_out += "\n"
        return text_out

    def parse(min_indent):
        node = None
        while pos[0] < n:
            indent, content = toks[pos[0]]
            if indent < min_indent:
                break
            if content.startswith("- "):
                if node is None:
                    node = []
                if not isinstance(node, list):
                    break
                item = content[2:].strip()
                m = key_re.match(item)
                if m:
                    sub = {}
                    k, val = m.group(1), m.group(2).strip()
                    if val in (">", "|", ">-", "|-"):
                        pos[0] += 1; sub[k] = _block_scalar(indent + 2, val)
                    elif val == "":
                        pos[0] += 1
                        sub[k] = parse(indent + 3) if (pos[0] < n and toks[pos[0]][0] > indent + 1) else None
                    else:
                        sub[k] = _scalar(val); pos[0] += 1
                    while pos[0] < n:                       # sibling keys of the same list item
                        i2, c2 = toks[pos[0]]
                        if i2 == indent + 2 and not c2.startswith("- "):
                            m2 = key_re.match(c2)
                            if m2:
                                k2, v2 = m2.group(1), m2.group(2).strip()
                                if v2 in (">", "|", ">-", "|-"):
                                    pos[0] += 1; sub[k2] = _block_scalar(indent + 4, v2)
                                elif v2 == "":
                                    pos[0] += 1
                                    sub[k2] = parse(indent + 3) if (pos[0] < n and toks[pos[0]][0] > indent + 2) else None
                                else:
                                    sub[k2] = _scalar(v2); pos[0] += 1
                                continue
                        break
                    node.append(sub)
                else:
                    node.append(_scalar(item)); pos[0] += 1
                continue
            m = key_re.match(content)
            if not m:
                pos[0] += 1; continue
            if node is None:
                node = {}
            if not isinstance(node, dict):
                break
            k, val = m.group(1), m.group(2).strip()
            if val in (">", "|", ">-", "|-"):
                pos[0] += 1; node[k] = _block_scalar(indent + 1, val)
            elif val == "":
                pos[0] += 1
                node[k] = parse(indent + 1) if (pos[0] < n and toks[pos[0]][0] > indent) else None
            else:
                node[k] = _scalar(val); pos[0] += 1
        return node if node is not None else {}

    result = parse(0)
    return result if isinstance(result, dict) else {}
# <<< END generated _mini_yaml <<<


def _iso_date_ok(v) -> bool:
    """True iff `v` is an ISO calendar date (YYYY-MM-DD). Dependency-light: datetime.date.fromisoformat,
    the same check the C1 embargo gate uses. A non-string / malformed value is False, never a crash."""
    try:
        from datetime import date as _date  # noqa: PLC0415
        _date.fromisoformat(str(v).strip())
        return True
    except (ValueError, TypeError):
        return False


def _iso_date_or_year_ok(v) -> bool:
    """True for an ISO date (YYYY-MM-DD) OR a bare 4-digit year (YYYY). sources[].retrieved may be
    either (a dataset is often cited by acquisition year, not an exact retrieval date). A YAML-unquoted
    year loads as an int, so str()-coerce before matching (the mini_yaml fallback numeric-coerces too)."""
    s = str(v).strip()
    return bool(re.match(r"^\d{4}$", s)) or _iso_date_ok(s)


def validate(folder: Path, *, allow_large=False, allow_mth5=False) -> Report:
    r = Report()
    root = folder.resolve()

    # --- structure ---
    sy = folder / "survey.yaml"
    if not sy.exists():
        r.add("FAIL", "structure", "survey.yaml is missing")
        return r
    for req in ("README.md", "LICENSE.md"):
        r.add("PASS" if (folder / req).exists() else "WARNING", "structure",
              f"{req} {'present' if (folder/req).exists() else 'missing'}")
    tf_dir = folder / "transfer_functions" / "edi"
    edis = sorted(tf_dir.glob("*.edi")) if tf_dir.exists() else []
    mh_dir = folder / "transfer_functions" / "mth5"
    mh_files = (sorted(mh_dir.glob("*.h5")) + sorted(mh_dir.glob("*.mth5"))) if mh_dir.exists() else []
    if not edis and not mh_files:
        r.add("FAIL", "structure", "no transfer functions under transfer_functions/edi/ or transfer_functions/mth5/")

    # --- metadata ---
    # Tolerant of both the Prototype-20 structured schema (project_name; organisation as a map with
    # name/ror; data_types list) and the older flat schema (name; organisation string; data_type).
    try:
        meta = _load_yaml(sy) or {}
    except Exception as e:  # malformed YAML -> a clear FAIL at the contributor gate, not a raw traceback
        r.add("FAIL", "structure", f"survey.yaml is not valid YAML: {e}")
        return r
    if not isinstance(meta, dict):
        r.add("FAIL", "structure", "survey.yaml must be a YAML mapping (key: value pairs), not a list or scalar")
        return r
    name = meta.get("project_name") or meta.get("name")
    org = meta.get("organisation")
    org_name = org.get("name") if isinstance(org, dict) else org
    acc = meta.get("access")
    acc_val = acc.get("level") if isinstance(acc, dict) else acc
    required = [("slug", meta.get("slug")), ("project name", name), ("country", meta.get("country")),
                ("organisation", org_name), ("access", acc_val)]
    for label, val in required:
        present = val not in (None, "", "TBD", "TODO")
        r.add("PASS" if present else "FAIL", "metadata",
              f"required field '{label}' {'set' if present else 'missing/placeholder'}")
    # C1 access gate — enum + embargo date. Only run once access is present (the required-field loop above
    # already FAILs a missing access). access.level must be one of the enum (FAIL — required field, no legacy
    # excuse); embargo_until must be ISO YYYY-MM-DD when present (FAIL if malformed). A non-open level is a
    # WARNING (curator attention: the engine will withhold this survey's bytes). An embargoed level whose
    # embargo_until is in the PAST is a stale-embargo WARNING (the engine still withholds — a curator flips
    # level->open to release; it never auto-publishes on a lapsed date). Mirrors engine access_serve_state.
    if acc_val not in (None, "", "TBD", "TODO"):
        acc_norm = str(acc_val).strip().lower()
        if acc_norm not in ACCESS_LEVELS:
            r.add("FAIL", "metadata",
                  f"access.level '{acc_val}' is not one of {ACCESS_LEVELS} — this is a required, enumerated field")
        else:
            emb = acc.get("embargo_until") if isinstance(acc, dict) else None
            emb_raw = str(emb).strip() if emb not in (None, "") else ""
            emb_date = None
            if emb_raw:
                try:
                    from datetime import date as _date  # noqa: PLC0415 (dependency-light; import where used)
                    emb_date = _date.fromisoformat(emb_raw)
                except ValueError:
                    r.add("FAIL", "metadata",
                          f"access.embargo_until '{emb_raw}' is not an ISO date (YYYY-MM-DD)")
            if acc_norm != "open":
                r.add("WARNING", "metadata",
                      f"access.level is '{acc_norm}' (not open) — AusMT will list this survey but WITHHOLD its "
                      f"data bytes until a curator sets level=open")
            if acc_norm == "embargoed" and emb_date is not None:
                from datetime import date as _date2  # noqa: PLC0415
                if emb_date < _date2.today():
                    r.add("WARNING", "metadata",
                          f"access.embargo_until {emb_raw} is in the PAST but level is still 'embargoed' — the "
                          f"survey stays withheld; flip level to open to release it (embargo is not auto-lifted)")
    # C42 (owner queue): access.coordinates gates how station coordinates are SERVED by the engine
    # (exact / generalised to ~11 km / withheld). When present it MUST be one of the enum — an
    # out-of-vocab value would silently fall back to 'exact' and serve exact coordinates the curator
    # meant to protect, so FAIL it (no legacy corpus of bad values). Absent => exact (silent, the
    # record's zero-change default). Mirrors engine extract/_coordaccess.parse_coordinate_policy.
    if isinstance(acc, dict):
        coord_pol = acc.get("coordinates")
        if coord_pol not in (None, ""):
            if str(coord_pol).strip().lower() not in COORDINATE_POLICIES:
                r.add("FAIL", "metadata",
                      f"access.coordinates '{coord_pol}' is not one of {COORDINATE_POLICIES} — it gates "
                      f"how station coordinates are served; an out-of-enum value silently serves them exactly")
    # The slug MUST equal the package folder name: the directory IS the slug, and every downstream
    # identifier/URL is au.<slug>.<station>. A divergence silently forks the survey's identity, so
    # this is a FAIL (the _template states the slug must equal the folder name).
    slug_val = meta.get("slug")
    if slug_val not in (None, "", "TBD", "TODO"):
        folder_name = folder.resolve().name
        r.add("PASS" if slug_val == folder_name else "FAIL", "metadata",
              f"slug '{slug_val}' {'matches' if slug_val == folder_name else 'does NOT match'} "
              f"folder name '{folder_name}'")
        # Charset gate: the slug becomes `au.<slug>.<station>` in every id/URL. Anything outside
        # [a-z0-9-] would be silently rewritten by the pipeline's safe_component(), forking the survey's
        # identity between what the contributor declared and what the catalogue/portal publish. FAIL it.
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", str(slug_val)):
            r.add("FAIL", "metadata",
                  f"slug '{slug_val}' must be lowercase-hyphenated [a-z0-9-] (no spaces, dots, slashes, "
                  f"underscores or uppercase) — other characters fork the survey identity downstream")
    lic = meta.get("license", "")
    if str(lic).startswith("TBD"):
        r.add("WARNING", "metadata", "license is 'TBD' — must be set before publication")
    elif lic in (None, "", "TODO"):
        r.add("FAIL", "metadata", "required field 'licence' missing/placeholder")
    elif is_recognised_license(lic):
        # Recognised id (allow-list ∪ aliases). Note whether AusMT will redistribute the bytes or only
        # list the station (metadata-only) — the same gate the engine's redistributable() applies.
        served = "redistributable" if canon_license(lic) in {s.upper() for s in REDISTRIBUTABLE_LICENSES} else "recognised (metadata-only — download routes to the source archive)"
        r.add("PASS", "metadata", f"licence '{lic}' is a recognised id ({served})")
    else:
        # Set but NOT a recognised id: a typo like 'CC-BY-4.O' or free text. WARNING keeps the legacy-friendly
        # posture; under --strict (the publication gate) main() escalates every WARNING to a FAIL, so an
        # unrecognised licence CANNOT be published. This is the hole C6 closes: the old build gate redistributed
        # anything starting 'CC', and the validator accepted ANY non-placeholder string.
        r.add("WARNING", "metadata",
              f"licence '{lic}' is not a recognised AusMT licence id (see contract/licenses.json) — "
              f"fix the id before publication; --strict FAILs this")
    # LICENSE.md <-> survey.yaml consistency (design §2.5 — closes the silent-divergence seam). Parse the
    # C34-generated instrument's machine "Licence:  <id>" line (extract/_license_text emits exactly that);
    # WARN if its canonical id disagrees with survey.yaml `license` (survey.yaml is the machine source of
    # truth). A hand-authored LICENSE.md carries no such machine line and is NOT machine-checkable — the
    # check stays SILENT there (no false alarm, no report churn for the existing hand-authored corpus). It
    # emits an item ONLY on a real divergence, which is the seam this closes.
    lic_md = folder / "LICENSE.md"
    if lic_md.exists() and lic not in (None, "", "TODO") and not str(lic).startswith("TBD"):
        try:
            md_text = lic_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            md_text = ""
        m_lic = re.search(r"^\s*Licence:\s+(\S.*?)\s*$", md_text, re.M)
        if m_lic and canon_license(m_lic.group(1)) != canon_license(lic):
            r.add("WARNING", "license_md",
                  f"LICENSE.md states licence '{m_lic.group(1).strip()}' but survey.yaml license is "
                  f"'{lic}' — the two must agree (survey.yaml is the machine source of truth)")
    # C46 (design §2.1): schema_version validation + attribution/sources capture. Every check here is
    # SILENT on a clean 0.2 survey (no C46 fields, valid version, consistent LICENSE.md) so the existing
    # corpus's report is byte-unchanged; items are emitted only for a NEW field or a real problem.
    sv = meta.get("schema_version")
    attribution = meta.get("attribution")
    sources = meta.get("sources")
    has_c46 = attribution is not None or sources is not None
    if sv is not None:
        sv_str = str(sv).strip()
        if sv_str not in SCHEMA_VERSIONS:
            r.add("WARNING", "schema",
                  f"schema_version '{sv_str}' is not a known AusMT schema ({', '.join(SCHEMA_VERSIONS)})")
        elif sv_str == "0.2" and has_c46:
            r.add("WARNING", "schema",
                  'attribution/sources are schema-0.3 fields but schema_version is "0.2" — bump '
                  'schema_version to "0.3" so the C46 rules apply')
    # attribution: a nested map with a FROZEN key allow-list (the care-field drift lesson). Unknown keys
    # WARN by name; changes_made must be a bool; declared_date ISO-shape when present.
    if attribution is not None:
        if not isinstance(attribution, dict):
            r.add("WARNING", "attribution",
                  "attribution must be a mapping (key: value pairs), not a list or scalar")
        else:
            for k in attribution:
                if k not in ATTRIBUTION_KEYS:
                    r.add("WARNING", "attribution",
                          f"attribution.{k} is not a recognised attribution key (allowed: "
                          f"{', '.join(sorted(ATTRIBUTION_KEYS))})")
            cm = attribution.get("changes_made")
            if cm is not None and not isinstance(cm, bool):
                r.add("WARNING", "attribution",
                      f"attribution.changes_made must be a boolean true/false, got '{cm}'")
            dd = attribution.get("declared_date")
            if dd not in (None, "") and not _iso_date_ok(dd):
                r.add("WARNING", "attribution",
                      f"attribution.declared_date '{dd}' is not an ISO date (YYYY-MM-DD)")
    # sources: a LIST of upstream-dataset maps. Per entry: FROZEN key allow-list; licence validated
    # against the SAME vocab as the top-level license (unrecognised WARNs, FAILs under --strict);
    # retrieved ISO-date-or-year shape; profile vocab. A "ga" profile makes attribution.statement
    # REQUIRED (the GA form mandates exact wording).
    any_ga = False
    if sources is not None:
        if not isinstance(sources, list):
            r.add("WARNING", "sources",
                  "sources must be a LIST of upstream-dataset entries (one map per source dataset)")
        else:
            for idx, s in enumerate(sources):
                if not isinstance(s, dict):
                    r.add("WARNING", "sources",
                          f"sources[{idx}] must be a mapping (title/custodian/identifier/licence/…)")
                    continue
                for k in s:
                    if k not in SOURCE_KEYS:
                        r.add("WARNING", "sources",
                              f"sources[{idx}].{k} is not a recognised source key (allowed: "
                              f"{', '.join(sorted(SOURCE_KEYS))})")
                slic = s.get("licence")
                if slic not in (None, "", "TBD", "TODO"):
                    if is_recognised_license(slic):
                        r.add("PASS", "sources", f"sources[{idx}] licence '{slic}' is a recognised id")
                    else:
                        r.add("WARNING", "sources",
                              f"sources[{idx}] licence '{slic}' is not a recognised AusMT licence id "
                              f"(see contract/licenses.json) — fix it before publication; --strict FAILs this")
                ret = s.get("retrieved")
                if ret not in (None, "") and not _iso_date_or_year_ok(ret):
                    r.add("WARNING", "sources",
                          f"sources[{idx}].retrieved '{ret}' is not an ISO date (YYYY-MM-DD) or a year (YYYY)")
                prof = s.get("profile")
                if prof not in (None, "") and str(prof) not in SOURCE_PROFILES:
                    r.add("WARNING", "sources",
                          f"sources[{idx}].profile '{prof}' is not a recognised attribution profile "
                          f"({', '.join(sorted(SOURCE_PROFILES))})")
                if str(prof) == "ga":
                    any_ga = True
                # §2a: a sources[] entry MAY carry the typed relation/identifier_type (it IS the object
                # the related-identifiers model types) — vocab-check them fail-closed wherever they appear.
                _check_typed_relation(r, "sources", idx, s)
    # A GA-profile source mandates the exact custodian wording — attribution.statement REQUIRED.
    if any_ga:
        stmt = attribution.get("statement") if isinstance(attribution, dict) else None
        if stmt in (None, "", "TBD", "TODO"):
            r.add("WARNING", "attribution",
                  "a sources[].profile is 'ga' (Geoscience Australia), which mandates exact attribution "
                  "wording, but attribution.statement is not set — fix it before publication; --strict FAILs this")
    # §2a (identifiers design — the related-identifiers model): a repeatable list of TYPED provenance
    # relations to identifiers AusMT does NOT own. It TYPES the C46 sources[] object — SAME key allow-list
    # (SOURCE_KEYS), not a parallel structure — adding a `relation` and an `identifier_type`, both
    # FAIL-CLOSED vocabs (like access.coordinates). This is the wave-1 EXPAND field: it lands ALONGSIDE the
    # flat identifiers.dataset_doi + time_series.collection_pid, which keep being populated until a later
    # wave switches consumers over. SILENT when absent (the existing corpus carries no related_identifiers).
    related = meta.get("related_identifiers")
    if related is not None:
        if not isinstance(related, list):
            r.add("WARNING", "related_identifiers",
                  "related_identifiers must be a LIST of typed relation entries "
                  "({identifier, identifier_type, relation, custodian})")
        else:
            for idx, ri in enumerate(related):
                if not isinstance(ri, dict):
                    r.add("WARNING", "related_identifiers",
                          f"related_identifiers[{idx}] must be a mapping "
                          f"(identifier/identifier_type/relation/custodian)")
                    continue
                for k in ri:
                    if k not in SOURCE_KEYS:
                        r.add("WARNING", "related_identifiers",
                              f"related_identifiers[{idx}].{k} is not a recognised key (allowed: "
                              f"{', '.join(sorted(SOURCE_KEYS))})")
                _check_typed_relation(r, "related_identifiers", idx, ri)
    # §2b (identifiers design): identifiers.instrument_pid — the ONE survey/platform-level instrument PID
    # (PIDINST, e.g. 10.82388/<id>), the survey-layer counterpart to the deep per-serial EDI DOIs. Same
    # light format posture as instruments[].pid / RAiD above: an https:// URL or a bare handle/DOI,
    # WARNING-only (a curator hint, no registry lookup) — an additive/optional field must never BLOCK.
    # Absent/blank/placeholder is silent.
    ids = meta.get("identifiers") if isinstance(meta.get("identifiers"), dict) else {}
    inst_pid = ids.get("instrument_pid")
    if inst_pid not in (None, "", "TBD", "TODO") and not instrument_pid_format_ok(inst_pid):
        r.add("WARNING", "metadata",
              f"identifiers.instrument_pid '{inst_pid}' does not look like a survey/platform instrument "
              f"PID (expected an https:// URL or a bare handle/DOI, e.g. 10.82388/<id>)")
    # §2a (the AusLAMP-SA redundancy the inventory found): identifiers.dataset_doi and the raw-TS
    # time_series.collection_pid carrying the BYTE-IDENTICAL value is the systematic pattern (all 7
    # AusLAMP-SA surveys reuse one NCI collection DOI as both) — a symptom of an empty dataset-DOI slot
    # papered over with the collection pointer. Surface it at curation time as a WARNING (never a FAIL —
    # the data is publishable): the fix is to model the shared value as a single related_identifiers
    # relation row, not to keep it in two roles. Trimmed-string compare (a stray space is not a real
    # distinction).
    ts = meta.get("time_series") if isinstance(meta.get("time_series"), dict) else {}
    dd, cp = ids.get("dataset_doi"), ts.get("collection_pid")
    if dd not in (None, "") and cp not in (None, "") and str(dd).strip() == str(cp).strip():
        r.add("WARNING", "provenance",
              f"identifiers.dataset_doi and time_series.collection_pid are byte-identical ('{dd}') — the "
              f"systematic AusLAMP-SA redundancy (one NCI collection DOI reused as both the dataset DOI and "
              f"the raw-TS pointer). Model it as a single related_identifiers relation row, not two roles")
    if not meta.get("identifiers", {}).get("dataset_doi") and not meta.get("identifiers", {}).get("survey_pid"):
        r.add("WARNING", "provenance", "no survey PID or dataset DOI — record will be badged 'provenance incomplete'")
    # C7: ORCID (ISO 7064 11-2 checksum) + ROR + RAiD format sanity — WARNING only (a curator hint;
    # these federated identifiers have real external registries this dependency-light validator does
    # not query). Absent/blank values are silent — these fields are optional, not required.
    li = meta.get("lead_investigator")
    orcid = li.get("orcid") if isinstance(li, dict) else None
    if orcid not in (None, "", "TBD", "TODO"):
        if not orcid_checksum_ok(orcid):
            r.add("WARNING", "metadata",
                  f"lead_investigator.orcid '{orcid}' is not a valid ORCID (bad format or failed ISO "
                  f"7064 11-2 checksum) — e.g. https://orcid.org/0000-0002-1825-0097")
    for pi in (meta.get("principal_investigators") or []):
        pi_orcid = pi.get("orcid") if isinstance(pi, dict) else None
        if pi_orcid not in (None, "", "TBD", "TODO") and not orcid_checksum_ok(pi_orcid):
            r.add("WARNING", "metadata",
                  f"principal_investigators ORCID '{pi_orcid}' is not a valid ORCID (bad format or "
                  f"failed ISO 7064 11-2 checksum)")
    org = meta.get("organisation")
    ror = org.get("ror") if isinstance(org, dict) else None
    if ror not in (None, "", "TBD", "TODO") and not ror_format_ok(ror):
        r.add("WARNING", "metadata",
              f"organisation.ror '{ror}' does not look like a ROR id (expected a bare 9-char id or "
              f"https://ror.org/<id>, e.g. https://ror.org/00892tw58)")
    raid = meta.get("identifiers", {}).get("project_raid") if isinstance(meta.get("identifiers"), dict) else None
    if raid not in (None, "", "TBD", "TODO") and not raid_format_ok(raid):
        r.add("WARNING", "metadata",
              f"identifiers.project_raid '{raid}' does not look like a RAiD URL (expected "
              f"https://raid.org/<prefix>/<suffix>)")
    # PID-schema: instruments[].pid (optional) — a persistent identifier for an instrument SYSTEM (the
    # AuScope Instrument Registry URL/handle). Same posture as ROR/RAiD above: WARNING-only curator hint,
    # deliberately light (no registry lookup — this validator is dependency-light and cannot resolve the
    # external registry). Absent/blank/placeholder values are silent (the field is optional, not required).
    for inst in (meta.get("instruments") or []):
        pid = inst.get("pid") if isinstance(inst, dict) else None
        if pid not in (None, "", "TBD", "TODO") and not instrument_pid_format_ok(pid):
            label = " ".join(str(x) for x in [inst.get("manufacturer"), inst.get("model")] if x) or "instrument"
            r.add("WARNING", "metadata",
                  f"instruments[].pid '{pid}' ({label}) does not look like an instrument-registry PID "
                  f"(expected an https:// URL or a bare handle/DOI, e.g. "
                  f"https://instruments.auscope.org.au/... or 10.25914/<id>)")
    ver = meta.get("version")
    if not ver:
        r.add("WARNING", "metadata", "no version — recommend semantic versioning, e.g. 1.0.0")
    elif not re.match(r"^\d+\.\d+\.\d+$", str(ver)):
        r.add("WARNING", "metadata", f"version '{ver}' is not semantic (expected MAJOR.MINOR.PATCH)")
    coll = meta.get("collection")
    if isinstance(coll, dict) and coll.get("id"):
        cid = str(coll["id"])
        if not re.match(r"^[a-z0-9]+(-[a-z0-9]+)*$", cid):
            r.add("WARNING", "collection",
                  f"collection id '{cid}' is not lowercase-hyphenated — see the AusMT docs developer/collection-ids.md "
                  f"(curator confirms it is the correct, existing programme id)")
        else:
            r.add("PASS", "collection", f"collection id '{cid}' well-formed")
        status = coll.get("status")
        if status is not None and str(status) not in ("active", "completed", "archived"):
            r.add("WARNING", "collection",
                  f"collection status '{status}' is not one of active/completed/archived")
    # nci_base (optional): a contributor-supplied NCI THREDDS fileServer dir concatenated into the
    # published download URL. Validate scheme + host so a typo'd or non-http(s) value can't ship a
    # broken/unsafe link (the engine also drops a non-http(s) nci_base defensively).
    nci_base = meta.get("nci_base")
    if nci_base is not None and str(nci_base).strip():
        if re.match(r"^https?://[^\s/]+/.+", str(nci_base).strip()):
            r.add("PASS", "distribution", "nci_base is a well-formed absolute http(s) URL")
        else:
            r.add("FAIL", "distribution",
                  f"nci_base must be an absolute http(s) URL to a NCI THREDDS fileServer directory, got "
                  f"'{nci_base}' — a typo'd scheme/host would publish broken or unsafe download links")
    rn = meta.get("release_notes")
    if rn is not None:
        if not isinstance(rn, list):
            r.add("WARNING", "metadata", "release_notes should be a list of {version, date, note}")
        else:
            for entry in rn:
                if not (isinstance(entry, dict) and entry.get("version")):
                    r.add("WARNING", "metadata", "each release_notes entry needs at least a 'version'")
                    break

    # --- security: traversal, symlinks, archives, extensions, size, magic bytes ---
    for f in folder.rglob("*"):
        rel = f.relative_to(folder)
        # path traversal / absolute / parent escapes
        if ".." in rel.parts or f.is_symlink():
            r.add("FAIL", "security", f"unsafe path or symlink: {rel}")
            continue
        try:
            if not str(f.resolve()).startswith(str(root)):
                r.add("FAIL", "security", f"path escapes survey root: {rel}")
                continue
        except OSError:
            r.add("FAIL", "security", f"unresolvable path: {rel}")
            continue
        if not f.is_file():
            continue
        ext = f.suffix.lower()
        if ext in DISALLOWED_EXT:
            r.add("FAIL", "security", f"disallowed executable/script type: {rel}")
        if ext in ARCHIVE_EXT:
            r.add("FAIL", "security", f"archives not accepted in a survey package (submit extracted files): {rel}")
        if f.stat().st_size > MAX_FILE_MB * 1e6:
            lvl = "WARNING" if allow_large else "FAIL"
            r.add(lvl, "security", f"file exceeds {MAX_FILE_MB} MB: {rel}"
                  + ("" if allow_large else " (curator may override with --allow-large)"))
        # magic-byte / anti-masquerade for declared binary TF types
        if ext in MAGIC:
            with f.open("rb") as fh:
                head = fh.read(len(MAGIC[ext]))
            if head != MAGIC[ext]:
                r.add("FAIL", "security", f"{rel}: declared {ext} but content is not {ext} (magic-byte mismatch)")
        # anti-masquerade for .edi (a TEXT format): EDIs are printable text (>MARKERS / KEY=VALUE). A NUL
        # byte means binary content — a renamed executable/zip/image, or a polyglot with a valid-looking
        # HEAD and an appended binary payload that the coordinate parse alone would not catch.
        if ext == ".edi" and b"\x00" in f.read_bytes():
            r.add("FAIL", "security", f"{rel}: declared .edi but content is binary (NUL byte) — possible masquerade")
    # Antivirus is a CI responsibility, not this validator's. If CI has already run ClamAV it
    # sets AUSMT_CLAMAV_RAN=1, and we record PASS so --strict does not fail an already-scanned
    # survey. Outside CI we stay honest: a WARNING that the scan was NOT performed here.
    if os.environ.get("AUSMT_CLAMAV_RAN") == "1":
        r.add("PASS", "security", "antivirus handled upstream (ClamAV ran in CI)")
    else:
        r.add("WARNING", "security",
              "antivirus (ClamAV) scan is NOT performed by this validator; it runs as a CI step "
              "(see .github/workflows). Set AUSMT_CLAMAV_RAN=1 once scanned to clear this.")
    accepted = ALLOWED_TF_EXT | (OPTIN_TF_EXT if allow_mth5 else set())
    tf_files = list((folder / "transfer_functions").rglob("*")) if (folder / "transfer_functions").exists() else []
    for f in tf_files:
        if not f.is_file():
            continue
        if f.suffix.lower() not in accepted:
            extra = "" if allow_mth5 else " (.edi and .mth5 accepted; enable EMTF-XML/.zmm/.zrr/.j with --allow-optin-formats)"
            r.add("FAIL", "security", f"unaccepted file type in transfer_functions/: {f.relative_to(folder)}{extra}")

    # generated provenance manifest: SHA256 for every accepted file (anti-tamper / canonicalisation record)
    man = []
    for f in sorted(folder.rglob("*")):
        if f.is_file() and not f.is_symlink():
            try:
                man.append({"path": str(f.relative_to(folder)),
                            "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
                            "bytes": f.stat().st_size})
            except OSError:
                pass
    r.manifest = man
    r.add("PASS", "manifest", f"SHA256 manifest generated for {len(man)} files")

    # --- EDI parse + coordinates + duplicates (lightweight; mt_metadata used if available) ---
    seen_xy = {}
    extent = meta.get("geographic_extent") or {}
    if not isinstance(extent, dict):
        extent = {}   # mini_yaml fallback leaves an inline {…} unparsed; fall back to the national box
    def _flt(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None   # a quoted/garbage bound (west: "136.97") -> treated as undeclared, never a str<float crash
    w, e, s, n = (_flt(extent.get("west")), _flt(extent.get("east")), _flt(extent.get("south")), _flt(extent.get("north")))
    box = (w, e, s, n) if None not in (w, e, s, n) else AUS_BBOX
    n_parse_fail = 0
    for p in edis:
        raw = p.read_text(encoding="latin-1", errors="replace")
        # tolerate CRLF/CR and indented >markers / KEY= lines (EDL/BIRRP) — same normalisation
        # the science readers use, so the validator and the pipeline agree on what is parseable.
        raw = _norm(raw)
        lat = parse_angle(_grab(raw, "LAT"))
        lon = parse_angle(_grab(raw, "LONG"))
        if lat is None or lon is None:
            n_parse_fail += 1
            r.add("FAIL", "edi_parse", f"{p.name}: missing coordinates (LAT/LONG in HEAD)")
            continue
        if not re.search(r"^>FREQ", raw, re.M):
            if re.search(r"SPECTRA", raw):
                # Phoenix EMpower spectra-section EDI: no >FREQ/impedance block, but the AusMT
                # extractor recovers Z + tipper from the cross-power SPECTRA directly (dependency-
                # free), so this is a supported, first-class format — not a failure or a special case.
                r.add("PASS", "edi_parse",
                      f"{p.name}: spectra-section EDI (cross-power SPECTRA) — supported; "
                      f"impedance is recovered from the spectra at build time")
            else:
                n_parse_fail += 1
                r.add("FAIL", "edi_parse", f"{p.name}: missing FREQ block (no impedance found)")
                continue
        if not (box[2] <= lat <= box[3] and box[0] <= lon <= box[1]):
            r.add("WARNING", "coordinates", f"{p.name}: lat/lon {lat:.3f},{lon:.3f} outside declared extent")
        key = (round(lat, 4), round(lon, 4))
        if key in seen_xy:
            r.add("WARNING", "duplicates", f"{p.name}: ~same location as {seen_xy[key]} (<~10 m)")
        else:
            seen_xy[key] = p.name
    if edis and n_parse_fail == 0:
        r.add("PASS", "edi_parse", f"all {len(edis)} EDIs parsed with coordinates")

    # --- MTH5 transfer-function validation (structure / version / TF groups / station metadata) ---
    for h5 in mh_files:
        _validate_mth5(h5, r)

    # --- citation/DOI sanity ---
    for pub in (meta.get("publications") or []):
        doi = pub.get("doi") if isinstance(pub, dict) else None
        if doi and not re.match(r"^10\.\d{4,9}/\S+$", str(doi)):
            r.add("WARNING", "citation", f"publication DOI looks malformed: {doi}")

    return r


def _grab(text, key):
    m = re.search(rf"^{key}\s*=\s*(.+?)\s*$", text, re.M | re.I)
    return m.group(1).strip().strip('"') if m else None


_HDF5_MAGIC = b"\x89HDF\r\n\x1a\n"


def _validate_mth5(path: Path, r) -> None:
    """Validate an MTH5 transfer-function file: HDF5 signature, then (if mth5/mt_metadata are
    installed) supported version, transfer-function groups present, and station metadata
    extractable. AusMT reads only transfer functions + metadata from MTH5 — never raw time series.
    Corrupt/unsupported files FAIL; missing-but-non-fatal metadata WARNs; absent libraries WARN
    (CI installs them and is authoritative)."""
    try:
        with open(path, "rb") as fh:
            sig = fh.read(8)
    except OSError as exc:
        r.add("FAIL", "mth5", f"{path.name}: cannot read file ({exc})")
        return
    if sig != _HDF5_MAGIC:
        r.add("FAIL", "mth5", f"{path.name}: not a valid HDF5/MTH5 file (bad signature)")
        return

    try:
        from mth5.mth5 import MTH5  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        r.add("WARNING", "mth5",
              f"{path.name}: HDF5 signature OK; mth5/mt_metadata not installed here so structure, "
              f"version and TF groups are validated in CI (pip install mth5 mt_metadata).")
        return

    m = MTH5()
    try:
        m.open_mth5(str(path), mode="r")
    except Exception as exc:  # noqa: BLE001
        r.add("FAIL", "mth5", f"{path.name}: not a readable MTH5 file ({exc})")
        return
    try:
        ver = getattr(m, "file_version", None)
        if ver:
            r.add("PASS", "mth5", f"{path.name}: MTH5 v{ver}")
        tf_ids = []
        try:
            df = m.tf_summary.to_dataframe() if getattr(m, "tf_summary", None) is not None else None
            if df is not None and len(df):
                tf_ids = list(df["station"]) if "station" in df.columns else list(range(len(df)))
        except Exception:  # noqa: BLE001
            tf_ids = []
        if not tf_ids:
            # fall back to walking the groups
            try:
                tf_ids = [k for k in m.transfer_functions_group.groups_list] if getattr(
                    m, "transfer_functions_group", None) is not None else []
            except Exception:  # noqa: BLE001
                tf_ids = []
        if tf_ids:
            r.add("PASS", "mth5", f"{path.name}: {len(tf_ids)} transfer-function group(s) present")
        else:
            r.add("FAIL", "mth5", f"{path.name}: no transfer-function groups found")
        # station metadata extractable?
        try:
            stns = list(m.station_list) if getattr(m, "station_list", None) is not None else []
        except Exception:  # noqa: BLE001
            stns = []
        if not stns and not tf_ids:
            r.add("WARNING", "mth5", f"{path.name}: station metadata not extractable")
    finally:
        try:
            m.close_mth5()
        except Exception:  # noqa: BLE001
            pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true", help="treat WARNINGs as failures")
    ap.add_argument("--allow-large", action="store_true",
                    help="curator override: downgrade >MAX_FILE_MB from FAIL to WARNING")
    ap.add_argument("--allow-optin-formats", dest="allow_mth5", action="store_true",
                    help="also accept EMTF-XML/.zmm/.zrr/.j (EDI and MTH5 are accepted by default)")
    ap.add_argument("--allow-mth5", dest="allow_mth5", action="store_true", help=argparse.SUPPRESS)  # deprecated alias, same dest
    a = ap.parse_args(argv)
    rep = validate(Path(a.folder), allow_large=a.allow_large, allow_mth5=a.allow_mth5)
    for i in rep.items:
        print(f"[{i['level']:7}] {i['check']:12} {i['message']}")
    c = rep.counts()
    print(f"\n{c['PASS']} PASS · {c['WARNING']} WARNING · {c['FAIL']} FAIL")
    if a.json:
        Path(a.json).write_text(json.dumps({"counts": c, "items": rep.items, "manifest": rep.manifest}, indent=2))
    fail = rep.worst() == LEVELS["FAIL"] or (a.strict and rep.worst() >= LEVELS["WARNING"])
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
