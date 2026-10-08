# Worklog

- 2026-10-08 P0: read authoritative handoff, cloned current upstream, captured Git bundle and source hashes, discovered full legacy local project; no production mutation.
- 2026-10-08 P1-P3/P5 offline pass: verified Python tests (33 passed, 1 optional private regression skipped), Ruff, TypeScript/frontend build, mock dashboard E2E, real local geometry/API browser E2E, doctor isolation, campaign controls, empty release verification, and external-root backup/restore. Zero model requests; no human review or production migration.
- 2026-10-08 Delivery docs: corrected README config/campaign/shutdown examples; added evidence-bounded acceptance, model, performance, and migration reports. The offline scale targets and unexercised T-cases are explicitly recorded as incomplete.
- 2026-10-08 Source delivery: shortened README to installation/startup/common commands, included the sandbox image build step, and prepared a screened source-only GitHub commit under the configured user identity. Runtime data and credentials remain outside Git.
