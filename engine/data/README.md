# data/ (CI sample only)

A tiny sample survey so `python -m extract.build_portal --surveys data --out site-data --products products`
has something to process in CI. **This is not the survey backbone** — published survey
packages live in the `ausmt-surveys` repo. In production the workflow runs against
contributed/curated data, not this folder.
