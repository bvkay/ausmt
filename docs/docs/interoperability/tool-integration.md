# Tool integration

This page is for people writing software that reads AusMT: an mtpy or MTH5 workflow, a reader module,
a federating catalogue, a plotting tool. The mechanics of fetching are in the
[data reference](api-reference.md). This page assumes you have the bytes and asks what to do with them.

---

## What an AusMT reader consumes

Three documents and one artifact family:

```text
data/mtcat.json      discovery: what surveys and stations exist, where, and under what licence
data/manifest.json   the artifact index: every fetchable file with its size and sha256
data/surveys.json    credit and citation, keyed by survey display name
data/<url>           the artifact itself, joined from a manifest row
```

A reader that goes through those four things needs no knowledge of how AusMT is organised internally.
It reads paths instead of building them, and it has no authorisation failure to handle, because a
withheld survey has no manifest rows to fail on. The artifact paths carry
`Content-Disposition: attachment`, which matters only when fetching from a browser.

---

## The three distributed formats

| Format | Granularity | What it is |
|---|---|---|
| EDI | per station | The custodian's original file, served byte for byte, unless the station was submitted only as EMTF XML |
| EMTF XML | per station | Derived, written by mt_metadata from the same transfer function |
| MTH5 | per survey and per station | Transfer functions only, one HDF5 file per survey and one per station |

### EDI is the citable artifact

For a station submitted as EDI, the served EDI is the file the custodian submitted, unmodified, and you
can check that without trusting this page. `catalogue.json` column 14 is the SHA-256 of the source
transfer-function file, and the manifest's `edi` row for the same station carries the SHA-256 of the
bytes the server hands you. For an EDI-sourced station those are the same file, so the digests agree.
Across the live corpus that comparison holds for all 2,389 served EDIs, with no mismatches.

A station can also arrive as EMTF XML alone, and then there is no original EDI to serve: its EDI is
written by mt_metadata from the same transfer function, and its XML is a re-emission of the submitted
one, so column 14, the digest of the file the custodian sent, matches neither served file. That is a
different provenance, not a tampered download. `build_report.json` records the source format for every
station under `ingest_sources`, the only place that fact is published, so look there before drawing a
conclusion from a digest that does not match. Where a station arrives in both formats the EDI wins and
is served as an original.

### EMTF XML is derived

The served EMTF XML is written through mt_metadata's EMTFXML writer, the same `EM_TF` serialisation
EarthScope's SPUD archive publishes, and the same library reads it back:

```python
from mt_metadata.transfer_functions.core import TF
tf = TF()
tf.read("A1.xml")                 # fetched from data/xml/vulcan-2022/A1.xml
print(tf.station, tf.period.size, tf.has_impedance(), tf.has_tipper())
# A1 62 True False
```

The reader warns that `external_url`, field notes and remote info are absent. Those elements are
optional and the source EDIs do not carry them, so the warnings are not a sign of a broken file.

The impedance survives the derivation exactly: reading the served EDI and the served XML for the same
station gives `numpy.allclose(...) == True`. `normalize()` runs a round-trip check on every station at
build time and raises on a mismatch, so a station whose impedance did not survive is never published in
either format.

What the derivation had to change is visible in the file:

- **mt_metadata's writer emits metadata its own reader rejects.** Six separate cases, from an enum
  serialised as a Python repr to identifier patterns that reject a real station id. AusMT works around
  each at write time; the workarounds are listed with their symptoms at the top of
  `engine/ausmt_science/ingest/normalize.py`.
- **Identifier fields are sanitised.** `Site/Id` is restricted to `^[a-zA-Z0-9]*$`, so a station id
  like `SA225_2` is written as `SA2252`. The unsanitised id is preserved in the free-text `Site/Name`
  element (`AusLAMP South Australia ausmt_src_id:SA225_2`). Recover it with
  `source_station_id_from_geographic_name()` in the same module, or by matching `ausmt_src_id:(\S+)`.
- **`Site/Survey` and `Site/Project` carry the source file's own naming, not the AusMT slug.** For an
  AusLAMP station `Site/Survey` reads `AusLAMP South Australia` and `Site/Project` reads
  `AusLAMP_South_Australia`; for a Vulcan station `Site/Survey` reads `A1`, which came from the EDI.
  Get survey membership from the manifest row or from `mtcat.json`, never from the XML.
- **Some values are library defaults the source never stated.** For EDI-sourced stations that covers
  the sign convention, the declination epoch and model, and degenerate-geometry channel orientations.
  AusMT records a conditioning note for each and surfaces it in that station's `station.json` under
  `canonical_conditioning`; a rotation angle the source did not assert is zero-filled and noted as not
  asserted. Read `canonical_conditioning` before treating any of those fields as an observation.

### MTH5 comes two ways, transfer functions only

One HDF5 file per survey at `data/bundles/<slug>-tf.h5`, and one per station at
`data/h5/<slug>/<station>.h5`. Both are built EDI to mt_metadata TF to MTH5 by the same writer, so a
station reads identically out of either. Neither carries time series. A single-station MTH5 is not a
small file: HDF5 pays its structural cost once per file, so the per-station files together are several
times the size of the one bundle holding the same transfer functions.

In the manifest, `mth5` appears in BOTH lists, and the list is what tells them apart: a `files[]` row
with `format: "mth5"` is one station, a `bundles[]` row with the same token is the whole survey. Filter
on the list first.

```python
from mth5.mth5 import MTH5
m = MTH5()
m.open_mth5("auslamp-sa-se-2014-tf.h5", mode="r")
rows = m.tf_summary.array
print(len(rows), rows.dtype.names[:6])
# 23 ('station', 'survey', 'latitude', 'longitude', 'elevation', 'tf_id')

def s(v): return v.decode() if isinstance(v, bytes) else str(v)
r = rows[0]
tf = m.get_transfer_function(s(r["station"]), s(r["tf_id"]), s(r["survey"]))
print(s(r["survey"]), s(r["station"]), tf.period.size, tf.has_impedance(), tf.has_tipper())
# auslamp-sa-se-2014 SA001 23 True True
m.close_mth5()
```

Read `m.tf_summary.array` directly rather than calling `summarize()`, which rebuilds the table, needs
write access, and fails on a file opened `mode="r"` with
`KeyError: "Couldn't delete link (no write intent on file)"`.

The bundles need a current HDF5 library. h5py 3.12.1 against libhdf5 1.12.1 cannot open the
`tf_summary` table (`KeyError: 'Unable to open object (bad version number for datatype message)'`);
h5py 3.16.0 against libhdf5 2.0.0 opens it. Upgrade h5py before assuming the file is damaged.

The survey group carries rights and credit as attributes. `Experiment/Surveys/<slug>` holds
`release_license` (`CC-BY-4.0` on all 25 bundles in the live corpus), `acquired_by.organization`,
`project_lead.author` with an ORCID in `project_lead.url`, `funding_source.organization` and the corner
coordinates. Do not read `time_period.end_date` off the survey group: it is `1980-01-01`, the library's
epoch default, on 22 of the 25 bundles. `time_period.start_date` is correct on all 25. Take acquisition
dates from `surveys.json`, where `year_start` and `year_end` are what the survey declares.

Unlike the EMTF XML, the MTH5 bundle's `survey` field is the AusMT slug and the station ids are the
AusMT station ids. `data/build.json` records the `mth5_version` and `mt_metadata_version` the bundles
were written with.

---

## MTCAT as a harvest surface

If you are building a catalogue rather than a processing workflow, `mtcat.json` is the thing to harvest:
one request, schema-versioned, designed so that another portal could serve the same shape.

```python
import json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]             # the portal root you are reading from
doc = json.load(urllib.request.urlopen(f"{BASE}/data/mtcat.json"))
print(doc["portal"]["schema"], doc["portal"]["version"], doc["portal"]["generated_at"])
print(len(doc["surveys"]), "surveys,", len(doc["stations"]), "stations")
# mtcat 2.0 2026-08-21T04:12:19Z
# 27 surveys, 2625 stations
```

**The schema travels with the document.** `portal.schema_url` resolves next to `mtcat.json`, so
validation needs no off-site resolution and no version guessing. The schema's own `$id` is the immutable
version-specific copy, `/data/schemas/mtcat/2.0/mtcat.schema.json`, which is what to cache by. Every
field, type and controlled vocabulary carries a `description` in the schema itself.

**Absence is the default state.** An optional key the producer cannot honestly state is omitted, never
`null` and never an empty array; the one defined null is a station's paired latitude/longitude. Test for
key presence. `additionalProperties` is true on every record object, so a consumer written against one
minor version reads a later one without changes. The exception is `surveys[].data_types`, a map of band
to count whose key names the schema pins, because an unexpected key there is an unknown band rather
than a local extension.

**The vocabularies are enum-pinned where a wrong value would publish a false claim.** Contributor
roles, name types, identifier types, relation types, the data-level vocabulary and `coordinates_state`
are fixed lists in the schema, and AusMT validates its own emitted document against that schema on
every build. Two fields are deliberately not pinned, `surveys[].access` and `collections[].status`,
because the producer passes an unrecognised value through and fails closed at serve time; pinning them
would turn a metadata typo into a failed build rather than a withheld survey.

**Metadata licensing is stated.** `portal.metadata_license` is `CC0-1.0` and covers the catalogue
metadata only. A survey's data licence is the `license` field on its own record.

For credit, `creators[]` order is the citation author order and must be preserved verbatim by anything
that re-renders a citation; `contributors[]` order carries no meaning, and the exported list always ends
with AusMT as `HostingInstitution`, appended by the export rather than declared by the survey, so strip
it if you are re-hosting rather than citing.

The field-by-field guide is the [MTCAT schema reference](../reference/mtcat-schema.md), and the
normative artifact is the schema itself.

---

## Things that will bite you

**`surveys.json` is keyed by display name.** `"Vulcan 2022"`, not `"vulcan-2022"`. Build your own slug
index from the `slug` field on each record.

**Manifest rows name the survey by display name too.** `"survey": "Vulcan 2022"`. To filter by slug,
test `ausmt_id.startswith("au." + slug + ".")`.

**A served filename is not the station id.** Station `A1` of `vulcan-2022` is served as
`edi/vulcan-2022/Vulcan_A1.edi`. Read the `url` from the manifest.

**Station filenames collide across surveys.** 108 EDI basenames in the live corpus are served under
more than one survey (`SA225_2.edi` under both `auslamp-musgraves-apy-2016` and `auslamp-sa-ne-2014`,
`B1.edi` under two others). If you flatten manifest paths to basenames when downloading across surveys,
one file overwrites the other and you will not be told.

**`catalogue.json`, `sci.json` and `tf.json` are aligned by index and nothing else.** There is no key on
the wire. If you filter one, carry the indices.

**A withheld station is still in the catalogue.** Its `tf.json` entry is 18 empty arrays and its
`sci.json` science fields are null, but the row exists and the width is preserved. Test for empty rather
than assuming a missing station.

**Coordinates may be generalised or absent.** A generalised position is rounded to 0.1°, roughly 11 km.
A withheld one is `null`. Guard for null before any numeric comparison; in JavaScript a null compares as
0, which silently places the station at 0°, 0°.

**`dimensionality.json` is absent for a withheld station, but `station.json` is not.** Gate the first
request on the survey's access level rather than treating the `404` as an error.
