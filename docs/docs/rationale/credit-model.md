# Why the credit model has two lists

## What it is

A survey records credit in two places. `creators[]` is an ordered list of the parties the citation
names, in author order. `contributors[]` is a repeatable list of who did what, and every row
carries a role from a fixed vocabulary. The field-by-field detail is in
[survey.yaml Reference](../reference/survey-yaml.md#3-credit-creators-and-contributors).

## Why it is built that way

Most Australian MT data reaches AusMT through a chain rather than from a single lab. A mining
company pays for a survey, a contractor collects it, a state geological survey holds it through an
embargo and then releases it, and a university reprocesses it years later. Asking which of those is
the "principal investigator" has no defensible answer, so the model does not ask.

Splitting the question into two answers it. The citation needs an ordered author list and nothing
else, so `creators[]` is ordered and carries no roles. Attribution needs to say what each party
actually did, so `contributors[]` is unordered, repeatable, and role-bearing. The same person can
appear once as a creator and three times as a contributor without either list becoming ambiguous.

The vocabularies are fail-closed. An unrecognised `name_type` or `role` blocks validation instead
of passing through. A wrong role publishes a false statement about who collected or owned a
dataset, and that is worse than refusing the package.

Credit is optional. Omit `creators[]` and the citation falls back to an organisation-and-year
synthesis, which is the correct citation for most state-survey releases. The model does not force
a curator to invent authorship that the source never had.

## Where the depth is

The clearest single read is the editor's typed credit rows in
[`gateway/editor_form.py`](https://github.com/bvkay/ausmt/blob/main/gateway/editor_form.py). The
vocabularies and their fail-closed behaviour are enforced by the survey validator, a pinned copy of
which is public at
[`gateway/tests/fixtures/vendored_validation/validate_survey.py`](https://github.com/bvkay/ausmt/blob/main/gateway/tests/fixtures/vendored_validation/validate_survey.py).
