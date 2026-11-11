# Module 05, Billing consumer, happy path

Effort: 10 hours · Prerequisites: M01 to M04

## 1. Goal

Deliver the Billing consumer of TDD §8.2 on its success path: a
VisitCompleted from `billing.inbox` is de-duplicated through
`billing.inbox`, its amount is computed (D11), one active billing record
is created or found (R8), and BillingRecordCreated is written to
`billing.outbox`, all in one transaction, with the message acknowledged
only after COMMIT. It also delivers `GET /api/billing-records?visit_id=`
(TDD §6.1). It does not consume Billing replies in Visits (M06), emit
BillingFailed, count retries or park exhausted messages (M07).

## 2. Prerequisites

- M04 acceptance criteria pass; M04 merged into `build/increments`
  (`fa5dec6`).
- HG-1 on this document and `gate-report-M05-IG-3.md` given by Sasha on
  2026-11-11, with OQ-14 to OQ-16 answered (DL-24 to DL-26), clean test
  state (DL-27) and the M06 carry-over (DL-28).

## 3. Rule for every consumer (M05, M06)

Consumers take their queue objects only from `app/outbox/topology.py`
(`INBOX_QUEUES`). They construct no `RabbitQueue`, call no
`declare_queue` and pass no `exchange` to the subscriber, so they add no
binding and never declare a queue with different arguments (FastStream
adds `x-queue-type = classic`; a mismatch fails with
`PRECONDITION_FAILED`). The topology is declared by the worker at start
(DL-21). Task 3.1.11 holds this rule for `app.billing` and `app.visits`.

## 4. Tasks

4.1 Tests first (each seen failing before its code):
- 4.1.1 Unit, T8 amount half: `amount = rate × hours(end − start)` in
  Decimal from the exact duration in microseconds, 2 places, ROUND_HALF_UP:
  25.00 for 2 h gives 50.00; 10.00 for 1 h 20 min gives 13.33; 0.01 for 30
  min gives 0.01 (half up, not 0.00); 33.33 for 30 min gives 16.67; no
  float at any step.
- 4.1.2 Unit, contracts: BillingRecordCreated (`visit_id`,
  `completion_attempt_id`, `billing_record_id`, `amount`), money as a
  decimal string, floats refused; routing key `billing.record_created`
  registered; BillingFailed not registered (DL-26).
- 4.1.3 Integration, service: one VisitCompleted envelope gives, in one
  transaction, one `billing.billing_record` (Created, the amount of
  4.1.1), one `billing.outbox` row BillingRecordCreated whose payload
  carries the visit id, the attempt id, the record id and the amount, and
  one `billing.inbox` row `processed` with `processed_at` set.
- 4.1.4 Integration, T2 and the idempotency test: the same envelope
  processed twice in sequence gives one record, one reply and one inbox
  row; the second call reports a duplicate and changes nothing.
- 4.1.5 Integration, concurrent duplicate: the same envelope processed at
  the same time on two connections gives one record and one reply.
- 4.1.6 Integration, R8: two VisitCompleted with different event ids for
  one visit give one record and two replies, both with that record's id,
  each with its own `completion_attempt_id`.
- 4.1.7 Integration, through the broker: a VisitCompleted published on
  `jiris.events` is consumed from `billing.inbox`; the record exists; the
  message is acknowledged and not delivered again; one Billing relay pass
  puts BillingRecordCreated in `visits.inbox` with routing key
  `billing.record_created` and `message_id` = the reply's `event_id`.
- 4.1.8 Integration, malformed message (DL-25): a body that is not JSON,
  JSON without the envelope fields, an envelope of another event type or
  schema version, and a VisitCompleted envelope whose payload fails
  validation (`{"n": 1}`, naive timestamps) each go to `billing.parking`
  once, with `x-death` count 1 and reason `rejected`, are never seen in
  `billing.inbox` again, leave no inbox row, and the next good message is
  processed.
- 4.1.9 Integration, interim failure (DL-25; dedicated broker): a
  VisitCompleted whose amount overflows `numeric(12,2)` makes the
  transaction fail; no record, no reply, no inbox row; the message is
  delivered again (`redelivered`) no sooner than 1 s later; an ERROR line
  names the event.
- 4.1.10 Integration, `GET /api/billing-records?visit_id=` (DL-24): 200
  with a JSON array of `id`, `visit_id`, `amount` (decimal string),
  `status`, `created_at`; `[]` for a visit with no record; 422 without
  `visit_id` or with a malformed one.
- 4.1.11 Unit, rule of section 3: no source file under `app/billing` or
  `app/visits` contains `RabbitQueue(`, `declare_queue` or an `exchange=`
  argument to `subscriber`.
- 4.1.12 Integration, worker: `python -m app.main_worker` consumes a
  `/complete` event; the record is visible through
  `GET /api/billing-records` within 10 s and BillingRecordCreated reaches
  `visits.inbox`; one log line per consumed event with `visit_id`,
  `event_id`, `event_type`, outcome. The M04 worker test, which read the
  VisitCompleted from `billing.inbox`, now asserts this instead (the
  worker consumes that queue from M05). T1 stays `xfail` with
  `WorkerNotReady` (no consumer on `visits.inbox` yet).
- 4.1.13 Clean test state (DL-27): the M04 tests that publish or read
  messages purge `billing.inbox`, `visits.inbox`, `billing.parking` and
  `visits.parking` after each test; the `worker` and `relay_worker`
  fixtures purge both inbox queues before the worker starts. The M04
  unknown type test uses a Billing type that stays unknown
  (`BillingRecordCreated` becomes known in this module).
4.2 `app.contracts`: BillingRecordCreated and its `EventSpec`
(`billing.record_created`) in `EVENTS` (OQ-16).
4.3 `app/billing/service.py`: `compute_amount()`; `process_visit_completed(
session, envelope)` exactly as TDD §8.2 up to the reply: `INSERT INTO
billing.inbox ... ON CONFLICT (event_id) DO NOTHING`, `SELECT ... FOR
UPDATE`, `processed` → duplicate; `INSERT INTO billing.billing_record ...
ON CONFLICT (visit_id) WHERE status = 'Created' DO NOTHING RETURNING id`,
else the existing active record (R8); `INSERT INTO billing.outbox`
BillingRecordCreated; inbox `processed`, `processed_at = now()`.
4.4 `app/billing/consumer.py`: a FastStream subscriber on
`INBOX_QUEUES["billing.inbox"]` (section 3) with `AckPolicy.MANUAL`
(FastStream's default, `REJECT_ON_ERROR`, would park a VisitCompleted on
any exception, against D6); one transaction per message, `ack` after
COMMIT; failures as DL-25; one message at a time.
4.5 `app/billing/api.py` and `app/main_api.py` (DL-24): router for
`GET /api/billing-records`, pool as `billing_app`; the M03 configuration
test updated.
4.6 `app/main_worker.py`: the broker starts the Billing subscriber after
the topology is declared, with the `billing_app` pool.
4.7 TDD §4 and index section d (`app/billing/api.py`, DL-24) and TDD §8.2
(DL-25): updated at HG-1; checked against the code at completion (IG-6).

## 5. Acceptance criteria

- [x] Every test of task 4.1 passes.
- [x] T2: one VisitCompleted delivered twice gives one record and one
  reply (4.1.4, 4.1.5).
- [x] T8 amount half passes (4.1.1).
- [x] A consumed message is acknowledged only after COMMIT: 4.1.9 shows
  redelivery after a failed transaction, 4.1.7 shows no redelivery after
  success.
- [x] No source under `app/billing` or `app/visits` declares a queue or
  binds one (4.1.11).
- [x] `uv run lint-imports` reports 3 contracts kept; `alembic -n visits
  check` and `alembic -n billing check` pass; T7 passes.
- [x] T1 remains collected 50 times and reported xfailed with
  `WorkerNotReady`.
- [x] Collected test count is at least 217 plus the new tests.

Completion report: `gate-report-M05-IG-7.md`.

## 6. Out of scope

| Item | Destination |
|---|---|
| Visits consumer, reply handling, T1 green | M06 |
| BillingFailed, permanent error class, persisted retry counter, parking after 5 attempts, T4, T5 | M07 |
| Outbox purge, consumer reconnection proof, README | M08 |
| Reversal operation | Next release (FB-1) |

## 7. What comes next

M06 builds the Visits consumer on `visits.inbox`: it applies
BillingRecordCreated to the visit when the attempt id matches, and T1
turns green.
