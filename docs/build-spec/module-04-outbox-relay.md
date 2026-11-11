# Module 04, Outbox relay and broker topology

Effort: 8 hours · Prerequisites: M01, M02, M03

## 1. Goal

Deliver the RabbitMQ topology of TDD §7.1 and the polling outbox relay of
TDD §8.1, run by the worker process for both schemas, so that every
unpublished outbox row reaches its queue with a publisher confirm, without
loss when the broker is down and without a manual step after it returns.
It does not consume anything (M05, M06), define the Billing reply models
(M05, M06), purge published rows (M08), or prove consumer reconnection
(M08).

## 2. Prerequisites

- M03 acceptance criteria pass; M03 merged into `build/increments`
  (`65bb3f7`).
- HG-1 on this document and `gate-report-M04-IG-3.md` given by Sasha on
  2026-11-11, with OQ-9 to OQ-13 answered (DL-18 to DL-21) and the M03
  test adjustment of DL-22.

## 3. Tasks

3.1 Tests first (each seen failing before its code):
- 3.1.1 Unit: backoff delays start at the poll interval, double, and stop
  at 30 s (TDD §10); the message body built from an outbox row is the
  envelope of TDD §7 (`occurred_at` in UTC with `Z`); the routing key of
  `VisitCompleted` is `visits.visit_completed`; an unknown event type has
  no routing key; a schema name other than `visits` or `billing` is
  refused.
- 3.1.2 Integration, topology: `declare_topology()` runs twice without
  error; `jiris.events` (topic, durable), `jiris.dlx`, `billing.inbox`,
  `visits.inbox`, `billing.parking`, `visits.parking` exist and are
  durable; `billing.inbox` and `visits.inbox` carry
  `x-dead-letter-exchange = jiris.dlx` and `x-dead-letter-routing-key`
  set to their parking queue (DL-18); a
  message on `visits.visit_completed` reaches `billing.inbox`, one on
  `billing.record_created` and one on `billing.failed` reach
  `visits.inbox`; a message rejected without requeue from `billing.inbox`
  reaches `billing.parking`, and from `visits.inbox` reaches
  `visits.parking`, with the original routing key in `x-death`.
- 3.1.3 Integration, one row: after `/complete`, one relay pass publishes
  the row; the message in `billing.inbox` is persistent, has
  `message_id = event_id`, `content_type = application/json`, and a body
  that validates as `Envelope[VisitCompleted]` and equals the row; the
  row has `published_at` set; a second pass publishes nothing.
- 3.1.4 Integration, batch: 150 unpublished rows give passes of 100 and
  50; messages leave in `occurred_at` order within a pass.
- 3.1.5 Integration, `SKIP LOCKED`: two relays run concurrently over 40
  rows; every `event_id` is delivered exactly once and every row is
  published.
- 3.1.6 Integration, broker outage (dedicated RabbitMQ container with a
  fixed host port): the relay runs in the background; the broker is
  stopped; a `/complete` is accepted with 202; the row stays unpublished
  and its `attempts` stays 0; the relay task stays alive; the broker is
  started; the row is published and the message is in `billing.inbox`
  within 30 s, with no manual step (first half of T3). The test runs the
  relay with a 2 s backoff ceiling to stay short; the 30 s ceiling is
  held by 3.1.1.
- 3.1.7 Integration, unroutable (DL-20): on a broker with `jiris.events`
  declared and no queue bound, the publish is returned; the pass rolls
  back; the row stays unpublished, its `attempts` stays 0, and an ERROR
  line names the row; the row is still selected by the next pass.
- 3.1.8 Integration, unknown event type (DL-19): a row with an event type
  unknown to `app.contracts` stays unpublished, its `attempts` increases
  by 1 per pass with an ERROR line, and the other rows of the pass are
  published; after its fifth pass it is no longer selected. The same for
  the `billing` relay as `billing_app` (a `BillingRecordCreated` row,
  unknown until M05).
- 3.1.10 Integration, no blocking (DL-19): 100 rows of an unknown type,
  older than 3 good rows, fill the first passes; the good rows are
  published by the sixth pass; the 100 rows end with `attempts = 5`,
  unpublished, and a further pass leaves them untouched.
- 3.1.9 Integration, worker: `python -m app.main_worker` with the stack
  environment declares the topology, runs the relays for `visits` (as
  `visits_app`) and `billing` (as `billing_app`), publishes a `/complete`
  event into `billing.inbox` within 10 s, and exits 0 within 10 s of
  SIGTERM. T1 stays `xfail` with `WorkerNotReady`: the worker has no
  consumer yet.
3.2 `app.contracts`: exchange names `jiris.events` and `jiris.dlx`; the
event type to routing key registry (VisitCompleted only, DL-14); the UTC
timestamp formatter used by the relay.
3.3 `app/outbox/topology.py` (OQ-13): queue names, arguments, bindings
and `declare_topology(broker)`; parking routing as OQ-9.
3.4 `app/outbox/relay.py`: `OutboxRelay(schema, engine, broker, batch_size
= 100, poll_interval = 0.5, backoff_ceiling = 30.0)` with `run_once()`
and `run_forever()`, exactly the loop of TDD §8.1 as amended by DL-19 and
DL-20: one transaction per pass, `SELECT ... WHERE published_at IS NULL
AND attempts < 5 ORDER BY occurred_at LIMIT 100 FOR UPDATE SKIP LOCKED`;
unknown event types skipped and counted after the pass in a short
transaction; each other row published with `mandatory=True` and its
confirm awaited, then `UPDATE ... SET published_at = now()`; COMMIT;
sleep 500 ms after an empty pass. Broker unavailable, connection lost,
publish timeout or unroutable: ROLLBACK, `attempts` unchanged, back off
exponentially to 30 s, retry forever; unroutable also logs ERROR. One INFO
line per published event. The relay imports neither module.
3.5 `app/main_worker.py`: one FastStream `RabbitBroker` (robust
connection, publisher confirms, `on_return_raises` per OQ-12), topology at
start, two relays with one pool per role (D13), clean stop on SIGTERM and
SIGINT.
3.6 TDD §7.1 (DL-18) and §8.1 (DL-19, DL-20), index section d (DL-21):
updated at HG-1; checked against the code at completion (IG-6).
3.7 M03 tests (DL-22): `test_visits_api.py` checks that the visit's
outbox row exists, without `published_at IS NULL`.

## 4. Acceptance criteria

- [x] Every test of task 3.1 passes.
- [x] After a `/complete` and one relay pass, the message is in
  `billing.inbox` with the properties of 3.1.3, the row has
  `published_at` set, and a second pass publishes nothing.
- [x] 3.1.6 passes: the event is published after the broker restart with
  no manual step, and the relay task never exited.
- [x] 3.1.5 passes: no `event_id` is delivered twice by two concurrent
  relays.
- [x] A message rejected from either inbox reaches its parking queue.
- [x] 3.1.7, 3.1.8 and 3.1.10 pass: broker failures and unroutable
  messages never change `attempts`; unknown event types are excluded
  after five passes and do not block good events.
- [x] `uv run lint-imports` reports 3 contracts kept (`app.outbox` imports
  neither module); `alembic -n visits check` and `alembic -n billing
  check` pass; T7 passes.
- [x] T1 remains collected 50 times and reported xfailed with
  `WorkerNotReady` (DL-17).
- [x] Collected test count is at least 187 plus the new tests.

Completion report: `gate-report-M04-IG-7.md`.

## 5. Out of scope

| Item | Destination |
|---|---|
| Billing consumer, BillingRecordCreated and BillingFailed models | M05 |
| Visits consumer; T1 green | M06 |
| Retry counting, parking decisions and malformed messages in consumers | M07 |
| Outbox purge job; consumer reconnection proof; README | M08 |
| LISTEN/NOTIFY wake-up | Future release (FB-3) |
| Any schema or migration change | Not needed: `visits.outbox` and `billing.outbox` exist since M02 |

## 6. What comes next

M05 builds the Billing consumer on `billing.inbox`: inbox de-duplication,
amount calculation, the billing record and the BillingRecordCreated reply
written to `billing.outbox`, which this relay then publishes.
