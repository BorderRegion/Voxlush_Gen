# Acceptance Report

Date: 2026-10-08 (Asia/Shanghai)

Repository baseline: `4f4be137d3924b38cb7301c2c4a0081ff32a7c2a`.

Environment: Python 3.12.3, Node 20.19.0, npm 10.8.2, Docker 29.1.3, APSW SQLite 3.51.3, Linux, `voxlush-sandbox:v1` (`sha256:50712f3b25dc`). The checked-in profile has `allow_live=false`, no author or visual endpoint, and global API cap 0. The acceptance data root was `/tmp/voxlush-acceptance-20261008`; it is outside the repository and is not production data.

## Result Boundary

The implementation is available and the offline local path is exercised. After the debug pass, the automated Python suite reports **85 passed, 1 skipped** (the skipped test needs a private legacy archive). Ruff passed. The frontend build (`tsc -b` plus Vite) passed. The mock dashboard suite reports **9 passed**, and the real local backend/browser suite reports **1 passed**. New fault tests use loopback HTTP/SSE and injected filesystem/readonly-DB failures; no model provider is contacted. Doctor returned `ready=true` with non-root, no-network, read-only root and read-only input checks. The external-root campaign run made **0 model requests**, ended with 0 samples and 0 assets, and produced a verified empty release. Backup and restore to a new root were verified; restored campaign counts matched.

No paid model request, real remote API test, human blind review, 100-candidate quality calibration, 100k/1m scale run, production migration, deployment, or rollback was performed. Those are not inferred from software tests.

Evidence labels:

- **L**: real local geometry/render/runtime or Store evidence.
- **N**: fake network/transport evidence; it does not qualify a model.
- **F**: filesystem/archive/security unit evidence.
- **B**: browser/UI evidence against the mock transport.
- **R**: external-root offline acceptance run.
- **M**: real model API evidence (none in this report).
- **H**: human blind-review evidence (none in this report).

## T01-T32

| ID | Status | Executable entry and observed evidence | Evidence |
|---|---|---|---|
| T01 | Partial | `test_catalog_contract_and_runtime_mapping`, `test_real_build_render_archive_export_backup_restore`, and the real browser fixture create a new local task/sample. A blank task with no legacy source is not an isolated acceptance case. | L |
| T02 | Partial | `test_single_store_owner_and_stale_callback_are_enforced` rejects a second Store owner. The original deliberately inconsistent legacy disk/state reproduction was not run. | L |
| T03 | Partial | `test_reservations_never_exceed_cap` covers 0/1/2/8/32; mock UI exercises durable cap updates for 1 and 2. Dynamic scheduler downgrade remains unverified. | L,N,B |
| T04 | Unverified | No concurrent author/fix/visual queue fairness run was recorded. | - |
| T05 | Partial | `test_busy_endpoint_defers_sample_and_releases_slot_without_semantic_repair` exercises real loopback 429/503 with Retry-After and freed occupancy. A full delayed retry lifecycle remains unverified. | N,L |
| T06 | Partial | `test_incomplete_or_failed_stream_is_never_executable` rejects empty content, reasoning-only and missing-DONE EOF; completion on open sockets and UTF-8/CR/LF chunk boundaries also pass. Scheduler execution rejection is not a separate case. | N |
| T07 | Partial | Client fixtures reject length, body error and missing completion while preserving raw evidence; no full scheduler truncation-repair lifecycle was run. | N |
| T08 | Pass | `test_post_disconnect_keeps_unknown_budget_and_rejects_retry` sends one loopback POST, retains unknown cost/reservation/occupancy and rejects retry; client disconnect behavior also passes. | N,L |
| T09 | Pass | `test_durable_response_recovers_after_restart_without_second_post` closes/reopens the Store after saving a complete response, restores build readiness and actual cost, and observes exactly one POST. | N,L,F |
| T10 | Pass | `test_fixture_archive_is_never_accepted_and_commit_recoverable`, `test_real_build_render_archive_export_backup_restore`, and integrity checks cover rename/commit recovery and exact-once registration for local artifacts. | L,F |
| T11 | Partial | `test_failed_finish_preserves_complete_response_and_other_work_continues` injects callback exception/cancellation, preserves complete response and billing, and completes another sample. Long-running loop continuation is not separately tested. | N,L,F |
| T12 | Partial | `test_persistent_response_storage_failure_settles_and_stops_paid_dispatch` and `test_readonly_store_retains_response_and_stops_dispatch_until_recovery` cover request/response write failures, conservative accounting, blocked dispatch and saved-response recovery. Disk-near-reserve behavior remains unverified. | N,L,F |
| T13 | Pass | `test_actual_isolation_host_secret_network_root_and_recovery` exercises timeout, memory, file/output bounds and confirms a later build continues. | L |
| T14 | Pass | `test_single_store_owner_and_stale_callback_are_enforced` rejects a late callback after a newer revision is claimed and preserves its lease. | L |
| T15 | Partial | Browser duplicate-click/uncertain-command tests and real persistent pause/reload pass. Saved-response restart preserves request/cost accounting; unknown retry is rejected. A full command/process-restart lifecycle remains unverified. | N,B,L |
| T16 | Unverified | No slow/crashed renderer backpressure run was recorded. | - |
| T17 | Unverified | No optional pool-health outage with successful calls was recorded. | - |
| T18 | Partial | `test_bad_endpoint_is_isolated_without_repair_loop` covers loopback 401/400/402/insufficient-quota isolation. No remote model endpoint was tested. | N,L |
| T19 | Partial | `test_adding_visual_endpoint_resumes_waiting_reviews` requeues awaiting_visual after configuring an image-capable endpoint without sending a request. Real local browser evidence shows fixture/provisional visual output and empty formal export; actual image capability remains unqualified. | L,B |
| T20 | Partial | `test_candidate_signature_ignores_translation_rotation_and_materials` covers candidate rotation/translation signatures; a full same-lineage archive/export material-derivative case was not run. | F |
| T21 | Pass | `test_real_natural_and_ruin_contracts` builds islands, cave and ruin contracts and renders them without the wooden-house gate. | L |
| T22 | Partial | Frozen wooden negative checks run in `test_opening_overdraw_and_frozen_legacy_gate`; the three private saved failures were skipped because the private archive was not supplied. | L |
| T23 | Pass | `test_opening_overdraw_and_frozen_legacy_gate` rejects filled openings and a missing required room, including skeleton/final contract differences. | L |
| T24 | Pass | `test_real_build_render_repeat_and_roundtrip` confirms identical canonical and annotation hashes and identical previews for the same source/seed/runtime. | L |
| T25 | Pass | Mock browser stream disconnect/reconnect and idempotent controls pass; real browser persistence/reload also passes. | N,B,L |
| T26 | Pass | Mock failed reads keep unknown metrics and do not switch to demo data; real settings/config validation passes. | N,B,L |
| T27 | Pass | Export grouping and leakage checks are covered by `test_source_and_geometry_and_lineage_groups_join` and deterministic export tests. | F |
| T28 | Pass | Path traversal, symlink, corrupted artifact and inert script-text tests pass; downloads are restricted to registered artifact paths. | F,B |
| T29 | Unverified | No run reached a global target or exhausted a real budget with surplus accounting. | - |
| T30 | Partial | Theme catalog and coverage planning are tested, but a live zero-output theme alongside healthy themes was not run. | L |
| T31 | Unverified | No long-lived zero-output stop-loss run was recorded. | - |
| T32 | Pass | `test_backup_restore_uses_sqlite_snapshot_and_preserves_assets`, the full local fixture integration test, and the external-root acceptance run verify backup, new-path restore, verification, and matching campaign counts. | F,L,R |

## Acceptance Run Details

The external-root run used the checked-in offline config copied to `/tmp/voxlush-acceptance-20261008/config.json`. Doctor passed. The service was started once, campaign `offline-demo` was created with `request_limit=1` and `api_cap=0`, then start/pause/resume/drain were applied. The service was stopped before export and backup, avoiding the Store lock. Release verification returned `schema_version=voxlush.release.v1`, `leakage_check=pass`, and counts `accepted=0`, `assets=0`, `provisional=0`, `repair_pairs=0`. The backup manifest used SQLite online backup and the restore receipt reported `database_integrity=ok`, `paths_rebased=true`, and one database file. The restored root was started separately and its campaign state/counts were inspected.

The local real fixture uses an islands scene and is explicitly marked `record_kind=fixture` / `fixture_mock`; it is not a production accepted asset. No repository `data/` directory was created.

## Remaining Release Gates

Model qualification requires a configured, authorized endpoint, actual image-capable calls, a pre-recorded profile, and human blind review. Scale qualification requires the specified 100,000 sample / 1,000,000 event fixtures and concurrency/latency measurements. Deployment requires an authorized production root, migration, canary, restart recovery and rollback evidence. All three remain open.
