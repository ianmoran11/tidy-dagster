# Historical summary reference v1

- `reference.schema.json` binds default sheet-summary objects generated from the
  immutable copied TidyCell closure in a disposable, network-denied relocation.
  It records historical-source provenance only, so `candidateImplementationUsed`
  and `parityEstablished` remain false.
- `parity.schema.json` is a later implementing-agent comparison record. It binds
  the exact candidate source closure and exact structural equality for four
  sheets across the three synthetic workbooks. Its scoped parity is true while
  full Phase C parity remains false.

```sh
npx tsx scripts/freeze-source-summary-reference.ts \
  --bundle reference/source-closures/sha256-... \
  --output fixtures/reference-summary/historical-v1.json \
  --recorded-at 2026-08-11T21:30:00Z
```

The worker emits `sheet-summary.json` only when `includeSummary: true`. Compact
context, formatting facts, catalogue inputs, produced-CSV summaries, prompt
messages, broad adversarial coverage, and independent review remain later gates.
