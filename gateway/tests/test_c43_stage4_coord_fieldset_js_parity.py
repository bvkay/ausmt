"""C43 Stage-4 — executable JS pins for the INTERACTIVE per-station coordinate-policy fieldset.

The C43-S2a standing rule requires the stations-panel behaviour to be pinned with EXECUTABLE JS (the
functions actually run under node), never a string match alone. This pins the DOM-free CORE of the
override fieldset — the functions the drill-down radios and the Save button rest on:

  * buildOverrideControls — the per-BASE control state, keyed via the base-id surface (baseStationId):
    a variant record collapses to its engine base; a DATAID-with-a-dot record keys by its OWN id
    (never a file stem, never a dot-guess); variant siblings SHARE one control (D2);
  * assembleOverrideMap — the {BASE_station_id: policy} map to POST: a base at INHERIT emits NO key;
  * overrideMapChanged — the Save no-op guard (an unchanged map must not POST — no phantom version bump).

Plus the END-TO-END editor pin (extending the editor's KEY-PARITY mechanism): the fieldset-assembled
payload, produced in Node from real records, is read back by the REAL engine parse_coordinate_policy +
validate_overrides over the SAME records — every key accepted, effective, and base-keyed (siblings
covered) — so a JS↔engine key/vocab drift can never pass silently.

Reds on pre-change code: buildOverrideControls / assembleOverrideMap / overrideMapChanged did not exist
in STATIONS_JS (the extraction assert raises), so the interactive fieldset had no drivable core — the
A2 stop-and-report gap this lane closes.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from gateway import curatorpage
from gateway.tests.test_c43_stage2a_js_parity import (  # reuse the pure-node driver harness
    _extract_js_function,
    _run_node,
    pytestmark,  # node-absent skip (deliberately NOT on the gateway skip tripwire)
)

__all__ = ["pytestmark"]


# The REAL engine coordinate-access parser, loaded from its file by path (engine-truth), exactly as
# test_editor_form.py loads it: engine/ is not a package, the module imports only pathlib, so it loads
# cleanly in the stack-less gateway test env.
_ENGINE_COORDACCESS_PY = Path(__file__).resolve().parents[2] / "engine" / "extract" / "_coordaccess.py"


def _load_engine_coordaccess():
    spec = importlib.util.spec_from_file_location("_ausmt_engine_coordaccess_fieldset_ro",
                                                  _ENGINE_COORDACCESS_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _core_driver(tail: str) -> str:
    """A node driver carrying the fieldset's DOM-free core (baseStationId + the three override helpers)
    plus a per-test `tail` that reads the JSON payload from argv[2] and writes a JSON result to stdout."""
    js = curatorpage.STATIONS_JS
    return (
        "import { readFileSync } from 'fs';\n"
        + _extract_js_function(js, "baseStationId") + "\n"
        + _extract_js_function(js, "buildOverrideControls") + "\n"
        + _extract_js_function(js, "assembleOverrideMap") + "\n"
        + _extract_js_function(js, "overrideMapChanged") + "\n"
        + "const P = JSON.parse(readFileSync(process.argv[2], 'utf8'));\n"
        + tail)


# A realistic served-row set mirroring the engine's own records: a DATAID-with-a-dot NON-variant
# station (id 'CP1L04.2', file stem 'ALPHA' — the dot is part of the DATAID, NOT a variant tag), a
# processing-variant PAIR of one physical site (MBV20.a / MBV20.b, base 'MBV20'), and a plain station.
# base_ids.json (the engine base-id surface) lists ONLY the variant stations.
_STATIONS = [
    {"ausmtId": "au.s.cp1l04.2", "catId": "CP1L04.2"},
    {"ausmtId": "au.s.mbv20.a", "catId": "MBV20.a"},
    {"ausmtId": "au.s.mbv20.b", "catId": "MBV20.b"},
    {"ausmtId": "au.s.cp1l10", "catId": "CP1L10"},
]
_BASE_IDS = {"au.s.mbv20.a": "MBV20", "au.s.mbv20.b": "MBV20"}


def test_js_key_construction_from_base_id_surface(tmp_path):
    """EXECUTABLE KEY-CONSTRUCTION PIN. buildOverrideControls keys each control STRICTLY via the base-id
    surface: a variant record collapses to its engine base ('MBV20'); a DATAID-with-a-dot record keys by
    its OWN catalogue id ('CP1L04.2'), NEVER the file stem ('ALPHA') and NEVER a dot-stripped guess
    ('CP1L04'); a plain station keys by its own id. Explicit-vs-inherit prefill comes from the current
    survey.yaml map. FAILS IF a fieldset key is a stem, a variant-suffixed id, or a dot-guess (the exact
    D2 / probe-e keys the engine's validate_overrides forbids)."""
    tail = ("const c = buildOverrideControls(P.stations, P.baseMap, P.overrides);\n"
            "const out = {};\n"
            "for (const k in c) out[k] = { control: c[k].control, explicit: c[k].explicit, "
            "members: c[k].members.slice().sort() };\n"
            "process.stdout.write(JSON.stringify(out));\n")
    got = _run_node(tmp_path, _core_driver(tail),
                    {"stations": _STATIONS, "baseMap": _BASE_IDS,
                     "overrides": {"MBV20": "withheld"}})
    # exactly the three BASE keys — the variant pair collapsed to ONE.
    assert set(got) == {"CP1L04.2", "MBV20", "CP1L10"}, got
    # the DATAID-with-a-dot record keyed by its OWN id — never the stem, never a dot-strip.
    assert "ALPHA" not in got and "CP1L04" not in got, got
    # the variant-suffixed ids are NOT keys (the base carries them).
    assert "MBV20.a" not in got and "MBV20.b" not in got, got
    # prefill honesty: the survey.yaml override shows EXPLICIT; the others INHERIT.
    assert got["MBV20"]["control"] == "withheld" and got["MBV20"]["explicit"] is True
    assert got["CP1L04.2"]["control"] == "inherit" and got["CP1L04.2"]["explicit"] is False
    assert got["CP1L10"]["control"] == "inherit" and got["CP1L10"]["explicit"] is False


def test_js_sibling_variants_share_one_control(tmp_path):
    """EXECUTABLE SIBLING-INVARIANT PIN (D2). The two processing variants of one physical site
    (MBV20.a / MBV20.b) resolve to the SAME base key and therefore ONE control, whose members list
    names both siblings. Setting that control writes a SINGLE base-keyed override that covers all
    variants. FAILS IF a sibling gets its own control (two competing keys) or a variant serves the
    physical site's true position while its sibling is masked (the variant class fix-round-2 outlawed)."""
    tail = ("const c = buildOverrideControls(P.stations, P.baseMap, {});\n"
            "process.stdout.write(JSON.stringify({\n"
            "  keys: Object.keys(c).sort(),\n"
            "  mbv20members: c['MBV20'] ? c['MBV20'].members.slice().sort() : null,\n"
            "}));\n")
    # drive with ONLY the variant pair to make the collapse unambiguous.
    pair = [_STATIONS[1], _STATIONS[2]]
    got = _run_node(tmp_path, _core_driver(tail), {"stations": pair, "baseMap": _BASE_IDS})
    assert got["keys"] == ["MBV20"], "both variants must collapse to the single base control"
    assert got["mbv20members"] == ["MBV20.a", "MBV20.b"], (
        "the shared control must reference both sibling rows honestly")


def test_js_inherit_position_emits_no_key(tmp_path):
    """EXECUTABLE INHERIT ROUND-TRIP PIN. assembleOverrideMap emits a key ONLY for a base whose control
    is an explicit policy; a base at INHERIT (the 4th position) emits NO key — it follows the survey
    default (the inherit-removes / byte-unchanged promise the editor_form assembly honours server-side).
    FAILS IF an inherit-position station lands in the POSTed map (a phantom override), or an explicit one
    is dropped."""
    tail = ("const c = buildOverrideControls(P.stations, P.baseMap, {});\n"
            "c['MBV20'].control = 'generalised';\n"     # explicit
            "c['CP1L04.2'].control = 'withheld';\n"     # explicit
            "c['CP1L10'].control = 'inherit';\n"        # inherit -> omitted
            "process.stdout.write(JSON.stringify(assembleOverrideMap(c)));\n")
    got = _run_node(tmp_path, _core_driver(tail), {"stations": _STATIONS, "baseMap": _BASE_IDS})
    assert got == {"MBV20": "generalised", "CP1L04.2": "withheld"}, got
    assert "CP1L10" not in got, "an inherit-position station must not appear in the override map"
    # an ALL-inherit set (nothing pinned) assembles to the EMPTY map (no key written at all).
    tail_empty = ("const c = buildOverrideControls(P.stations, P.baseMap, {});\n"
                  "process.stdout.write(JSON.stringify(assembleOverrideMap(c)));\n")
    empty = _run_node(tmp_path, _core_driver(tail_empty), {"stations": _STATIONS, "baseMap": _BASE_IDS})
    assert empty == {}, "an all-inherit fieldset writes no overrides key (byte-unchanged promise)"


def test_js_unchanged_map_is_a_noop(tmp_path):
    """EXECUTABLE NO-OP PIN. overrideMapChanged is the Save guard: an assembled map EQUAL to the survey's
    current one (order-independent) must report NO change (Save short-circuits — no phantom version bump);
    any add / remove / value change reports changed. FAILS IF an unchanged resubmit would POST (a spurious
    diff / version bump on a policy-bearing survey), or a real change is missed."""
    tail = ("process.stdout.write(JSON.stringify(P.cases.map(function (c) {\n"
            "  return overrideMapChanged(c.assembled, c.current);\n"
            "})));\n")
    cases = [
        # identical (different key order) -> NOT changed.
        {"assembled": {"MBV20": "generalised", "CP1L04.2": "withheld"},
         "current": {"CP1L04.2": "withheld", "MBV20": "generalised"}},
        # both empty -> NOT changed.
        {"assembled": {}, "current": {}},
        # a value changed -> changed.
        {"assembled": {"MBV20": "withheld"}, "current": {"MBV20": "generalised"}},
        # a key added -> changed.
        {"assembled": {"MBV20": "generalised", "CP1L10": "withheld"}, "current": {"MBV20": "generalised"}},
        # a key removed (inherit) -> changed.
        {"assembled": {}, "current": {"MBV20": "generalised"}},
    ]
    got = _run_node(tmp_path, _core_driver(tail), {"cases": cases})
    assert got == [False, False, True, True, True], got


# ---- END-TO-END editor pin: JS-assembled payload through the REAL engine -------------------------
# Realistic engine records [(path, record), ...] the way build_portal's parsed + _disambiguate'd
# records look — the SAME shape test_editor_form._override_records uses, extended with the
# DATAID-with-a-dot non-variant station so the base id carries a legitimate '.' (never dot-stripped).
def _engine_records():
    return [
        (Path("ALPHA.edi"), {"id": "CP1L04.2", "variant": None, "ausmt_id": "au.s.cp1l04.2"}),
        (Path("MBV20_lemi.edi"), {"id": "MBV20.a", "variant": "a", "ausmt_id": "au.s.mbv20.a"}),
        (Path("MBV20_ohmega.edi"), {"id": "MBV20.b", "variant": "b", "ausmt_id": "au.s.mbv20.b"}),
        (Path("CP1L10.edi"), {"id": "CP1L10", "variant": None, "ausmt_id": "au.s.cp1l10"}),
    ]


def test_fieldset_payload_passes_real_engine_parse_and_validate(tmp_path):
    """END-TO-END KEY-PARITY PIN (the load-bearing one). The payload the JS fieldset ASSEMBLES — built in
    Node from real served rows + the base-id surface, with the curator's chosen positions applied — is
    fed through the editor_form assembly AND the REAL engine parse_coordinate_policy + validate_overrides
    over the SAME records. Every key is accepted, base-keyed, and EFFECTIVE (a base override covers ALL
    its variants); the variant-suffixed and stem ids the fieldset never emits would be REJECTED. FAILS IF
    a JS↔engine key/vocab drift makes an override silently absent, inert, or engine-rejected."""
    from gateway import editor_form

    # (1) Node builds the fieldset payload the way the drill-down Save does: base-keyed controls, the
    #     curator sets a variant site to generalised and the DATAID-with-a-dot site to withheld.
    tail = ("const c = buildOverrideControls(P.stations, P.baseMap, {});\n"
            "c['MBV20'].control = 'generalised';\n"
            "c['CP1L04.2'].control = 'withheld';\n"
            "process.stdout.write(JSON.stringify(assembleOverrideMap(c)));\n")
    payload = _run_node(tmp_path, _core_driver(tail), {"stations": _STATIONS, "baseMap": _BASE_IDS})
    assert payload == {"MBV20": "generalised", "CP1L04.2": "withheld"}, payload

    # (2) The editor assembles the access block from that payload (the ONE s_access_coordinate_overrides
    #     field), exactly as the hidden #coord-policy-form POSTs it.
    form = {
        "s_access_level": "open",
        "s_access_coordinate_overrides": json.dumps(payload),
        "o_access": json.dumps({"level": "open"}),
    }
    assembled = editor_form.assemble_section(form, "access")
    assert assembled["coordinate_overrides"] == payload

    # (3) The REAL engine reads that block back as the intended per-station policy and validates every
    #     key against the SAME records (engine-truth) — none is a stem, a variant-suffixed id, or inert.
    coordacc = _load_engine_coordaccess()
    records = _engine_records()
    default, overrides = coordacc.parse_coordinate_policy(assembled)
    assert default == "exact"
    assert overrides == payload, (
        f"engine parsed {overrides!r}, not the JS-assembled {payload!r} — a key/spelling drift would "
        f"make the per-station policy a silent no-op")
    coordacc.validate_overrides(overrides, records)   # no raise: every key is a real base id
    # each key is EFFECTIVE, and a BASE override (MBV20) covers BOTH variant records.
    mbv20_hits = [r for (_p, r) in records
                  if coordacc.station_policy(default, overrides, r.get("id"), r.get("variant"))
                  == "generalised"]
    assert sorted(r["id"] for r in mbv20_hits) == ["MBV20.a", "MBV20.b"], (
        "the base override must cover ALL processing variants of the physical site")
    cp_hits = [r for (_p, r) in records
               if coordacc.station_policy(default, overrides, r.get("id"), r.get("variant")) == "withheld"]
    assert [r["id"] for r in cp_hits] == ["CP1L04.2"], "the DATAID-with-a-dot base key must be effective"

    # (4) NON-VACUOUS counter-proof: the variant-suffixed id the fieldset NEVER emits IS rejected by the
    #     same validator — so the base-keying above is load-bearing, not incidental.
    _d, bad = coordacc.parse_coordinate_policy({"level": "open",
                                                "coordinate_overrides": {"MBV20.a": "withheld"}})
    try:
        coordacc.validate_overrides(bad, records)
    except coordacc.CoordinatePolicyError:
        pass
    else:
        raise AssertionError("engine accepted a variant-suffixed key — the base-keying pin is vacuous")
