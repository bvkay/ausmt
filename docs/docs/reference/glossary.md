# Glossary

## Collection
A logical grouping of related surveys.

## Survey Package
The primary publication unit within AusMT.

## Transfer Function
The primary scientific product published by AusMT.

## MTCAT
A lightweight discovery schema for MT catalogue exchange.

## Provenance
Information describing the origin and processing history of a published product.

## Creators
The ordered list of parties a survey's citation names, in author order.

## Contributors
The parties who did the work, each row carrying a role from a fixed vocabulary. Separate from
creators, because who is cited and who did what are different questions.

## Related identifier
A typed pointer to a record AusMT does not own, stating what the identifier is, what data level it
points at, and who holds it.

## Coordinate access
The custodian's declaration of how a survey's station positions are served: exact, generalised to
about 11 km, or withheld.

## Release
A frozen snapshot of the whole served corpus, cut into `/data/releases/<tag>/` with its own download
manifest and citation record. A release directory is immutable, so a paper can cite a fixed state of
the corpus rather than a build that moves. The documents and their fields are in
[Releases tier](releases.md).
