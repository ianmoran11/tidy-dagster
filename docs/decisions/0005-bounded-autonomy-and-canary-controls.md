# ADR 0005 — bounded autonomy and canary controls

- Status: accepted
- Decision date: 2026-08-11
- Scope: post-Phase-A migration, Phase C source custody, the first real import canary, and the conditionally authorized provider pilot

## Context

Phase A produced a frozen provider-free TidyCell inventory. Fixture-only Phase B
and Phase C scaffolds then established content import, conservative evidence,
approval reconciliation, and no-copy source-closure primitives. Advancing every
implementation choice through interactive confirmation would unnecessarily stall
reversible provider-free work. The user delegated routine and architectural
implementation choices to the implementing agent while retaining the existing
hard boundaries around fabricated human authority, destructive changes, and
unauthorized external effects.

The source spreadsheets are publicly available and non-sensitive. Integrity,
provenance, recovery, parser isolation, credential protection, and least-privilege
writes remain important even though workbook confidentiality is not the primary
risk.

## Decision

### 1. Use bounded autonomous execution

The implementing agent may autonomously:

- make reversible repository-local implementation choices;
- inspect the explicitly authorized pinned TidyCell and Tidybank sources
  read-only;
- freeze manifests before interpretation, copying, or scoring;
- use conservative deterministic defaults;
- self-review and commit small independently revertible increments;
- quarantine uncertain evidence rather than infer authority; and
- continue other work when one branch is blocked.

The agent must not fabricate reviewer identity, workbook acceptance criteria,
approval, licensing evidence, or source authority. Missing human evidence remains
inactive. Unavailable credentials or a prohibited external side effect block only
the affected branch.

### 2. Record review status honestly

Implementing-agent self-review is sufficient for the Phase A/B import canary,
Phase C source-custody/parity work, and the provider gateway. None of those
artifacts may be described as independently reviewed. This supersedes the
independent-review requirements for those named scopes in the planning baseline;
it does not turn self-review into independent acceptance.

### 3. Use a separate migration-only TypeScript executable

One-time RecipeV01 parsing, historical digest compatibility, and other
migration-specific interpretation run through a dedicated, digest-bound,
network-denied TypeScript executable. The accepted production domain worker
protocol remains narrow. Python continues to own orchestration, repositories,
authorization, custody, and reconciliation.

### 4. Discover and freeze the real Phase C closure before copying

Read-only discovery is authorized against:

- TidyCell bytes that exactly match the frozen Phase A snapshot; and
- Tidybank at pinned commit `c26e7f67091c414b411221af461b8ea3974c6320`.

Discovery must name every selected source, test, fixture, manifest, lockfile,
licence, and notice byte. It stops on a source mismatch. After an exact closure
manifest, licence evidence, and self-review pass, the selected repository-local
source closure may be copied with exact provenance. No runtime dependency on a
sibling worktree is allowed.

### 5. Stage the real content import

The first real import is a deterministic stratified canary selected mechanically
and frozen before bytes are copied. It must exercise relevant artifact classes,
dispositions, duplicate aliases, and adverse cases within a hard bound. A full
44,682-item / 19.33-GiB import remains a separate later authorization and is not
authorized by this ADR.

The canary targets the NAS blob store while SQLite authority remains local. It
may run only after the applicable NAS controls and importer gates pass.

### 6. Apply these NAS controls

- Runtime writes use a dedicated non-admin NAS service identity restricted to
  the Tidy Dagster subtree; a separate administrator remains available for
  recovery.
- SMB3 signing is required. SMB payload encryption is optional.
- The user explicitly accepts the scoped risk of unencrypted data at rest.
- NAS snapshots and a successful restore drill are required for the canary.
- A separate backup is required before any full import.
- The SMB commit-marker adapter must pass integrity, restart, and recovery tests.
- SQLite over SMB remains prohibited.

### 7. Preserve approval uncertainty

Historical reviewer labels are shown in a bounded curation queue. Only an exact
label-to-person mapping explicitly confirmed by a human can establish reviewer
identity. Under autonomous operation, unconfirmed labels remain
`legacy_approved_unattributed`.

Historical workbook/sheet targets resolve only through one exact digest-based
evidence chain. Zero, multiple, name-only, fuzzy, or inferred matches remain
unresolved. No manual target-guessing queue is required.

### 8. Archive legacy models without opening them

All legacy model binaries remain archival. They are not deserialized, inspected,
converted, parity-tested, or executed. Consequently, the ML-assisted live path
remains blocked until a new eligible model is trained from attributable
human-approved material or a later decision changes this rule.

### 9. Curate acceptance manifests incrementally

Human-written workbook acceptance manifests are prepared for canary workbooks
first. The AI, provider, or ML model cannot author the oracle that accepts its own
output. Workbooks without an attributable manifest remain ineligible for
automatic acceptance.

A canary recipe may become active only after its manifest and every immutable
gate pass. Pointer movement is atomic and cannot silently replace a currently
human-approved recipe. TidyCell remains the historical source of truth during the
canary; there is no source-of-truth cutover.

### 10. Preserve the conditional USD 25 provider authorization

After all provider-free gates pass, the frozen campaign is preauthorized up to a
hard cumulative USD 25 ceiling. The provider gateway may use broadly relevant
migrated textual evidence only after classification and secret scanning.
Credentials, private reviewer details, machine-local paths, binary models, and
executable content remain excluded.

Worst-case cost is reserved transactionally before dispatch. Ambiguous attempts
are never blindly retried. Self-review is sufficient but must be reported as
self-review. The provider pilot remains blocked while any required model,
acceptance manifest, source closure, security control, replay test, or budget gate
is missing.

## Autonomous stop rules

The implementing agent leaves the affected branch blocked, records evidence, and
continues elsewhere when work would require:

- guessing human identity or acceptance truth;
- unavailable credentials or administrator access;
- destructive mutation of source evidence;
- a full real-estate import without its later authorization;
- provider spend above USD 25;
- public publication, justice semantic adoption, calibration, simulation, or
  Sembla execution;
- a source-of-truth cutover; or
- any other explicitly prohibited side effect.

## Consequences

Provider-free implementation can advance without repeated interaction, and
uncertainty becomes explicit inactive data rather than an invented workaround.
The trade-off is that self-review carries correlated-error risk, NAS at-rest
confidentiality is knowingly weaker, and several human-authority-dependent paths
may remain blocked indefinitely. Those limitations must remain visible in status
reports and cannot be converted into claims of independent acceptance.
