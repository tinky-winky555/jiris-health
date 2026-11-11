# Gate report M04, IG-3 (planning), Outbox relay and broker topology

Module: `module-04-outbox-relay.md` · Date: 2026-11-11 · Branch:
`feature/m04-outbox-relay`, created from `build/increments` at `65bb3f7`
(M03 merged) · Baseline: 187 collected, 137 passed, 50 xfailed, at
`14349e4` (the rate precision test requested after M03 IG-7, committed on
this branch before the module starts).

HG-1 given by Sasha on 2026-11-11 with these decisions: OQ-9 option A
(DL-18); OQ-10 and OQ-11 replaced by error classes per cause (DL-19,
DL-20); OQ-12 yes (DL-20); OQ-13 yes (DL-21); M03 outbox checks by
presence of the row (DL-22). The sections below are amended accordingly.

## IG-1. Scope and affected surfaces

In scope:

| Surface | Change |
|---|---|
| `app/contracts/__init__.py` | `EXCHANGE = "jiris.events"`, `DEAD_LETTER_EXCHANGE = "jiris.dlx"`; registry from event type to `EventSpec` (VisitCompleted only, DL-14); public UTC timestamp formatter (today the private `_utc_z`) |
| `app/outbox/topology.py` (new, OQ-13) | Queue names `billing.inbox`, `visits.inbox`, `billing.parking`, `visits.parking`; queue arguments; bindings `visits.*` and `billing.*`; parking routing per OQ-9; `declare_topology(broker)`, idempotent |
| `app/outbox/relay.py` | `OutboxRelay` per TDD §8.1, generic over `visits` and `billing`; pure helpers for backoff delays, message body and routing key; schema name validated against `{"visits", "billing"}` because it is interpolated into SQL |
| `app/main_worker.py` | Broker, topology, two relays with one pool per role, signal handling |
| `tests/unit/test_outbox_relay.py` (new) | 3.1.1 |
| `tests/integration/test_topology.py`, `test_outbox_relay.py`, `test_worker.py` (new) | 3.1.2 to 3.1.9 |
| `tests/integration/conftest.py` | A broker fixture with topology declared; a dedicated function-scoped RabbitMQ container with a fixed host port for 3.1.6 and 3.1.7; a helper that drains a queue and filters by `message_id` |
| `docs/TDD.md` | §7.1 parking routing (OQ-9); §8.1 unknown types, `attempts`, unroutable messages (OQ-10 to OQ-12) |
| `docs/build-spec/index.md` | Section d: `app/outbox/topology.py` (OQ-13) |

Not touched: `app/visits`, `app/billing`, both migration chains (the
outbox tables exist since M02), `docker-compose.yml` (the `worker`
service already runs `python -m app.main_worker` with `RABBITMQ_URL` and
both database URLs), `Dockerfile`, `.importlinter`.

Out of scope, binding (module section 5): consumers (M05, M06), the
Billing reply models (M05, M06), consumer retries and parking decisions
(M07), the purge job and the consumer reconnection proof (M08),
LISTEN/NOTIFY (FB-3).

## IG-2. Dependencies, risks, assumptions, edge cases

Dependencies:

- M03 complete and merged (`65bb3f7`). Met.
- No new package: FastStream 0.7.8 and aio-pika 10.2.3 are in `uv.lock`.
  Read from the installed sources: `RabbitBroker` connects with
  `aio_pika.connect_robust`; channels default to
  `publisher_confirms=True`; `broker.publish()` takes `exchange`,
  `routing_key`, `mandatory` (default `True`), `persist`, `message_id`,
  `content_type` and `timeout`, and returns the confirmation frame; a
  returned message raises `aio_pika.exceptions.DeliveryError` only when
  the channel has `on_return_raises=True` (default `False`), hence OQ-12.

Assumptions:

| ID | Assumption | Consequence if false |
|---|---|---|
| A1 | `broker.publish()` returns only after the broker confirms, and raises on a negative confirm | The relay would mark unconfirmed rows published; fallback is the aio-pika channel used directly with `publisher_confirms=True` |
| A2 | With a robust connection, a publish during an outage either raises or blocks; the publish timeout turns a block into an error | Without the timeout, the relay would hang during an outage instead of backing off |

Spike after HG-1 (scratch script on a dedicated RabbitMQ 4.2 container,
not in the repository): `publish()` returned the confirm frame `Ack`;
the message arrived with the raw bytes, `content_type =
application/json`, `delivery_mode = 2`, the given `message_id` and no
extra headers; an unroutable `mandatory` publish raised
`aiormq.exceptions.PublishError`, a subclass of
`aio_pika.exceptions.DeliveryError`; with the broker stopped, `publish()`
raised `ConnectionClosed` (an `AMQPConnectionError`) at once, without
blocking; after the container started again, the robust connection
published again after 4.1 s. A1 and A2 hold; the relay classifies
`DeliveryError` as unroutable and every other publish error as broker
unavailable.
| A3 | `visits_app` and `billing_app` may `SELECT ... FOR UPDATE` and `UPDATE` their own outbox (M02 grants) | T7 already proves DML on both outbox tables |
| A4 | The broker keeps durable queues and persistent messages across a container stop and start | The outage test would lose the message; this would reopen D8 (PRD §9 stop condition) |

Risks:

| Risk | Mitigation |
|---|---|
| The relay holds row locks on up to 100 rows while it publishes | By design (TDD §8.1); `SKIP LOCKED` lets another relay take other rows; publish timeout bounds the hold |
| Crash after the confirm and before COMMIT publishes a row twice | By design: at-least-once; consumers de-duplicate by `event_id` from M05 |
| A negative confirm inside a pass rolls back rows already confirmed in the same pass, so they are published again | By design of the batch transaction (TDD §8.1); same de-duplication |
| The outage test needs the broker at the same address after restart, but testcontainers maps a random host port | Dedicated container with a fixed free host port; stopped and started through the Docker API, never removed between the two |
| The session broker accumulates messages in `billing.inbox`, since no consumer exists before M05, and relay passes in tests publish rows left by other tests | Every assertion filters by `message_id`; tests drain only what they need |
| Test order: relay passes mark rows of earlier tests published | M03 assertions read only rows of their own visit; their `published_at IS NULL` count runs in the same test, before any relay pass. Recorded as a watch item for M05 and M06, where a long-running worker in the session could publish rows between the write and the assertion |
| The worker process from T1's `worker` fixture now lives for 30 s and publishes rows while waiting for consumers | Accepted: it terminates the process before raising `WorkerNotReady`; filtered assertions are unaffected |
| `ORDER BY occurred_at` ties: rows written in one transaction share `now()` | Order within a tie is not guaranteed; no consumer relies on it (each event carries its attempt id) |

Edge cases covered by tests:

- Empty outbox: a pass publishes nothing and the relay sleeps 500 ms.
- Already published rows are never selected again.
- Exactly 100, 101 and 150 rows: the limit holds per pass.
- Two relays at once: no row twice.
- Broker down at start of a pass, and broker lost in the middle of a
  pass: ROLLBACK, backoff, recovery after restart.
- Broker that accepts the connection but does not route (no bound queue):
  ROLLBACK, backoff, ERROR line, `attempts` unchanged, row selected again
  (DL-20).
- Unknown event type (for example a Billing reply row before M05):
  `attempts + 1` per pass after the pass, excluded at 5 (DL-19); 100 such
  rows ahead of good rows delay them by at most five passes.
- `attempts` never changes for broker unavailability, lost connection,
  publish timeout or an unroutable message, so an outage of any length
  never excludes an event (D6).
- SIGTERM during a pass: the pass ends with COMMIT or ROLLBACK, the
  process exits 0, no row is marked published without a confirm.
- Topology declared twice (two workers, or a worker restart): no error,
  no argument conflict.

## IG-3. Execution sequence (tests first)

1. After HG-1: commit `module-04`, this report and contract §5 and §7a
   (`docs:`).
1b. M03 test adjustment (`test:` commit, DL-22): outbox row presence
   instead of `published_at IS NULL`; suite stays green.
2. Tests (`test:` commit): 3.1.1 to 3.1.10 and the conftest fixtures. Run
   the suite and record the red result: unit tests fail on import of the
   relay helpers; integration tests fail on `declare_topology` and
   `OutboxRelay`; the 187 tests of the baseline unchanged.
3. `app.contracts` additions (`feat:`): 3.1.1 routing key tests green.
4. `app/outbox/topology.py` (`feat:`): 3.1.2 green.
5. `app/outbox/relay.py` (`feat:`): 3.1.1, 3.1.3 to 3.1.8 green.
6. `app/main_worker.py` (`feat:`): 3.1.9 green; T1 still xfailed with
   `WorkerNotReady`.
7. Documentation: TDD §7.1 and §8.1 and index section d were updated at
   HG-1; check them against the code and correct any difference (`docs:`).
8. Validation: full suite from a clean clone; `lint-imports`; both
   `alembic check`; T7; outage test run three times in a row to check
   stability; `docker compose up` smoke run: a `/complete` reaches
   `billing.inbox` through the `worker` service; `git branch
   --show-current` and the collected count after every commit.
9. `gate-report-M04-IG-7.md`, module checkboxes, contract §5; stop for the
   developer's approval; then merge per BS-3.

## Questions for HG-1 (contract section 7a)

Answered at HG-1; the answers are in the contract (section 7a, resolved,
and DL-18 to DL-22). The questions as asked:

| ID | Question | Agent's recommendation |
|---|---|---|
| OQ-9 | HG-2: parking routing. A: `jiris.dlx` direct, `x-dead-letter-routing-key` per inbox queue, parking queues bound by name. B: `jiris.dlx` topic, parking queues bound to `visits.*` and `billing.*` | A |
| OQ-10 | Unknown event type in an outbox row: skip, keep unpublished, increment `attempts`, log, continue the pass? | Yes |
| OQ-11 | `attempts`: increment in a separate short transaction after the ROLLBACK of a failed pass? | Yes |
| OQ-12 | `mandatory=True` with `on_return_raises=True`, so an unroutable message is a failure? | Yes |
| OQ-13 | New file `app/outbox/topology.py`; exchange names and routing keys in `app.contracts`; index section d updated? | Yes |
