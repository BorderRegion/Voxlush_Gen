# API pool receipts

An opt-in patch for the operator-supplied gateway and worker versions pinned in `prepare.py`. It adds durable single-send identities and authenticated response retrieval; it does not replace the pool or change unopted requests. Deployment evidence is in [production_validation.json](../../reports/production_validation.json).

## Prepare and verify

Keep private pool sources, accounts, configuration and receipts outside Git. The original source must include `proxy_allocator.py`; the worker imports it at startup. Preparation checks source hashes, normalizes the gateway's CRLF, applies these narrow patches and compiles the resulting files. It never connects to or restarts services.

```bash
python ops/pool-receipts/prepare.py --source-dir /private/pool-source --output-dir /private/new-release
VOXLUSH_POOL_PATCHED_DIR=/private/new-release \
VOXLUSH_POOL_ORIGINAL_DIR=/private/pool-source \
PYTHONPATH=ops/pool-receipts \
pytest -q ops/pool-receipts/test_protocol.py
```

The loopback protocol tests additionally use `requests==2.32.5` and `aiohttp==3.13.3`. They exercise extracted real gateway/worker handlers against fixture upstreams, including disconnect persistence, single POST, TLS retry suppression, authenticated lookup, duplicate rejection across restart and stable routing. They do not call a model.

## Enable on a verified deployment

Set `pool_receipts: true` on each applicable Voxlush endpoint. Default is false; opting in changes the model profile identity and requires fresh qualification. Keep existing thinking/stream/budget settings and capacity identity. Preserve the original ledger when enabling this field.

The client sets `X-Pool-Request-Id` to its existing attempt UUID. The worker acknowledges `pool.receipt.v1`, persists a reservation before sending and allows at most one upstream POST. An exclusive lock rejects duplicate identities with 409, including after restart. Tracked calls disable both the old candidate retry and TLS retry. Predispatch rejections explicitly acknowledge `not_sent`; a timeout or generic gateway error does not.

Authenticated GETs using the existing pool credential read:

- `/v1/pool/requests/{id}`: original request hash, upstream POST count, HTTP/provider IDs, usage, execution evidence and body hash.
- `/v1/pool/requests/{id}/body`: persisted original response bytes after settlement.

The scheduler queries at most 16 unknown attempts per batch, rotating every 30 seconds in a background lane. It only reconciles opted-in attempts with the matching original route, request hash, exactly one upstream execution and a verified semantic finish. It saves a separate recovered response before advancing the original sample. It never repeats the POST or resets counters. Missing prices/usage remain unknown financial reservations even after execution ends.

## Deployment and recovery boundaries

Use a pinned release, a private persistent `API_POOL_RECEIPT_DIR` owned by the worker, drain markers, zero local in-flight work, consistent state/config/unit backups and one canary before rolling all workers and gateway. Verify cumulative counters do not decrease. Pin **the worker count and order**: placement is `int(request_id,16) % len(NODES)`. Keep receipt locks and bodies across restarts and storage maintenance. Lost/changed placement is not a reason to resend.

The authorized 2026-10-09 deployment covered five workers and the gateway; it tested a real canary rollback and re-upgrade before admitting tracked inference. After tracked requests exist, rollback must retain identity rejection and read-only receipt access. Do not blindly revert to a worker that ignores the ID, erase locks or restore an older ledger to admit duplicate POSTs. Drain new admission first; preserve all newer receipts and reconcile them before any incompatible rollback.

The patch handles **downstream disconnect while the worker survives and eventually receives the upstream finish**. Upstream EOF, worker crash, local deadline, missing receipt, healthy status or service restart still cannot prove model termination. A worker may have no local in-flight handler while remote computation remains unknown. Historic untracked requests cannot be recovered retroactively. The old worker had a structural maximum of 3 candidate attempts × 2 TLS attempts; actual multiplicity of the 15 historic unknowns is unproven.

For those requests obtain provider completion/cancellation evidence tied to all possible upstream executions, or a documented dispatch-to-termination contract. Retain financial uncertainty separately and use the existing [execution reconciliation command](../../docs/OPERATIONS.md#unknown-execution-reconciliation) only with that evidence. A documented independent execution pool can be configured separately; an alternate model name, healthy account or fresh data root does not establish independence.
