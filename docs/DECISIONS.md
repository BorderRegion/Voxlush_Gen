# Decisions and Deviations

## 2026-10-08: Keep the delivery profile offline by default

`configs/campaign.example.json` uses the current strict `Config` schema, has no inference endpoint, sets `allow_live` to false, and sets the global request cap to zero. This keeps the copied example useful for diagnosis and UI startup without implying a paid-call budget or model qualification. Evidence: `voxlush doctor` is the intended non-billing local command; `Config` rejects unknown keys and `Scheduler` blocks live inference when authorization is false.

## State and artifact ownership

The SQLite `Store` is the state authority, guarded by a data-root owner lock. API controls enqueue durable commands; the scheduler applies them. Filesystem artifact installation and database registration use a recoverable commit record rather than claiming a cross-filesystem transaction. Evidence: `backend/src/voxlush/store/store.py`, `backend/src/voxlush/dataset/archive.py`, and their tests.

## Qualification remains separate from implementation

The four-request DeepSeek/GLM probe is recorded as model evidence, but it did not produce a usable accepted asset or any human blind-review evidence. DeepSeek and GLM thinking-mode requests timed out; DeepSeek with thinking disabled returned source that failed pre-execution source validation, including a bounded repair. The model source was not executed during the original four-request probe. The later offline review replay reached Docker for the first response and failed because an authored C call omitted its required floor argument; no geometry or preview was produced. Costs remain unknown because the endpoint did not provide a usable price settlement. Local rendering and mock review fixtures remain candidates/provisional results. Model qualification therefore stays false, independent of software test status. This follows the evidence boundary in `docs/04_DELIVERY_AND_ACCEPTANCE.md`.

## Deployment is not inferred from local readiness

No production service, production data root, or external endpoint was changed. A service unit and release checklist are documented for a later authorized deployment; deployment and rollback evidence remain outstanding.

## Review correction: shared primitive contract v3

The v2 blanket ban on `_` names was excessive. Ordinary `_`, `_helper` and local arguments now pass; reflection, private runtime attributes, primitive replacement and rebinding/reseeding the supplied `SEED`/`rng` remain prohibited. Extraction and validation share a 256 KiB source limit. Landscape metadata permits zero floors, while architectural and frozen timber contracts retain their requirements. The same bounded evidence and primitive contract serve author, refinement and repair. Review JSON format failures retry only review and never rebuild the source.

## Review correction: execution capacity and financial uncertainty

Unknown execution and unknown cost are separate fields. An unresolved pool is isolated; other pools can use remaining authorized global capacity. A service completion/cancellation receipt or an explicit dispatch-to-termination upper-bound contract releases execution occupancy only. Unknown cost and request identity remain, and the original POST is not retried. A local timeout is not termination evidence. When unknown execution fills the whole global cap, more global dispatch cannot be promised until reconciliation. Role aliases are not capacity identities; shared services use one capacity key unless documented independent pools are configured.

## Review correction: bounded recovery, coverage and schema 2

Schema 2 is additive and transactional. Partial active-attempt indexes and transactionally maintained seed summaries replace history-wide scheduling/coverage aggregation. Family health uses consecutive failures with cooldown/probes; lifetime statistics remain available. Saved responses are applied by sample/revision/attempt identity, independent of old leases, in batches of at most 1024; later ticks drain restart leftovers. Missing settled-response files stay blocked without changing known billing or authorizing a new POST.

## Review correction: quality identity and immutable history

Qualification fingerprints cover model, routing identity, output parameters, completion/time budgets, prompt/rubric and geometry/runtime versions. Concurrency/RPM/TPM changes affect the frozen runtime snapshot and revision history, without changing quality identity. Initial samples and dispatched attempts retain their own snapshot hashes; archived provenance contains redacted snapshots. Historical schema-1 configurations cannot be reconstructed and are left unknown, not retroactively qualified.

## Review correction: variant counting and archive decisions

Exact occupied cells under translation and four rotations preserving +Y, ignoring material choice, identify variants. Explicit lineage also prevents extra independent counts. Full cube rotations and coarse quantization only find comparison candidates; upside-down or merely similar geometry is not automatically merged. One scheduler archive lock spans uniqueness decision, immutable manifest preparation and Store commit, including when two archive workers are configured. The Store rejects a conflicting manifest rather than silently changing its acceptance. Existing immutable assets are not rewritten by migration.

## Frozen legacy resource lint scope

Three preserved legacy resource modules (`legacy_quality.py`, `legacy_render.py`, and `legacy_wooden.py`) contain compact formatting and one unused import. Ruff ignores only their E401/E701/E702/F401 style findings; the files remain covered by version hashes and sandbox tests. Reformatting them would change the declared runtime/renderer hash and requires rebuilding the sandbox image, with no behavioral value for this delivery.

## Task contract mapping

The published nested task v1 contract is mapped to the flatter runtime task record by the planner adapter and validated against the packaged task schema. `backend/tests/test_themes.py` checks schema parity and representative contract mappings. The earlier gap is resolved for the shipped task types; future schema additions must update both schema copies and the adapter.

## Live follow-up: deterministic fence normalization and prompt v4

A complete DeepSeek response contained exactly one leading Python block followed by explanatory prose. Rejecting that unambiguous wrapper spent an author repair call without addressing geometry. Extraction now removes only that wrapper and trailing commentary, preserves the complete enclosed program, and still rejects multiple/unclosed/non-Python fences and invalid source. Transport completion and runtime guards remain independent. Saved-response replay exposed floor=None in natural components; prompt v4 adds an explicit correct C call, while the runtime requirement stays unchanged. The GLM v4 request returned reasoning but timed out without final answer content, so the prompt adjustment has no positive model evidence yet.

## Pool audit: distinguish reasoning progress from answer completion

Read-only SSH evidence and isolated replay show that the pool forwards the requested thinking field without adapting it to NVIDIA GLM. The provider documents reasoning_effort low/high/max (default max). The user explicitly prefers retaining thinking for quality, so future profiles should retain the model default or its documented enabled mode, without an automatic low-effort fallback. Local stream policy v2 tracks reasoning progress separately, retains absolute/idle deadlines, ignores heartbeats, and requires complete answer content before execution. Parameters remain caller-controlled; policy changes invalidate qualification hashes. This is offline-verified, without a new inference call. The time-correlated BrokenPipe follows the local timeout; cached pool health and closed HTTP connections do not prove upstream computation terminated or settle billing. Existing outcome_unknown state remains intact.


## Live concurrency: EOF needs semantic termination

The 16-request concurrent author run exposed a GLM HTTP stream that closed after 59.832 seconds, retaining 2592 reasoning characters but no answer, finish reason or DONE marker. Stream policy v2 incorrectly classified that clean EOF as an ordinary incomplete answer, released occupancy and scheduled a repair. Policy v3 classifies EOF without either semantic termination marker as outcome_unknown. Known length/stop/DONE endings still reject unusable answers without claiming unknown execution. The saved response now replays as unknown, and scheduler regression verifies occupancy/reservation retention and retry rejection. This changes qualification identity; raw historical evidence is retained.

## Live archive: adapt observed labels at the manifest boundary

The first passing real GLM image review contained three nonempty tag/evidence/confidence records. These matched the visual rubric but lacked the manifest's key/value fields, so archive failed after rendering and review. Archive now maps this explicit visual-review shape to key=visual_tag/value=tag while retaining all evidence and the unchanged review artifact. Existing canonical observations pass through. This also supports archive-only retry of an already persisted review; no model call, schema relaxation, geometry editing or requested-tag inference is needed. The actual arch resumed via the API, exported as provisional and survived nonempty backup/restore. Human calibration and formal acceptance remain separate.
