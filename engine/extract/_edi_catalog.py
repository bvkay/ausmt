#!/usr/bin/env python3
"""AusMT: lightweight EDI header/coordinate helpers (importable library).

After the regex retirement mt_metadata builds the per-station record; what remains here are the
small, stdlib-only helpers the build pipeline (extract.build_portal) still needs and that
mt_metadata does NOT provide: coordinate reads + QC (coords_of / info_coords / parse_angle /
detect_coord_issue), the AU-state facet (state_of), and the Phoenix DATAID /
processing-note scrape (parse_dataid / proc_note). Fast across thousands of files; no install.
"""
import math
import re
from pathlib import Path

import _ediparse as ep  # noqa: E402  (shared _norm / cached read_norm)

NUM = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"

# Australian bounding box (w, e, s, n) — used to guard the AU-only state_of() facet so non-AU
# coordinates are not mislabelled as Australian states. Generous; matches the validator's box.
AUS_BBOX = (108.0, 156.0, -45.0, -8.0)


def parse_angle(tok: str):
    """Parse EDI angle: decimal degrees or DD:MM:SS(.s) or DD:MM(.m)."""
    tok = tok.strip().strip('"')
    if not tok:
        return None
    try:
        if ":" in tok:
            parts = tok.split(":")
            deg = float(parts[0])
            sign = -1.0 if tok.lstrip().startswith("-") else 1.0
            mag = abs(deg)
            if len(parts) > 1 and parts[1] != "":
                mag += abs(float(parts[1])) / 60.0
            if len(parts) > 2 and parts[2] != "":
                mag += abs(float(parts[2])) / 3600.0
            return sign * mag
        return float(tok)
    except ValueError:
        return None


def grab(text: str, key: str):
    m = re.search(rf"^{key}\s*=\s*(.+?)\s*$", text, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip().strip('"') if m else None


def state_of(lat, lon):
    """COARSE Australian-state guess from a coordinate — a crude lon/lat box, NOT authoritative
    geography (border cases misclassify).

    SCOPE: this is now a minor helper. The catalogue's region facet (r[9]) comes from the
    survey's `survey.yaml` `region`/`country`, NOT from this function. `state_of` is only used to
    seed the AusLAMP **raw/bulk-mode** per-state survey split (`build_portal` `--raw`), where there
    is no per-survey metadata to read. Non-AU coordinates return "" (the region guard).

    The dense threshold ladder below (especially the VIC/NSW split) is deliberately crude and its
    exact behaviour is pinned by tests/test_state_of.py — if you ever clean it up, keep that test
    green so the AusLAMP grouping does not silently move.
    """
    if lat is None or lon is None:
        return "?"
    # Region guard: this is Australia-only point-in-box geometry. For anything outside the
    # Australian bounding box (US Array, overseas, ocean-bottom, null-island parse errors) the AU
    # state labels are meaningless, so return "" rather than silently calling, e.g., a US station
    # "WA". For AU data the state/territory should ultimately come from survey.yaml, not geometry.
    w, e, s, n = AUS_BBOX
    if not (w <= lon <= e and s <= lat <= n):
        return ""
    if lon < 129:
        return "WA"
    if lon < 141:
        if lat > -26:
            return "NT"
        return "SA"
    if lat < -39.2:
        return "TAS"
    if lat < -34 and lon < 150.2 or (lat < -36):
        # Vic vs NSW rough split along the Murray; crude but fine for a facet
        if lat < -35.7 or (lat < -34 and lon < 142):
            return "VIC" if lat < -35.9 or lon < 147 and lat < -35.5 else "NSW"
    if lon >= 141 and lat > -29:
        return "QLD"
    return "NSW"


def detect_coord_issue(head_lat, head_lon, info_lat, info_lon, lat, lon):
    """Coordinate QC shared by every extractor (regex AND mt_metadata). Compares the HEAD
    coordinate (the EDI-standard, authoritative field) against the decimal INFO block and returns
    (coord_flag, candidates, coord_conflict_deg).

    The DMS sign-bug signature head == 2*floor(info) - info is SYMMETRIC (file content alone cannot
    say which side is right), so we DETECT AND FLAG ONLY; the chosen coordinate stays HEAD unless a
    survey declares a resolution (see build_portal._apply_coord_resolution). Direction must come
    from external ground truth per survey, not from the bytes."""
    coord_flag = None
    candidates = None

    def signature_delta(head, info):
        if head is None or info is None or info >= 0:
            return None
        return abs(head - (2 * math.floor(info) - info))

    sd = signature_delta(head_lat, info_lat)
    if sd is not None and abs((head_lat or 0) - (info_lat or 0)) > 0.01:
        nominal = abs((info_lat * 4) - round(info_lat * 4)) < 1e-3
        if sd < 2e-3:
            coord_flag = "dms_sign_ambiguous"
            candidates = {"head": [head_lat, head_lon], "info": [info_lat, info_lon]}
        elif sd < 0.05 and not nominal:
            coord_flag = "info_anomalous_review"
            candidates = {"head": [head_lat, head_lon], "info": [info_lat, info_lon]}

    coord_conflict = None
    if info_lat is not None and lat is not None and coord_flag is None:
        d = math.hypot(info_lat - lat, (info_lon or lon) - lon)
        if d > 0.01:  # ~1 km; for AusLAMP this usually flags nominal grid-node INFO coords
            coord_conflict = round(d, 4)
    return coord_flag, candidates, coord_conflict


def info_coords(raw):
    """Decimal INFO-block coordinates (Geotools style: 'LATITUDE: -29.3675'), or (None, None)."""
    mi_lat = re.search(r"LATITUDE\s*:\s*(" + NUM + ")", raw)
    mi_lon = re.search(r"LONGITUDE\s*:\s*(" + NUM + ")", raw)
    return (float(mi_lat.group(1)) if mi_lat else None,
            float(mi_lon.group(1)) if mi_lon else None)


def coords_of(path: Path):
    """(lat, lon) from an EDI's HEAD/REF/INFO fields via the light coord helpers only (read_norm, grab,
    parse_angle, info_coords) — a quick read for AusLAMP state-bucketing / QC that does NOT invoke
    mt_metadata. HEAD-first precedence (REF, then INFO as fallbacks)."""
    raw = ep.read_norm(path)
    head_lat = parse_angle(grab(raw, "LAT") or "")
    head_lon = parse_angle(grab(raw, "LONG") or "")
    ref_lat = parse_angle(grab(raw, "REFLAT") or "")
    ref_lon = parse_angle(grab(raw, "REFLONG") or "")
    info_lat, info_lon = info_coords(raw)
    lat = head_lat if head_lat is not None else (ref_lat if ref_lat is not None else info_lat)
    lon = head_lon if head_lon is not None else (ref_lon if ref_lon is not None else info_lon)
    return (round(lat, 6) if lat is not None else None,   # 6 dp: ~0.1 m, well under EDI precision
            round(lon, 6) if lon is not None else None)


# Phoenix EMpower remote-reference DATAID: 'P=<station> R=<remote> (H)'. Plain DATAIDs (A01, MBI21,
# Vulcan_A1) don't match and pass through. Best-effort, never raises.
_PHX_DATAID = re.compile(r"\bP\s*=\s*(\S+)\s+R\s*=\s*([^\s()]+)", re.I)
_INFO_BLOCK = re.compile(r"^>\s*INFO\b[^\n]*\n(.*?)(?=^\s*>|\Z)", re.S | re.M)
_REF_STATION = re.compile(r"REFERENCE\b.*?STATION\s+NAME:\s*(\S+)", re.S | re.I)
# Conservative email match (C3/PII scrub): >INFO free text is uncontrolled and has carried real
# operator emails (e.g. a curator's institutional address) straight into the PUBLIC, non-licence-gated
# station.json processing.note. Redact here, at the single point the note is derived, so every caller
# (build_portal, any future consumer) gets the scrubbed form for free. Original EDI bytes are untouched
# (D1) -- this only rewrites the returned string.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def parse_dataid(dataid):
    """Phoenix remote-reference DATAID 'P=<station> R=<remote> (H)' -> (station, remote_site).
    Plain DATAIDs pass through unchanged (remote=None). So a compound id is no longer mangled and the
    remote site is recovered. Best-effort, never raises."""
    if not dataid:
        return dataid, None
    m = _PHX_DATAID.search(dataid)
    return (m.group(1), m.group(2)) if m else (dataid, None)


def proc_note(text, dataid=None):
    """Free-text processing note from the EDI >INFO block (cleaned of common latin-1/UTF-8 mojibake)
    + the remote-reference SITE where named (Phoenix 'R=' DATAID, else a REFERENCE section). Format-
    agnostic (rich for Phoenix, sparse for Geotools), best-effort, never raises.
    Returns (note_or_None, remote_site_or_None)."""
    m = _INFO_BLOCK.search(text)
    note = (m.group(1).strip() if m else "")
    if note:  # mojibake from reading a UTF-8 EDI as latin-1 (degree sign, ohm sign)
        note = note.replace("Â°", "°").replace("[â¦]", "[Ω]").replace("â¦", "Ω").replace("Â", "").strip()
        note = _EMAIL.sub("[email removed]", note)  # PII scrub (C3): never let an operator email reach station.json
    remote = parse_dataid(dataid)[1] if dataid else None
    if not remote:
        r = _REF_STATION.search(text)
        remote = r.group(1) if r else None
    return (note or None), remote
