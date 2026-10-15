"""The run-metadata.csv contract: the one column list, nullable rule, time-basis vocabulary, PID
form and instrument-class rule that the distillers (_tools/distill_run_metadata.py,
_tools/distill_master.py), the run-id tool and the validator all import.

It lives beside validate_survey.py because the engine and the gateway put this directory on the
import path to reach the validator; the tools under _tools add it themselves. Stdlib only.

The file is keyed by the PUBLISHED station id, one row per station: the engine publishes one run
per station, so a second row for a station has nowhere to go.
"""
from __future__ import annotations

import re

FILE_NAME = "run-metadata.csv"

# The columns the engine's run-sheet reader has always read, in their file order.
LEGACY_COLUMNS = (
    "station_id", "start", "end", "sample_rate_hz",
    "dipole_length_ex_m", "dipole_length_ey_m", "azimuth_ex_deg", "azimuth_ey_deg",
    "logger_manufacturer", "logger_model", "logger_serial", "logger_pid",
    "sensor_manufacturer", "sensor_model", "sensor_bx_serial", "sensor_bx_pid",
    "sensor_by_serial", "sensor_by_pid",
)
# sensor_* is induction coils only, one per axis, sharing sensor_manufacturer and sensor_model.
# A single-unit fluxgate magnetometer lives in magnetometer_* and is the sensor of every magnetic
# axis that names no coil. There is deliberately no owner and no operator column: a PIDINST DOI
# resolves to the registry's own record of the instrument.
NEW_COLUMNS = (
    "sensor_bz_serial", "sensor_bz_pid",
    "magnetometer_manufacturer", "magnetometer_model", "magnetometer_serial", "magnetometer_pid",
    "time_basis",
)
COLUMNS = LEGACY_COLUMNS + NEW_COLUMNS
REQUIRED_COLUMNS = ("station_id",)
NULLABLE_COLUMNS = frozenset(COLUMNS) - set(REQUIRED_COLUMNS)

# Every published start and end is true UTC. time_basis says how the row's times got there: read
# as UTC from the source, or shifted by -8 h from a logger clock that ran on local time. A row
# whose clock cannot be corrected carries no times at all rather than a caveat.
TIME_BASIS_UTC = "utc"
TIME_BASIS_CORRECTED = "corrected -8 h from a local clock"
TIME_BASIS = (TIME_BASIS_UTC, TIME_BASIS_CORRECTED)
TIME_COLUMNS = ("start", "end")

# Each PID column and the serial column of the same instrument role.
PID_SERIAL = {
    "logger_pid": "logger_serial",
    "sensor_bx_pid": "sensor_bx_serial",
    "sensor_by_pid": "sensor_by_serial",
    "sensor_bz_pid": "sensor_bz_serial",
    "magnetometer_pid": "magnetometer_serial",
}
PID_COLUMNS = tuple(PID_SERIAL)
# AuScope PIDINST DOIs, in the single form the corpus writes them. The registry mints lowercase
# alphanumeric suffixes.
PID_RE = re.compile(r"^https://doi\.org/10\.82388/[a-z0-9]+$")

# The instrument-class rule, read over manufacturer and model together, case-insensitively.
# No model below, no master model and no registry title matches both patterns.
FLUXGATE_RE = re.compile(r"fluxgate|bartington|mag-?03|lemi-?424|chamalaun", re.I)
COIL_RE = re.compile(r"induction coil|\bcoil\b|lemi-?120|mtc-?150", re.I)

# (manufacturer, model) pairs the patterns are held to: the master's coil and magnetometer
# models, its raw magnetometer_type values, the registry titles, and the pairs the corpus files
# record in sensor_*. A test asserts each classifies as listed.
COIL_MODELS = (
    ("", "LEMI-120"),
    ("", "LEMI-120 (inferred from logger family)"),
    ("", "Phoenix MTC-150"),
    ("", "Phoenix MTC-150L (contractor report)"),
    ("", "Phoenix coil (model unrecorded)"),
    ("", "induction coil (model unrecorded)"),
    ("", "induction coil"),
    ("", "LEMI-120 magnetic induction coil sensor"),
    ("", "Phoenix Geophysics MTC-150 magnetic induction coil sensor"),
    ("LEMI", "LEMI-120"),
    ("Phoenix", "MTC-150"),
    ("Phoenix", "MTC-150L"),
)
FLUXGATE_MODELS = (
    ("", "Bartington fluxgate"),
    ("", "LEMI-424 fluxgate"),
    ("", "Chamalaun-Walker fluxgate (self-recording)"),
    ("", "fluxgate (model unrecorded)"),
    ("", "Bartington"),
    ("", "Bartington (model not recorded)"),
    ("", "Bartington Instruments"),
    ("", "Bartington Mag-03"),
    ("", "Bartington Mag03"),
    ("", "Bartington Mag03MC70"),
    ("", "Bartington Mag03MS70"),
    ("", "Bartington fluxgate (unrecorded)"),
    ("", "Chamalaun-Walker microprocessor-based digital 3-component fluxgate magnetometer "
         "(self-recording)"),
    ("", "LEMI-424 3-component fluxgate magnetometer"),
    ("", "LEMI-424 integrated fluxgate"),
    ("", "Three-component fluxgate"),
    ("", "fluxgate"),
    ("", "fluxgate (3-component)"),
    ("", "LEMI-424 Magnetotelluric Data Acquisition System"),
    ("Bartington", "Mag03MS70"),
    ("Bartington", "Mag03MC70"),
    ("Bartington", "Mag03"),
    ("Bartington", "Mag-03"),
    ("Bartington", ""),
    ("Bartington Instruments", ""),
    ("LEMI", "LEMI-424 fluxgate"),
    ("LEMI", "LEMI-424 3-component fluxgate magnetometer"),
)


def instrument_class(manufacturer, model):
    """"coil", "fluxgate" or None for a (manufacturer, model) pair. None covers loggers, blanks,
    unknown names and a name matching both patterns."""
    text = f"{manufacturer or ''} {model or ''}".strip()
    if not text:
        return None
    coil, fluxgate = bool(COIL_RE.search(text)), bool(FLUXGATE_RE.search(text))
    if coil == fluxgate:
        return None
    return "coil" if coil else "fluxgate"


def pid_ok(value) -> bool:
    """True when `value` is an AuScope PIDINST DOI in the corpus form."""
    return bool(PID_RE.match(value or ""))
