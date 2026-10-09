# Acceptance Report

Date: 2026-10-09 (Asia/Shanghai); historical pilots are recorded separately below.

Repository baseline: `4f4be137d3924b38cb7301c2c4a0081ff32a7c2a`.

Environment: Python 3.12.3, Node 20.19.0, npm 10.8.2, Docker 29.1.3, APSW SQLite 3.51.3, Linux, `voxlush-sandbox:v1` (`sha256:50712f3b25dc`). The checked-in profile has `allow_live=false`, no author or visual endpoint, and global API cap 0. The acceptance data root was `/tmp/voxlush-acceptance-20261008`; it is outside the repository and is not production data.

## Review 4f95a9e: final reliability and bounded quality validation

Review baseline: `4f95a9e1359d0ce66ca04a5fe414b0c53960662e`. Reliability code: `b684fcf5d1667cbd553f41490dd7597ddfd7f486`. Final metadata diagnostics: `8b424344739115e1897710c397a0d7aa1a329a25`. The remote baseline was checked before editing. No architecture replacement, template generator, new panel, multi-agent workflow, production deployment or pool change was introduced.

| Defect | Correction and evidence |
|---|---|
| Historical blocked/render_failed poisoned global backpressure | Historical terminal samples no longer imply a current bottleneck. Queue hysteresis remains. A regression dispatches a healthy campaign beside the failed sample. |
| Shared Docker failure could remain blocked or retry indefinitely | Local trusted one-voxel Docker/render probe, at most once per 30 s, automatically requeues unchanged source; at most four failed sandbox executions per task. Repeated healthy probes cannot loop a permanent failure. Actual absent-socket recovery completed build/render/archive in 32.231 s with zero model calls/author repairs. |
| Normal stop persisted user drain | Owner stop now preserves campaign state. Startup applies queued controls, recovers saved requests/artifacts and only revives legacy draining/shutdown. Actual CLI stop/start retained one settled request and budget; cap restoration continued the second fixture without start/resume. Pause/drain/emergency stop stayed unchanged. The second identical fixture was correctly rejected as duplicate. |
| Every local OSError could stop paid work globally | Explicit shared-volume/database/durable-ledger failures stop admission; missing/path/permission errors in one sample stay local with diagnostics. Local render retries remain finite and spend no author repairs. |
| Review uncertainty could redraw correct source | Gray or inconsistent verdicts use bounded review-only retry. Rubric v3 explicitly evaluates image composition, proportions, detail, materials, theme and visible repetition. Evidence types and tag sources remain separate. |
| Weak-model metadata errors were misleading or treated as environment failure | Actual library source had strings in MODEL_SPEC.spaces but received an ID error. Feedback now locates the list item and required object type. A non-object air_bbox previously raised host AttributeError and retried locally; it now becomes a bounded author repair. Saved source remains rejected and unmodified; no claimed real model repair success. |

The first liveness regression run had **7 failures / 6 passes**. The later metadata cases had **4 failures / 1 prior pass** before repair. Final complete suite: **221 passed, 1 optional private fixture skipped / 92.20 s**, including 31 new regressions. Ruff, frontend build, 10 mocked-transport browser cases and 1 real local backend/browser case passed; the real browser case was rerun on final backend code (17.3 s). Crash-after-response, unknown occupancy/billing/budget retention, finite local failures, skeleton repair → exactly one refinement and repaired archive/export remain covered. Fake HTTP/SSE and injected faults are software evidence, not model-quality measurements.

Actual local evidence also includes restoration of the previous nonempty model backup, verified export of **11 historical provisional assets and 17 repair pairs**, and unchanged complex-source rebuild/render with the same **267209-voxel hash**. Its 79-attempt ledger and three historical unknowns remain unchanged. These are historical replay counts, not new output. The new forest source independently rebuilt to its original **125204-voxel hash**, with all three saved previews loading in an authenticated browser. It has not passed visual review and was not archived.

### New uniform cohort: stopped before quality calibration completed

The existing explicit own-pool authorization was bounded to six tasks / 48 calls, with no automatic expansion. All **six actual calls** used DeepSeek v4.1 Flash, prompt v5, rubric v3 configuration and stream v4 on one pinned b684fcf profile. Thinking stayed enabled; max_tokens=262144, temperature=1, top_p=.95. GLM 5.3 Flash with reasoning_effort=max / max_tokens=8192 was configured, but **zero visual requests were sent**. First-progress/idle/total budgets were 600/240/2300 s. The final metadata patch was made after the batch and changes validator/profile identity; it has only offline evidence.

| Group / scale | Independent tasks | Successful source execution | Skeleton pass | Final geometry pass | Visual calls / passes | Archived |
|---|---:|---:|---:|---:|---:|---:|
| Natural / S, M | 2 | 1 (50%) | N/A | 1 (50%) | 0 / 0 | 0 |
| Direct architecture / S, M | 2 | 1 (50%) | N/A | 0 | 0 / 0 | 0 |
| Two-stage architecture / L, XL | 2 | 1 (50%) | 0 | 0 | 0 / 0 | 0 |

Five complete author programs returned. Forest passed geometry; coast used an unsupported gravel material; timber had a window backed/refilled by wall geometry; library supplied strings instead of space records; courtyard had detached lanterns, backed/refilled windows and missing floor semantics. The other complex author stream stopped without final content or semantic termination. It retained **10694 SSE events / 118202 reasoning characters**, but no finish_reason or DONE. The saved stream does not locate the disconnect or prove upstream termination. No W-cardinal-argument error occurred in the five returned programs; this tiny unmatched sample cannot demonstrate improvement over the mixed-version historical run.

Four returned samples are queued for their bounded author repair and one for review. All six tasks are censored/incomplete, including the unknown. The table uses all attempted tasks as denominator; zero visual passes is **zero assessed samples**, not a measured aesthetic rejection rate. No repairs or refinements were sent, so complex two-stage success and new-rubric visual quality were not validated. Formal accepted_unique=0 and human reviews=0.

| Group | Initial author calls | Reported total tokens | Calls missing usage | Repair / refine / review calls |
|---|---:|---:|---:|---:|
| Natural | 2 | 72604 | 0 | 0 / 0 / 0 |
| Direct architecture | 2 | 116952 | 0 | 0 / 0 / 0 |
| Two-stage architecture | 2 | 43705 | 1 | 0 / 0 / 0 |

Total known reported tokens: **233261** (10478 prompt, 222783 completion, including 189297 reasoning); one call has no usage. All six currency costs are unknown because no verified prices/settlement are available; zero known cost is not zero total cost. Tokens/time per qualified candidate are undefined because no new candidate completed. Per-stage tokens, p50/p95 call latency, measured local container durations, group/scale rows and per-task failures are in [final_quality_validation.json](final_quality_validation.json). Five families / six seeds were attempted. No archived assets exist for a new-cohort duplicate-rate estimate; no cross-asset aesthetic diversity claim is possible.

The experiment admitted at most six new occupied slots alongside 14 externally retained historical client reservations (combined ceiling 20); internal upstream retry multiplicity remains unconfirmed. This fresh-ledger test is an **explicit supervised historical admission exception**, not independent capacity or validation of normal admission with all historical unknowns in one Store. The unmodified CLI/Scheduler/Store held cap0 after initial dispatch to prepare a paid-safe restart. A new unknown then triggered harness drain before cap restoration. **The planned paid restart and further calibration did not occur.** Separate loopback tests verify automatic running-intent recovery and production unknown isolation; this paid test does not establish unattended recovery. Historical unknowns remain unchanged, **14 → 15 total**; no unknown was released/replayed and no budget was reset. Empty new-cohort exports and nonempty ledger backup/restore verified.

Read-only pool audit again found the same gateway and five workers, no per-request termination/cancellation receipt and no dispatch-to-termination contract. Socket EOF, local deadlines and health recovery remain insufficient. Production whole-pool unknown isolation is unchanged. Software fixes do not solve that external evidence gap.

**Readiness:** software reliability corrections are verified; high-quality generation is not qualified. Neither low-maintenance unattended operation nor 10000–100000 formal generation is ready. Minimum blockers are (1) reliable upstream execution termination/reconciliation or documented independent capacity, (2) bounded uniform real validation of author repairs and complex-path yield plus actual visual review, and (3) human blind calibration followed by sustained recovery/throughput observation. A one-item geometry-only preview package with blank scores is prepared privately; it is not the required 100-candidate blind-review evidence. No provisional record was promoted.

Reproduce the final software checks with `.venv/bin/pytest -q backend/tests --tb=short`, `.venv/bin/ruff check backend/src backend/tests`, `npm --prefix frontend run build`, `npm --prefix frontend run test:e2e` and `npm --prefix frontend run test:real`. Raw responses/reasoning, credentials, runtime roots, previews and backups remain outside Git. README/LICENSE are unchanged.

## Review b02c362: software and supervised live validation

Review baseline: `b02c362e86eb705a5f317f8e82c0e25222c73083`. Fixed code: `ad44d8162d9e2f969c2be3182b5be2d27e1e8a30`. Existing architecture, author independence, thinking preference and final quality contracts are retained. Production services and data were not changed.

| Issue | Before fix | Verified result |
|---|---|---|
| N01 | Malformed SSE/structure/byte limit released occupancy and scheduled author repair without termination evidence. | Actual loopback HTTP → PoolClient → Store → scheduler keeps occupancy, reservations and one POST. Stop/length release execution; malformed usage after finish stays invalid/unknown-cost without occupying execution. Duplicate settlement/recovery does not double-advance. Pool 502/504/interruption-frame cases also retain occupancy. |
| N02 | A failed skeleton changed to final because revision/repair count increased. | Explicit persistent phase keeps skeleton repair, exactly one refine, and final-only repair across owner restarts. Brief remains unchanged. Phase transitions use a patched build-boundary fixture; real geometry is verified separately. |
| N03 | Docker/image/OSError faults spent author repair budget and could contaminate quality failures. | Injecting actual sandbox image checks preserves source/revision and spends no model calls; restored Docker builds the same source. Two local retries then block; image mismatch blocks immediately. Storage failure stops network dispatch; unrelated local work survives a rendering failure. Real source/geometry failures still use finite author repair. |
| N04 | A capped campaign's 64 old ready rows hid another campaign. | Indexed campaign occupancy filter runs before LIMIT; the actual next scheduler tick POSTs the other campaign. |

The initial review-specific run on old code had **14 failures in 1.92 s**. This is not 14 distinct behavioral defects: normal controls also failed because the new execution/phase fields did not exist. Behavioral assertions reproduced all four review issues. After additional boundary coverage, **23 review cases pass**. Complete verification: **189 passed, 1 optional private fixture skipped in 90.10 s**, Ruff passed, frontend build passed, **10 mock-transport browser tests + 1 real local backend/browser test passed**. Existing clean EOF, reasoning/heartbeat, timeout, recovery, capacity and budget tests remain included.

The local recovery integration additionally exposed repair-pair records missing the exporter's source/lineage/before-and-after checks. Fixed without changing the schema: an actual failing source is repaired through loopback HTTP, survives Docker outage/restart and renderer retry, archives, and exports one verified repair pair. Passing skeletons and infrastructure failures are not training error examples.

Nonempty schema-2 data was restored from the previous real stone-arch backup into an isolated root and migrated to schema 3. Unchanged DeepSeek source rebuilt and rendered **222949 voxels with the identical canonical hash**. Formal export remains empty; provisional export contains the same one existing asset. Schema-3 backup/restore and integrity checks passed; its request ledger remains exactly 4. **This is offline replay of an existing model-authored asset, not a new model call, candidate or visual review.**

Reproduce software verification from the repository root:

```bash
.venv/bin/pytest -q backend/tests/test_review_b02.py --tb=short
.venv/bin/pytest -q backend/tests --tb=short
.venv/bin/ruff check backend/src backend/tests
npm --prefix frontend run build
npm --prefix frontend run test:e2e
npm --prefix frontend run test:real
git diff --check
```

**D01:** read-only inspection confirmed worker TLS retries and candidate-route retries; no usable upstream termination receipt/query path was found. Keep whole-pool unknown isolation. A proxy's 2400-second timeout is not a maximum upstream execution contract. See [the decision and recovery conditions](../docs/DECISIONS.md#d01-retain-shared-pool-isolation-until-termination-is-evidenced).

**Real 24-task pilot completed.** Selected 8 natural, 8 direct-architecture and 8 complex two-stage briefs from the existing calibration plan. These are **24 independent tasks**, counted once across all phases. There were **79 requests** (24 initial author, 36 author repairs, 2 refinements, 17 visual reviews). 76 calls have termination evidence and 74 have complete protocol responses; these counts do not imply executable source or valid review JSON.

| Task group | Tasks | Source executed | Skeleton geometry pass | Final geometry pass | Valid visual pass | Candidate archived | Formal accepted_unique |
|---|---:|---:|---:|---:|---:|---:|---:|
| Direct architecture | 8 | 6 | 0 | 5 | 5 | 5 | 0 |
| Natural | 8 | 7 | 0 | 7 | 5 | 5 | 0 |
| Two-stage architecture | 8 | 2 | 2 | 1 | 1 | 1 | 0 |

The archived complex water-living task completed the real skeleton repair → exactly one refinement → final repair → image review → archive sequence. The other task that passed its skeleton also refined once, then exhausted final-stage repairs.

Final task states: `{"awaiting_review": 1, "blocked": 3, "provisional_pass": 11, "rejected": 9}`. Terminal/blocking reasons: `{"outcome_unknown": 3, "repair_exhausted": 8, "review_format_exhausted": 1, "same_error_no_progress": 1, "unqualified_model_profile": 11}`. Source/build diagnostics include `{"W_cardinal_side_argument": 15, "execution_failure_without_diagnostic": 1, "metadata_list_type_or_limit": 2, "metadata_space_id": 1, "nonliteral_metadata": 1, "object_id_collision": 1, "other_source_or_runtime_diagnostic": 13, "primitive_rebinding": 1, "protected_metadata_mutation": 1, "unknown_material": 1}`; these are failure **occurrences across revisions**, not task counts. The detailed task rows and all geometric rules are in [model_qualification.json](model_qualification.json).

| Phase | Source commit | New requests | Cumulative requests |
|---|---|---:|---:|
| initial_v4 | `ad44d8162d9e` | 25 | 25 |
| supervised_v4 | `ad44d8162d9e` | 24 | 49 |
| supervised_v5 | `1db2e940a7d3` | 30 | 79 |

The initial implementation retained the default pool isolation and drained on a new unknown. Under the user's explicit own-pool authorization, subsequent supervised phases bypassed only the two blanket unknown-pool admission checks in a private test bootstrap. Existing/new unknown records, occupancy, budgets, blocked samples and legal caps remained. Historical 11 unknowns remain in their original ledgers/canary record; they are not included in the fresh ledger's 24 slots or proven terminated. **This is an explicit supervised policy exception, not unmodified production admission or unattended recovery validation.** Production services and production default policies were unchanged.

The first continuation drained before changing code. Its harness recorded KeyboardInterrupt only after active calls and local running samples reached zero; normal finalization, export and backup succeeded. It was a planned boundary, not a killed model call. Prompt v5 and visual rubric v2 clarify W cardinal sides/coordinates, literal metadata, reserved root ownership and numeric confidence. Bounded traceback feedback now retains the exception at the end. A failing-before/passing-after regression protects that repair evidence; the final complete suite is **190 passed, 1 skipped in 84.55 s**, with Ruff passing. Patch commit: `1db2e940a7d3b1368cbaab3cc7c139332e3217e3`. The final continuation reuses the same tasks/ledgers and consumed 30 calls. 1 existing review-format-exhausted task(s) received one audited supervised reevaluation with the new schema and unchanged previews; request/retry counters were retained. No generated program, original brief, geometric threshold or model confidence value was edited to manufacture success.

DeepSeek retained default thinking with max_tokens=262144, temperature=1, top_p=0.95; GLM visual retained reasoning_effort=max with max_tokens=8192. First-progress/idle/total budgets were 600/240/2300 seconds. One API/Store/scheduler instance reached **24 concurrent calls**, with a private initial adaptive-cap override and authenticated campaign ramp 8/16/24; production initial adaptive cap remains min(8, hard_cap). Thinking parameters were not reduced. Actual returned reasoning varies, so configuration alone does not prove identical upstream behavior.

| Call stage (including failures) | Calls | p50 seconds | p95 seconds |
|---|---:|---:|---:|
| author | 24 | 1056.154 | 1525.038 |
| repair | 36 | 1094.383 | 2186.006 |
| review | 17 | 223.103 | 639.494 |
| refine | 2 | 764.958 | 792.785 |

Task-terminal latency: `{"n": 20, "p50_seconds": 5306.563, "p95_seconds": 6817.143, "method": "nearest rank"}`. Incomplete/blocked tasks are censored and excluded; task durations include supervised pause/restart wall time. The total observation window was 7892.695 seconds. Mixed prompt phases and this small pilot do not establish steady accepted/hour or a model comparison. Reported total tokens sum to **3320751 across 76 calls**, with 3 calls missing totals; reported reasoning tokens sum to 2482803 across 76 calls. No verified prices were available; all 79 new call costs remain unknown, not zero. Unknown executions changed **11 → 14** (3 new); none were released or replayed without evidence.

Pool read-only health during peak load showed 24 active requests against capacity 512, 132/133 healthy sources and no quota block. The incomplete reasoning streams do not identify whether the disconnect occurred at worker, proxy or upstream. The demonstrated W-axis, metadata and review-schema failures are independent software/model-contract problems; they cannot be attributed to pool saturation.

Actual-service browser checks passed authentication, live state, mobile layout and all three new candidate previews, with zero browser errors. Sixty authenticated overview queries had p95 **2.569 ms** (median 2.086 ms); service RSS was 136.29–137.25 MB during that short query window, excluding containers. A new model-authored dune candidate rebuilt from unchanged source with the identical **331283-voxel hash**, and rendered again without new inference. Final formal export has 0 assets; provisional export has 11 assets, 11 source-SFT rows and 17 repair pairs. Release verification and nonempty backup/restore preserved request and unknown state.

**Qualification and deployment:** 11 new candidates are provisional calibration data. Formal accepted_unique=0, human blind reviews=0; model profile, long soak and unattended production yield remain unqualified. No production deployment or API-pool modification was performed. Source publication does not change that boundary. Raw responses/reasoning, configs, generated assets and backups stay outside Git; README and LICENSE are unchanged.

## Earlier concurrent live validation

The latest instruction authorized real higher-concurrency testing and publication after verification, with no fee constraint. This run sent **29 new requests (36 cumulative)** while retaining thinking; finite campaign/sample/repair limits remained active. Data and raw responses stayed outside Git. No production service was modified.

| Workload | Actual result |
|---|---|
| Two real CLI/API instances, 16 mixed-theme samples, ramp 8 → 16 | Measured aggregate peak 16. DeepSeek: 12 calls ended at length=24576 with no usable program. GLM: 2 length endings, 5 total-timeout unknowns, 2 clean-EOF unknowns. |
| Four image canaries | GLM Flash max reasoning answered both correctly in 9.0/13.1 s. Gemma answered one correctly in 52.7 s; the other timed out at 180.2 s and remains unknown. |
| DeepSeek follow-up, 2 samples at concurrency 2 | max_tokens=262144, temperature=1, top_p=.95, first-progress=600 s, idle=240 s, total=2300 s. Both first programs completed in 1254.1/1254.4 s. Timber repair completed in 954.9 s but repeated invalid spaces metadata and stopped. |
| Stone arch and GLM Flash image review | 222949 voxels, 11 components, 117×68×120 bounds. Real review passed in 519.7 s with 3 evidence-backed tags. Rebuilding unchanged source reproduced the canonical hash. All 3 previews loaded in the actual browser. |
| Archive, export, recovery | A real tag-schema integration defect was reproduced and fixed. Authenticated archive-only retry after service restart added zero model requests. One provisional/calibration asset exported and verified; formal export contains zero. Nonempty backup/restore preserved the asset and four-request ledger. |

The [provider model card](https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash/modelcard) recommends at least 256K output allowance. The two successful first author responses used 49248/53027 completion tokens, including 44484/42502 reasoning tokens. This explains why a 24576-token allowance could end before source appeared. GLM retained reasoning_effort=max; no silent effort reduction was used.

The run also exposed clean HTTP EOF without finish_reason or DONE. The old v2 policy treated two such GLM responses as ordinary incomplete answers and sent one automatic repair before detection. New dispatch drained; v3 now retains unknown execution/financial reservations and prevents replay. Original responses were preserved, the two new-run ledger entries were corrected and audited, and backup restoration retained occupancy. The latest run has **8 unknown executions, 11 cumulative** including historical requests; health recovery does not reconcile them.

The arch archive failed because the rubric emits `{tag,evidence,confidence}` while the manifest requires `{key,value,source,evidence_ref}`. The archive adapter now adds `key=visual_tag` and `value=tag`, preserving original tags, evidence, confidence and review.json. Canonical deterministic/human observations remain intact. A nonempty-review archive/export regression covers restart-shaped input, integrity and idempotence without changing the schema or acceptance rules.

Read-only pool observations showed 132/133 healthy sources and 13 in-flight against capacity 512 during load, then 133/133 healthy. Three proxy errors were logged without correlation IDs. Capacity saturation was not observed; intermittent proxy faults cannot be excluded. Real authenticated overview GET latency over 60 observations was median 2.303 ms, p95 2.606 ms, max 3.557 ms; this short window is not a soak measurement.

**Final verification: 166 Python tests passed, 1 optional private fixture skipped in 79.98 s; Ruff and frontend build passed.** Actual-service browser authentication, mobile layout and preview checks passed without browser errors. Machine-readable evidence is in [model_qualification.json](model_qualification.json) and [performance.json](performance.json).

**Qualification remains false:** one successful natural scene is provisional; accepted_unique=0 and human reviews=0. Timber remains rejected. High-concurrency generation yield, complex-path quality and long-duration stability are not qualified. Source publication is separate from production deployment.

## Earlier capped live run after review publication

The user requested an actual run after commit `2230ef6`. This new batch was capped at four requests and concurrency one; **three requests were sent**, giving seven cumulative requests including the historical probe. Private runtime roots were separate from production, and previous ledgers were retained.

| Attempt | Profile | Measured result |
|---|---|---|
| New 1 | DeepSeek v4.1 Flash, prompt v3, requested thinking disabled | Complete in 66.67 s, 6329 tokens. A single Python block followed by prose was rejected by extraction. After the local wrapper fix, unchanged program replay reaches Docker but fails explicit `floor=None`. |
| New 2 | Same author, bounded repair | Complete in 78.08 s, 5727 tokens. Source validation passes; Docker fails C declarations omitting required floor. |
| New 3 | GLM 5.3 Flash, prompt v4, requested thinking disabled | 828 SSE JSON events contain 7897 reasoning characters but no final content within 180 s; `outcome_unknown`, financial uncertainty and execution occupancy retained. |

Raw-stream inspection shows that the GLM connection returned reasoning while the client deadline waited only for final content. Subsequent authorized read-only SSH inspection found an active gateway and five workers with NVIDIA routes for both tested model names, no configured aliases for these routes, and no model defaults. The gateway forwards the body unchanged. An isolated replay of the copied live worker method preserves `thinking={"type":"disabled"}` and messages, adding only stream usage options. This verifies the code transformation, not a historical wire capture.

In the test window, worker2 logged HTTP 200 at **2026-10-08 15:13:42.133 CST**, followed by upstream `BrokenPipeError` at **15:16:41.290**, matching the local 180-second deadline. This is temporal correlation; the worker logs contain no matching request ID. Worker request timeouts are 2400 seconds. The evidence supports client disconnect as the cause of the BrokenPipe, rather than a pool-imposed 180-second timeout. Cached health at 15:37:45 CST reported five reachable nodes and 133/133 healthy/routable sources with zero quota-blocked sources; this snapshot is not a throughput test or proof of upstream cancellation.

The [NVIDIA GLM 5.3 Flash model documentation](https://docs.api.nvidia.com/nim/reference/z-ai-glm-5-3-flash) states that thinking budget uses `reasoning_effort` (`low`, `high`, `max`; default `max`). It does not document the tested `thinking.type=disabled` as a disable switch. The requested field did not suppress reasoning in this run. The user prefers retaining thinking for quality; future GLM profiles should omit the disable field and retain the documented default or explicitly select `max`. No inference parameters are silently reduced. The SSH audit added **zero inference calls**, changed no production service, and did not reconcile the unknown ledger or create a commit/push.

The local client now counts nonempty `reasoning_content` deltas as stream progress and records the first reasoning timestamp/character count separately from answer content. Heartbeats, empty deltas and role-only events cannot extend progress. Idle and absolute deadlines still apply, and reasoning without complete final content remains non-executable. Stream policy v2 participates in the profile hash. Twelve new regression cases cover delayed reasoning-to-answer with default/max/enabled parameters, total/idle deadlines, ineffective heartbeats and qualification invalidation. A delayed offline replay of the saved GLM SSE recognizes all 7897 reasoning characters without the old first-content cutoff and rejects the missing final answer/finish at EOF. The replay restores only the recorder's last line terminator, preserving the saved decoded raw text. This does not establish that the original upstream request would eventually succeed.

The fourth slot was unused after the unresolved GLM request. No POST was replayed, no unknown cost was reset, and no production services were modified. **Successful model geometry=0, previews=0, visual-model calls=0, accepted_unique=0.** Reported model names do not establish the upstream route. Different prompts and incomplete outputs make this unsuitable for a model quality comparison.

The actual service browser checks passed for both runs: authentication, UI state, pause persistence and mobile layout. Formal/provisional exports were empty; backup restoration preserved failed/unknown request state. These checks do not establish a successful generation chain.

This live failure led to a deterministic extraction fix and eight regression cases: one complete leading Python fence may have trailing commentary; multiple/incomplete/non-Python fences, invalid code and runtime mutation remain rejected. Prompt v4 adds a correct natural-component floor example without weakening the contract. **Final Python suite including stream policy v2: 160 passed, 1 skipped in 61.87 seconds; Ruff passed.** The earlier frontend build and 10 mock/1 real-fixture browser results below remain unchanged. Detailed sanitized request evidence is in [model_qualification.json](model_qualification.json).

## Result Boundary — review bb556101

Review baseline: `bb55610119dc3abe816dad573e163878337534d5`. The original architecture is retained. R01–R13 implementation corrections are present, with the operating conditions below. The first new regression run against the old code yielded **10 failed, 3 passed**; the review package separately supplied seven reproduced observations. The final complete Python run is **140 passed, 1 skipped** in 91.39 s. The skip still requires the optional private legacy archive. Ruff and frontend build passed. Browser results are **10 mock transport tests passed** and **1 real local backend/browser test passed**. The latter executes isolated geometry and rendering, immutable archive, persistent controls, authenticated artifact access and formal export exclusion for a fixture.

This pass made **zero additional paid model calls** and changed no production service or data root. The earlier four-request authorization is exhausted. The saved first complete DeepSeek source now passes ordinary underscore names and landscape `floors=0` validation. Its unchanged source reaches Docker and fails on `C('ground_slope', ...)` without the required `floor` argument. The second complete source still rebinds protected `SEED`, so it is not executed. The DeepSeek and GLM thinking-mode timeouts have no source body to replay. These results distinguish client validation, authored execution errors and protocol/time-budget failures; they do not measure visual design quality.

| Historical paid request | Requested/reported model | Original result | This review's offline replay |
|---|---|---|---|
| 1 | `deepseek-ai/deepseek-v4.1-flash`, thinking | 90 s first-content timeout, `outcome_unknown` | No body; no POST replay |
| 2 | `z-ai/glm-5.3`, thinking | 180 s first-content timeout, `outcome_unknown` | No body; no POST replay |
| 3 | `deepseek-ai/deepseek-v4.1-flash`, thinking disabled | Complete in 110.07 s; `_` rejected before execution | Name/metadata pass; Docker execution fails at a missing component floor argument |
| 4 | Same, bounded author repair | Complete in 60.16 s; `SEED` replacement rejected | Protected-state rejection retained |

All four settled costs remain unknown. Endpoint-reported model names do not prove the upstream route. The original probes used prompt v1; the current shared contract is v3 and has no new remote-model test. **Successful model geometry=0, model previews=0, real visual-model requests=0, human blind reviews=0, production accepted_unique=0.** Neither software fixtures nor synthetic accepted-counter records qualify a model. Raw responses, private configs, credentials, datasets and backups remain outside Git.

The required short synthetic load was run with **100000 samples, 1000000 events and 300000 historical attempts**, plus loopback dispatch at **128/256/512**. Nonempty migration and asset/failed/unknown backup restoration passed in local test roots. This is not long-duration fault/soak, production migration, canary or rollback evidence. No production deployment or release tag exists.

Evidence labels:

- **L**: real local geometry/render/runtime or Store evidence.
- **N**: fake network/transport evidence; it does not qualify a model.
- **F**: filesystem/archive/security unit evidence.
- **B**: browser/UI evidence against the mock transport.
- **R**: external-root offline acceptance run.
- **M**: real model API evidence from the capped DeepSeek/GLM probe; it does not qualify a model.
- **H**: human blind-review evidence (none in this report).

## R01–R13 review acceptance

Run all backend review regressions with `.venv/bin/pytest -q backend/tests/test_review_regressions.py`. Per-item commands below use `R="backend/tests/test_review_regressions.py"` as a shell variable. “Before” is the reviewed defect/reproduction, not a claim that every expanded test was run against the old commit. “After” reports local evidence only.

| ID | Before → implemented correction | Minimal command / final result | Conditions and limits |
|---|---|---|---|
| R01 | 500 successes + 8 lifetime failures suppressed planning → consecutive failure health, cooldown and one probe; success resets the streak | `.venv/bin/pytest -q "$R" -k r01` — pass: productive family plans, cooldown expires, one probe, success restores availability | Fixture terminal outcomes; global budget and zero-yield stop rules remain |
| R02 | Unknown attempts had no execution reconciliation → separate occupancy from billing, isolate affected pool, authenticated receipt command or documented server deadline | `.venv/bin/pytest -q "$R" -k r02` — pass: independent route dispatch, restart/deadline, ledger unchanged, no original retry, API evidence required | Local timeout never releases remote occupancy. A full global cap still requires termination evidence. The command records an operator/service confirmation; no provider-specific query/cancel integration was invented |
| R03 | Author 128/visual 2 reduced global cap to 2; visual 0 disabled author → global/campaign and per-pool limits enforced independently; unavailable routes filtered before candidate LIMIT | `.venv/bin/pytest -q "$R" -k r03` — pass: independent caps, shared roles, legacy alias/role mapping and visual 0/unknown prefix | Same service shares one pool unless independent pools are explicitly configured; global authorization is always enforced |
| R04 | Saved/settled response disappeared from recovery after callback cleared lease → durable application flag, identity matching and new local lease | `.venv/bin/pytest -q "$R" -k r04` — pass: saved/settled/consume/finish faults advance the original sample with one POST; 1025 responses drain across batches; missing/corrupt files preserve billing | Missing complete files require restoring the saved response; blocked state never authorizes another paid POST. Delayed reapplication is local |
| R05 | Invalid review JSON incremented author revision → bounded review-format retry using unchanged build and render | `.venv/bin/pytest -q "$R" -k r05` — pass: no author revision/visual repair for malformed JSON; exhausted format retries await review; concrete visual defects still request author repair | No added calls on the normal successful path; sample/campaign request budgets still apply |
| R06 | Global sequence selected only 8 of 64 natural seeds → family-local accepted/active deficit and planned-count tie break | `.venv/bin/pytest -q "$R" -k r06` — pass: production plan covers all 64 seeds under ordered and shuffled completion | Accepted outcomes injected for planner verification, not model quality evidence; rejected outcomes do not repay accepted debt |
| R07 | Translation/yaw/recolor/lineage counted independently → exact material-independent occupancy under translation and four +Y rotations plus explicit lineage | `.venv/bin/pytest -q "$R" -k r07` — pass: synthetic accepted-counter branches count variants once; coarse collision and upside-down design stay distinct; actual fixture DB/manifest/export agree | Coarse and full-cube hashes are candidates only. Fixtures remain unqualified and excluded from formal training; rejected duplicates remain archived and are omitted from export. Existing immutable assets are not rewritten |
| R08 | `_` rejected, size limits disagreed, full error trees entered prompts → safe local names, common 256 KiB bound, read-only primitive/seed protections and private runtime guards, bounded root-cause view and complete local evidence | `.venv/bin/pytest -q "$R" -k r08` — pass: safe/unsafe syntax, private runtime access and alias reseeding rejection, size edge, feedback bound, natural metadata; saved response replay reaches real Docker | Landscape floors=0 no longer inherits the architecture minimum. Missing component floor in saved source still fails; SEED repair still fails. No positive model asset or aesthetic claim |
| R09 | Repeated old SSE timestamps kept showing live → only increasing server_time refreshes snapshot age | `cd frontend && npm run test:e2e -- --grep R09` — pass in the 10-test browser suite; repeated old snapshots age out, fresh idle timestamps remain live | Connection, snapshot age and task progress remain separate; browser clock is virtualized in the regression |
| R10 | Occupancy/RPM/coverage depended on historical scans; scale evidence absent → partial active indexes, pool/time range index, transactional seed summaries | `.venv/bin/python scripts/benchmark_store.py --output /tmp/voxlush-review-scale.json` — pass: 100k/1m/300k, real 128/256/512 loopback dispatch, capped peaks, zero final occupancy | Short synthetic workload only. Loaded ticks include reservation writes; no geometry workers or real-model throughput, long soak or monitoring-overhead qualification |
| R11 | Provider caps polluted qualification hash; no frozen config history → quality identity separated from immutable redacted runtime/config revisions | `.venv/bin/pytest -q "$R" -k r11` — pass: cap/RPM preserve quality hash, temperature changes it, samples keep initial snapshot, API hides secret/route values | Model/output/protocol/time-budget/prompt/rubric/runtime changes invalidate identity. Old configurations cannot be reconstructed and remain unqualified |
| R12 | Two archives could publish accepted manifests before DB demoted the loser → one archive decision lock through manifest publication and commit; DB rejects conflicting decisions | `.venv/bin/pytest -q "$R" -k r12` — pass for simultaneous identical and translated geometry at archive_workers=2; one independent candidate, one duplicate, manifests equal DB | One Store owner is required. Lock serializes the archive stage; existing inconsistent historical manifests are not silently rewritten |
| R13 | 64 older blocked-campaign tasks filled LIMIT before eligibility checks → campaign dispatch eligibility inside SQL before LIMIT | `.venv/bin/pytest -q "$R" -k r13` — pass: healthy activity selected immediately; local drain still available | Running/cap/budget eligibility applies to network work; blocked/degraded/draining local finalization remains possible |

### Scale observations and scope

The exact sanitized run is in [performance.json](performance.json); the reproducible script uses a temporary root and loopback only. The final run overlapped local pytest/browser work on the shared host. Query measurements comprise 60 observations each; concurrency ladders comprise one dispatch tick per cap, so their three-value aggregate is not a steady-state tick p95. SQL occupancy uses the partial active-only index, RPM uses a pool/time range, and coverage scans catalog-sized summaries.

| Operation | p95 ms |
|---|---:|
| overview | 10.509 |
| page | 0.288 |
| coverage | 0.819 |
| ready | 0.182 |
| reserve | 11.57 |
| settle | 11.693 |
| response_apply | 10.645 |
| idle_tick | 0.527 |

| Loopback cap / observed server peak | Dispatch tick ms | HTTP/SSE drain seconds | Occupancy after settlement |
|---|---:|---:|---:|
| 128 / 128 | 831.311 | 7.172 | 0 |
| 256 / 256 | 1662.462 | 15.667 | 0 |
| 512 / 512 | 3617.112 | 27.106 | 0 |

Query-window RSS: 97.41–97.65 MiB; process peak RSS: 140.86 MiB. Per run:896 loopback requests, zero external model requests. No accepted_unique/hour or tokens/accepted result can be inferred.


Recovery timing in the benchmark is an empty pending query. Nonempty recovery evidence comes from the callback-boundary, 1025-response, unknown-restart, migration and `test_nonempty_backup_restores_assets_failed_and_unknown_requests` regressions. The latter verifies the archived fixture, failed/unknown attempts and request/cost/occupancy counters after backup restoration to a new root. The schema-1 migration fixture verifies preserved unknown reservations, populated seed summaries and SQLite integrity. Neither test modifies production data.

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
| T11 | Partial | `test_failed_finish_preserves_complete_response_and_other_work_continues` injects callback exception/cancellation, preserves complete response and billing, and completes another sample. R04 additionally verifies advancement of the original failed sample at all four response boundaries; long-running soak remains untested. | N,L,F |
| T12 | Partial | `test_persistent_response_storage_failure_settles_and_stops_paid_dispatch` and `test_readonly_store_retains_response_and_stops_dispatch_until_recovery` cover request/response write failures, conservative accounting, blocked dispatch and saved-response recovery. Disk-near-reserve behavior remains unverified. | N,L,F |
| T13 | Pass | `test_actual_isolation_host_secret_network_root_and_recovery` exercises timeout, memory, file/output bounds and confirms a later build continues. | L |
| T14 | Pass | `test_single_store_owner_and_stale_callback_are_enforced` rejects a late callback after a newer revision is claimed and preserves its lease. | L |
| T15 | Partial | Browser duplicate-click/uncertain-command tests and real persistent pause/reload pass. Saved-response restart preserves request/cost accounting; unknown retry is rejected. A full command/process-restart lifecycle remains unverified. | N,B,L |
| T16 | Unverified | No slow/crashed renderer backpressure run was recorded. | - |
| T17 | Unverified | No optional pool-health outage with successful calls was recorded. | - |
| T18 | Partial | `test_bad_endpoint_is_isolated_without_repair_loop` covers loopback 401/400/402/insufficient-quota isolation. No real endpoint auth/quota failure was reproduced. | N,L |
| T19 | Partial | `test_adding_visual_endpoint_resumes_waiting_reviews` requeues awaiting_visual after configuring an image-capable endpoint without sending a request. Real local browser evidence shows fixture/provisional visual output and empty formal export; actual image capability remains unqualified. | L,B |
| T20 | Partial | R07 covers exact translation/yaw/material/lineage accounting, coarse collisions, inverted designs and actual fixture archive/export consistency; no qualified model variant set exists. | F |
| T21 | Pass | `test_real_natural_and_ruin_contracts` builds islands, cave and ruin contracts and renders them without the wooden-house gate. | L |
| T22 | Partial | Frozen wooden negative checks run in `test_opening_overdraw_and_frozen_legacy_gate`; the three private saved failures were skipped because the private archive was not supplied. | L |
| T23 | Pass | `test_opening_overdraw_and_frozen_legacy_gate` rejects filled openings and a missing required room, including skeleton/final contract differences. | L |
| T24 | Pass | `test_real_build_render_repeat_and_roundtrip` confirms identical canonical and annotation hashes and identical previews for the same source/seed/runtime. | L |
| T25 | Pass | Mock browser stream disconnect/reconnect and idempotent controls pass; real browser persistence/reload also passes. | N,B,L |
| T26 | Pass | Mock failed reads keep unknown metrics and do not switch to demo data; real settings/config validation passes. | N,B,L |
| T27 | Pass | Export grouping and leakage checks are covered by `test_source_and_geometry_and_lineage_groups_join` and deterministic export tests. | F |
| T28 | Pass | Path traversal, symlink, corrupted artifact and inert script-text tests pass; downloads are restricted to registered artifact paths. | F,B |
| T29 | Unverified | No run reached a global target or exhausted a real budget with surplus accounting. | - |
| T30 | Partial | R01/R06 verify historical success, consecutive-failure cooldown/probes and all 64 natural seeds under production planning. Real-model coverage and sustained mixed healthy/failing themes remain unqualified. | L |
| T31 | Unverified | No long-lived zero-output stop-loss run was recorded. | - |
| T32 | Pass | `test_backup_restore_uses_sqlite_snapshot_and_preserves_assets`, the full local fixture integration test, and the external-root acceptance run verify backup, new-path restore, verification, and matching campaign counts. The review adds an archived asset together with failed/unknown requests and verifies restored financial/execution counters. | F,L,R |

## Acceptance Run Details

The external-root run used the checked-in offline config copied to `/tmp/voxlush-acceptance-20261008/config.json`. Doctor passed. The service was started once, campaign `offline-demo` was created with `request_limit=1` and `api_cap=0`, then start/pause/resume/drain were applied. The service was stopped before export and backup, avoiding the Store lock. Release verification returned `schema_version=voxlush.release.v1`, `leakage_check=pass`, and counts `accepted=0`, `assets=0`, `provisional=0`, `repair_pairs=0`. The backup manifest used SQLite online backup and the restore receipt reported `database_integrity=ok`, `paths_rebased=true`, and one database file. The restored root was started separately and its campaign state/counts were inspected.

The local real fixture uses an islands scene and is explicitly marked `record_kind=fixture` / `fixture_mock`; it is not a production accepted asset. No repository `data/` directory was created.

## Remaining Release Gates

Model qualification remains open: representative ordinary/complex/natural author-to-image-review chains, recorded profiles and human blind review are required. The latest request authorized real calls without a fee constraint; testing retained finite request/repair limits. One natural chain now passes. Short synthetic scale and real concurrency 16 were exercised; long-duration fault/soak, real accepted throughput and monitoring overhead remain open. Deployment remains open: pinned release, authorized production root, verified pre-migration backup, schema-2 migration, canary and tested rollback. The older schema-1 binary requires restoring its pre-upgrade database backup. No production migration, rollback or release tag is claimed.
