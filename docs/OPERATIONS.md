# Operations

## Local startup

Use Python 3.12, install the pinned project dependencies, build the static frontend, and point `data_root` to a dedicated non-Git directory. Run `voxlush --config <config> doctor` before serving. Doctor runs local isolation checks and does not send an inference request. Start one API/scheduler process with `voxlush --config <config> serve`; do not run multiple service workers against the same data root.

The example profile intentionally has no endpoints and cannot create live requests. Before enabling live use, set a unique data root, endpoint aliases and capabilities, explicit enforceable request/cost budgets, API credentials through environment variables, and `allow_live: true`. The endpoint's actual protocol and parameter support must be checked against the endpoint, and model qualification must be evidenced separately. Remote binding requires an authenticated TLS reverse proxy and a configured admin token.

## Controls and shutdown

Use the dashboard or CLI campaign commands. They submit idempotent commands to the API; do not edit `runtime.db` directly. Pause stops further campaign dispatch while allowing local work to settle; drain stops new paid work and lets returned results finish local stages. For normal shutdown, drain active campaigns and then stop the process. `emergency_stop` can leave an external request with unknown billing/outcome; inspect the attempt record before retrying.

## Unknown execution reconciliation

Inspect attempt details in `GET /api/v1/samples/<sample_id>`. An `outcome_unknown` request keeps its financial reservation and blocks further dispatch to the same capacity pool. Independent routes can continue within the remaining global cap. If unknown execution occupies the full global authorization, obtain termination evidence before expecting new dispatch.

After the service confirms completion or cancellation, use:

```bash
voxlush --config <config> campaign reconcile_execution <campaign_id> \
  --attempt-id <attempt_id> --outcome cancelled \
  --evidence 'service cancellation receipt reference'
```

This releases execution occupancy, retains unknown cost, and does not retry the original POST. An endpoint may instead configure `server_max_execution_seconds` together with `execution_contract_ref`, but only if the service guarantees termination within that duration **from dispatch**, including queue time. Client idle/total timeouts do not supply that guarantee.

Roles on one service share capacity by default. Configure `capacity_pool` only for documented independent pools; roles sharing a pool must agree on cap/RPM/TPM. Config revision history is available from authenticated `GET /api/v1/config/history?campaign_id=<id>`; `before=<revision>` pages older records. Pure cap changes do not invalidate model qualification.

## Backup and restore

1. Pause or drain the campaign and wait for leases and pending archive commits to settle.
2. Run `voxlush --config <config> backup --output <new-directory>` and preserve its manifest and checksums with the backup.
3. Verify with `voxlush verify-release` for releases; backup verification is performed during backup and restore.
4. Restore only to a new destination: `voxlush restore --source <backup> --destination <new-data-root>`.
5. Start a temporary service against the restored root, inspect campaign/sample counts and artifact access, then stop it before any later use of that root.

The automated backup/restore integration test restores to a new path and verifies registered assets, releases, source paths, and database state. This is fixture evidence; it is not a restore of production data.

## Import and release

Run legacy import in dry-run mode first. Review counts, path/coordinate warnings and duplicates; a repeated import must be idempotent. Legacy completed records remain `legacy_complete_unverified`. Export creates an immutable release with a dataset card and deterministic ordering; run `verify-release` before distributing it. Fixture/provisional records are excluded from formal accepted counts.

## Schema 1 to 2 migration

The first new Store open upgrades schema 1 transactionally to schema 2, adding response application, capacity reconciliation, config history, exact upright dedup and seed summary records. Back up with the old release before opening a production database with the new release. Legacy alias mapping uses role plus alias; verify the configured route is the historical route during migration. Unknown historical snapshots remain unknown. The migration preserves existing assets, billing and unknown occupancy; it does not retroactively repair old immutable manifests or certify old accepted records.

The nonempty migration fixture preserves unknown reservations and passes SQLite integrity checking; a separate nonempty backup/restore fixture includes an archived asset plus failed and unknown requests. These are local test roots. No production migration was run. The previous release only reads schema 1, so rollback requires its verified pre-migration backup restored to a new root; pointing the old binary at schema 2 is not a supported rollback.

## Updates and rollback

Production update procedure is not exercised. When authorized, use a pinned commit/tag: drain, take and verify a consistent backup, inspect schema compatibility, deploy one process, run doctor and a local canary, and verify API/store/artifact counts. Before rollback, confirm the older binary can read the current schema. If it cannot, stop and restore the consistent backup to a new root, then reconcile artifacts and database records before switching traffic. Do not reset the live database or run two scheduler owners.

## systemd template

For a later single-host deployment, set the user, checkout, config path, data root, and environment file to locally managed values. The environment file must be readable only by the service account.

```ini
[Unit]
Description=Voxlush Gen
After=network-online.target docker.service
Requires=docker.service

[Service]
Type=simple
User=voxlush
Group=voxlush
WorkingDirectory=/opt/voxlush
EnvironmentFile=/etc/voxlush/voxlush.env
ExecStart=/opt/voxlush/.venv/bin/voxlush --config /etc/voxlush/config.json serve
Restart=on-failure
RestartSec=5
TimeoutStopSec=60
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

The template has not been installed or exercised on a production host. Use a protected TLS proxy for remote access; keep the backend bound to loopback unless the auth token and proxy requirements are satisfied.
