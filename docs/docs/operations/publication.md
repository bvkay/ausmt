# Publication

Publication is where a validated and reviewed survey package becomes part of the curated AusMT
record. It is not a file transfer. It establishes the package as an AusMT release: stable,
discoverable, citable, and traceable back to its sources.

Publication says the package meets the requirements for inclusion. It does not endorse any
scientific interpretation.

The unit is the survey package, never the individual file. What follows publication is a data
rebuild, which generates the derived products into the portal's data products rather than back
into the package; see [Science products](../science/science-products.md).

## Registration and discovery

A published survey is registered in one or more collections, which is how most navigation
reaches it. Discovery metadata are generated from the package rather than maintained
separately, so the survey becomes findable through the collection pages, the portal's search,
and the machine-readable MTCAT document served as static JSON alongside the other data files.
See [How AusMT serves data](../interoperability/api-overview.md).

## Version and citation

Every publication carries a version, and users should cite the version they used. The
convention and what the build does with it are in [Versioning](../data-model/versioning.md).

A citation may include the survey title, version, publication date and a persistent
identifier. Where a DOI is present it was supplied by the submitter and minted through an
external service such as Zenodo or an institutional minter. **AusMT does not mint DOIs.**
Integrated DataCite minting via ARDC is planned, not implemented.

## Access levels and embargoes

Every survey declares an access level in `survey.yaml`, and the build pipeline **enforces**
it. This is the serving gate, not a documentation convention:

```yaml
access:
  level: open            # open | metadata_only | embargoed
  embargo_until: null    # ISO date YYYY-MM-DD; required in spirit when level is embargoed
```

- **`open`**: the survey's transfer-function bytes are distributed, subject also to a
  redistributable licence. This is the default when the field is absent, matching the legacy
  all-open corpus.
- **`metadata_only`**: the survey is fully discoverable (catalogue, map, science diagnostics
  and the machine-readable MTCAT record) but **no product bytes are served**: no EDI, EMTF-XML
  or bundle downloads, and `edi_available` is `0`. Downloads route to the source archive.
- **`embargoed`**: same as `metadata_only`, discoverable with bytes withheld, until the
  embargo lifts.

Embargoes are common for active research projects, industry collaborations and
funding-agreement requirements. Metadata **remain discoverable throughout** an embargo; only
the bytes are withheld.

The access level is the **state of record**. A lapsed `embargo_until` does **not**
auto-publish the survey. Releasing data is a deliberate act, so the build keeps an embargoed
survey withheld even past its date and raises a stale-embargo warning for the curator. To
release, a curator changes `level` to `open` and re-runs the build. Conversely, an `embargoed`
level with no `embargo_until`, or with an unparseable date, is treated as embargoed
indefinitely (fail-closed) with a loud warning.

The submission validator enforces the same contract at the contributor gate: `access.level`
must be one of the three enum values (a hard failure otherwise), `embargo_until` must be an ISO
`YYYY-MM-DD` date when present, any non-`open` level raises a curator-attention warning, and a
past-dated embargo raises the stale-embargo warning.

The access level is not the only serving control. A survey can also declare
`access.coordinates`, which decides whether station positions are served exactly, generalised
to about 11 km, or withheld entirely. It is the custodian's call, the engine applies it at a
single seam before anything is emitted, and a station whose position is not exact has its
source bytes withheld too. See
[Why coordinates have an access policy](../rationale/coordinate-access.md).

> Note: the canonical EMTF-XML store (`--canonical-dir`) is a preservation artifact and carries
> no served download bytes or manifest rows. The per-station `products/` files behave
> differently. In a deployment they are written inside the served build directory, so they ride
> the same access gate as the rest. A station in a non-served survey gets a withheld
> `station.json` with no derived science, no exact position and no dimensionality file.

What a data consumer sees on the other side of this gate, including why there is no
authorisation branch to write, is in
[How AusMT serves data](../interoperability/api-overview.md#access-levels-and-embargo-by-omission).

## Withdrawal and supersession

Occasionally a published package has to be withdrawn or superseded: a serious metadata error,
an incorrect product assignment, an ownership dispute, or replacement by a corrected version.
Where possible a withdrawn package should stay discoverable with its status explained. A
visible publication history is usually better than a hole in the record.

When a package genuinely has to go, retirement is a curator action rather than an operator
recipe. The workbench's Retire survey path shows how many station files will be removed,
requires the slug typed back plus a release note, and takes a second factor before it commits
the removal to the survey repository. It refuses to retire the last remaining survey, because
an empty corpus fails the next build and would leave the retired survey serving off the
previous one.
