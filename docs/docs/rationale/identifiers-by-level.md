# Why identifiers carry a data level

## What it is

Dataset-level DOIs, handles and URLs are recorded in one list, `related_identifiers[]`. Each row
states what the identifier points at using the NCI Table 1 data-level terms, and the DataCite
relation is derived from that level rather than typed by hand. The vocabularies and the row shape
are in [survey.yaml Reference](../reference/survey-yaml.md#6-identifiers-by-data-level).

## Why it is built that way

AusMT is a curator, not a minter. It does not issue DOIs, so almost every identifier a survey
carries points at somebody else's record: an NCI collection, a raw time-series deposit, a state
geological survey landing page, a GA eCAT entry. A named slot per relationship cannot describe
those, because the same identifier legitimately plays different roles for different surveys, and a
slot has no way to say which role it is playing. One value in two slots is not a richer record; it
is the same fact asserted twice, and it makes a corpus look like it holds dataset DOIs it does not
hold.

Typing the pointer describes them all. A row says what the identifier is (`identifier_type`), what
it points at (`identifies`), and who holds it (`custodian`). That covers every relationship a named
slot could, and it scales to relationships nobody has thought of yet without a schema change.

Deriving the relation from the level matters more than it looks. Curators know what a DOI points
at, because they can read the landing page. Very few curators know whether that makes the AusMT
record `IsDerivedFrom` or `IsVariantFormOf` the target. Asking for the level and computing the
DataCite relation puts the question where the knowledge is. A hand-edited file can still set the
relation explicitly, and if it disagrees with the derived value the validator says so and leaves
the explicit value alone.

The level vocabulary is fail-closed for the same reason the credit roles are. An out-of-vocabulary
level publishes a wrong provenance claim about somebody else's data, so it blocks.

## Where the depth is

The vocabularies and their fail-closed behaviour are written out in the survey validator, a pinned
copy of which is public at
[`gateway/tests/fixtures/vendored_validation/validate_survey.py`](https://github.com/bvkay/ausmt/blob/main/gateway/tests/fixtures/vendored_validation/validate_survey.py).
