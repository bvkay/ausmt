# Download Manifest Schema

## Overview

`manifest.json` is the key-based index of every **downloadable** AusMT artifact. It lets a client
discover what can be downloaded for a station or survey, in which format, from where, and with what
integrity (size + SHA-256).

It rides **beside** the positional `catalogue.json`/`sci.json`/`tf.json` arrays — download metadata
is never added as new positional columns — so adding or changing it costs the index-reading consumers
nothing. The portal's download resolver (`portal/src/data.js`) is the primary consumer.

The authoritative schema is `engine/schema/manifest.schema.json` (JSON Schema draft-07,
`$id: https://ausmt.org/schema/manifest-1.0.schema.json`). The field-by-field walkthrough lives in
[Developer → Data files](../developer/data-files.md); this page is the schema reference.

---

## Document Structure

```text
generated_count   integer   total artifacts = len(files) + len(bundles)
base_url          string    URL prefix applied to artifact urls ("" = portal-relative)
files             array     per-station downloadable artifacts
bundles           array     per-survey bundles
```

`generated_count`, `files` and `bundles` are required. An empty deployment emits a valid empty
manifest:

```json
{ "generated_count": 0, "base_url": "", "files": [], "bundles": [] }
```

---

## files[] — per-station artifacts

Each row describes one downloadable file for one station.

```text
ausmt_id   string                      the station's unique public id (catalogue r[12])
survey     string                      survey label
station    string                      station id within the survey
format     "edi" | "emtfxml"           artifact format
url        string | null               portal-relative path; null only for tier=nci (reserved)
size       integer (bytes)             size of the SERVED artifact
sha256     string (64 hex chars)       SHA-256 of the SERVED artifact (download integrity)
tier       "repo" | "nci"              hosting tier (repo today; nci reserved)
license    string                      the survey's license (always a redistributable one)
```

All fields are required.

---

## bundles[] — per-survey artifacts

Each row describes one pre-built per-survey download.

```text
survey       string                    survey label
slug         string                    survey slug (path-safe)
format       "edi-zip" | "xml-zip" | "mth5"   bundle format (mth5 = transfer functions only)
url          string | null             portal-relative path; null only for tier=nci
size         integer (bytes)
sha256       string (64 hex chars)
tier         "repo" | "nci"
license      string
n_stations   integer                   number of stations in the bundle
```

All fields are required.

---

## Semantics

- **URLs are portal-relative by default** — e.g. `edi/<slug>/<file>.edi`,
  `xml/<slug>/<station>.xml`, `bundles/<slug>-edi.zip`, `bundles/<slug>-xml.zip`, `bundles/<slug>-tf.h5`.
  The portal joins each url onto its `data_base_url`, so migrating a tier to NCI later is a manifest
  change with zero consumer edits. A `tier: "nci"` row carries a `null` url (reserved until the
  NCI/THREDDS base is configured); the current build emits only `tier: "repo"`.
- **Integrity is of the served bytes.** EDI copies and the per-survey EDI zip are byte-reproducible
  (so their SHA-256 is a stable cross-build invariant, given a fixed zlib). EMTF XML (and the EMTF-XML
  zip) and the transfer-function MTH5 embed timestamps/uuids and are **not** byte-reproducible — their
  SHA-256 is a per-build download-integrity hash, not a cross-build invariant.
- **The manifest lists only what AusMT serves.** Only redistributably-licensed surveys appear; a
  non-served station has no row and the portal routes it to the source DOI archive (via the catalogue's
  `edi_available` bit). So the manifest answers "what can I download here, and is it intact?".
- **Feature flags** (`portal.config.yaml` → `flags:`, default OFF) gate optional bundles:
  `survey_h5_enabled` produces the per-survey transfer-function MTH5 `bundles/<slug>-tf.h5` (decision D4
  keeps MTH5 off pending a storage/management decision); `collection_download_enabled` is reserved. The
  EDI zip and EMTF-XML zip are unconditional for a served survey. Flags are recorded in
  `build_provenance.json` under `distribution_flags`.

---

## Versioning

The schema id carries the version (`manifest-1.0.schema.json`). Minor updates may add optional fields;
incompatible changes bump the major version and ship as a separate schema file, mirroring the MTCAT
policy.
