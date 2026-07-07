# MTCAT

## Overview

MTCAT (Magnetotelluric Catalogue) is a lightweight discovery schema for exchanging information about MT holdings between repositories.

MTCAT exists to answer:

- What collections exist?
- What surveys exist?
- Where are they located?
- Which organisations published them?
- Which stations are available?

It does not exist to exchange scientific data.

## Scope

MTCAT describes:

- Collections
- Survey packages
- Stations
- Identifiers
- Access information

MTCAT does not contain:

- Time-series data
- Transfer functions
- Derived products
- Inversion models

## Relationship to Survey Packages

The survey package is the authoritative scientific object.

MTCAT is a discovery record describing that survey package.

```text
Survey Package
      ↓
MTCAT Record
      ↓
Discovery
```

## Relationship to the API

MTCAT allows a survey package to be discovered.

The API allows the discovered survey package to be queried.

## Design Principle

MTCAT should remain small, stable and focused on discovery.
