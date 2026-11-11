# Module 06, Visits consumer; T1 green

Effort: 8 hours · Prerequisites: M01 to M05

## 1. Goal

Deliver the Visits consumer of TDD §6.4 on `visits.inbox`: each Billing
reply is de-duplicated through `visits.inbox`, applied only when its
`completion_attempt_id` matches the visit's current attempt (R1), and
then sets the visit to Completed (BillingRecordCreated, R3) or resets the
pending completion (BillingFailed, D16), in one transaction, acknowledged
after COMMIT, with the failure classes of DL-31. With it the full flow
runs end to end: T1 turns green and its `xfail` marker is removed, T3 and
T6 pass. It does not make Billing emit BillingFailed or classify Billing's
errors (M07).

## 2. Prerequisites

- M05 acceptance criteria pass; M05 merged into `build/increments`
  (`755a547`).
- HG-1 on this document and `gate-report-M06-IG-3.md` given by Sasha on
  2026-11-11, with OQ-17 to OQ-21 answered (DL-29 to DL-33).

## 3. Rules carried into this module

- Consumers take their queue objects only from `app/outbox/topology.py`
  (module-05 section 3); 4.1.11 of M05 covers `app/visits` as well.
- DL-28, as OQ-20: tests that read queues directly, or assert a visit's
  state right after a command, never run while a worker is alive. A
  worker lives only inside the test modules that need it.

## 4. Tasks

4.1 Tests first (each seen failing before its code):
- 4.1.1 Unit, contracts (OQ-17): BillingFailed (`visit_id`,
  `completion_attempt_id`, `reason`, `error_class` in
  `transient_exhausted`, `permanent`), routing key `billing.failed`
  registered.
- 4.1.2 Unit, parsing: a `visits.inbox` body is accepted only as a
  BillingRecordCreated or BillingFailed envelope of schema version 1 with
  a valid payload; not JSON, missing envelope fields, another event type
  (for example VisitCompleted), another version, an invalid payload
  (`{"n": 1}`, a float amount, an unknown `error_class`) are malformed.
- 4.1.3 Integration, service, BillingRecordCreated: a pending visit whose
  attempt matches becomes Completed; `completion_pending` false;
  `completion_requested_at` kept (D23); one `visits.inbox` row.
- 4.1.4 Integration, service, idempotency: the same reply twice (same
  `event_id`) changes nothing the second time and reports a duplicate.
- 4.1.5 Integration, service, R3: a second BillingRecordCreated for the
  same attempt (another `event_id`) on a Completed visit is a no-op.
- 4.1.6 Integration, service, T6 (R1): after attempt A is reset and
  attempt B accepted, a reply for A (either type) is ignored; the visit
  stays pending on B; the reply's inbox row is written, so it is not
  processed again; then the reply for B completes the visit.
- 4.1.7 Integration, service, BillingFailed (OQ-17; FR8, D16):
  `completion_requested_at` reset to NULL, `completion_failure_reason` =
  the payload's `reason`, status unchanged; `/complete` is accepted again
  and starts a new attempt.
- 4.1.8 Integration, service, concurrency: two different replies for one
  visit at the same time are serialised by `SELECT ... FOR UPDATE`; the
  final state is the one of TDD §6.4 for that order, and no reply is lost.
- 4.1.9 Integration, through the broker (in-process consumer, no
  worker): a reply published on `billing.record_created` is consumed from
  `visits.inbox`, applied and acknowledged once; one log line per
  consumed event with `visit_id`, `event_id`, `event_type`, outcome.
- 4.1.10 Integration, malformed and unknown visit (DL-30, DL-31): each
  malformed case of 4.1.2, and a reply for a visit that does not exist
  (with an ERROR line), reach `visits.parking` once (`x-death` count 1,
  reason `rejected`), never loop, and the next good reply is processed.
- 4.1.11 Integration, database unavailable (DL-31; dedicated broker): a
  consumer whose session factory points at a closed port requeues the
  reply with growing delays (0.5 s, then 1 s), never parks it, and writes
  nothing; after the consumer stops, the reply is still in `visits.inbox`.
- 4.1.16 Integration, stable failure (DL-31): a reply on which the
  handler always fails (a trigger on `visits.visit`, created by
  `jiris_migrator` for the test visit only, raises) is delivered 5 times;
  `visits.inbox` holds `attempts = 5`, `last_error` with the trigger's
  message and `processed_at` NULL; the fifth delivery goes to
  `visits.parking` with an ERROR line; the next normal reply is processed.
  The trigger is dropped after the test.
- 4.1.12 T1 (PRD §8): the `xfail(strict=True, raises=WorkerNotReady)`
  marker stays until the worker commit; the first T1 run after that
  commit must fail as `XPASS(strict)` 50 of 50, the recorded proof that
  the full flow works and the marker is obsolete; a separate `test:`
  commit then removes the marker, and T1 passes 50 of 50 runs: one 202,
  one 409, one VisitCompleted in the outbox, the visit Completed with
  exactly one billing record. No `xfail` remains in the suite.
- 4.1.13 T3 (PRD §8; NFR1, NFR4, NFR5): a worker process on a dedicated
  RabbitMQ container with a fixed host port; once both inbox queues have
  a consumer, the broker is stopped; `/complete` returns 202; the event
  waits in `visits.outbox` and the visit stays pending; the broker is
  started; the visit becomes Completed with one billing record within
  60 s, with no manual step and no worker restart.
- 4.1.14 Worker test (M04, M05): reworked for a worker that consumes both
  inbox queues: a `/complete` ends Completed with one record through
  `GET /api/visits/{id}` within 10 s; the worker exits 0 on SIGTERM.
- 4.1.15 Isolation (OQ-20): the `worker` fixture is module scoped; the
  modules `test_topology.py`, `test_outbox_relay.py`,
  `test_billing_consumer.py`, `test_visits_consumer.py`,
  `test_visits_api.py` and `test_rate_precision.py` start with a guard
  that fails when `billing.inbox` or `visits.inbox` has a consumer they
  did not start; the full suite passes in file order and with the T1
  module run first (`pytest tests/integration/test_t1_concurrent_complete.py
  tests/integration`).
4.2 `app.contracts`: BillingFailed and `BILLING_FAILED` (`billing.failed`)
in `EVENTS` (OQ-17).
4.3 `app/outbox/consumer.py` (OQ-21): the shared consumer mechanics;
`app/billing/consumer.py` moved onto it with no change of behaviour (the
M05 tests stay green unchanged).
4.4 `app/visits/service.py`: `apply_billing_reply(session, envelope)` as
TDD §6.4 amended by DL-31: inbox insert `ON CONFLICT (event_id) DO
NOTHING`, then `SELECT processed_at ... FOR UPDATE`, set means duplicate;
visit `FOR UPDATE`; absent visit → unknown (DL-30); attempt mismatch →
ignored (R1); BillingRecordCreated → Completed unless already Completed
(R3); BillingFailed → reset (D16); `processed_at = now()`.
4.4a Migration `visits_0002` and `app/visits/models.py` (DL-31):
`visits.inbox.attempts` int not null default 0, `last_error` text null,
`processed_at` nullable without a default; downgrade restores the M02
shape; `alembic -n visits check` clean; T7 unchanged.
4.5 `app/visits/consumer.py`: subscriber on
`INBOX_QUEUES["visits.inbox"]` through `app/outbox/consumer.py`,
`visits_app` sessions, failures as DL-31.
4.6 `app/main_worker.py`: the Visits consumer registered; the worker is
then ready by the TDD §11 rule (a consumer on both inbox queues).
4.7 TDD §4, §5.1 and §6.4, index section d, contract §3 Idempotency and
Retries: updated at HG-1; checked against the code at completion (IG-6).
The M05 test `test_billing_failed_is_not_registered_yet` is replaced by
its opposite (DL-29); every other M05 test passes unchanged (DL-33).

## 5. Acceptance criteria

- [ ] Every test of task 4.1 passes.
- [ ] T1 passes 50 of 50 runs with no `xfail` marker left in the suite.
- [ ] T3 passes: Completed with one record after the broker restart, no
  manual step, no worker restart.
- [ ] T6 passes: a reply with an old attempt id is ignored.
- [ ] 4.1.11 and 4.1.16 pass: a database outage never parks a reply; a
  stable failure parks it after 5 counted attempts and does not block the
  next reply.
- [ ] `alembic -n visits downgrade -1` then `upgrade head` succeeds on a
  throwaway database.
- [ ] The idempotency test of the Visits consumer passes (4.1.4).
- [ ] The suite passes in file order and with the T1 module first; the
  isolation guard of 4.1.15 never fires.
- [ ] `uv run lint-imports` reports 3 contracts kept; both `alembic
  check` pass; T7 passes.
- [ ] Collected test count is at least 276 plus the new tests.

## 6. Out of scope

| Item | Destination |
|---|---|
| Billing emits BillingFailed; permanent class; persisted counter; parking after 5 attempts; T4, T5 | M07 |
| Outbox purge; README; release | M08 |
| Reversal operation | Next release (FB-1) |

## 7. What comes next

M07 adds the failure paths of TDD §8.2: error classification, the
persisted attempt counter, BillingFailed after a permanent error or the
fifth transient one, and parking of exhausted messages (T4, T5).
