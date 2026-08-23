# Tool integration

For people writing software that reads AusMT: an mtpy or MTH5 workflow, a reader module, a federating
catalogue, a plotting tool. The mechanics of fetching are in the [data reference](api-reference.md);
this page assumes you have the bytes.

---

## What an AusMT reader consumes

```text
data/mtcat.json                              discovery, credit and citation: what surveys and stations exist, where, under what licence, by whom
data/manifest.json                           the download index: every fetchable file with its size and sha256
data/products/<slug>/<station>/station.json  the per-station record: identity, diagnostics, distribution state, provenance
data/<url>                                   the artifact itself, joined from a manifest row
```

A reader that goes through those four things needs no knowledge of how AusMT is organised internally.
It reads paths instead of building them, and has no authorisation failure to handle, because a withheld
survey has no manifest rows. The artifact paths carry `Content-Disposition: attachment`, which matters
only when fetching from a browser.

---

## The three distributed formats

| Format | Granularity | What it is |
|---|---|---|
| EDI | per station | The custodian's original file, served byte for byte, unless the station was submitted only as EMTF XML |
| EMTF XML | per station | Derived, written by mt_metadata from the same transfer function |
| MTH5 | per survey and per station | Transfer functions only, one HDF5 file per survey and one per station |

### EDI is the citable artifact

For a station submitted as EDI, the served EDI is the file the custodian submitted, and you can check
that: the station's `station.json` carries `provenance.input_sha256`, the SHA-256 of the source
transfer-function file, and the manifest's `edi` row for the same station carries the SHA-256 of the
bytes the server hands you. For an EDI-sourced station the two agree; across the live corpus they agree
for all 2,389 served EDIs.

A station can also arrive as EMTF XML alone. Then its EDI is written by mt_metadata from the same
transfer function, its XML is a re-emission of the submitted one, and `provenance.input_sha256`, the
digest of the file the custodian sent, matches neither served file. That is a different provenance,
not a tampered download, and the digest comparison is how a reader tells the two cases apart. Where a
station arrives in both formats the EDI wins.

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

The reader warns that `external_url`, field notes and remote info are absent; those elements are
optional and the source EDIs do not carry them. The impedance survives the derivation exactly
(`numpy.allclose(...) == True` between the served EDI and XML of one station): `normalize()` runs a
round-trip check on every station at build time and raises on a mismatch, so a station whose impedance
did not survive is never published in either format.

What the derivation had to change is visible in the file:

- **mt_metadata's writer emits metadata its own reader rejects**, six separate cases, worked around at
  write time and listed with their symptoms at the top of `engine/ausmt_science/ingest/normalize.py`.
- **Identifier fields are sanitised.** `Site/Id` is restricted to `^[a-zA-Z0-9]*$`, so `SA225_2` is
  written as `SA2252`. The unsanitised id is preserved in the free-text `Site/Name` element
  (`AusLAMP South Australia ausmt_src_id:SA225_2`); recover it with
  `source_station_id_from_geographic_name()` in the same module, or by matching `ausmt_src_id:(\S+)`.
- **`Site/Survey` and `Site/Project` carry the source file's own naming, not the AusMT slug** (for an
  AusLAMP station `AusLAMP South Australia` and `AusLAMP_South_Australia`; for a Vulcan station
  `Site/Survey` reads `A1`). Get survey membership from the manifest row or from `mtcat.json`.
- **Some values are library defaults the source never stated**: for EDI-sourced stations the sign
  convention, the declination epoch and model, and degenerate-geometry channel orientations. Each is
  recorded as a conditioning note in that station's `station.json` under `canonical_conditioning`; a
  rotation angle the source did not assert is zero-filled and noted as not asserted. Read
  `canonical_conditioning` before treating any of those fields as an observation.

### MTH5 comes two ways, transfer functions only

One HDF5 file per survey at `data/bundles/<slug>-tf.h5`, and one per station at
`data/h5/<slug>/<station>.h5`, built EDI to mt_metadata TF to MTH5 by the same writer, so a station
reads identically out of either. Neither carries time series. A single-station MTH5 is not a small
file: HDF5 pays its structural cost once per file.

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

Read `m.tf_summary.array` directly rather than calling `summarize()`, which needs write access and
fails on a file opened `mode="r"` with `KeyError: "Couldn't delete link (no write intent on file)"`.
The bundles need a current HDF5 library: h5py 3.12.1 against libhdf5 1.12.1 cannot open the
`tf_summary` table (`KeyError: 'Unable to open object (bad version number for datatype message)'`);
h5py 3.16.0 against libhdf5 2.0.0 opens it.

The survey group carries rights and credit as attributes. `Experiment/Surveys/<slug>` holds
`release_license` (`CC-BY-4.0` on all 25 bundles in the live corpus), `acquired_by.organization`,
`project_lead.author` with an ORCID in `project_lead.url`, `funding_source.organization` and the corner
coordinates. Do not read `time_period.end_date` off the survey group: it is `1980-01-01`, the library's
epoch default, on 22 of the 25 bundles; `time_period.start_date` is correct on all 25. Take acquisition
dates from the survey's `mtcat.json` record (`year_start`, `year_end`). Unlike the EMTF XML, the
bundle's `survey` field is the AusMT slug and the station ids are the AusMT station ids. The library
versions the bundles were written with are in the download index: `/data/manifest.json` carries
`mth5_version` and `mt_metadata_version` at its top level, beside the rows that carry each bundle's
size and digest. The file's own root attribute `mth5.software.version` carries the `mth5` version
only; there is no `mt_metadata` version attribute in the file.

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

That output is the merged engine's MTCAT 2.0 document; a deployment whose data build predates the 2.0
engine still serves 1.2 until its next rebuild, so branch on `portal.version`.

`portal.schema_url` resolves next to `mtcat.json`, so validation needs no off-site resolution; the
schema's own `$id` is the immutable version-specific copy `/data/schemas/mtcat/2.0/mtcat.schema.json`,
the one to cache by. An optional key the producer cannot honestly state is omitted, never `null` or an
empty array, so test for key presence. `additionalProperties` is true on every record object, and the
vocabularies that would publish a false claim if wrong (roles, name types, identifier types, relation
types, data levels, `coordinates_state`) are enum-pinned and validated on every build; `surveys[].access`
and `collections[].status` are deliberately not pinned, because the producer passes an unrecognised
value through and fails closed at serve time. `portal.metadata_license` (`CC0-1.0`) covers the
catalogue metadata only; a survey's data licence is its own `license`. `creators[]` order is the
citation author order and must be preserved; the exported `contributors[]` always ends with AusMT as
`HostingInstitution`, so strip it if you are re-hosting rather than citing. The field-by-field guide,
including how to read absence, credit, relations and access, is the
[MTCAT schema reference](../reference/mtcat-schema.md).

---

## Things that will bite you

**Manifest `files[]` rows name the survey by display name.** `"Vulcan 2022"`, not `"vulcan-2022"`. To
filter by slug, test `ausmt_id.startswith("au." + slug + ".")`; `bundles[]` rows carry the slug.

**A served filename is not the station id.** Station `A1` of `vulcan-2022` is served as
`edi/vulcan-2022/Vulcan_A1.edi`. Read the `url` from the manifest.

**Station filenames collide across surveys.** 108 EDI basenames in the live corpus are served under
more than one survey (`SA225_2.edi` under both `auslamp-musgraves-apy-2016` and `auslamp-sa-ne-2014`,
`B1.edi` under two others). Flatten manifest paths to basenames across surveys and one file overwrites
the other silently.

A withheld station is still in the catalogue. Its `mtcat.json` record and its `station.json` exist;
the `station.json` carries `"withheld": true` and no derived science, and there is no manifest row.

**Coordinates may be generalised or absent.** A generalised position is rounded to 0.1°, roughly 11 km.
A withheld one is `null`; guard for it before any numeric comparison, because JavaScript compares null
as 0 and places the station at 0°, 0°.

**`dimensionality.json` is absent for a withheld station, but `station.json` is not.** Gate the first
request on the survey's access level rather than treating the `404` as an error. It is served alongside
`station.json` and is not a contract; do not build on its shape. You rarely need it: `station.json`'s
`diagnostics` states the same screening result, so one request answers both.
