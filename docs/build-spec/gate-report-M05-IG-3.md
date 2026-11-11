# Gate report M05, IG-3 (planning), Billing consumer, happy path

Module: `module-05-billing-consumer.md` · Date: 2026-11-11 · Branch:
`feature/m05-billing-consumer`, created from `build/increments` at
`fa5dec6` (M04 merged) · Baseline: 217 collected, 167 passed, 50 xfailed.

HG-1 given by Sasha on 2026-11-11: OQ-14 yes (DL-24); OQ-15 (a) extended
to payloads that fail their event type's validation, (b) yes until M07
(DL-25); OQ-16 yes (DL-26); clean test state (DL-27); queue-reading tests
isolated from the long-lived worker in the M06 plan (DL-28). The sections
below are amended accordingly.

## IG-1. Scope and affected surfaces

In scope:

| Surface | Change |
|---|---|
| `app/contracts/__init__.py` | BillingRecordCreated payload and `BILLING_RECORD_CREATED` spec in `EVENTS` (OQ-16) |
| `app/billing/service.py` | `compute_amount()`; `process_visit_completed()`: inbox, record (R8), reply, one transaction |
| `app/billing/consumer.py` | FastStream subscriber on `INBOX_QUEUES["billing.inbox"]`, `AckPolicy.MANUAL`, ack after COMMIT, failures per OQ-15, one log line per consumed event |
| `app/billing/api.py` (new, OQ-14) | `GET /api/billing-records?visit_id=` |
| `app/main_api.py` | Second pool as `billing_app`; billing router |
| `app/main_worker.py` | Billing subscriber registered; broker started after the topology |
| `app/billing/models.py` | Unchanged columns; constants reused |
| `tests/unit/` | `test_billing_amount.py`, contract cases in `test_contracts.py`, `test_consumer_rule.py` (4.1.11), `test_main_api.py` (configuration test changed, OQ-14) |
| `tests/integration/` | `test_billing_service.py`, `test_billing_consumer.py`, `test_billing_api.py`; `test_worker.py` reworked (4.1.12); a consumer fixture that runs the subscriber in process against the session or a dedicated broker |
| `docs/TDD.md` | §4 (billing API file), §8.2 interim behaviour note (OQ-15) |
| `docs/build-spec/index.md` | Section d: `app/billing/api.py` |

Not touched: `app/visits` (the Visits consumer is M06),
`app/outbox` (the Billing relay already exists and routes the reply as
soon as its type is registered), migrations (tables exist since M02),
compose, Dockerfile, `.importlinter`.

Out of scope, binding: the Visits consumer and T1 (M06); BillingFailed,
the permanent class, the persisted counter, parking after 5 attempts, T4
and T5 (M07); purge and reconnection proof (M08).

## IG-2. Dependencies, risks, assumptions, edge cases

Dependencies:

- M04 complete and merged (`fa5dec6`). Met.
- No new package. FastStream 0.7.8, read from the installed sources:
  `broker.subscriber(queue, exchange=None, ..., ack_policy=...)`; when
  `ack_policy` is not given, the subscriber uses
  `AckPolicy.REJECT_ON_ERROR`, which rejects without requeue on any
  unhandled exception. With the inbox queue's dead-letter arguments that
  sends the VisitCompleted to `billing.parking` with no retry: a visit
  would stay pending for ever (against D6). The consumer therefore uses
  `AckPolicy.MANUAL` and settles each message itself. Without `exchange`,
  the subscriber consumes the queue and adds no binding.

Assumptions:

| ID | Assumption | Consequence if false |
|---|---|---|
| A1 | With `AckPolicy.MANUAL`, FastStream never acks, nacks or rejects on its own, also when the handler raises | A failure would settle the message before our code decides; checked by 4.1.9 |
| A2 | A FastStream subscriber started with the topology's `RabbitQueue` object redeclares the queue with identical arguments, so no `PRECONDITION_FAILED` | The worker would fail at start; checked by 4.1.7 and 4.1.12 on a broker where the topology was declared first |
| A3 | `INSERT ... ON CONFLICT (visit_id) WHERE status = 'Created' DO NOTHING` matches the partial unique index `ux_active_record` | A unique violation would abort the transaction; fallback is a savepoint around the INSERT |
| A4 | Under READ COMMITTED, the second of two concurrent inbox inserts for one `event_id` waits for the first transaction and then inserts nothing; its `SELECT ... FOR UPDATE` then reads `processed` | Two records or two replies; would reopen D6 (PRD §9 stop condition, T2) |

Risks:

| Risk | Mitigation |
|---|---|
| `billing.inbox` in the session broker holds the malformed `VisitCompleted` messages that M04 relay tests published (payload `{"n": ...}`) | DL-27: M04 tests purge the queues after each test and worker fixtures purge both inboxes before start; DL-25: anything left goes to `billing.parking` at once; tests filter by their own ids |
| From M05 the worker consumes `billing.inbox`, so any test that reads VisitCompleted from that queue while a worker runs loses the race | Only `test_worker.py` and T1 run a worker; `test_worker.py` asserts the billing record instead (4.1.12); T1's worker lives 30 s and stops before `test_topology.py` and `test_visits_api.py` run |
| From M06 the session `worker` fixture of T1 will be ready and live until the end of the session, consuming both inbox queues while `test_topology.py` and others read them | DL-28: the M06 plan isolates queue-reading tests on a dedicated vhost or broker, or stops the worker for them |
| The interim requeue of OQ-15 (b) loops a poison message every second until M07 | Accepted until M07; 4.1.9 runs on a dedicated broker so no loop reaches the session broker |
| Amount from `float` | `compute_amount()` takes `Decimal` and `datetime` only; the duration is `timedelta` in whole microseconds, converted with `Decimal(int)` |
| `GET /api/billing-records` in the API process widens the API's database access to `billing_app` | One pool per module role (D13); T7 still proves each role sees only its own schema; the API still reads neither `MIGRATIONS_DATABASE_URL` nor `RABBITMQ_URL` |
| BillingRecordCreated accumulates in `visits.inbox` until M06 | Durable queue, no consumer; tests filter by id; DL-27 purges it before each worker start |
| The M04 unknown type test used `BillingRecordCreated` for the Billing relay; it becomes a known type here, and the relay would publish its `{"n": 0}` payload | The test switches to a type that stays unknown (4.1.13) |

Edge cases covered by tests:

- Same envelope twice in sequence, and twice at the same time: one
  record, one reply (T2).
- Two attempts for one visit (R8): one record, two replies with the same
  record id.
- Half-up rounding at the cent; durations that are not whole hours.
- Malformed body: not JSON, JSON without the envelope fields, envelope
  of another event type or schema version, VisitCompleted with payload
  `{"n": 1}`, naive timestamps: parked once, never looping (DL-25).
- Transaction failure after the inbox insert: everything rolls back,
  including the inbox row, so the redelivery is processed as new.
- Ack never before COMMIT; no ack after ROLLBACK.
- `GET /api/billing-records` for a visit with none, without the
  parameter, with a malformed id.

## IG-3. Execution sequence (tests first)

1. After HG-1: commit `module-05`, this report, contract §5 and §7a
   (`docs:`), with TDD §4, §8.2 and index section d if OQ-14 and OQ-15
   are approved.
2. Tests (`test:` commit): 4.1.1 to 4.1.12, the reworked M04 worker test,
   the M03 configuration test change, the consumer fixtures. Red run
   recorded; the 217 baseline tests otherwise unchanged.
3. `app.contracts` BillingRecordCreated (`feat:`): 4.1.2 green.
4. `app/billing/service.py` (`feat:`): 4.1.1, 4.1.3 to 4.1.6 green.
5. `app/billing/consumer.py` (`feat:`): 4.1.7 to 4.1.9, 4.1.11 green.
6. `app/billing/api.py`, `app/main_api.py` (`feat:`): 4.1.10 green.
7. `app/main_worker.py` (`feat:`): 4.1.12 green; T1 still xfailed with
   `WorkerNotReady`.
8. Documentation check against the code (`docs:`).
9. Validation: clean clone; full suite; lint; both `alembic check`; T7;
   4.1.5 and 4.1.9 three times in a row; `docker compose up` smoke: a
   `/complete` produces a billing record and a reply in `visits.inbox`;
   branch and count after every commit.
10. `gate-report-M05-IG-7.md`, checkboxes, contract §5; stop for
    approval; merge per BS-3.

## Questions for HG-1 (contract section 7a)

Answered at HG-1; the answers are in the contract (section 7a, resolved,
and DL-24 to DL-28). The questions as asked:

| ID | Question | Agent's recommendation |
|---|---|---|
| OQ-14 | `GET /api/billing-records` in the API process with a `billing_app` pool and a new `app/billing/api.py`; M03 configuration test changed accordingly? | Yes |
| OQ-15 | Interim failures until M07: malformed → `billing.parking` at once; any other exception → ROLLBACK, ERROR, `nack` with requeue after 1 s, no counter? | Yes |
| OQ-16 | Only BillingRecordCreated in `app.contracts` now; BillingFailed with M06 or M07? | Yes |
