# M4 provider-free Dagster projection and operations

## Scope and authority

M4 is a replaceable Dagster OSS projection over the Python-owned immutable
content, derivation, custody, and pointer repository. Dagster stores run,
sensor, partition, check, and materialization operations. It does **not** own
artifact bytes, deterministic identities, approvals, provenance truth, or
recipe semantics. Materialization metadata is bounded to full digests, counts,
statuses, work-unit IDs, schema/version labels, and `artifact://` references.

The only active cohort is the three licensed, identity-pinned synthetic fixture
triplets. Full deterministic work-unit IDs bind the exact workbook digest,
exact sheet name, requested use case `provider-free-reference-parity`, and
processing-profile digest. Recipe digest is a revision/input beneath the work
unit and is deliberately not part of work-unit identity. One shared dynamic
partition definition named `provider_free_work_units_v1` is used by every
partitioned asset. The cap is
1,000 active keys; temporary source absence never deletes keys. Removal and
historical retention policy are deliberately deferred.

The graph is intentionally small:

1. unpartitioned `source_catalog_snapshot` observes/publishes the immutable
   catalog digest and is an explicit dependency selected into every default
   work-unit run;
2. `verified_fixture_inputs_index` verifies and indexes one work unit's inputs;
3. `recipe_execution_evidence_index` invokes the sandboxed TypeScript worker,
   checks independent frozen-reference parity, and publishes an authoritative
   execution index; and
4. `active_work_unit_projection` publishes a reconstructable digest index.

The default-running sensor returns partition additions and stable run requests
in one `SensorResult`. It enforces the 1,000-key bound across the union of
existing and discovered keys. Its cursor is the immutable catalog digest rather
than a time. Run keys include the stable work-unit ID, exact recipe-revision
digest, and processing profile: a new recipe revision is projected under the
same dynamic partition without being deduplicated as an old revision. The
sensor also pins the expected recipe revision and catalog digest into run tags;
every asset and check rejects source drift after dispatch rather than
re-discovering a different revision mid-run. Revision-scoped immutable input,
execution, projection, and gate pointers retain history, while small active
pointers advance only after the corresponding immutable gate succeeds.
Re-evaluation before cursor commit returns identical run keys; after commit it
skips. Dagster's persistent run storage is the deduplication surface, while the
authoritative repository rejects deterministic output drift.

Each stage publishes a parsed and closure-validated immutable
`tidy.gate-result/v1` artifact for input/provenance, frozen-reference execution,
or reconstruction. Dagster asset checks only mirror these authoritative gate
results; they do not establish authority from pointers or byte-string searches.

Recipe summary remains unsupported, so M2 is still not accepted. M4 does not
add providers, credentials, ML, semantic adoption, calibration, justice
contracts, or Sembla execution.

## Pinned OSS decision matrix

All selected Dagster packages are exactly `1.13.17` in `uv.lock`.

| Capability                  | Dagster OSS selected for M4                                | Dagster+ status                 |
| --------------------------- | ---------------------------------------------------------- | ------------------------------- |
| Code location / asset graph | One local OSS `Definitions` module                         | Not elected                     |
| UI and GraphQL              | `dagster-webserver==1.13.17`                               | Not required                    |
| Sensors / daemon            | Local `dg dev` daemon                                      | Managed automation not required |
| Run/event/schedule storage  | Local persistent SQLite under `DAGSTER_HOME`               | Managed storage not required    |
| Run coordinator             | OSS queued coordinator, two concurrent runs                | Managed queue not required      |
| Launcher/executor           | Local default launcher/executor                            | Remote/HA launcher not selected |
| Concurrency pool            | OSS `provider_free_worker` pool, default limit two         | Managed pools not required      |
| Health / alerting           | Local process and HTTP health only                         | Managed alerting not selected   |
| Authentication / RBAC       | Tailnet identity boundary only; Dagster UI has no app auth | Dagster+ RBAC not selected      |
| High availability           | Not provided by one Mac/local SQLite                       | Dagster+ HA not selected        |

`dagster-dg-cli` currently brings helper/cloud CLI packages transitively, but
no Dagster+ service, deployment, credential, API, or authority is configured
or used.

## Validation

```sh
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run pytest -q -m persistent
RUN_DAGSTER_OPERATIONAL=1 uv run pytest -q -m operational
uv run dg check defs
npm run check
```

`dg check defs` is the confirmed Dagster 1.13.17 definitions-validation
command. The persistent test creates an actual `DAGSTER_HOME`, materializes
all three sandboxed work units and their immutable gate mirrors, closes and
reopens `DagsterInstance.get()`, and verifies runs, events, and dynamic
partitions. It deletes only disposable Dagster metadata and reconstructs the
catalog, all active materializations, and check mirrors from unchanged
authoritative index and gate digests.

The real `dg dev` operational test starts webserver plus daemon on a
disposable loopback port, waits for an actual default-sensor tick, all three
atomic partition additions and queued successful jobs, verifies stable run keys,
cursor/tick/materialization persistence, restarts `dg dev`, and proves no
run-key duplicates are created. Deterministic queue saturation, concurrency-pool
backpressure, large/multi-partition backfills, crash during a daemon-launched
run, and HA/failover are **not** accepted in M4 and remain explicit operational
gaps. M4 does not use unstable multi-asset backfills.

## Local UI lifecycle

The checked-in controller never changes Tailscale:

```sh
scripts/dagster-ui start
scripts/dagster-ui status
scripts/dagster-ui restart
scripts/dagster-ui stop
```

`start` performs the locked sync and TypeScript build, creates private state
under ignored `.dagster/`, and forces both `DAGSTER_HOME` and `TMPDIR` into that
repo-owned state so gRPC sockets survive the launching terminal/tool. It
launches the pinned `dg dev` command in a new session and accepts success only
when both HTTP health and an exact
`127.0.0.1:3030` listener are present. It rejects occupied/wildcard ports.
`stop` verifies the recorded PID, PGID, UID, exact command/token, OS start
time, launcher digest, and child environment markers before signaling. Listener
probes fail closed, every listener must belong to the managed process group,
and every bind must be exactly IPv4 loopback. Ownership is retained whenever
the group or listener cannot be proven gone. TERM is followed by a bounded,
revalidated process-group KILL; the controller never uses `pkill`. Logs and
ownership files are private and untracked.

The foreground command is exactly:

```sh
DAGSTER_HOME="$PWD/.dagster/home" \
  uv run dg dev --host 127.0.0.1 --port 3030
```

The controller survives terminal exit but does not restart after a Mac reboot.
Tailscale Serve can remain configured while the local process is absent, which
will produce an upstream error until `scripts/dagster-ui start` is run again.
A reviewed per-user LaunchAgent is a future option; none is installed here.

## Tailnet-only Android access

Do loopback health first. Only after the UI is accepted and healthy, enable the
single additive route:

```sh
scripts/tailscale-dagster-ui status
scripts/tailscale-dagster-ui enable
# Android/Tailscale browser:
# https://ians-mac-mini-1.taild519de.ts.net:3030/
scripts/tailscale-dagster-ui disable
```

The script captures the private pre-3030 Serve JSON, uses only:

```sh
tailscale serve --bg --https=3030 http://127.0.0.1:3030
tailscale serve --https=3030 off
```

and verifies the configuration is the baseline plus exactly HTTPS 3030. The
private baseline is written before mutation, retained after any ambiguous
addition or rollback, and consumed only after exact restoration. Disable first
proves the current route still matches the owned upstream. The script never
uses Funnel, reset, whole-config replacement, or changes another route. Process
stop and Serve disable are intentionally separate.

**Persistent-route warning:** Tailscale Serve can remain configured while the
managed UI is stopped. Any later unrelated service that reuses loopback port
3030 would then become reachable through that route. Disable Serve when the UI
is not intended to be reachable; enable refuses generic HTTP health and requires
the repo-managed `scripts/dagster-ui status` ownership/health result.

Dagster's development UI is not an application-authentication boundary. Any
tailnet identity permitted by grants/ACLs may be able to inspect metadata or
launch provider-free runs. Keep grants narrow, never enable Funnel, and do not
put workbook bytes, cell values, secrets, credentials, or provider data in
Dagster metadata/logs. The Mac must be awake, online, connected to Tailscale,
and running the local UI; Android must also be connected to the tailnet.
