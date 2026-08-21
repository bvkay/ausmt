# Publication

Publication is where a validated and reviewed survey package becomes part of the curated AusMT record:
stable, discoverable, citable, and traceable back to its sources. It says the package meets the
requirements for inclusion; it does not endorse any scientific interpretation. The unit is the survey
package, never the individual file. What follows publication is a data rebuild, which generates the
derived products into the portal's data products rather than back into the package.

## Registration and discovery

A published survey is registered in its collection, and discovery metadata are generated from the
package rather than maintained separately, so the survey becomes findable through the collection pages,
the portal's search, and the MTCAT document served as static JSON beside the other data files. See
[How AusMT serves data](../interoperability/api-overview.md).

## Version and citation

Every publication carries a version, and users should cite the version they used; see
[Versioning](../data-model/versioning.md). Where a DOI is present it was supplied by the submitter and
minted through an external service. AusMT does not mint DOIs; integrated DataCite minting via ARDC is
planned, not implemented.

## Access levels and embargoes

Every survey declares an access level in `survey.yaml`, and the build enforces it. This is the serving
gate, not a documentation convention:

```yaml
access:
  level: open            # open | metadata_only | embargoed
  embargo_until: null    # ISO date YYYY-MM-DD
```

- `open`: the survey's transfer-function bytes are distributed, subject also to a redistributable
  licence. The default when the field is absent.
- `metadata_only`: the survey is fully discoverable (catalogue, map, science diagnostics and the MTCAT
  record) but no product bytes are served: no EDI, EMTF XML or bundle downloads, and `edi_available` is
  `0`. Downloads route to the source archive.
- `embargoed`: as `metadata_only`, until the embargo lifts.

Metadata remain discoverable throughout an embargo; only the bytes are withheld. The access level is
the state of record: a lapsed `embargo_until` does not auto-publish the survey. The build keeps an
embargoed survey withheld past its date and raises a stale-embargo warning; a curator releases it by
changing `level` to `open` and re-running the build. An `embargoed` level with no `embargo_until`, or
with an unparseable date, is treated as embargoed indefinitely with a loud warning.

The submission validator enforces the same contract at the contributor gate: `access.level` must be one
of the three values (a hard failure otherwise), `embargo_until` must be an ISO `YYYY-MM-DD` date when
present, any non-`open` level raises a curator-attention warning, and a past-dated embargo raises the
stale-embargo warning.

A survey can also declare `access.coordinates`, which decides whether station positions are served
exactly, generalised to about 11 km, or withheld. The engine applies it at a single seam before
anything is emitted, and a station whose position is not exact has its source bytes withheld too. See
[Why coordinates have an access policy](../rationale/coordinate-access.md).

The canonical EMTF XML store (`--canonical-dir`) is a preservation artifact and carries no served
download bytes or manifest rows. The per-station `products/` files are written inside the served build
directory and ride the same access gate: a station in a non-served survey gets a withheld `station.json`
with no derived science, no exact position and no dimensionality file. What a data consumer sees on the
other side of the gate is in
[How AusMT serves data](../interoperability/api-overview.md#access-levels-and-embargo-by-omission).

## Withdrawal and supersession

A published package is occasionally withdrawn or superseded: a serious metadata error, an ownership
dispute, or replacement by a corrected version. Where possible a withdrawn package stays discoverable
with its status explained; a visible publication history is better than a hole in the record.

Retirement is a curator action. The workbench's Retire survey path shows how many station files will be
removed, requires the slug typed back plus a release note, and takes a second factor before it commits
the removal to the survey repository. It refuses to retire the last remaining survey, because an empty
corpus fails the next build.
