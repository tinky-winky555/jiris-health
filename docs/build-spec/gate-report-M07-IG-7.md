# Gate report M07, IG-7 (completion), Failure paths in Billing

Module: `module-07-failure-paths.md` · Date: 2026-11-11 · Branch:
`feature/m07-failure-paths` (from `build/increments` at `0459df5`) ·
Planning report: `gate-report-M07-IG-3.md`, approved with HG-1 on
2026-11-11 (DL-35, DL-36).

## Commits on the branch

| Commit | Content |
|---|---|
| `e3f8e3d` | docs: HG-1 record; TDD §8.2 rewritten (DL-35, DL-36); contract §1 D15, §3 Retries; module-07; IG-3; index section b (M07 8 hours, total 64) |
| `b4ebb3d` | test: M07 tests; M05 test 4.1.9 replaced; committed red |
| `40584b4` | feat: `PermanentError`, payload validation, `record_permanent_failure()`, `count_transient_failure()` in `app/billing/service.py` |
| `2bc09b0` | feat: `classify()` and the failure path in `app/billing/consumer.py`; `error_chain()` made public in `app/outbox/consumer.py` |

## Red run (tests first)

| After | Result |
|---|---|
| `b4ebb3d`, tests | 325 passed, 11 failed, 1 error: `test_billing_classify.py` not collectable (`classify` missing); failed: four payload validation cases, both service failure tests, the permanent, stable transient and outage consumer tests (the stable transient case looped every second under the interim rule, about 20 requeues), T4, T5. The concurrent duplicate test (4.1.11) passed already: the inbox de-duplication of M05 resolves it; it now guards the 23505 rule as well. 325 = 325 of the baseline, minus the replaced M05 test, plus 4.1.11 |
| `40584b4`, service | Amount and service tests: 25 passed |
| `2bc09b0`, consumer | Unit, Billing consumer and service tests: 148 passed; T4 and T5: 2 passed |

## IG-4. Implementation consistent with the approved scope

- `app/billing/service.py`: `compute_amount()` raises `PermanentError`
  for a rate or duration that is not positive, before any write;
  `record_permanent_failure()` upserts the inbox row to `failed` (only
  from `processing`, so BillingFailed is written at most once) and writes
  BillingFailed `permanent`; `count_transient_failure()` upserts `attempts
  + 1` and `last_error` (only while `processing`), and at 5 sets `failed`
  and writes BillingFailed `transient_exhausted`. `reason` and
  `last_error` are the error type and the first line of its message,
  never the payload.
- `app/billing/consumer.py`: `BillingConsumer` with `classify()`:
  `PermanentError` → permanent; database unavailable → unavailable;
  SQLSTATE 23505 → transient; other class 22 or 23 → permanent; any other
  SQLSTATE or none → transient. Outcomes: permanent → ack after the
  BillingFailed COMMIT (`outcome=failed error_class=permanent`); transient
  below 5 → requeue after 1 s (`outcome=requeued attempts=n`); at 5 →
  reject to `billing.parking` (`outcome=parked attempts=5
  error_class=transient_exhausted`); unavailable → backoff 0.5 s doubling
  to 30 s, unlimited (`cause=database_unavailable`); a failure of the
  short transaction is classified again.
- `app/outbox/consumer.py`: `error_chain()` public; no other change.
- Out of scope respected: `app/visits`, the relay, the topology, the
  schema and migrations unchanged; no purge. Files changed under `app/`:
  `app/billing/consumer.py`, `app/billing/service.py`,
  `app/outbox/consumer.py`.

## IG-5. Validation

From a clean clone of the branch at `2bc09b0` (`git clone`, `uv sync`):
353 collected, 353 passed; `lint-imports` 3 kept.

| Criterion | State | Evidence |
|---|---|---|
| Every test of task 4.1 passes | Met | `test_billing_classify.py` 17, `test_billing_amount.py` 15 (4 new), `test_billing_service.py` 10 (2 new), `test_billing_consumer.py` 10 (4 new), `test_t4_permanent_failure.py` 1, `test_t5_transient_exhausted.py` 1: all passed |
| T4 end to end: source status and `completion_failure_reason`; `/complete` accepted again | Met | Visit In Progress, rate 9999999999.99 for 2 h: after `/complete` the visit is In Progress again, not pending, `completion_requested_at` NULL, reason equal to the BillingFailed `reason`, `error_class = permanent`, no record; the second `/complete` 202 with a new attempt. Three further runs: 3 of 3 |
| T5 end to end: counter survives a restart; BillingFailed after the fifth attempt | Met | Worker stopped with SIGTERM at `attempts >= 2` (exit 0), a new worker started; final inbox row `failed`, `attempts = 5` (continued, not restarted), `last_error` with the trigger message; BillingFailed `transient_exhausted`; message in `billing.parking`; visit Scheduled and not pending; after the trigger was dropped, `/complete` ended Completed with one record `50.00`. Three further runs: 3 of 3 |
| A permanent error is never retried; an outage is never counted; no failure creates a record | Met | 4.1.5: one consumed line, acknowledged, not parked, no record; 4.1.7: three deliveries with growing gaps, `cause=database_unavailable`, no inbox row, nothing parked, message kept; every failure test asserts no billing record |
| 4.1.11: concurrent duplicate delivery gives one record and no BillingFailed | Met | Two consumers, the same VisitCompleted published twice at once: one record, one BillingRecordCreated, no BillingFailed |
| Suite in file order and with the T1 module first; T1 50 of 50 | Met | File order: 353 passed (166.5 s); T1 module first: 353 passed (168.5 s) |
| `lint-imports`; both `alembic check`; T7 | Met | `Contracts: 3 kept, 0 broken.`; `test_models_match_migrations` 2 passed; T7 21 passed |
| Collected count at least 325 plus the new tests, minus the replaced M05 test | Met | 353 collected (325 minus 1 plus 29) |

Verdict tally: 8 met, 0 not met, 0 not verified.

Smoke run on an isolated compose project (`jiris-m07-check`, removed with
`down -v`): a visit with rate 9999999999.99 for 2 h, started, then
`/complete` 202; after 4 s the visit is In Progress, not pending, with
`completion_failure_reason` "DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error)
numeric field overflow"; no billing record; `billing.inbox` row `failed`
with `attempts = 0`; one BillingFailed `permanent`; parking queues empty;
the second `/complete` 202; `docker compose stop worker` exit 0.

Branch and count after each commit: `git branch --show-current` returned
`feature/m07-failure-paths` after every commit. Collected totals: 325
after `e3f8e3d`; not collectable in full after `b4ebb3d` and `40584b4`
(the classification module imports `classify`, added in `2bc09b0`); 353
after `2bc09b0` and in every full run.

## IG-6. Documentation

- `docs/TDD.md` §8.2: pseudo-code with the four error classes, the
  refined D15 (DL-35, DL-36), the 23505 exception, permanent failures
  acknowledged, the interim DL-25 (b) note replaced; checked against the
  code at completion.
- `docs/build-spec/contract.md`: §1 D15 row; §3 Retries; §5; §6 DL-35,
  DL-36; §7a resolved OQ-22, OQ-23; §7b TD-7.
- `docs/build-spec/index.md` section b: M07 8 hours, total 64.
- `module-07-failure-paths.md`: amended at HG-1; criteria ticked from
  this report.
- `docs/technical-debt.md`: TD-7.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| `BillingFailed.reason`, and so the visit's `completion_failure_reason` shown by the API, carries the exception type and its first message line, for example "DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error) numeric field overflow" | Library internals reach API clients; the text is not a stable business reason | TD-7, target M08: map the error classes to stable reasons (for example "amount out of range", "transient errors exhausted") and keep the raw text in `billing.inbox.last_error` only |
| A crash after the BillingFailed COMMIT and before the reject or ack: the redelivery finds `failed` and is acknowledged as a duplicate, so an exhausted message is not parked | The message is not in `billing.parking`, although BillingFailed was sent | Accepted: the outcome reached the visit; the inbox row keeps the history |
| A permanent failure is acknowledged, not parked (TDD §8.2) | No copy of the message in a parking queue | The inbox row keeps `last_error`; the visit keeps the reason |
| TD-6 applies to Billing as well | A non-connection `OperationalError` is retried for ever | TD-6, target M08 |
| A message parked after 5 transient failures has no replay tool | An operator must republish it by hand | Not in this release (module-07 section 6) |

Registers: TD-7 opened and mirrored in contract section 7b. No backlog
entry.
