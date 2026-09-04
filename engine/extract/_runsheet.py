#!/usr/bin/env python3
"""Survey-declared run metadata: the curated per-station acquisition facts a survey package may
commit as `run-metadata.csv` beside its EDIs.

The csv is a WHITELIST surface. Field sheets carry crew names, deployment notes and other text
that must never reach a served document, so only the columns named in COLUMNS are ever read;
anything else in the file is ignored and reported as a curation note. The engine performs no
fuzzy station matching here: `station_id` must equal the corpus station id byte-for-byte
(suffixed ids like C6_BxByReplaced included). The distiller that produces the csv from a field
sheet (extract/_tools/distill_run_metadata.py) owns the sheet-to-corpus id join, so the join is
reviewed by a human before it enters the corpus, and the build stays deterministic.

Run IDS are deliberately absent from this file: the per-survey run-id store (run-ids.yaml,
extract/_runids) remains the only id authority, so a station with sheet facts but no stored id
still publishes no runs[] and the gap is reported.

Stdlib only: a leaf like _runfacts, importable by the spawn workers' build_portal.
"""
from __future__ import annotations

import csv
from pathlib import Path

from _runfacts import CURATOR_SUPPLIED, _Doc, _instrument, _blank_document

FILENAME = "run-metadata.csv"

# The whole whitelist. A column not named here never crosses into a served document.
COLUMNS = (
    "station_id",
    "start", "end", "sample_rate_hz",
    "dipole_length_ex_m", "dipole_length_ey_m",
    "azimuth_ex_deg", "azimuth_ey_deg",
    "logger_manufacturer", "logger_model", "logger_serial", "logger_pid",
    "sensor_manufacturer", "sensor_model",
    "sensor_bx_serial", "sensor_bx_pid",
    "sensor_by_serial", "sensor_by_pid",
)
_REQUIRED = ("station_id",)

# Merge conflicts are reported per field; these are the scalar run/channel paths compared.
_CONFLICT_PATHS = (
    ("run", "sample_rate_hz"),
)


def _text(v):
    v = ("" if v is None else str(v)).strip()
    return "" if v in ("", "-") else v


def _number(v):
    v = _text(v)
    if not v:
        return None
    try:
        n = float(v)
    except ValueError:
        return None
    return n if n > 0 else None


def _isotime(v):
    """The schema types time_period members as format: date-time, so a value passes only as a
    FULL date+time (fromisoformat accepts a bare date, which the schema rejects - the sheets'
    date-only retrieve entries must go absent, never published as a non-time)."""
    from datetime import datetime
    v = _text(v)
    if not v:
        return None
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return v if ("T" in v or " " in v.strip()) else None


def _window(row):
    """The publishable (start, end) pair: each member a full date-time or None, and an end at or
    before its start is dropped (an inverted window is a sheet data-entry error - publishing it
    would assert a negative-duration run)."""
    from datetime import datetime
    start, end = _isotime(row.get("start")), _isotime(row.get("end"))
    inverted = False
    if start and end:
        s = datetime.fromisoformat(start.replace("Z", "+00:00"))
        e = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if e <= s:
            end, inverted = None, True
    return start, end, inverted


def load(pkgdir) -> tuple[dict, list]:
    """(rows-by-corpus-station-id, curation notes) for one survey package. Fail-closed: a sheet
    with a duplicate station_id or no station_id column asserts nothing at all (partial ingest
    would silently publish half a survey's acquisition record)."""
    notes: list = []
    if not pkgdir:
        return {}, notes
    path = Path(pkgdir) / FILENAME
    if not path.is_file():
        return {}, notes
    try:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            header = [h.strip() for h in (reader.fieldnames or [])]
            rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return {}, [f"curation: {FILENAME} unreadable ({exc}); no run metadata ingested"]
    unknown = [h for h in header if h not in COLUMNS]
    if unknown:
        notes.append(f"curation: {FILENAME} carries non-whitelist column(s) "
                     f"{', '.join(sorted(unknown))}; they are IGNORED - if this is a raw field "
                     f"sheet, replace it with the distiller's output")
    missing = [c for c in _REQUIRED if c not in header]
    if missing:
        return {}, notes + [f"curation: {FILENAME} lacks required column(s) "
                            f"{', '.join(missing)}; no run metadata ingested"]
    out: dict = {}
    for raw in rows:
        sid = _text(raw.get("station_id"))
        if not sid:
            continue
        if sid in out:
            return {}, notes + [f"curation: {FILENAME} repeats station_id {sid}; the sheet is "
                                f"refused whole rather than half-applied"]
        out[sid] = {c: _text(raw.get(c)) for c in COLUMNS if c != "station_id"}
    return out, notes


def _sheet_doc(row, station_id="", notes=None) -> dict:
    """A run_facts-shaped document holding ONLY what the sheet asserts, every value classed
    CURATOR_SUPPLIED (the sheet is the custodian's curated record, not a scrape). Values the
    schema cannot publish (date-only times, inverted windows) go absent WITH a curation note."""
    doc = _Doc()
    doc.dialect("survey_run_metadata")
    start, end, inverted = _window(row)
    if notes is not None:
        for member in ("start", "end"):
            v = _text(row.get(member))
            if v and _isotime(row.get(member)) is None:
                notes.append(f"curation: {station_id} run {member} {v!r} is not a full "
                             f"date-time; left absent (schema types time_period as date-time)")
        if inverted:
            notes.append(f"curation: {station_id} run end {_text(row.get('end'))!r} is not "
                         f"after start {_text(row.get('start'))!r}; end left absent - verify "
                         f"the sheet row")
    if start:
        period = {"start": start}
        if end:
            period["end"] = end
        doc.run("time_period", period, CURATOR_SUPPLIED, fact="time_period")
    rate = _number(row.get("sample_rate_hz"))
    if rate:
        doc.run("sample_rate_hz", rate, CURATOR_SUPPLIED, fact="sample_rate")
    logger = _instrument(row.get("logger_manufacturer"), row.get("logger_model"),
                         row.get("logger_serial"), row.get("logger_pid"))
    if logger:
        doc.run("data_logger", logger, CURATOR_SUPPLIED, fact="data_logger")
        if "serial_number" in logger:
            doc.fact("serial")
    for axis in ("ex", "ey"):
        length = _number(row.get(f"dipole_length_{axis}_m"))
        if length:
            doc.channel(axis, "dipole_length_m", length, CURATOR_SUPPLIED, fact="dipole_length")
        azimuth = _text(row.get(f"azimuth_{axis}_deg"))
        if azimuth:
            try:
                doc.channel(axis, "measurement_azimuth_deg", float(azimuth), CURATOR_SUPPLIED)
            except ValueError:
                pass
    for axis, comp in (("bx", "hx"), ("by", "hy")):
        sensor = _instrument(row.get("sensor_manufacturer"), row.get("sensor_model"),
                             row.get(f"sensor_{axis}_serial"), row.get(f"sensor_{axis}_pid"))
        if sensor:
            doc.channel(comp, "sensor", sensor, CURATOR_SUPPLIED, fact="sensor")
    return doc.doc


def merge(edi_facts, sheet_row, station_id, notes) -> dict:
    """One run_facts document from both sources. The sheet is applied FIRST (the accumulator keeps
    the first writer, so the curated record outranks the >INFO scrape), then the EDI document
    refills whatever the sheet left unsaid. A field both sources state differently is a curation
    signal, reported by name with both values - never silently resolved."""
    if not sheet_row:
        return edi_facts
    merged = _Doc()
    merged.doc = _sheet_doc(sheet_row, station_id=station_id, notes=notes)
    edi = edi_facts or _blank_document()
    for name in edi.get("dialects") or []:
        merged.dialect(name)
    for fact in edi.get("facts") or []:
        merged.fact(fact)
    for key, value in (edi.get("run") or {}).items():
        if key in merged.doc["run"]:
            if key == "sample_rate_hz" and value != merged.doc["run"][key]:
                notes.append(f"curation: {station_id} run.{key} differs between the survey run "
                             f"metadata ({merged.doc['run'][key]}) and the station's own header "
                             f"({value}); the curated value is published")
            continue
        merged.doc["run"][key] = value
        merged.doc["confidence"][f"run.{key}"] = (edi.get("confidence") or {}).get(f"run.{key}")
    for comp, channel in (edi.get("channels") or {}).items():
        target = merged.doc["channels"].setdefault(comp, {})
        merged.named(comp)
        for key, value in channel.items():
            if key in target:
                if key == "dipole_length_m" and value != target[key]:
                    notes.append(f"curation: {station_id} {comp}.{key} differs between the survey "
                                 f"run metadata ({target[key]}) and the station's own header "
                                 f"({value}); the curated value is published")
                continue
            target[key] = value
            merged.doc["confidence"][f"channels.{comp}.{key}"] = \
                (edi.get("confidence") or {}).get(f"channels.{comp}.{key}")
    for comp in edi.get("named_components") or []:
        merged.named(comp)
    for comp in edi.get("excluded_components") or []:
        merged.excluded(comp)
    return merged.doc
