# Voxlush Gen — repository working contract

Read CODEX_HANDOFF_ZH.md and docs/01–04 before changing behavior. They define the user-approved product direction; archived reviews are evidence, not additional mandatory runtime layers.

## Non-negotiable

- Each asset is independently designed and coded by the model. Shared low-level drawing/runtime tools are allowed. Fixed house/roof generators or a restrictive high-level geometry DSL are not.
- Target accepted unique usable assets, not request counts. Never lower a contract, fabricate metrics, copy requested tags into observed tags, or treat unverified legacy complete records as newly accepted.
- Use one modular backend, one scheduler/state owner, bounded resource queues, persistent budgets and idempotent local commits. Separate frontend code from backend; the browser never schedules work.
- Normal direct path: author + real visual review. Complex path: free-form skeleton + refinement + real visual review. Repairs are finite and evidence-guided. Do not add multi-agent review committees or unnecessary model calls.
- Preserve final component ownership, coordinate conventions, raw provenance, actual voxel previews and reproducibility. Natural scenes have appropriate contracts; they do not inherit timber-house room/window requirements.
- Generated code executes only in a tested isolated environment. Never expose credentials, network access, the Docker socket, or broad host mounts to it.

## Development

Inventory the latest full project first. Protect LICENSE and prior work. Use small reversible commits. Follow implementation phases automatically; only consolidate genuinely missing access/budget/irreversible-operation decisions for the user.

Keep docs/STATUS.md and a short WORKLOG current. Record important deviations in one DECISIONS.md with rationale and evidence. Do not create parallel state machines, duplicated theme runners or speculative infrastructure.

Test the critical failure paths with a fake HTTP/SSE server and real local geometry/render fixtures. Clearly distinguish mocked transport, real local integration, paid API tests, and human quality calibration. Never claim implementation from documentation or schema validation alone.

## Data and permissions

Runtime data lives outside Git. Do not commit private_inputs/, live configs, secrets, logs, generated datasets or backups. Do not blindly copy an archive into the public repository. Retain upstream attribution and do not infer dataset license from repository license.

Without explicit existing authorization, do not make paid calls or modify running production services. Within an approved budget/cap, automatically continue qualified stages instead of asking per sample. Never reset budgets on restart or blindly replay outcome_unknown POSTs.

Production updates use a pinned release, drain, consistent backup, migration, canary and a tested rollback. No unattended git-pull-main deployment.

## Done

Deliver a working installation, CLI/API/UI, theme coverage planning, durable artifacts, training export, tests, metrics, operations guide and a precise acceptance report. Report Implemented / Offline verified / Model profile qualified / Deployed separately.
