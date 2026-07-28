# Tool integration

This page is for people writing software that reads AusMT. An mtpy or MTH5 workflow, a reader module,
a federating catalogue, a plotting tool. It covers what to consume, what the artifacts are actually
like, and where the sharp edges are.

The mechanics of fetching are in the [data reference](api-reference.md). This page assumes you have the
bytes and asks what to do with them.

---

## What an AusMT reader consumes

Three documents and one artifact family. That is the whole surface:

```text
data/mtcat.json      discovery: what surveys and stations exist, where, and under what licence
data/manifest.json   the artifact index: every fetchable file with its size and sha256
data/surveys.json    credit and citation, keyed by survey display name
data/<url>           the artifact itself, joined from a manifest row
```

A reader that goes through those four things needs no knowledge of how AusMT is organised internally.
It reads paths instead of building them, so it never guesses a filename. It has no authorisation
failure to handle either, because a withheld survey has no manifest rows to fail on.

The artifact paths carry `Content-Disposition: attachment`, which matters only if you are fetching from
a browser. A command-line or library client is unaffected.

---

## The three distributed formats

| Format | Granularity | What it is |
|---|---|---|
| EDI | per station | The custodian's original file, served byte for byte |
| EMTF XML | per station | Derived, written by mt_metadata from the same transfer function |
| MTH5 | per survey | Transfer functions only, one HDF5 file per survey |

### EDI is the citable artifact

The served EDI is the file the custodian submitted, unmodified. You can check that without trusting
this page. `catalogue.json` column 14 is the SHA-256 of the source transfer-function file, and the
manifest's `edi` row for the same station carries the SHA-256 of the bytes the server hands you. Across
the live corpus those agree on all 1,182 served EDIs, with no mismatches.

That is the point of keeping EDI in the distribution. Every other representation is derived, and a
derived file is only as trustworthy as the derivation. The original is there so you can check.

### EMTF XML is derived, and honest about it

The served EMTF XML is written through mt_metadata's EMTFXML writer, so it carries the same `EM_TF`
serialisation that EarthScope's SPUD archive publishes, and the same library reads it back. Verified
against the live site with mt_metadata 1.0.9:

```python
from mt_metadata.transfer_functions.core import TF
tf = TF()
tf.read("A1.xml")                 # fetched from data/xml/vulcan-2022/A1.xml
print(tf.station, tf.period.size, tf.has_impedance(), tf.has_tipper())
# A1 62 True False
```

The reader emits warnings about `external_url`, field notes and remote info being absent. Those elements
are optional in EMTF XML and the source EDIs do not carry them, so the warnings are correct and not a
sign of a broken file.

The impedance survives the derivation exactly. Reading the served EDI and the served XML for the same
station and comparing gives `numpy.allclose(...) == True`. That is not luck. `normalize()` runs a
round-trip check on every station at build time and **raises** on a mismatch, so a station whose
impedance did not survive is never published in either format.

What the derivation had to change is worth knowing, because some of it is visible in the file:

- **mt_metadata's writer emits metadata its own reader rejects.** Six separate cases, from an enum
  serialised as a Python repr to identifier patterns that reject a real station id. AusMT works around
  each one at write time. The workarounds are listed with their symptoms at the top of
  `engine/ausmt_science/ingest/normalize.py`, which numbers a seventh item as well. That one is the
  library-default category described in the last bullet below, not another writer/reader mismatch.
- **Identifier fields are sanitised.** `Site/Id` is restricted to `^[a-zA-Z0-9]*$`, so a station id like
  `SA225_2` is written as `SA2252`. The unsanitised id is preserved inside the artifact, in the free-text
  `Site/Name` element, which for that station reads `AusLAMP South Australia ausmt_src_id:SA225_2`.
  Recover it with `source_station_id_from_geographic_name()` in the same module, or by matching
  `ausmt_src_id:(\S+)`.
- **`Site/Survey` and `Site/Project` carry the source file's own naming, not the AusMT slug.** For an
  AusLAMP station they read `AusLAMP South Australia`; for a Vulcan station `Site/Survey` reads `A1`,
  which came from the EDI. Get survey membership from the manifest row or from `mtcat.json`, never from
  the XML.
- **Some values in the file are library defaults the source never stated.** For EDI-sourced stations
  that covers the sign convention, the declination epoch and model, and degenerate-geometry channel
  orientations. The writer requires them, so they are present, but AusMT records a machine-readable
  conditioning note for each one and surfaces it in that station's `station.json` under
  `canonical_conditioning`. A rotation angle that the source did not assert is zero-filled and noted as
  not asserted, rather than published as a claimed 0°.

Read `canonical_conditioning` before treating any of those fields as an observation. It is the list of
things the file states that the source did not.

### MTH5 is per survey, transfer functions only

One HDF5 file per survey at `data/bundles/<slug>-tf.h5`, built EDI to mt_metadata TF to MTH5. There is
no per-station MTH5, so don't look for one in the manifest's `files` list.

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

Two practical notes from running that.

Read `m.tf_summary.array` directly rather than calling `summarize()`. `summarize()` rebuilds the table
and needs write access, so it fails on a file opened `mode="r"` with
`KeyError: "Couldn't delete link (no write intent on file)"`.

The bundles need a reasonably current HDF5 library. On the machine these examples were run on, h5py
3.12.1 built against libhdf5 1.12.1 could not open the `tf_summary` table at all
(`KeyError: 'Unable to open object (bad version number for datatype message)'`), and h5py 3.16.0
against libhdf5 2.0.0 opened it fine. If you see that error, upgrade h5py before assuming the file is
damaged.

The survey group carries the rights and credit metadata as attributes, so a workflow can pick them up
without a second request. `Experiment/Surveys/<slug>` holds `release_license`, which is `CC-BY-4.0` on
all 19 bundles in the live corpus, along with `acquired_by.organization`, `project_lead.author` with an
ORCID in `project_lead.url`, `funding_source.organization` and the corner coordinates.

Do not read `time_period.end_date` off the survey group. It is `1980-01-01`, the library's epoch
default, on 16 of the 19 bundles; only three carry a real end date. `time_period.start_date` is
correct on all 19. Take acquisition dates from `surveys.json`, where `year_start` and `year_end` are
what the survey declares.

Unlike the EMTF XML, the MTH5 bundle's `survey` field **is** the AusMT slug, and the station ids are the
AusMT station ids. The bundle is built by AusMT rather than round-tripped through a format with its own
naming rules, so nothing had to be sanitised.

`data/build.json` records the `mth5_version` and `mt_metadata_version` the bundles were written with, so
you can record them in a workflow. As of the 2026-07-27 build those are `0.6.8` and `1.0.9`.

---

## MTCAT as a harvest surface

If you are building a catalogue rather than a processing workflow, `mtcat.json` is the thing to harvest.
It is one request, it is schema-versioned, and it is designed so that another portal could serve the
same shape.

```python
import json, urllib.request
doc = json.load(urllib.request.urlopen("https://ausmt.au/data/mtcat.json"))
print(doc["portal"]["schema"], doc["portal"]["version"], doc["portal"]["generated_at"])
print(len(doc["surveys"]), "surveys,", len(doc["stations"]), "stations")
# mtcat 1.1 2026-07-27T08:29:39Z
# 21 surveys, 1418 stations
```

Four things make it harvestable rather than merely readable.

**The schema travels with the document.** `portal.schema_url` resolves next to `mtcat.json`, and the
schema's own `$id` is that same URL, so validation needs no off-site resolution and no version guessing.
Every field, type and controlled vocabulary carries a `description` in the schema itself.

**Unknown keys are safe.** `additionalProperties` is true on every record object, deliberately, so a
consumer written against 1.1 reads a 1.2 document without changes. There is one exception,
`surveys[].data_types`, which is a map of band to count. An unexpected key there is an unknown band and
not a local extension, so the schema pins the key names.

**The vocabularies are enum-pinned where a wrong value would publish a false claim.** Contributor roles,
name types, identifier types, relation types and the NCI data-level vocabulary are all fixed lists in the
schema, and AusMT validates its own emitted document against that schema on every build. An enum there
is a build gate rather than documentation. Two fields are deliberately not pinned, `surveys[].access` and
`collections[].status`, because the producer passes an unrecognised value through on purpose and fails
closed at serve time; pinning them would turn a metadata typo into a failed build rather than a withheld
survey.

**Metadata licensing is stated.** `portal.metadata_license` is `CC0-1.0`, which covers the catalogue
metadata only. A survey's data licence is the `license` field on its own record. Do not conflate them
when you re-publish.

For harvesting credit, `creators[]` order is the citation author order and must be preserved verbatim by
anything that re-renders a citation. `contributors[]` order carries no meaning. The exported
`contributors[]` always ends with AusMT as `HostingInstitution`, appended by the export rather than
declared by the survey, so strip it if you are re-hosting rather than citing.

The field-by-field guide is the [MTCAT schema reference](../reference/mtcat-schema.md), and the
normative artifact is [`mtcat.schema.json`](https://ausmt.au/data/mtcat.schema.json) itself.

---

## Things that will bite you

A short list, all of them observed rather than imagined.

**`surveys.json` is keyed by display name.** `"Vulcan 2022"`, not `"vulcan-2022"`. Build your own
slug index from the `slug` field on each record.

**Manifest rows name the survey by display name too.** `"survey": "Vulcan 2022"`. If you are filtering
by slug, test `ausmt_id.startswith("au." + slug + ".")` instead.

**A served filename is not the station id.** Station `A1` of `vulcan-2022` is served as
`edi/vulcan-2022/Vulcan_A1.edi`. Always read the `url` from the manifest.

**Station filenames collide across surveys.** Exactly one collision exists in the live corpus:
`SA225_2.edi` is served under both `auslamp-musgraves-apy-2016` and `auslamp-sa-ne-2014`. One is enough.
If you flatten manifest paths to basenames when downloading across surveys, one file overwrites the
other and you will not be told.

**`catalogue.json`, `sci.json` and `tf.json` are aligned by index and nothing else.** There is no key
on the wire. If you filter one, carry the indices.

**A withheld station is still in the catalogue.** Its `tf.json` entry is 18 empty arrays and its
`sci.json` science fields are null, but the row exists and the width is preserved. Test for empty rather
than assuming a missing station.

**Coordinates may be generalised or absent.** A generalised position is rounded to 0.1°, roughly 11 km.
A withheld one is `null`. Guard for null before any numeric comparison. In JavaScript a null compares as
0, which silently places the station at 0°, 0° instead of excluding it.

**`dimensionality.json` is absent for a withheld station, but `station.json` is not.** Gate the first
request on the survey's access level rather than treating the `404` as an error.
