# AusMT data reference

This page lists the documents AusMT publishes as contracts and as a download surface, says how to key
into them, and shows worked patterns for getting bytes out. [How AusMT serves data](api-overview.md)
covers the architecture behind it, [Tool integration](tool-integration.md) covers reading the artifacts
from MT software, and the [Reference section](../reference/index.md) documents the contracts field by
field.

Counts and sizes quoted here describe the live corpus on 2026-08-21, 27 surveys and 2,625 stations,
and move with the corpus. The shapes and the rules do not.

---

## Base URL and conventions

All data lives under one prefix:

```text
/data/
```

Paths on this page are relative to the portal root, so `/data/mtcat.json` means
`<portal root>/data/mtcat.json`. The examples take that root from a `BASE` variable; set it to the
deployment you are reading from.

Paths inside the documents are relative to the data prefix, not to the document that carries them. A
manifest row whose `url` is `edi/vulcan-2022/Vulcan_A1.edi` resolves to
`/data/edi/vulcan-2022/Vulcan_A1.edi`. Join, do not template.

The manifest's `base_url` field is the escape hatch for a deployment that publishes artifacts
somewhere else. It is `""` on the live site, which means portal-relative. If it is set, join `url`
onto it instead. Rows also carry a `tier`, which is `repo` for every row in the live corpus; a `nci`
row would carry an absolute URL to a THREDDS file server and needs no joining at all. Handle both by
checking whether the `url` already starts with a scheme.

Two identifiers key almost everything:

| Identifier | Form | Example | Where it appears |
|---|---|---|---|
| survey slug | lowercase, hyphenated | `vulcan-2022` | `mtcat.json` as `survey_id`, the manifest as `bundles[].slug`, bundle filenames, product paths |
| `ausmt_id` | `au.<slug>.<station>[.<variant>]` | `au.vulcan-2022.A1` | `mtcat.json` as `station_id`, every manifest `files[]` row, `station.json` as `ausmt_id`, every GeoJSON feature |

---

## The documents

Sizes are rounded, and are there to tell you what is cheap to fetch and what is not.

| URL | Bytes | What it is |
|---|---|---|
| `/data/mtcat.json` | 511 kB | The discovery document and the contract to harvest. Portal identity, surveys, stations, collections. Start here. |
| `/data/mtcat.schema.json` | 21 kB | The JSON Schema the document above validates against; the same bytes sit at `/data/schemas/mtcat/2.0/mtcat.schema.json`. |
| `/data/products/<slug>/<station>/station.json` | a few kB each | The per-station record, a contract: identity, location, band, diagnostics, distribution state and provenance. |
| `/data/manifest.json` | 2.5 MB | The download index: every fetchable artifact with its size and SHA-256. |
| `/data/stations.geojson` | 773 kB | Every station that has a position, as a GeoJSON point layer. A GIS export; open it in a GIS. |
| `/data/feed.xml` | 4.2 kB | Atom feed of surveys, newest first. |
| `/data/releases/releases.json` | `404` today | The index of citable release snapshots; none has been cut yet. |

Other documents are served under `/data/` because the portal's own pages need them. They are
portal-internal, carry no contract and no stability promise, and are documented only in the Developer
section; a consumer that reads one is reading an implementation detail that can change with any
build. The contracts above (`mtcat.json` with its schema, and `station.json`) and the download surface
are the whole public surface.

### `mtcat.json`

MTCAT is the document to harvest. It is small, schema-versioned and designed to be read by a catalogue
that is not AusMT. Four top-level keys carry the payload, and nothing else is emitted at the top level:

```json
{
  "portal": { "portal_id": "ausmt", "portal_name": "...", "schema": "mtcat",
              "version": "2.0", "schema_url": "mtcat.schema.json",
              "metadata_license": "CC0-1.0", "generated_at": "2026-08-21T04:12:19Z" },
  "surveys":     [ ... ],
  "stations":    [ ... ],
  "collections": [ ... ]
}
```

Read the schema version off `portal.version` rather than assuming one. This page describes 2.0, which
is what the merged engine writes. 2.0 is a MAJOR version: the 1.x document served `null` for every
undeclared optional key, served `formats: []` for a withheld survey, carried `surveys[].sources[]` and
`surveys[].changes`, and carried the library versions `mt_metadata_version` and `mth5_version` at the
top level. All four are gone. A deployment whose data build predates the change still serves a `1.2`
document with those shapes, so branch on `portal.version` if you read more than one deployment. The
library versions are no longer published in the catalogue.

The 2.0 rule is absence: an optional key the producer cannot honestly state is omitted, never `null`
and never an empty array or object. The one defined null is a station's paired `latitude`/`longitude`,
meaning the position is not published. `collections` is present only when at least one collection
exists. Test for key presence, not for `null`. `additionalProperties` stays true on every record object,
so a consumer written against one minor version reads a later one without changes.

`portal.schema_url` is served next to the document, so a harvester can validate without resolving
anything off-site; the schema's immutable `$id` is `/data/schemas/mtcat/2.0/mtcat.schema.json`, the
copy to cache by. `portal.metadata_license` is `CC0-1.0` and covers the catalogue metadata only; a
survey's data licence is the separate `license` field on its own record and varies by survey.

Survey records are identified by `survey_id` (the survey's slug). Required on every record are `survey_id`,
`title`, `organisation` and `country`. These facets are derived from the document's own `stations[]`,
from the build's download manifest and from explicit run metadata, so a harvester can size and filter a
survey without walking the station list:

| Field | Derived from | Note |
|---|---|---|
| `n_stations` | `stations[]` | `stations[]` stays authoritative if the two ever disagree. |
| `data_types` | `stations[].data_type` | A map of band to station count, in the order BBMT, LPMT, AMT, GDS; omitted for a survey with no stations. |
| `period_min_s`, `period_max_s` | per-station period ranges | Omitted when no station reports a range. |
| `n_stations_tipper` | per-station component lists | Compare against `n_stations` to read tipper coverage. |
| `sample_rates_hz` | explicit run metadata | Distinct acquisition rates in Hz, sorted ascending; omitted when no run declares one. Never inferred from instrument type or period coverage. |
| `formats` | the download manifest | The formats distributed for this survey; omitted when none is. |
| `year_start`, `year_end` | the survey's declared dates | Passed through, never inferred from file timestamps. |
| `coordinates_state` | the declared coordinate policy | `exact`, `generalised` or `withheld`; omitted when the survey declares no policy. A `withheld` state forbids `bbox` and `centroid`. |

`formats` is not curated. It is read off the manifest the same build has just written, so an embargoed
or metadata-only survey OMITS the key: its holdings and their formats are known, they are simply not
distributed, and an empty list would have said "no formats known". Absence is "no distribution
statement", never "unknown holdings".

Two curated fields join the facets in 2.0: `description`, a discovery blurb (the survey's explicit
discovery text, else its abstract when within 1200 characters, never truncated by the engine), and
`subjects[]`, rows of `{code, scheme, label?, uri?}` passed through verbatim from curation. The relation
vocabulary on `related_identifiers[]` is nine values, `References`, `IsIdenticalTo` and `HasMetadata`
having joined the 1.x six; a HasMetadata row may carry a `scheme` naming the metadata family at the
target.

Station records are flat and small: `station_id` (the `ausmt_id`), `survey_id`, `latitude`, `longitude`
and `data_type`. `data_type` is one of `AMT`, `BBMT`, `LPMT`, `GDS` or `unknown`, derived from the
station's shortest period and which transfer functions are present. The survey does not declare it.
Latitude and longitude are nullable, paired, because a custodian can withhold a position. The schema
also defines `stations[].has_time_series` (the constant `true`, present only when the catalogue has
verified that a time-series resource exists) and its survey count `n_stations_time_series_verified`;
the engine emits neither yet, so both are absent everywhere, which under the absence rule asserts
nothing.

Every field, including the credit and provenance blocks and the access fields, is documented field by
field in the [MTCAT schema reference](../reference/mtcat-schema.md), which also explains how to read a
served record. The normative artifact is the schema itself.

### `stations.geojson`

An RFC 7946 `FeatureCollection` of `Point` features, one per station that has a position, in WGS84
(GeoJSON's only coordinate reference system, so there is nothing to set). It exists so you can put the
corpus on a map without first writing a script against the positional catalogue.

In QGIS: **Layer > Add Layer > Add Vector Layer**, set Source Type to **Protocol: HTTP(S)**, and paste
the URL:

```text
<portal root>/data/stations.geojson
```

The same URL works anywhere that reads GeoJSON over HTTP, and with `ogr2ogr` for a local conversion:

```bash
BASE=${AUSMT_BASE:?the portal root you are reading from}
ogr2ogr -f GPKG stations.gpkg "/vsicurl/$BASE/data/stations.geojson"
```

The document is a `FeatureCollection` whose members are `type` and `features`; a build with no
positioned stations emits `{"type": "FeatureCollection", "features": []}`. Each feature is
`{"type": "Feature", "geometry": {"type": "Point", "coordinates": [longitude, latitude]}, "properties": {...}}`,
and the geometry is never null. The properties are seven flat members, chosen to be joinable and to
keep the file small:

| Property | Type | Definition |
|---|---|---|
| `ausmt_id` | string | the station identifier, the join key to the download manifest and to `station.json` |
| `station` | string | station id within its survey |
| `survey` | string | survey display name |
| `survey_id` | string or null | survey slug, the join key to `mtcat.json` |
| `data_type` | string or null | band classification, for example `BBMT` |
| `period_min_s` | number or null | shortest period in the transfer function, seconds |
| `period_max_s` | number or null | longest period, seconds |

Properties are flat and few because a GIS attribute table cannot render nesting. Licence and credit are
deliberately not repeated per feature: they are survey-level facts, and `mtcat.json` owns them. Join on
`ausmt_id` or `survey_id` for anything else.

Two membership rules, and they are the same rules the catalogue follows:

- a station whose position the custodian withholds is absent, rather than present with a null
  geometry. A null-geometry feature parses but nothing draws it, so it would be an invisible row. The
  station itself is not hidden: it keeps its `mtcat.json` entry (with paired null coordinates) and its
  `station.json`, whose `coordinate_policy` reads `withheld`;
- a station whose position is generalised is here, at the same 0.1° cell the catalogue serves, so a
  point can sit up to about 5 km from the true site. Nothing is rounded twice.

An embargoed survey's stations are on this layer. An embargo withholds bytes, never discovery, and
this document carries no bytes.

### `feed.xml`

A minimal Atom 1.0 feed at `/data/feed.xml`, not at the site root. One entry per dated survey, newest
first, 27 entries in the current corpus:

```xml
<entry>
  <id>tag:ausmt:vulcan-2022</id>
  <title>Vulcan 2022</title>
  <updated>2026-07-27T00:00:00Z</updated>
</entry>
```

| Element | Obligation | Definition |
|---|---|---|
| `entry/id` | mandatory | `tag:ausmt:<slug>`, so the entry id carries the survey slug |
| `entry/title` | mandatory | the survey display name |
| `entry/updated` | mandatory | the survey's date, as an ISO 8601 timestamp |
| `entry/link` | optional | emitted only when the build is given a site base URL |

The entry id carries the slug, so resolve the survey from there; entries carry no `<link>` element,
because the production invocation supplies no site base URL. A survey's date is the latest of its
release-note dates and its rights declaration date, falling back to 31 December of its last acquisition
year; a survey with no date at all is omitted rather than given an invented one. The feed's own
`updated` is the newest entry date, not the build time, so two builds of the same surveys produce a
byte-identical feed.

---

## Download inventory: manifest.json

`/data/manifest.json` is the index of every downloadable artifact: what exists for a station or a
survey, in which format, where it is served, and with what size and SHA-256. It is the download index,
not a metadata contract. What it promises is the row shape: every row of `files[]` and of `bundles[]`
carries `url`, `size`, `sha256`, `format`, `tier` and `license`, and the build validates the document
against `engine/schema/manifest.schema.json` (JSON Schema draft-07, `$id`
`https://ausmt.org/schema/manifest-1.0.schema.json`) before publishing it. The portal's own download
resolver reads the same document. Where this page and the schema disagree, the schema is right.

Four top-level keys: `generated_count` (integer, `len(files) + len(bundles)`, a cheap sanity check after
parsing), `base_url` (optional string, `""` meaning portal-relative), `files` (one row per downloadable
file per station) and `bundles` (one row per pre-built per-survey download). An empty deployment emits
`{ "generated_count": 0, "base_url": "", "files": [], "bundles": [] }`. Rows are closed
(`additionalProperties: false`), so an unrecognised key in a row is a validation failure rather than a
local extension; the document root stays open.

| Key | In | Type | Meaning |
|---|---|---|---|
| `url` | both | string or null | where the artifact is served. A `repo` row is a portal-relative path joined onto `base_url`; an `nci` row is an absolute THREDDS file-server URL; `null` only when an `nci` survey has no resolvable base. A served filename is not derivable from the station id, so read the path rather than templating one. |
| `size` | both | integer | bytes of the served artifact |
| `sha256` | both | string, 64 hex | SHA-256 of the bytes the server hands you |
| `format` | both | string | `edi`, `emtfxml` or `mth5` in `files[]`; `edi-zip`, `xml-zip` or `mth5` in `bundles[]`. `mth5` in `files[]` is one station's transfer function; in `bundles[]` it is the whole survey's. |
| `tier` | both | string | `repo` or `nci` |
| `license` | both | string | the survey's licence as declared. A row exists only for a redistributably licensed survey, so it is always a redistributable one. A `LICENSE.txt` carrying it rides inside each zip; the MTH5 bundle carries it as `release_license` on `Experiment/Surveys/<slug>`. |
| `canon_license` | both, optional | string | the de-aliased licence id; group and compare on this, not on `license` |
| `custodian` | both, optional | string or null | custodian of record, falling back to the survey's organisation |
| `survey` | both | string | the survey's display name, not the slug |
| `ausmt_id` | `files[]` | string | `au.<slug>.<station>[.<variant>]`, the join key to `mtcat.json` `stations[].station_id` and to `station.json`. To filter by slug, test for the prefix `au.<slug>.` |
| `station` | `files[]` | string | station id within the survey |
| `slug` | `bundles[]` | string | the survey slug, the key used in bundle filenames; group bundles per survey on this |
| `n_stations` | `bundles[]` | integer | stations inside the bundle |

Four rules govern how to read it.

URLs are portal-relative by default. The served forms are `edi/<slug>/<file>.edi`,
`xml/<slug>/<station>.xml`, `h5/<slug>/<station>.h5`, `bundles/<slug>-edi.zip`, `bundles/<slug>-xml.zip`
and `bundles/<slug>-tf.h5`. The portal joins each url onto its configured data base, so moving a tier
to NCI is a manifest change with no consumer edits. Handle both tiers by checking whether the `url`
already starts with a scheme.

Integrity across builds. Every digest is of the served bytes. A served EDI and the per-survey EDI zip
are byte-reproducible across builds given a fixed zlib and, for a generated EDI, a fixed mt_metadata:
the writer stamps its own name and version into the EDI's HEAD block, so a toolchain bump moves the
digest of every generated EDI without any change to the transfer function, and a copied custodian EDI
is unaffected. The only clock-dependent field an EMTF-XML-sourced station's EDI would carry is its
`FILEDATE`, and the build stamps that from the date the source document declares. Within those pins the
SHA-256 is a stable cross-build invariant. EMTF XML, the EMTF-XML zip and the transfer-function MTH5
embed timestamps and UUIDs and are not byte-reproducible: their SHA-256 is a per-build
download-integrity hash, not a cross-build invariant.

The manifest lists only what AusMT serves. Only redistributably licensed surveys with an open access
level appear. A non-served station has no row and the portal routes it to the source archive; an
embargoed survey has no rows at all, so there is no access error to handle and no request to make. The
manifest is also the only statement of which formats a station has.

The MTH5 products are flag-gated. The deployment's `flags:` configuration enables them:
`survey_h5_enabled` produces the per-survey transfer-function MTH5 bundle and `station_h5_enabled` the
per-station MTH5 files, and both ship enabled; the collection-level producer and its portal tile ship
disabled. The EDI, the EMTF XML, the EDI zip and the EMTF-XML zip are unconditional for a served
survey. The manifest is authoritative for what a build produced, whatever its configuration says.

The schema id carries the version. A minor update may add optional keys; an incompatible change bumps
the major version and ships as a separate schema file, mirroring the MTCAT policy.

---

## Fetching data today

These are the patterns for the current build, as opposed to the frozen snapshots described under
[the releases tier](#the-releases-tier). There is no key to obtain and no quota to stay under, and every
response carries `Access-Control-Allow-Origin: *`, so a browser application can fetch it cross-origin.

Every example sets `BASE` to the portal root it reads from, and joins the site-relative paths onto it.

The portal's own About page carries a short quickstart. This is the long version.

### Whole-survey bundles

One request per survey, keyed by the survey slug (`vulcan-2022` and the like). Each published survey is
packaged three ways:

```text
/data/bundles/<slug>-edi.zip     every served station of that survey as EDI
/data/bundles/<slug>-xml.zip     the same stations as EMTF XML
/data/bundles/<slug>-tf.h5       the survey's transfer functions as MTH5
```

```bash
BASE=${AUSMT_BASE:?the portal root you are reading from}
curl -O "$BASE/data/bundles/vulcan-2022-edi.zip"
```

A `LICENSE.txt` rides inside each zip, carrying that survey's licence and its required attribution.
The MTH5 bundle is a single HDF5 file, so its licence is an attribute instead:
`Experiment/Surveys/<slug>` carries `release_license`, alongside `project_lead.author`, the ORCID and
the funding source.

To find a slug, read `/data/mtcat.json`. Its survey records carry the slug under `survey_id`, and the
manifest's `bundles[]` rows carry it under `slug`.

25 of the 27 live surveys have bundles, three each, which is the 75 rows in the manifest's `bundles`
list. The two that do not are the embargoed ones.

### Per-station fetch through the manifest

Fetch `/data/manifest.json` once, filter its `files` rows by `format` (`edi`, `emtfxml` or
`mth5`) and by `survey`, then fetch `/data/` joined to each row's `url` and check the bytes against that
row's `sha256`.

Go through the manifest rather than building paths yourself. A served filename is not derivable from the
station id, so the manifest is the only correct way to locate one station's file. In the current corpus,
station A1 of `vulcan-2022` is served as `edi/vulcan-2022/Vulcan_A1.edi`.

A served station has up to three rows, one per distributed format:

```text
/data/edi/<slug>/<file>.edi     the station's transfer function as EDI
/data/xml/<slug>/<station>.xml  the same station as canonical EMTF XML
/data/h5/<slug>/<station>.h5    the same station as a transfer-function MTH5
```

The EDI is the custodian's own file for a station submitted as EDI, and one mt_metadata generated from
the same transfer function for a station submitted only as EMTF XML. The station's `station.json` says
which: its `provenance.input_sha256` is the digest of the file the custodian supplied, and it equals the
manifest `edi` row's `sha256` exactly when the served EDI is that file. [EDI is the citable
artifact](tool-integration.md#edi-is-the-citable-artifact) says what that means for a digest check. The
manifest is also the only statement of which of the three a station has: in the live corpus 246
stations of one survey have an EDI and an EMTF XML but no per-station MTH5.

`mth5` is the one token that means two different things depending on which list it came from. A
`files[]` row with `format: "mth5"` is ONE station; a `bundles[]` row with the same token is the whole
survey in one file. Filter on the list first, then the format, or a per-survey bundle will arrive where
a per-station file was expected. Both are transfer functions only, never time series.

The per-station MTH5 is the format to take when a tool wants one station with its metadata attached and
the survey bundle would be an oversized fetch. It is also the largest of the three per-station files by
some margin, because HDF5 pays its structural cost once per file rather than once per survey. Take the
survey bundle when you want the whole survey.

```bash
BASE=${AUSMT_BASE:?the portal root you are reading from}
curl -s "$BASE/data/manifest.json" \
  | jq -r '.files[] | select(.survey=="Vulcan 2022" and .format=="edi") | "\(.url) \(.sha256)"' \
  | while read -r url sha; do
      curl -s -O "$BASE/data/$url"
      echo "$sha  $(basename "$url")" | shasum -a 256 -c -
    done
```

The same loop in Python, standard library only:

```python
import hashlib, json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]             # the portal root you are reading from
man = json.load(urllib.request.urlopen(f"{BASE}/data/manifest.json"))
for r in man["files"]:
    if r["survey"] != "Vulcan 2022" or r["format"] != "edi": continue
    body = urllib.request.urlopen(f"{BASE}/data/{r['url']}").read()
    assert hashlib.sha256(body).hexdigest() == r["sha256"], r["url"]
    open(r["url"].split("/")[-1], "wb").write(body)
```

The `files` filter above matches on the survey DISPLAY name, which is what a manifest row carries,
not the slug. `au.<slug>.` as a prefix test on `ausmt_id` works too and is less fragile.

An embargoed survey has no rows in the manifest at all. Its bytes are withheld by construction, so
there is nothing to request and no access error to handle, while its catalogue record stays public.

### Bounding-box fetch

`/data/mtcat.json` carries every station as a flat record in `stations[]`: `station_id` (the
`ausmt_id`), `survey_id`, `latitude`, `longitude` and `data_type`. Filter those records to the box, join
to the download manifest on `ausmt_id` (the one identifier a station record and a manifest row both
carry), then fetch each matched row's `url` under `/data/` and check its `sha256`.

```python
import hashlib, json, os, pathlib, urllib.request
BASE = os.environ["AUSMT_BASE"]             # the portal root you are reading from
W, S, E, N = 133.0, -30.0, 135.0, -28.0     # west, south, east, north
cat = json.load(urllib.request.urlopen(f"{BASE}/data/mtcat.json"))
ids = {st["station_id"] for st in cat["stations"]
       if st["latitude"] is not None and st["longitude"] is not None
       and S <= st["latitude"] <= N and W <= st["longitude"] <= E}
man = json.load(urllib.request.urlopen(f"{BASE}/data/manifest.json"))
for row in man["files"]:
    if row["ausmt_id"] not in ids or row["format"] != "edi": continue
    body = urllib.request.urlopen(f"{BASE}/data/{row['url']}").read()
    assert hashlib.sha256(body).hexdigest() == row["sha256"], row["url"]
    out = pathlib.Path(row["url"])          # mirror the manifest path, do not flatten it
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
```

Two coordinate caveats apply to any box filter.

A station whose position its custodian withholds carries `null` in `latitude` and `longitude`, always
as a pair, so the example tests both for null before comparing and those stations are excluded rather
than compared. A null is not a position, and no box contains one. Do not leave that to the language.
JavaScript reads `null` as `0` in a numeric comparison, which silently treats a withheld station as if
it sat at 0°, 0° instead of dropping it.

A station whose position is generalised at the custodian's request is served rounded to a 0.1° cell,
roughly 11 km, so a box edge is approximate. A generalised station can land on the wrong side of it by
up to 0.05°. The survey record's `coordinates_state` says whether a survey's positions are `exact`,
`generalised` or `withheld` (a mixture reads `generalised`) and is omitted when the survey declares no
policy; each station's `station.json` carries `coordinate_policy` when its own position is not exact,
and omits the key when it is.

One practical note. A box crosses surveys, and two surveys can hold a station with the same filename, so
write files out under the manifest's `url` path rather than flattening them to a basename or you will
lose one of the pair.

---

## Per-station products

Each station has a small product directory:

```text
/data/products/<slug>/<station>/station.json
/data/products/<slug>/<station>/dimensionality.json
```

`station.json` is the per-station record and a public contract. It carries identity, location, band and
period range, the derived diagnostics, the processing strings read from the source file, the
distribution state, the coordinate QC verdict, any canonical conditioning notes, and a `provenance`
block naming the input file and its SHA-256. It is documented field by field in
[Per-station products](../reference/station-products.md); its schema artifact arrives with the station
promotion lane.

`dimensionality.json` is served alongside it and is not a contract: it is the phase-tensor screening
result (`classification`, `skew_beta_median_deg`, `pct_periods_3d`, `method`), and its `note` says
"screening diagnostic, not an interpretation product". Treat it as a filter and not as a finding, and do
not build on its shape; whether it folds into `station.json` or stays a feature file is an open
decision.

The two files are gated differently, and the difference matters if you loop over stations:

| | Open survey | Withheld survey |
|---|---|---|
| `station.json` | Full record | `200`, with `"withheld": true`, an `access` block, and no derived science |
| `dimensionality.json` | Full record | `404`, never written |

So `station.json` always resolves and is worth requesting for any station; `dimensionality.json` should
only be requested when the survey's `access` is `open`. Check `mtcat.json` first, and do not treat that
`404` as a transport error.

There is no index of product directories. Directory listing is off. Build the paths from the
`survey_id` and the station part of the `station_id` in `mtcat.json`, which is safe here because the
product path uses the station id verbatim, unlike an artifact filename.

---

## Selecting a format

Three transfer-function formats are distributed, and which ones exist for a survey is stated, never
implied.

`mth5` is the one token that appears at both granularities, so read the list it came from rather than
the token alone: a `files[]` row is one station's transfer function, a `bundles[]` row is the whole
survey's.

| Format token | Where it appears | Granularity |
|---|---|---|
| `edi` | manifest `files[].format` | per station |
| `emtfxml` | manifest `files[].format` | per station |
| `mth5` | manifest `files[].format` | per station |
| `edi-zip` | manifest `bundles[].format` | per survey |
| `xml-zip` | manifest `bundles[].format` | per survey |
| `mth5` | manifest `bundles[].format` | per survey |

The manifest is the answer that always works, because it is the thing the formats are derived from:

```python
import collections, json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]             # the portal root you are reading from
man = json.load(urllib.request.urlopen(f"{BASE}/data/manifest.json"))
per_station = collections.Counter(r["format"] for r in man["files"])
per_survey = collections.Counter(b["format"] for b in man["bundles"])
print(per_station, per_survey)
```

That prints `Counter({'edi': 2389, 'emtfxml': 2389, 'mth5': 2143})` and
`Counter({'edi-zip': 25, 'xml-zip': 25, 'mth5': 25})` against the current corpus. To ask the same
question per survey, group `bundles` by `slug`.

MTCAT carries a shortcut. Each survey record has a `formats` list derived from that same manifest during
the same build, so a harvester can filter without fetching 2.5 MB:

```python
import json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]
cat = json.load(urllib.request.urlopen(f"{BASE}/data/mtcat.json"))
for s in cat["surveys"]:
    if "xml-zip" in s.get("formats", []):
        print(s["survey_id"])
```

The key is present only when at least one format is distributed. An embargoed or metadata-only survey
OMITS it: its holdings and their formats are known, they are simply not served, and MTCAT 2.0 has no
empty-array state to say so with. A producer with no manifest to derive from omits it too. So absence
means "no distribution statement", never "nothing exists", and the example above reads a missing key
as an empty list only because it is selecting surveys to download from.

---

## Watching for new or changed data

Two documents answer two different questions.

`feed.xml` answers "has a survey been added or updated?". It is an Atom feed, so an existing feed
reader handles it, and the entry id carries the slug you would then fetch.

`mtcat.json` answers "is what I hold still current?". Its `portal.generated_at` is the build timestamp,
and it changes on any rebuild, including one that only changed a survey's metadata:

```bash
curl -s "$BASE/data/mtcat.json" | jq -r .portal.generated_at
```

A polling client should not download the document to find that out. Every response carries an `ETag`,
so send a conditional request and an unchanged document costs a `304` instead of 511 kB:

```python
import json, os, urllib.request
BASE = os.environ["AUSMT_BASE"]                 # the portal root you are reading from
known_etag = None                               # persist this between polls; None on the first one
req = urllib.request.Request(f"{BASE}/data/mtcat.json")
if known_etag:                                  # from the previous poll
    req.add_header("If-None-Match", known_etag)
try:
    resp = urllib.request.urlopen(req)
    known_etag = resp.headers.get("ETag")
    generated_at = json.load(resp)["portal"]["generated_at"]
except urllib.error.HTTPError as e:
    if e.code != 304: raise                     # 304 means nothing changed
```

A `HEAD` request returns the same `ETag` without the body, if all you want is the comparison. Poll the
catalogue, not any other document: the small build-identity file the portal footer reads is
portal-internal and carries no stability promise.

Poll gently. The site is one small server, the data changes on the order of days, and there is no
rate limiter to protect it from a tight loop.

---

## The releases tier

The documents above describe the current build, and the current build moves. Build directories are
pruned and the pointer to the current build is swapped every rebuild, so neither is a citable target.

The release tier is the citable one. It freezes one build's catalogue surface (`mtcat.json`,
`surveys.json`, `manifest.json`) plus every per-survey bundle into `/data/releases/<tag>/`, writes a
`release.json` provenance document beside them, and updates a newest-first index at
`/data/releases/releases.json`.

```text
/data/releases/releases.json          the index: tag, cut time, doi, build_id, counts, path
/data/releases/<tag>/release.json     that release's own record, including per-file size + sha256
/data/releases/<tag>/datacite.json    a DataCite record, prepared but not submitted
/data/releases/<tag>/mtcat.json       the frozen catalogue surface
/data/releases/<tag>/bundles/         the frozen artifacts
```

Every copied bundle is re-hashed from the bytes that landed in the release directory and checked
against the manifest's own SHA-256 claim. Any mismatch fails the cut and leaves no release behind. An
existing tag is never overwritten.

No release has been cut yet. `/data/releases/releases.json` returns `404`, and the portal's
Releases page says "No releases cut yet" and names the document it looked for.

A consumer should copy that distinction. A `404` or an empty `releases[]` means none is published. Any
other error means this request could not find out, which is a different fact and usually an operator's
problem.

The tooling mints nothing. It prepares a DataCite record that can be submitted as it stands, with the
minted DOI stamped back into the release that already exists. Until then a release's `doi` is `null`,
and a consumer renders that as plain text rather than as a link.

The documents are specified in the [Releases tier reference](../reference/releases.md), and the policy
is in [Versioning and releases](../data-model/versioning.md).

---

## What the portal does that this page does not

The browser portal builds custom downloads from an arbitrary station selection, zips them client-side
and writes a citation pack (`CITATIONS.txt`, `citations.bib`, `citations.ris`) into the archive. That
work happens in the browser, from the same documents listed above, and there is no server endpoint
behind it. If you want the same result from a script, select from `mtcat.json`, fetch through the
manifest, and assemble the citation from the survey record's `creators[]` (in citation order), `title`,
`year_start`, `organisation` and `doi`.
