"""The six >INFO dialect extractors, and the acquisition facts each one really recovers.

mt_metadata reads a transfer function, not a field record: for every EDI in this corpus its Run
carries library defaults and none of the acquisition metadata the custodians wrote, because each
wrote it a different way inside the free-text >INFO section. extract/_runfacts.py has one extractor
per dialect; this suite pins what each recovers, and what it deliberately does not.

FIXTURES ARE REAL BYTES. Each tests/fixtures/runfacts/*.info file is the >INFO block of a published
corpus EDI, copied verbatim except that an email address is replaced by the same `[email removed]`
token the engine's own PII scrub writes:

    enriched-dotted.info      newer-volcanic-province-2019 / A1.edi
    mtpy-fieldnotes.info      auslamp-sa-ne-2014 / SA205.edi
    lemimt-site.info          auslamp-nsw-2016-21 / A23.edi
    empower-json.info         western-gawler-2023 / LineNo__StationNo_259.edi
    phoenix-fieldsheet.info   western-gawler-2023 / LineNo__StationNo_46.edi
    phoenix-compact.info      western-gawler-2023 / LineNo__StationNo_107.edi
    ga-geotools.info          auslamp-qld-2021-22 / OCCD30.edi

NON-VACUOUS (Invariant 10): every expected value below was read OUT of those bytes, so an extractor
that silently stopped matching fails here; and the build half asserts the facts reach the parse
product, whose shape change is what the C18 cache tag bump covers.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FIX = HERE / "fixtures" / "runfacts"
sys.path.insert(0, str(ROOT / "extract"))
sys.path.insert(0, str(ROOT))
import _runfacts as rf  # noqa: E402


def facts(name):
    return rf.run_facts((FIX / f"{name}.info").read_text(encoding="utf-8"))


# ---- one test per dialect family ---------------------------------------------------------------

def test_enriched_dotted_recovers_the_whole_run():
    """The AusMT header enrichment is the only dialect stating a run id, a nominal rate, a UTC
    window, instrument PIDs and a unit-bearing contact resistance."""
    d = facts("enriched-dotted")
    assert d["dialects"] == ["enriched-dotted"]
    assert d["run"]["id"] == "A1_001"
    assert d["run"]["sample_rate_hz"] == 1000.0
    assert d["run"]["time_period"]["start"] == "2019-08-20T10:53:03.000000+00:00"
    assert d["run"]["data_logger"] == {
        "manufacturer": "LEMI", "model": "LEMI-423", "serial_number": "#0034",
        "identifiers": [{"scheme": "DOI", "identifier": "10.82388/u3jf7ztm"}]}
    assert d["channels"]["ex"]["dipole_length_m"] == 43.0
    assert d["channels"]["ex"]["measurement_azimuth_deg"] == 180.0
    assert d["channels"]["hy"]["sensor"]["identifiers"] == [
        {"scheme": "DOI", "identifier": "10.82388/hy7tibrx"}]
    assert d["named_components"] == ["ex", "ey", "hx", "hy"]


def test_the_unit_bearing_contact_resistance_keeps_its_source_string():
    """Scope section 6: dual representation where parsing is safe, and the source text is never
    discarded. `1.82 kilo-ohms` is a STRING in a float-typed source field."""
    d = facts("enriched-dotted")
    assert d["channels"]["ex"]["contact_resistance"] == {
        "source_value": "1.82 kilo-ohms", "value": 1820.0, "unit": "ohm"}
    assert d["channels"]["ey"]["contact_resistance"]["source_value"] == "2.34 kilo-ohms"


def test_an_unparseable_unit_keeps_the_source_and_gains_no_number():
    """A missing value beats a confidently wrong one: an unknown unit yields source_value alone, so
    the schema's `unit required whenever value is present` can never be violated."""
    assert rf.unit_value("1.82 kilo-ohms") == {"source_value": "1.82 kilo-ohms",
                                               "value": 1820.0, "unit": "ohm"}
    assert rf.unit_value("about 2 squiggles") == {"source_value": "about 2 squiggles"}
    assert rf.unit_value("  ") is None


def test_the_exclusion_rule_beats_any_corroboration():
    """D9: a source assertion contradicting the channel list wins. A1.edi states that its HZ/RX/RY
    channel declarations are exporter template artifacts, so those three are excluded by name."""
    d = facts("enriched-dotted")
    assert d["excluded_components"] == ["hz", "rx", "ry"]
    assert "hz" not in d["named_components"]


def test_mtpy_fieldnotes_reads_the_manufacturers_and_the_geometry_only():
    """The ids and coordinates in this block are template values repeated across a whole survey, so
    only the manufacturer strings and the electrode geometry are read."""
    d = facts("mtpy-fieldnotes")
    assert d["dialects"] == ["mtpy-fieldnotes"]
    assert d["run"]["data_logger"] == {"manufacturer": "Earth Data Logger"}
    assert d["channels"]["ex"]["dipole_length_m"] == 50.0
    assert d["channels"]["hx"]["sensor"] == {"manufacturer": "Lemi"}
    assert "measurement_azimuth_deg" not in d["channels"]["hx"]
    assert "serial_number" not in d["run"]["data_logger"]


def test_lemimt_site_reads_the_instrument_and_leaves_the_rate_where_none_is_stated():
    """A23's SITE line carries no rate token at all, so only the Instrument line qualifies it. A
    dialect that matched would otherwise invent a rate for 296 stations."""
    d = facts("lemimt-site")
    assert d["dialects"] == ["lemimt-site"]
    assert d["run"]["data_logger"] == {"model": "LEMI-424"}
    assert "sample_rate_hz" not in d["run"]
    assert d["facts"] == ["data_logger"]


def test_lemimt_site_reads_the_rate_off_the_site_token_where_one_is_stated():
    """The other half of the same dialect: the rate rides the job string as `_S-10Hz_`."""
    d = rf.run_facts("SITE        : P-A1_RR-RR_S-10Hz_1\nProcessing code: LEMIMT\n")
    assert d["run"]["sample_rate_hz"] == 10.0
    assert d["confidence"]["run.sample_rate_hz"] == rf.PATTERN_EXTRACTED


def test_empower_json_takes_the_highest_rate_as_the_run_nominal_rate():
    """D10: the 24 kHz sampleRate is the run's nominal rate and the lower ones are the decimation
    ladder riding the transfer-function product, not extra runs."""
    d = facts("empower-json")
    assert d["dialects"] == ["empower-json"]
    assert d["run"]["sample_rate_hz"] == 24000.0
    assert d["run"]["data_logger"] == {"model": "RMT03-J", "serial_number": "10263"}


def test_phoenix_compact_json_reads_the_local_blocks_and_never_the_remote_one():
    """D10 again, in the other Phoenix shape: `RH` is the REMOTE station. Its coordinates differ
    from the local receiver's, and nothing it states may become this station's channel or run."""
    d = facts("phoenix-compact")
    assert d["run"]["data_logger"] == {"model": "MTU5A", "serial_number": "4759"}
    assert d["run"]["time_period"] == {"start": "2023-02-16T06:34:51Z",
                                       "end": "2023-02-17T07:58:49Z"}
    assert d["channels"]["ex"]["dipole_length_m"] == 100.0
    assert d["channels"]["hx"]["sensor"] == {"serial_number": "BMT53815"}
    assert "4574" not in json.dumps(d), "the RH (remote) receiver serial must not be published here"


def test_phoenix_field_sheet_reads_the_local_coil_serials_only():
    """The free-text MTU sheet lists Hx/Hy/Hz and Rx/Ry coil serials in the same column. Rx and Ry
    are the REMOTE pair and are never read as this station's sensors."""
    d = facts("phoenix-fieldsheet")
    assert d["run"]["data_logger"] == {"model": "MTU5A", "serial_number": "U-4573"}
    assert d["channels"]["hx"]["sensor"] == {"serial_number": "54769"}
    assert set(d["channels"]) == {"hx", "hy", "hz"}
    assert d["confidence"]["channels.hx.sensor"] == rf.PATTERN_EXTRACTED


def test_ga_geotools_states_no_acquisition_fact_at_all():
    """The correct outcome for a bare legacy EDI: the dialect is recognised and populates nothing,
    so the station publishes no runs[] rather than a fabricated one."""
    d = facts("ga-geotools")
    assert d["dialects"] == ["ga-geotools"]
    assert d["facts"] == []
    assert d["run"] == {} and d["channels"] == {}


def test_every_dialect_fixture_is_covered_and_every_value_carries_a_confidence_class():
    """Scope section 6: every extractor classifies its output. A value with no class is a value with
    no provenance."""
    seen = set()
    for path in sorted(FIX.glob("*.info")):
        d = rf.run_facts(path.read_text(encoding="utf-8"))
        assert d["dialects"], f"{path.name} matched no dialect"
        seen.update(d["dialects"])
        for key in d["run"]:
            assert d["confidence"][f"run.{key}"] in rf.CONFIDENCE_CLASSES
        for component, channel in d["channels"].items():
            for key in channel:
                assert d["confidence"][f"channels.{component}.{key}"] in rf.CONFIDENCE_CLASSES
        assert set(d["facts"]) <= set(rf.FACTS), d["facts"]
    assert seen == {"enriched-dotted", "mtpy-fieldnotes", "lemimt-site", "empower-json",
                    "phoenix", "ga-geotools"}


def test_an_edi_with_no_info_block_yields_an_empty_document():
    d = rf.run_facts("")
    assert d["facts"] == [] and d["dialects"] == [] and d["run"] == {}


def test_a_doi_is_normalised_to_the_bare_canonical_form():
    """Scope 4.2: identifiers carry the bare form, never the resolver prefix."""
    assert rf.bare_doi("https://doi.org/10.82388/u3jf7ztm") == "10.82388/u3jf7ztm"
    assert rf.bare_doi("http://dx.doi.org/10.11636/Record.2020.011") == "10.11636/Record.2020.011"
    assert rf.bare_doi("not-a-doi") is None


# ---- the facts reach the parse product, which is what the cache tag bump covers -----------------

def test_the_parse_product_carries_the_run_facts():
    """The extractors run inside the cached per-EDI parse, so a warm rebuild emits the same runs a
    cold one does. FAILS against the pre-A6 parse, whose product had no `run_facts` key."""
    pytest.importorskip("mt_metadata")
    import build_portal as bp  # noqa: PLC0415
    edi = HERE / "fixtures" / "example-survey" / "transfer_functions" / "edi" / "EXAMPLE01.edi"
    parsed = bp._parse_one_edi(edi)
    assert parsed["run_facts"]["run"]["sample_rate_hz"] == 10.0
    assert json.dumps(parsed["run_facts"])   # JSON-serialisable: it rides the C18 cache value


def test_the_extraction_confidence_classes_reach_the_build_report(tmp_path):
    """SCOPE:254-258: the curation layer keeps the extraction provenance even where the public
    document does not display it. station.json publishes the VALUE and never the class, so the class
    needs a home, and build_report is the curation surface the presence rule already uses.

    FAILS against the pre-fix build, whose report carried no `run_extraction` at all: the class and
    the dialect were computed for every value, cached inside the C18 parse product and then dropped,
    so nothing shipped could tell a structured_dialect value from a pattern_extracted one. This
    fixture is the case that makes it matter - EXAMPLE01's rate is read out of a LEMIMT SITE
    processing token, which is the weakest class the extractors emit."""
    pytest.importorskip("mt_metadata")
    surveys = tmp_path / "surveys"
    surveys.mkdir()
    shutil.copytree(HERE / "fixtures" / "example-survey", surveys / "example-survey")
    out = tmp_path / "data"
    r = subprocess.run([sys.executable, "-m", "extract.build_portal", "--surveys", str(surveys),
                        "--out", str(out), "--no-validate"], cwd=str(ROOT),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    report = json.loads((out / "build_report.json").read_text(encoding="utf-8"))
    entry = report["surveys"]["example-survey"]["run_extraction"]["EXAMPLE01"]
    assert entry["dialects"] == ["lemimt-site"]
    assert entry["confidence"] == {"run.sample_rate_hz": rf.PATTERN_EXTRACTED}
    published = json.loads((out / "products" / "example-survey" / "EXAMPLE01" / "station.json")
                           .read_text(encoding="utf-8"))
    assert published["runs"][0]["sample_rate_hz"] == 10.0
    assert "confidence" not in json.dumps(published["runs"]), (
        "the class is curation provenance, not a published member")


def test_the_cache_format_tag_records_the_parse_product_shape_change(tmp_path):
    """The house mechanism for a parse-product shape change (the v4 and v5 notes record the same
    case): bump the format tag so every pre-change entry is a clean MISS rather than a replay of a
    stale-shape parse."""
    import cache as cache_mod  # noqa: PLC0415
    salt = cache_mod.BuildCache(tmp_path, engine_commit="deadbeef",
                                lib_versions={}, contract_digest="")._fixed_salt
    assert "ausmt-c47-cache-v6" in salt
