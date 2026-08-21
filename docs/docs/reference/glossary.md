# Glossary

## Collection
A grouping of related surveys (a programme, a release, an institutional holding). Discovery context,
not data.

## Survey package
The primary publication unit: transfer functions, metadata, provenance and citation information for one
survey, versioned together.

## Transfer function
The primary scientific product AusMT publishes: the impedance tensor and tipper estimates for one
station.

## MTCAT
The JSON discovery schema AusMT emits for exchange between MT catalogues.

## Provenance
The origin and processing history of a published product.

## Creators
The ordered list of parties a survey's citation names, in author order.

## Contributors
The parties who did the work, each row carrying a role from a fixed vocabulary. Separate from creators,
because who is cited and who did what are different questions.

## Related identifier
A typed pointer to a record AusMT does not own, stating what the identifier is, what data level it
points at, and who holds it.

## Coordinate access
The custodian's declaration of how a survey's station positions are served: exact, generalised to
about 11 km, or withheld.

## Release
A frozen snapshot of the whole served corpus, cut into `/data/releases/<tag>/` with its own download
manifest and citation record. Immutable, so a paper can cite a fixed state of the corpus. See
[Releases tier](releases.md).
