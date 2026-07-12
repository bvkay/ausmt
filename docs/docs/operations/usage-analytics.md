# Usage analytics

AusMT records **anonymous, aggregate** usage of the served data — how much is downloaded, which
datasets, from which countries, and how many portal visits — for research-infrastructure reporting
(AuScope) and custodian conversations ("your survey was downloaded *N* times from *M* countries").

It is deliberately **not** ad-tech. There are no cookies, no cross-site tracking, and no per-user
identity. Only aggregate counts are ever stored.

## What is measured

| Metric | Source |
| --- | --- |
| Downloads by survey / station / format | Server access-log paths (`/data/edi`, `/data/xml`, `/data/bundles`) resolved through the build's `manifest.json` reverse map. |
| Portal visits | One `catalogue.json` fetch per single-page-app boot — the only server-observable visit signal. |
| Downloads & visits by country | The **masked** client address resolved to a country (see below). |
| Daily time series | Downloads and visits folded per calendar day (UTC). |

### What is *not* measured — honestly

Per-station and per-survey **page views** are **not** counted, because they cannot be measured from
server logs: the portal is a single-page application that loads the whole catalogue once and renders
every station and survey view in the browser, making **zero** additional server requests per
navigation. This screen therefore reports *downloads* (a real server request) and *whole-portal
visits*, not page views. User identification, sessions, and funnels are never collected.

## Privacy design

The public privacy promise — cookieless, no personal data — is a feature of this design, not an
obstacle to it. Research-infrastructure analytics need aggregates, never identities.

- **IP addresses are masked at the edge.** The web server truncates every client address *at write
  time* — IPv4 to a /24, IPv6 to a /48 — so a full address never touches disk. Address-bearing
  headers (`X-Forwarded-For`, `X-Real-IP`, `Forwarded`, `Referer`) and credentials (`Cookie`,
  `Authorization`) are dropped from the log entirely.
- **Only aggregates are retained.** The daily aggregator folds the log into cumulative counts; the
  published `stats.json` contains **no address** (masked or otherwise) and **no user-agent string** —
  only counts and a daily series.
- **Raw logs are short-lived.** The access log is rotated with a ~7-day retention; the tail exists
  only for debugging and is not the database.

## Country data attribution

Country resolution uses the **IP to Country Lite** database by **DB-IP** (<https://db-ip.com>),
made available under the **Creative Commons Attribution 4.0 International (CC-BY-4.0)** licence.

> This product includes IP to Country Lite data created by DB-IP.com, available from
> <https://db-ip.com>, licensed under [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/).

The dataset is a monthly CSV of IP ranges read directly by a small standard-library lookup — AusMT
uses no MaxMind/GeoIP tooling and holds no licence key. Country attribution from a /24-masked address
is correct in the overwhelming majority of cases; a small amount of wrong-country noise at range
boundaries is acceptable for aggregate reporting. If the CSV is absent or out of date, country simply
resolves to `unknown` and every other metric is unaffected.

## Operating it

The aggregator runs as a daily host timer and the workbench **Analytics** screen (under *Operations*)
renders the result. Installing the timer and placing/refreshing the DB-IP CSV are one-time / monthly
operator chores documented in the deployment runbook (`deploy/README.md` → "Usage analytics").
