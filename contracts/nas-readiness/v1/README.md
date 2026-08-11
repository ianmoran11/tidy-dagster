# NAS readiness inspection v1

`report.schema.json` records a sanitized, implementing-agent, read-only inspection
of client-visible NAS controls required by ADR 0005. The inspector stores no raw
command output, server address, account label, SID, workstation path, or
credential, and it performs no write or configuration operation against the NAS.

```sh
uv run python -m tidy_orchestrator.nas_readiness_cli \
  --mount-path "/private/mounted/share" \
  --metadata-root .local-repository \
  --output fixtures/nas-readiness/phase-b-current-v1.json \
  --inspected-at 2026-08-11T21:00:00Z
```

The current report confirms a mounted SMB 3.1.1 session, an observed signing
algorithm, and local SQLite. It deliberately fails the signing gate because
neither client nor server reports signing as required. Dedicated non-admin
service identity, snapshot availability, a restore drill, and formal current
commit-marker-adapter gate evidence also remain unverified. Therefore
`canaryImportReady` is always false in this inspection version.
