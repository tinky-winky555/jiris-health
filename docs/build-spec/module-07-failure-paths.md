# Module 07, Failure paths in Billing

Effort: 8 hours (reduced from 10: the Visits side of BillingFailed was
delivered in M06, DL-29) · Prerequisites: M01 to M06

## 1. Goal

Replace the interim failure rule of the Billing consumer (DL-25 b) with
the failure path of TDD §8.2 and D15: errors are classified; a permanent
error emits BillingFailed `permanent` at once; a transient or unclassified
error is counted in `billing.inbox` and retried, and the fifth failure
emits BillingFailed `transient_exhausted` and parks the message; the
counter survives a worker restart. With the Visits side already in place
(M06), T4 and T5 pass end to end. It does not change the Visits consumer,
the relay or the schema.

## 2. Prerequisites

- M06 acceptance criteria pass; M06 merged into `build/increments`
  (`0459df5`).
- HG-1 on this document and `gate-report-M07-IG-3.md` given by Sasha on
  2026-11-11, with OQ-22 and OQ-23 answered (DL-35, DL-36).

## 3. Already delivered, not repeated here

- BillingFailed contract and its handling by the Visits consumer: reset,
  reason stored, `/complete` accepted again, old attempts ignored, no-op
  with a WARNING for a Completed visit (M06, DL-29, DL-34).
- Malformed VisitCompleted to `billing.parking` at once (M05, DL-25 a).
- The `billing.inbox` columns `status`, `attempts`, `last_error`,
  `processed_at` (M02).

## 4. Tasks

4.1 Tests first (each seen failing before its code):
- 4.1.1 Unit, permanent validation: `compute_amount` or the service
  refuses a VisitCompleted with `end_date_time <= start_date_time` or
  `rate <= 0` with `PermanentError`.
- 4.1.2 Unit, classification (OQ-22, OQ-23): database unavailable
  (as `is_database_unavailable`) → `unavailable`; `PermanentError`,
  SQLSTATE class 22 (for example numeric overflow) and class 23 except
  23505 → `permanent`; 23505 `unique_violation` and everything else,
  including a `RAISE EXCEPTION` (P0001), a deadlock (40P01) and a
  serialisation failure (40001) → `transient` (DL-36).
- 4.1.3 Integration, service, permanent: a short transaction after the
  ROLLBACK sets the inbox row `failed` with `last_error`, writes no
  record, and writes one BillingFailed (`permanent`, `reason` from the
  error) to `billing.outbox`; a second delivery is a duplicate.
- 4.1.4 Integration, service, counted transient: each call adds 1 to
  `attempts` and stores `last_error`; at 5 the row becomes `failed` and
  one BillingFailed (`transient_exhausted`) is written; never a record.
- 4.1.5 Integration, consumer, permanent (crafted VisitCompleted with
  `end <= start`): BillingFailed `permanent` in `billing.outbox`, inbox
  `failed`, the message acknowledged once, not parked, not redelivered.
- 4.1.6 Integration, consumer, stable transient (a trigger on
  `billing.billing_record`, created by `jiris_migrator` for the test
  visit, raises P0001): outcomes `requeued` four times then `parked`;
  inbox `attempts = 5`, `failed`, `last_error` with the trigger message;
  one BillingFailed `transient_exhausted`; the message in
  `billing.parking`; the next VisitCompleted processed. Trigger dropped
  after the test.
- 4.1.7 Integration, consumer, database unavailable (OQ-22; dedicated
  broker, closed database port): requeued with growing delays, never
  parked, nothing counted; the message still in `billing.inbox` after the
  consumer stops.
- 4.1.8 T4 (PRD §8; FR7, FR8), end to end with a worker process: a visit
  In Progress with rate 9999999999.99 for 2 hours; `/complete` 202; within
  10 s the visit is In Progress again, `completion_pending` false,
  `completion_failure_reason` set; no billing record; BillingFailed
  `permanent` was published; `/complete` is accepted again (202, new
  attempt).
- 4.1.9 T5 (PRD §8; FR7, D15), end to end: a worker process; the trigger
  of 4.1.6 on the visit; `/complete` 202; once `billing.inbox.attempts`
  reaches 2, the worker is stopped with SIGTERM and a new worker started;
  the counter continues from 2 (it survived the restart); after the fifth
  attempt the visit is reset with BillingFailed `transient_exhausted`, the
  inbox row is `failed` with `attempts = 5`, and the message is in
  `billing.parking`. After the trigger is dropped, `/complete` ends
  Completed with one record.
- 4.1.10 M05 test 4.1.9 (overflow requeued every second, interim) is
  replaced by 4.1.5 and 4.1.8: the overflow is now permanent (DL-36).
- 4.1.11 Integration, concurrent duplicate delivery (DL-36): two
  consumers run at once and the same VisitCompleted (same `event_id`) is
  delivered to each; exactly one billing record and one
  BillingRecordCreated, and no BillingFailed in `billing.outbox`.
4.2 `app/billing/service.py`: `PermanentError`; payload validation
before any write; `record_permanent_failure()` and `count_transient_failure()`
in their own short transactions: inbox `failed`, `last_error`,
`processed_at`; BillingFailed via `app.contracts` in `billing.outbox`.
4.3 `app/billing/consumer.py`: `classify()` as 4.1.2; outcomes: permanent
→ short transaction, ack, ERROR line; transient below 5 → requeue after
1 s; transient at 5 → short transaction, reject to `billing.parking`, ERROR
line; unavailable → backoff 0.5 s doubling to 30 s, unlimited; a failure
of the short transaction itself is classified again.
4.4 TDD §8.2 (DL-35, DL-36; the interim note of DL-25 b replaced),
contract §1 D15 row and §3 Retries: updated at HG-1; checked against the
code at completion (IG-6).

## 5. Acceptance criteria

- [x] Every test of task 4.1 passes.
- [x] T4 passes end to end: visit back to its source status with
  `completion_failure_reason`, and `/complete` accepted again.
- [x] T5 passes end to end: the counter survives a worker restart and
  BillingFailed `transient_exhausted` follows the fifth attempt.
- [x] A permanent error is never retried; a database outage is never
  counted; no failure ever creates a billing record.
- [x] 4.1.11 passes: a concurrent duplicate delivery gives one record and
  no BillingFailed.
- [x] The suite passes in file order and with the T1 module first; T1
  50 of 50.
- [x] `uv run lint-imports` reports 3 contracts kept; both `alembic
  check` pass; T7 passes.
- [x] Collected test count is at least 325 plus the new tests, minus the
  replaced M05 test.

Completion report: `gate-report-M07-IG-7.md`.

## 6. Out of scope

| Item | Destination |
|---|---|
| Outbox purge, README, release, TD-1 to TD-4 and TD-6 | M08 |
| Replay tooling for parked messages | Not in this release |
| Reversal operation | Next release (FB-1) |

## 7. What comes next

M08 closes the delivery: outbox purge job (R5, D25), the remaining
technical debt, the README, and the merge of `build/increments` into
`main` under HG-3.
