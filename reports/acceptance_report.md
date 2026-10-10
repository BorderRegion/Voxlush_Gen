# Acceptance Report

Updated: 2026-10-10 (Asia/Shanghai); timestamped deployments and historical pilots are recorded separately below.

Original acceptance baseline: `4f4be137d3924b38cb7301c2c4a0081ff32a7c2a`; current follow-up and live results are first below.

Original acceptance environment: Python 3.12.3, Node 20.19.0, npm 10.8.2, Docker 29.1.3, APSW SQLite 3.51.3, Linux, `voxlush-sandbox:v1` (`sha256:50712f3b25dc`). The checked-in profile has `allow_live=false`, no author or visual endpoint, and global API cap 0. The acceptance data root was `/tmp/voxlush-acceptance-20261008`; it is outside the repository and is not production data.

## Lossless storage and on-demand image display (2026-10-10)

Runtime `932323395573ef672f4bae7acfca807e3f01ab59` and sandbox v2 are deployed. [Storage evidence](storage_compaction_20261010.json) records engineering tests, existing-real-asset replay, maintenance and resumed production separately. New builds/archives use bounded lossless gzip for sample JSON; NPZ, palette, coordinates, source and quality gates are unchanged. Old immutable archives/releases retain their paths and bytes. Readers, gallery and nonempty training exports accept both formats. New renders retain the two hash-bound images actually used by visual review, omit the unused contact sheet, and the browser loads images only for an opened sample. No new model call or rendering service is involved in viewing.

**Engineering:** 350 Python passed / one optional private-fixture skip, Ruff, frontend build, 11 transport browser tests and one actual backend/Docker browser test passed. Tests cover compression integrity/limits, old plain compatibility, manifest-bound reading, interrupted conversion/archive commit, exclusive maintenance ownership, preserved budgets and backup restoration. Twelve existing real-model candidates rearchived in an isolated root used 12,795,309 bytes instead of 191,254,878 (93.3% reduction); source, geometry, annotation and decompressed sample bytes matched. A real rerender from saved voxels produced the same two review images byte-for-byte. The nonempty export verified 12 calibration assets, 12 source SFT rows and three repair pairs, with zero formal accepted. These are existing-asset/local results, not new paid quality experiments.

**Production:** after natural request drain, the 17,642-file / 35.07 GiB backup was verified on a separate disk. Offline work conversion compressed 950 files and released 14,189,034,346 bytes (13.21 GiB); all 2,267 existing immutable files rehashed unchanged, the whole prior request/campaign ledger matched, and all 1,622 previous request identities were retained. No active request was interrupted by deployment. Paused restart and doctor passed before resuming cap 256. An isolated rollback canary restored an old plain backup and verified the old reader and v1 renderer; old binaries require this backup and cannot read new gzip-only assets by switching code alone. Actual public HTTPS browser checks passed all main pages with no JavaScript errors, zero image requests on the list and successful existing-image retrieval on opening a sample.

At 02:36 UTC, resumed production had 139 candidates / zero formal accepted, 1,885 cumulative requests, 184 locally active and 245 retained unknown attempts. Sixteen newly written real build revisions matched compressed sample/canonical geometry/annotation hashes; twelve passed geometry and nine had matching saved-voxel render/image hashes with two views and no contact sheet. No new-format live archive was complete at that snapshot; archive/export proof comes from the isolated replay and regression tests above. Storage validation did not require new paid experiments; normal authorized production continued.

Free live-disk space was 19.81 GiB at the postflight snapshot. The work area still retains plain pre-weathering geometry references (~13.7 GiB across 950 files at maintenance); these are provenance, not identical copies of final geometry. The backup also remains on another disk. The 93.3% archive reduction does not establish a whole-pipeline capacity estimate or long-duration qualification. No unknown execution, uncertain cost, human score or candidate status was rewritten.

## Local production deployment and 256-concurrency startup (2026-10-09)

Pinned runtime `9a975fbe4bc694ffba181a6905eb25289654d20c` is now deployed as one systemd owner on a separate data disk, with a persistent authenticated HTTPS reverse tunnel. [Timestamped deployment evidence](deployment_20261009.json) records the actual campaign, counters and validation scope. This supersedes older statements below that no generator service was deployed; historical experiments remain historical.

The user authorized 256 concurrent calls on the 512-capacity pool. Actual production ramped 32 → 64 → 128 → 256 and reached 256 active requests, retaining server/account limits, finite budgets, local build/render bounds and unknown ledgers. Subsequent busy/interrupted responses reduced the adaptive limit to 179 at the recorded snapshot; existing in-flight calls were not cancelled to fake an immediate drop. DeepSeek v4.1 Flash authors with thinking retained; GLM 5.3 Flash reviews real previews at reasoning_effort=max. The first 17 requests used Tierflow, so campaign totals are **not** a unified-model quality comparison. Previous endpoint receipts are queried without new POSTs after the route switch. Missing receipts and local disconnects do not release unknown occupancy or turn missing bills into zero.

Two real candidates and zero formal accepted were present at the initial handover snapshot. The first archived candidate passed real voxel/geometry checks and actual-image review; a nonempty release containing it passed integrity and leakage verification and remained in calibration. The remaining tasks are pending or failed, never counted as successful. Current mixed-model startup counts do not establish final pass rate, complex-building yield or cost per qualified asset.

Validation: **333 Python passed / 1 optional private-fixture skip**, Ruff, generated API types and frontend build. New tests include actual loopback 256 dispatch, cap boundaries, downward backoff, and paid-response recovery from an explicitly retained previous route without duplicate POST or accounting reset. Actual local Docker execution/rendering passed inside the service's systemd namespace. A discovered PrivateTmp bind-source issue was corrected with a host-visible private TMPDIR; original source resumed without author repair for infrastructure failure. Public browser login/all pages, candidate preview access, TLS, secure HttpOnly cookies, unauthenticated 401 and SSE were checked. Pause/drain/running restart controls, pre-live backup/restore, a consistent backup with 17 sent requests and real artifacts, and code rollback/re-upgrade at cap zero passed. Historical roots, receipt files and budgets were preserved.

The service is left running, targeting 1,000 candidates within 8,000 total requests. This is an authorized production startup with real output, **not** a completed long-duration soak or formal model/human qualification. The monitor exposes actual yield and failures; no provisional promotion or artificial human score is used.

## Prior follow-up: continuity despite unresolved execution (2026-10-09)

The user now explicitly accepts losing interrupted samples and asks that they not permanently halt new production. Commit `49e3dfb` implements the opt-in `continue_new_tasks` policy. This section supersedes the earlier requirement to isolate the entire pool before any new work; it does **not** supersede the historical quality results or claim that unknown upstream work ended. [Machine-readable evidence](unknown_continuation_validation.json) records this change separately.

After a persistent pool cooldown (30 seconds by default), unknown attempts are excluded only from local dispatch-slot accounting at all three admission boundaries. Their original identity, `outcome_unknown` status, `occupancy=1`, response bytes and unknown financial reservation are retained. The failed sample is blocked and cannot repost its original request. Existing authenticated GET recovery may apply a later complete original response through the normal build, render, review and archive checks. Request/money budgets, RPM/TPM, provider Retry-After, local active concurrency caps, explicit endpoint failures and user pause/drain remain effective. No model health probe, weakened gate, schema migration or second state machine was introduced. Actual remote concurrency cannot be inferred from this local cap.

**Software verification: 322 Python tests passed / 1 optional private fixture skipped in 106.82 seconds; Ruff and diff checks passed.** The new file has 14 cases. A real loopback TCP server receives the first POST and drops its connection; after Scheduler/Store restart, a distinct second task reaches build with the original unknown row/raw response unchanged and no premature archive. Twelve alternating unknown/completed rounds also advance while retaining every uncertain bill. Strict-mode isolation, persistent cooldown, active caps, budget limits and manual controls are tested. These are fixture/transport-fault tests, not a paid model run or sustained production measurement. The unchanged UI and pool code retain their prior build/browser/protocol evidence below.

**Operational change:** one worker-0 source disabled by the prior strict policy was restored after drain and backup. Only its enabled flag changed; cap 2, probes off, pinned service code and gateway routes were retained. All 102 stored receipt files stayed byte-identical and cumulative counters did not decrease. Six authenticated GETs then retrieved two original unknown receipts/bodies and one completed receipt/body with matching hashes and unchanged execution states. No inference POST was sent; no unknown was reconciled away. All 21 historical/new unknown executions remain recorded. The current generator release is available in the workspace, but no generator service or new campaign was started; existing private configurations require the explicit policy field. The example selects continuation while remaining offline (`allow_live=false`, cap 0, no endpoints).

**Decision:** this resolves the application-level whole-pool deadlock under the user's accepted uncertainty, allowing bounded candidate production when the upstream service accepts requests. It cannot guarantee output during a complete upstream outage, exhausted budget, storage failure or sustained model failure. It does not qualify formal 10,000–100,000-asset production: live yield/soak, complex-building quality and formal model/human calibration remain unverified. The user has viewed and accepted the example quality informally; no human scores or accepted assets were invented. This follow-up made zero new model requests and left all prior quality evidence unchanged.

## Prior authorized live composition validation (2026-10-09)

This section supersedes the older zero-new-call findings below. Engineering through `c19c628`; generation baseline for final cohort D: `57de341`. [Machine-readable evidence](live_composition_validation.json) retains separate batches, attempts, stages, observed models, usage, failure rules, deployment and verification. Broad experiment and pool-modification authorization was used; no prior small-call cap was applied.

**Real outcome: 16 dispatched independent tasks, 31 pipeline requests, 2 archived candidates and 0 formal accepted assets.** Two additional two-image capability probes completed; one additional rubric-v6 review of unchanged saved contextual previews ended unknown without a verdict. It is not a new generated asset and does not establish v6 quality. Known pipeline usage is 1256851 tokens; 5 pipeline attempts lack usable usage and every pipeline currency charge remains unknown. Failed tasks stay in the denominator; unsent tasks remain separately counted.

| Cohort | Theme / scale / route | Mode | Dispatched tasks | Ever executable / final geometry / visual pass / candidate | Requests | Reported tokens | Tokens per candidate | Candidate elapsed minutes* |
|---|---|---|---:|---|---:|---:|---:|---:|
| A | commerce_01 / S / direct | pure_target | 1 | 1 / 0 / 0 / 0 | 1 | 51991 | — | — |
| A | commerce_01 / S / direct | contextual | 1 | 0 / 0 / 0 / 0 | 1 | 67600 | — | — |
| A | timber_04 / L / two_stage | pure_target | 1 | 0 / 0 / 0 / 0 | 1 | unknown | — | — |
| A | timber_04 / L / two_stage | contextual | 1 | 0 / 0 / 0 / 0 | 1 | 67626 | — | — |
| B | commerce_01 / S / direct | pure_target | 1 | 0 / 0 / 0 / 0 | 1 | 49692 | — | — |
| B | commerce_01 / S / direct | contextual | 1 | 0 / 0 / 0 / 0 | 1 | 67576 | — | — |
| B | timber_04 / L / two_stage | pure_target | 1 | 0 / 0 / 0 / 0 | 1 | unknown | — | — |
| B | timber_04 / L / two_stage | contextual | 1 | 0 / 0 / 0 / 0 | 1 | 62334 | — | — |
| C | commerce_01 / S / direct | pure_target | 1 | 1 / 1 / 1 / 1 | 4 | 164461 | 164461 | 39.4 |
| C | commerce_01 / S / direct | contextual | 1 | 1 / 1 / 1 / 1 | 4 | 133397 | 133397 | 33.1 |
| C | timber_04 / L / two_stage | pure_target | 1 | 1 / 0 / 0 / 0 | 4 | ≥ 158282 | — | — |
| C | timber_04 / L / two_stage | contextual | 1 | 1 / 0 / 0 / 0 | 3 | 158928 | — | — |
| D | commerce_01 / S / direct | pure_target | 1 | 0 / 0 / 0 / 0 | 2 | ≥ 67728 | — | — |
| D | commerce_01 / S / direct | contextual | 1 | 1 / 0 / 0 / 0 | 3 | ≥ 84242 | — | — |
| D | timber_04 / L / two_stage | pure_target | 1 | 0 / 0 / 0 / 0 | 2 | 79057 | — | — |
| D | timber_04 / L / two_stage | contextual | 1 | 0 / 0 / 0 / 0 | 1 | 43937 | — | — |

*Elapsed includes queueing and recovery. Token/unit figures include the group's failed work where applicable. `unknown` means no usage was returned; `≥` marks a partial sum with missing usage. No candidate means an undefined unit figure, not zero. Per-stage initial/repair/refinement/review requests and tokens, first-attempt executable rates and actual model seconds are in the JSON. A/B/C/D used different configurations and must not be pooled into a controlled quality comparison. C used prompt v8/rubric v5 and a drained medium-to-high configuration recovery; D kept prompt v9/rubric v6/stream v6 and high thinking unchanged. Even D's exposed fixed configuration uses a supplier auto-route alias: the underlying GLM variants are not pinned.

### Actual quality and preserved evidence

C's ordinary pure candidate measures 0% environmental voxels and retains roof, chimney, awning and architectural detail. Its ordinary contextual candidate measures 90.3% environmental voxels and about 4.3% building footprint; visual inspection reveals disproportionate empty ground even though the v5 model passed it. This is a concrete calibration weakness, not a qualified high-quality result. Components supply declared semantics; measured voxel ownership and saved images provide separate evidence. Human blind scores remain missing. Complex two-stage results are reported separately above; simple buildings do not hide their failures.

Prompt v10 additionally clarifies that W requires an explicit floor, while G/K set the roof floor internally and accept no floor/wall_id argument. This targeted follow-up has offline regression evidence only; no new model call or quality improvement is claimed for v10. The v9 prompt clarifies C's one-time registration and W/G/K ownership, window backing and concise complete-code output without turning designs into templates. Bounded repair feedback exposed six distinct rules from a saved complex failure where the old prefix exposed only three; the original report remains unchanged. Rubric v6 flags disproportionate scene padding, but improvements require completed image verdicts and human calibration, not the existence of new text. Source/runtime, geometry/space metadata, length exhaustion, assessor/transport and environment faults remain distinct in the report.

Actual previews, original model source/response/reasoning and logs stay in the private experiment root; the user gallery is `outputs/composition-20261009/index.html`. The candidate blind package strips known burned-in captions only, records hashes and supplies blank scoring records. It invents no human scores and promotes no provisional samples. C's new pure candidate reproduced canonical hash `6d3d41e2866d46067c48504a88b325b19f30ef880ac1cfa02dc625b0df90342f` when rebuilt/rendered unchanged in Docker. Restored filtered exports retain candidate/calibration partitions and repair pairs; formal export remains empty. Exact per-cohort export evidence is in the report.

### Execution evidence and deployment

Read-only account/quota inspection established independent Tierflow subscription capacity, separate from historical NVIDIA requests. Legal concurrent generation was two; uncertain source accounts were excluded before using remaining verified accounts. Tracked workers persist source hashes before exactly one POST; gateway model routes pin receipt placement. Real failures exposed a too-small 16 MiB receipt cap and a bare-DONE terminal false positive: limits are now bounded at 32 MiB across client/worker/recovery, and bare-DONE stays unknown. B's wrongly settled original send was corrected with retained raw bytes, backup, separate reassessment and no repost/budget reset. One complete authenticated unsupported-medium HTTP400 rejection was reconciled by GET/hash proof; one audited experimental requeue after setting supported high thinking preserved budgets and repair allowance. It does not imply generic automatic error recovery.

D's final two worker receipts each record exactly one POST, a settled partial HTTP200 stream and ChunkedEncodingError, without semantic finish or usage. Authenticated GET recovery found no valid termination evidence. Their source was disabled after drain/backup, with receipt bytes and counts unchanged; all five workers are healthy. This leaves no verified unoccupied test account enabled. All 15 historical unknowns remain byte/accounting-identical. Including new experiments and the image audit, **21 unknown executions remain**. Neither receipt 404, socket EOF, elapsed time, health recovery nor a provider-log 502 released them. Provider account logs expose subscription quota and request IDs, but no verified upstream cancel/end/max-execution contract. The old audit receipt lacks the provider's trace header, and its model response ID does not match the account log ID. `5402dd2` retains `X-Tierflow-Request-Id` for future correlation; that field itself never changes occupancy or billing uncertainty.

The gateway and five workers were backed up and updated with receipt hashes and cumulative counters preserved. Trace-header rollout on workers 2/3 initially exceeded a 20-second control timeout; both restored the prior single-send release and then updated serially using the actual 90-second stop grace. Worker 0's active model requests were not interrupted. Deployment records distinguish each successful revision and preserve all old identities.

After the final source isolation, six authenticated GETs retrieved both D unknown receipts/bodies and one previously completed receipt/body through the original public route. All three body hashes matched the retained evidence, each still recorded exactly one upstream POST, and their execution states remained unchanged. This check made no model request and modified no ledger. A final historical-preservation check also passed for all 14 ledger records plus the original raw image canary.

### Verification and decision

**308 Python tests passed, 1 optional private fixture skipped (116.94 s); 17 actual copied-handler loopback tests passed (6.30 s); Ruff, frontend build, 11 mocked browser cases and 1 real local backend/Docker/render/browser case passed.** The trace-header regression failed before the fix and now retains the ID, drops cookies and leaves an incomplete stream unknown. Prior composition regressions cover requested/observed category matrices, immutable legacy archives, effective accepted/provisional quotas and filtered/mixed export bypasses. Offline fixture reviews are mocked; only the separately recorded live reviews read model-submitted actual images.

**Safe to start formal mass pure-building training production: no.** Positive evidence establishes one ordinary pure candidate, correct local archive/export operations and substantial software reliability fixes. It does not establish stable complex-building yield, economical throughput, a qualified stable model pair or human aesthetic acceptance. Minimum remaining work is to secure verifiable upstream execution reconciliation or durable independent capacity with stable author/image models; finish a positive matched full-chain quality cohort; perform the existing blind qualification and then scale/soak only after positive yield. More unbounded requests, weakened contracts and quota relabeling are not substitutes. Prompt v10 has no paid validation yet because the remaining independent test source is now uncertain. No new framework or dashboard expansion was introduced in this follow-up.

## Historical composition consistency review: baseline c1a5a1a (before live validation)

Latest fetched main was `c1a5a1aed75354a9601f6706a855945f5eca6265`; implementation commit: `fbbb881ddf0a7f3e910837193dacb6148872450c`. [Machine-readable evidence](composition_consistency_validation.json) records this follow-up separately from the earlier feature and model pilots.

The defect is fixed at review, archive admission, Store accounting, scheduler completion/replenishment and export boundaries. Requested environmental permission is separate from observed class. Pure observed content cannot fill contextual or rich quotas; excessive observed rich content cannot fill contextual. Natural variation within classes and the existing pure/light geometry tolerances remain, while unresolved boundaries remain gray. No authored source, architectural quality requirement, thinking setting or normal-path call count was reduced. Prompt v7 and visual rubric v5 reflect the corrected contract.

Schema 5 adds a derived eligibility cache and transactionally rebuilds summary counts. It retains original asset files, statuses, labels, campaign lifetime counters and request/budget records. Legacy v1 archive integrity can still verify under its original evidence; current quota/export eligibility independently rejects false passes. Matching old image evidence remains reusable without a paid request. Accepted/provisional modes remain separate. A surplus in one class cannot stop planning for another; completed/paused campaigns are not automatically restarted. Old-policy export staging requires a new output path, and current release verification reports mismatches without modifying files.

Validation: **296 Python tests passed, 1 optional private fixture skipped in 138.51 s**; Ruff and frontend build passed; **11 mocked browser tests** passed in 19.5 s and **1 real local backend/Docker/render/browser test** passed in 16.2 s. The 25 added cases cover all 16 requested/observed combinations, four legacy false-pass archive cases, matching legacy response reuse, schema-4 accepted/provisional migration and actual scheduler ticks, quota surplus, filtered/unfiltered/mixed export, stale staging and release validation. Geometry, rendering, archive backup/restore and export are real local operations; visual verdicts in these tests are explicitly mocked.

**The requested new real quality comparison is not complete.** Broad API authorization remains valid. Fresh read-only inspection found the patched gateway and five workers running, but no retained upstream completion/cancellation record for the 15 historical unknowns. Fourteen authenticated receipt queries returned 404. Five worker receipt roots had no records; a bounded retained-log scan of 30000 lines found 28 matching identity lines, all receipt-query 404s. The original 14 raw responses have no semantic finish or DONE marker and no stored upstream request headers; their status, occupancy, cost and response hashes, plus the fifteenth raw visual canary hash, are unchanged. Local 2400/600-second timeouts are not remote termination contracts. The alternate provider exposes two custom aliases and no verified independent execution or image-capability contract. No inference POST, release of unknown capacity, original-ledger write or shared-service modification was made.

| Requested mode / route | New independent tasks | Valid candidates | Formal samples | Context / quality / yield / tokens and cost per valid sample |
|---|---:|---:|---:|---|
| pure_target / ordinary direct | 0 | 0 | 0 | Not measured |
| contextual / ordinary direct | 0 | 0 | 0 | Not measured |
| pure_target / complex two-stage | 0 | 0 | 0 | Not measured |
| contextual / complex two-stage | 0 | 0 | 0 | Not measured |

**Safe to start formal batch pure-building training production: no.** The minimal next steps are provider-backed reconciliation of the historical sends (including possible upstream retries), or documented independent capacity with the required author/image models; then the matched full-chain comparison and existing same-profile human blind qualification. The prepared first cohort is two independent repeats of each mode for `commerce_01` and `courtyard_east_01` (S/direct) and `timber_04` (L/two-stage), 12 tasks with the same DeepSeek author / GLM image-review configuration and retained thinking. This is an experiment design, not an authorization cap. Expand only after positive actual quality/yield evidence. The existing 40/30/20/10 default remains an engineering starting point, not an experimentally optimized recommendation. Earlier unspecified historical replays do not establish the new mode-conditioned quality or unit cost.

## Composition control review: baseline eec41da (historical; admission semantics corrected above)

Fetched main matched `eec41dab19fe8616b8a7a26f36aa86e286cff417` before editing and before delivery. Backend `8a5c6d9` and dashboard `c877d01` implement the requested dataset dimension. [Machine-readable evidence](composition_validation.json) separates fixtures, historical model replay and the blocked new experiment. No production data/service mutation or new model request occurred in this feature review.

| Delivered behavior | Evidence |
|---|---|
| Four explicit modes across the full creative route | Task JSON/schema, prompts v6, visual rubric v4; direct, skeleton, refinement and repair carry the same mode. Actual scheduler regressions cover skeleton geometry/syntax repair and restart with pure/light modes, followed by exactly one refinement. Thinking and normal call count are unchanged. |
| Lightweight context enforcement | Final occupied voxel ownership and occupied XZ columns detect both deep terrain and thin wide scenery. Pure limits start at 10% context / 80% subject columns; light at 25% / 60%. Distant decoration/foundation labels cannot automatically count as building. Contextual/rich retain a recognizable architectural subject without a ratio cap. Actual saved previews feed the existing single independent image review; absent/malformed/uncertain observations cannot pass. |
| Free design and theme compatibility | No geometry template or source alteration. Existing structural/spatial/aesthetic requirements remain. Natural tasks are exempt. Hybrid settlement/landscape briefs use contextual/rich weights normalized to 2:1 by default; a zero compatible mass is rejected. Three explicitly multiple-building architecture seeds are excluded from pure pairing, with other briefs retained in every family. |
| Final-output composition quotas | Persisted indexed summaries and deficit selection count accepted for qualified production, accepted plus verified candidates for calibration; formal debt remains visible. Simulated unequal yield reaches 8/6/4/2 outputs from 16/6/4/2 attempts. Failed/duplicate tasks do not fill quotas. Existing finite failure budgets remain active. |
| Trustworthy archives and releases | Requested mode, measured context and observed image context remain distinct. Verification binds component ownership, actual voxels, geometry report, previews and review. Manifest-only relabeling fails. Filters require mode plus compliance; exact apportioned mixed export rejects shortages without replacing a low-yield mode. Candidate/fixture training splits remain calibration/excluded. |
| Existing UI and human inspection | Mode filters, detail evidence, per-mode tasks/archive/visual rates, failures and average requests; campaign weights and single/multiple/mixed export controls. Anonymous gallery stratifies by composition, exposes requested instructions but no model verdict, and keeps human observed mode/compliance scores blank. |
| Compatibility and recovery | Additive schema 4 leaves old briefs/modes unspecified and preserves unknown occupancy/budgets. Real local pure/contextual archive backup/restore retains weights, summaries and nonempty filtered export. Old unfiltered assets/releases remain readable. |

Final checks: **271 Python tests passed, 1 optional private fixture skipped, 107.23 s**; Ruff passed; TypeScript/Vite build passed (154 s); **11 mocked browser tests passed** (19.9 s), and **1 actual local API/Docker/render/browser test passed** (17.1 s). The latter uses fixture review, not a model. The new real geometry/archive fixtures likewise do not count as quality candidates. A test-fixture setup error (claiming a draft campaign) was corrected before the final suite; the final run has no test failures. The only Python warning is the existing Starlette/AnyIO deprecation.

### What the real-source replay establishes

Six historical model-authored candidates were rebuilt and rendered without source/seed changes. Each retained its canonical voxel hash. These were originally unspecified tasks; the two checks below are retrospective, not successful new mode-conditioned generation.

| Historical route / scale | Assets | Contextual geometry pass | Pure geometry pass | Non-subject occupied voxels |
|---|---:|---:|---:|---:|
| Direct buildings / S | 5 | 5 | 0 | 75.1%–97.9% |
| Two-stage building / L | 1 | 1 | 0 | 90.1% |

All six failed both pure voxel-fraction and footprint-extent checks. Actual preview inspection of the bakery and complex lodge showed broad ground/road or river/terrain surroundings. This is diagnostic support for the requested control. Semantic categories remain generator declarations, the new replay did not call an image model, and no human blind score was supplied. It proves the checker can detect excessive surroundings while leaving authored geometry intact; it does **not** prove prompt v6 reduces surroundings or preserves/improves new generated building aesthetics.

### New pure/contextual batches: blocked, not reported as successful

There were **zero new paid calls, independent tasks, candidates or formal accepted assets**. Consequently new source/geometry/visual/archive rates, tokens/time per candidate and actual currency cost differences are **null**, not zero-performance claims. Broad API authorization is already present; there is no renewed small-call cap or permission question.

Fresh read-only inspection found the deployed gateway/five workers running. Fourteen authenticated historical receipt lookups returned 404; the fifteenth unknown is a raw visual canary. Read-only original-ledger comparison retained status, occupancy, settled-cost uncertainty and raw response hashes for all fourteen, plus the canary hash. None was released/replayed. Absent receipts and healthy workers cannot establish upstream termination or independent capacity, so a new data root was not used to evade shared isolation.

The minimum next experiment after valid execution evidence is available is a matched first batch across `commerce_01` (S), `courtyard_east_01` (S) and `timber_04` (L/two-stage), independently generated in pure and contextual modes with the same model/thinking configuration. Run the complete normal chain and inspect actual defects before expansion. Compare mode-specific yield, building quality, context, tokens, elapsed time and known/unknown cost; preserve failures in denominators. This six-task design is a starting experiment, not an authorization ceiling.

Recommended architecture default remains **40% pure / 30% light / 20% contextual / 10% rich**, an engineering starting point within the requested ranges. It is not an empirical optimum. Qualification is invalidated by the new prompt/rubric/validator version. **Unattended formal production and 10000–100000 scale remain unqualified** pending external execution evidence, new full-chain quality/efficiency and sustained-run evidence, and genuine existing-contract human blind calibration. No provisional asset was promoted.

## Review 2672ca7: response recovery, deployed pool receipts and quality evidence

Baseline `2672ca76e2c0e1fba73a2f0b8d683ad0b311c41c` matched freshly fetched main before editing. Reliability/protocol commit: `44f8be5`; quality diagnostics/gallery commit: `f52766e`. [Machine-readable evidence](production_validation.json) separates this review from the historical paid cohorts. Broad API use was authorized; prior small-call limits no longer apply. The user separately authorized draining, backing up and rolling out the reviewed API-pool patch.

| Change | Evidence and boundary |
|---|---|
| Complete paid responses stuck after `local_artifact_invalid` | Four regressions failed before the fix. Startup/tick/callback recovery reuses the saved response, including after a real path collision. Three local application failures are terminal across restart; explicit retry after path repair still uses the original response. No duplicate POST, budget reset or author repair consumption. Shared storage faults continue to block paid admission. |
| Pool/client request lifecycle was unobservable | Optional `pool_receipts` pins one attempt UUID to one worker and one upstream POST; captures request/body hashes and provider HTTP IDs; persists the upstream response after downstream disconnection. Authenticated GET reconciliation verifies identity, original request hash, single execution, body integrity and semantic finish before applying it. Polling rotates through bounded batches without blocking controls. Unknown charges remain reserved independently of released execution. |
| Window repair feedback did not identify the actual obstruction | Diagnostic coordinates now include final component owner and material. Unchanged saved source identifies the timber obstruction as `cabin_balcony`; courtyard obstructions include actual wall/window components. Five original programs retain their prior pass/fail; all three that produced canonical voxels retain their hashes. No final contract, geometry, prompt v5, rubric v3 or thinking setting was weakened. A higher real model repair success rate is **not yet established**. |
| Candidate blind review lacked a usable anonymous package | CLI exports verified, stratified candidates, two actual saved previews, blank scores and a separate private mapping. Browser inspection caught burned-in IDs/names/voxel counts in the initial package. The final package removes only known caption margins losslessly, records original/derived hashes and crop coordinates, and rejects unknown layouts. Geometry pixels are unchanged. Eleven historical candidates/22 images load on desktop/mobile; no human scores or promotions. |

Complete Python suite: **248 passed, 1 optional private fixture skipped, 103.47 s**. Ruff passed for backend/tests and the new ops package. TypeScript/Vite build passed; **10 mocked-transport browser tests** and **1 real local backend/browser test** passed. The latter uses actual Docker geometry/render and fixture review, not a model. Ten separate pool protocol tests execute the real copied gateway/worker handlers against loopback upstreams; their two warnings are aiohttp test application string-key warnings.

Actual process stop/start retained running intent, pause/drain/emergency controls, the existing request and budget; continuation needed no manual resume. Its duplicate fixture was rejected. An actual absent Docker socket recovered through the 30-second local probe in **32.37 s**, preserving source/revision with zero author repairs or model calls. Nonempty historical backup restore retained 79 attempts/three unknowns, re-exported **11 candidates and 17 repair pairs**, and rebuilt/rendered a complex original to the same **267209-voxel hash**. These counts are historical replay, not newly generated assets. Existing regression coverage still exercises historical permanent failures beside healthy tasks, finite local failures, repaired archive/export and skeleton repair followed by exactly one refinement.

### Authorized production pool deployment

The gateway and all five workers now run the pinned receipt patch. Deployment drained local handlers, backed up code/config/units/state, rolled workers and gateway, checked cumulative request/token/cost counters, and tested backup extraction plus an actual worker canary rollback/re-upgrade. The initial canary lacked the existing `proxy_allocator.py` dependency; it was immediately rolled back, the pinned dependency was included, and the canary and rollback were repeated successfully before proceeding. No active model handler was interrupted by that canary. The source-only [ops package](../ops/pool-receipts/README.md) reproduces the tested release from the exact private originals.

All six services were running, all five workers reachable, deployment drain markers removed, and counters retained. Actual external authenticated GETs reached each worker's receipt route (404 for unused IDs); unauthenticated queries returned 401. **No inference POST was used for deployment or smoke tests.** The generator itself has not been deployed or qualified for production. Tracked mode remains an explicit client opt-in; existing unopted behavior is retained.

The old worker could structurally make **3 candidate attempts × 2 TLS attempts**, up to six upstream POSTs per client call; this is an audited code bound, not a measured history. The new tracked mode permits at most one. It can recover a future client/gateway disconnect when the worker survives and receives the final upstream response. It cannot reconstruct old request IDs or prove termination after upstream EOF, worker crash or local deadline. The provider documents tracing/HTTP behavior, but no reliable termination/cancel/maximum-execution contract for the configured route was established. An alternate model catalog also supplies no proof of independent capacity or image/model capability.

**All 15 historical unknown executions remain unresolved:** 14 ledger records across six original roots plus one raw visual canary. Read-only comparison retained status, occupancy, cost and response hashes; none was released or replayed. The patch is not retrospective evidence. The [operations guide](../docs/OPERATIONS.md#unknown-execution-reconciliation) describes evidence-backed reconciliation; the private dossier retains attempt IDs, original ledger locations, timestamps and available model IDs for upstream investigation. Finance remains unknown even if a later valid terminal receipt releases execution.

### Actual quality and efficiency: no new paid cohort this review

**This review made zero model calls and produced zero new independent tasks, candidates or formal samples.** The blocker is unresolved shared execution capacity, not missing API permission or a former small-call allowance. No fresh-ledger admission exception was repeated. Stages A–D (new full-chain calibration, matched optimization, 100–200 tasks and sustained operation) remain unverified.

The historical mixed-version 24-task cohort is useful diagnostic evidence, with every attempted task retained in the denominator:

| Group / scale | Tasks | Initial / ever executed source | Final geometry | Visual pass / archived | Observed tokens per candidate* | Candidate mean elapsed* |
|---|---:|---:|---:|---:|---:|---:|
| Natural / S | 8 | 3 / 7 | 7 (87.5%) | 5 (62.5%) | 201896 | 81.9 min |
| Direct architecture / S | 8 | 0 / 6 | 5 (62.5%) | 5 (62.5%) | 218070 | 95.2 min |
| Two-stage architecture / L | 8 | 0 / 2 | 1 (12.5%) | 1 (12.5%) | 1220922 | 108.2 min |

*Tokens include failed tasks but omit missing usage, so these are observed lower bounds. Elapsed means include pauses/local recovery; concurrent call-seconds are not wall-clock throughput. Per-stage requests/tokens, scale groups and failure occurrences are in the JSON report. The cohort used **24 initial author + 36 repair + 2 refinement + 17 review = 79 requests**. All 79 currency charges are unknown; actual cost per candidate is **null**, not zero. It covered 24 theme seeds, with 11 archived unique geometries and no recorded duplicate rejection; human aesthetic repetition/diversity measurement is absent. Formal accepted and human-reviewed counts are both zero.

The later uniform six-task cohort remains unchanged: **six initial DeepSeek calls, five complete programs, three successful executions, one final geometry pass, zero repairs/refinements/visual calls and zero archives**. Its two natural S/M, two direct S/M and two complex L/XL tasks all remain incomplete/censored. Five calls reported **233261 tokens**; one usage and all six currency charges remain unknown. The sixth call introduced the fifteenth cumulative unknown and stopped admission. Its detailed [historical report](final_quality_validation.json) is preserved; zero visual passes here means no evaluated images, not an aesthetic rejection rate.

Observed failures remain separated: unsupported coast material is a source/runtime error; library strings instead of space objects are metadata errors; balcony-covered windows and courtyard disconnection are geometry errors; missing floor relations are spatial semantics; review-format exhaustion is an assessor-format issue. The new obstruction feedback and earlier metadata fix target these causes without redrawing for infrastructure/review faults. They have offline replay evidence only. Prompt, thinking and two-stage freedom remain intact; no building template or additional review loop was introduced.

### Readiness and minimum remaining work

**Not yet a qualified low-maintenance generator; do not start 10000–100000 formal assets.** The genuine remaining blockers are:

1. Provider evidence resolving all possible historical upstream executions, or documented independent execution capacity; reliable query/cancel/dispatch-to-termination evidence is also needed for future upstream EOF/crash. Gateway receipts alone cannot supply that external fact.
2. One pinned real full-chain calibration with repairs/refinement and actual image review, particularly for complex buildings; matched quality/efficiency comparison, then positive-result-gated 100–200 tasks and a sustained concurrency/recovery window.
3. One hundred same-profile auto-pass candidates and genuine human blind calibration under the existing contract. The exported eleven historical mixed-profile candidates have blank scores and cannot qualify or become accepted.

Reproduce software checks with `.venv/bin/pytest -q backend/tests --tb=short`, `.venv/bin/ruff check backend/src backend/tests ops/pool-receipts`, `npm --prefix frontend run build`, `npm --prefix frontend run test:e2e`, and `npm --prefix frontend run test:real`; pool protocol setup is in its ops guide. Raw responses, credentials, galleries, generated assets and backups remain outside Git. README/LICENSE are unchanged.

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
