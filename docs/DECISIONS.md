# Decisions and Deviations

## 2026-10-08: Keep the delivery profile offline by default

`configs/campaign.example.json` uses the current strict `Config` schema, has no inference endpoint, sets `allow_live` to false, and sets the global request cap to zero. This keeps the copied example useful for diagnosis and UI startup without implying a paid-call budget or model qualification. Evidence: `voxlush doctor` is the intended non-billing local command; `Config` rejects unknown keys and `Scheduler` blocks live inference when authorization is false.

## State and artifact ownership

The SQLite `Store` is the state authority, guarded by a data-root owner lock. API controls enqueue durable commands; the scheduler applies them. Filesystem artifact installation and database registration use a recoverable commit record rather than claiming a cross-filesystem transaction. Evidence: `backend/src/voxlush/store/store.py`, `backend/src/voxlush/dataset/archive.py`, and their tests.

## Qualification remains separate from implementation

No paid endpoint requests or human blind review were performed in this delivery pass. Local rendering and mock review fixtures remain candidates/provisional results. Model qualification therefore stays false, independent of software test status. This follows the evidence boundary in `docs/04_DELIVERY_AND_ACCEPTANCE.md`.

## Deployment is not inferred from local readiness

No production service, production data root, or external endpoint was changed. A service unit and release checklist are documented for a later authorized deployment; deployment and rollback evidence remain outstanding.

## Frozen legacy resource lint scope

Three preserved legacy resource modules (`legacy_quality.py`, `legacy_render.py`, and `legacy_wooden.py`) contain compact formatting and one unused import. Ruff ignores only their E401/E701/E702/F401 style findings; the files remain covered by version hashes and sandbox tests. Reformatting them would change the declared runtime/renderer hash and requires rebuilding the sandbox image, with no behavioral value for this delivery.

## Task contract mapping

The published nested task v1 contract is mapped to the flatter runtime task record by the planner adapter and validated against the packaged task schema. `backend/tests/test_themes.py` checks schema parity and representative contract mappings. The earlier gap is resolved for the shipped task types; future schema additions must update both schema copies and the adapter.
