# ADR 0004 — waive Phase A review only for dry Phase B implementation

- Status: accepted by explicit user instruction
- Date: 2026-08-10

## Decision

Proceed from the committed Phase A candidate into provider-free Phase B
implementation without obtaining the planned independent Phase A review first.
Do not describe Phase A as independently reviewed.

The user selected the bounded option: implement and test Phase B, but do not run
the real 19.33 GiB import.

## Authorized now

- strict Phase B core import/reconciliation contracts;
- a local-SQLite/replaceable-blob-store boundary;
- SMB-compatible committed blob publication;
- fixture-only import, restart, crash, tamper, and reconciliation tests;
- provider-free historical-digest compatibility, explicit approval outcome,
  reviewer-identity, and conservative typed-evidence fixture tests; and
- documentation of unresolved live semantic-import work.

## Still unauthorized

- copying any real TidyCell source-content object;
- pointing SQLite directly at SMB;
- adding a live-import authorization or operational CLI;
- moving an effective recipe pointer;
- interpreting a legacy approval as attributable or active without evidence;
- provider calls, model execution, publication, semantic adoption, or Sembla;
  and
- claiming that waived review occurred.

## Safety replacement for this slice

The implementation exposes only `FixtureImportAuthorization`. It requires source
system `phase-b-fixture` and has hard caps of 1,000 items and 64 MiB. The frozen
TidyCell snapshot cannot satisfy this boundary. A later live-import capability
requires a new explicit authorization after storage, security, semantic-import,
and reconciliation gates are complete.

## Consequences

The Phase B content core may advance while independent review remains absent.
Any defects that review would have found remain an explicit residual risk. The
work must report partial status honestly:
`core-content-complete-semantic-import-pending` is not Phase B acceptance.
