# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately** — do not open a public issue, and do not disclose
the details publicly until they have been addressed.

- **Email:** <ben@auscope.org.au>
- Alternatively, use GitHub's [private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
  ("Report a vulnerability" under the repository's **Security** tab), if enabled.

Please include enough detail to reproduce: affected component, version/commit, and steps.

## What to expect

- Reports are **acknowledged within five business days** (matching the operator contact commitment on
  the [governance page](docs/docs/introduction/governance.md)).
- We will confirm the issue, keep you updated on remediation, and credit you if you wish once a fix is
  released.

## Scope

This policy covers:

- **This repository** (the `ausmt` framework: engine, portal, gateway, contract, deploy tooling), and
- **the AusMT deployment** it operates (the submission gateway and the served catalogue).

Out of scope: the survey *data* itself (each survey remains the responsibility of its originating
custodian — see the governance page), and third-party dependencies (report those upstream, though we
welcome a heads-up).

## No bug bounty

AusMT is a pre-institutional, non-commercial research deployment. There is **no paid bug-bounty
program**. Good-faith reports are genuinely appreciated and will be acknowledged.
