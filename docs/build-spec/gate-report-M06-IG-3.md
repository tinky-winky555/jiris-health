# Gate report M06, IG-3 (planning), Visits consumer; T1 green

Module: `module-06-visits-consumer.md` · Date: 2026-11-11 · Branch:
`feature/m06-visits-consumer`, created from `build/increments` at
`755a547` (M05 merged) · Baseline: 276 collected, 226 passed, 50 xfailed
(T1).

HG-1 given by Sasha on 2026-11-11: OQ-17 yes, the Visits side of
BillingFailed moves from M07 to M06 (DL-29); OQ-18 park with ERROR
(DL-30); OQ-19 replaced by failure classes as in the relay, with a counter
in `visits.inbox` and migration `visits_0002` (DL-31); OQ-20 yes (DL-32);
OQ-21 yes, M05 tests unchanged (DL-33). Consequence taken by the agent and
recorded in DL-31: `visits.inbox.processed_at` becomes nullable and is
the processed marker, because a failing reply now has an inbox row before
it is processed.

## IG-1. Scope and affected surfaces

In scope:

| Surface | Change |
|---|---|
| `app/contracts/__init__.py` | BillingFailed and `BILLING_FAILED` (`billing.failed`) in `EVENTS` (OQ-17) |
| `app/outbox/consumer.py` (new, OQ-21) | Shared consumer mechanics: subscription on a topology queue with `AckPolicy.MANUAL`, raw body decoder, prefetch 10; settle rules (malformed or unknown → reject without requeue; success → ack after COMMIT; other exception → ERROR, 1 s, nack with requeue); one log line per consumed message |
| `app/billing/consumer.py` | Moved onto `app/outbox/consumer.py`; behaviour unchanged |
| `app/visits/service.py` | `apply_billing_reply()` per TDD §6.4 as amended (DL-31) |
| `app/visits/models.py`, `app/visits/migrations/versions/0002_*.py` | `visits.inbox`: `attempts`, `last_error`, `processed_at` nullable (DL-31) |
| `app/visits/consumer.py` | Parsing of the two reply types; subscriber on `INBOX_QUEUES["visits.inbox"]` |
| `app/main_worker.py` | Visits consumer registered with `visits_app` sessions |
| `tests/unit/` | BillingFailed contract cases; `test_visits_parse.py` |
| `tests/integration/` | `test_visits_reply_service.py`, `test_visits_consumer.py`, `test_t3_broker_outage.py` (new); `test_t1_concurrent_complete.py` (marker removed after the XPASS proof); `test_worker.py` reworked; `conftest.py`: module-scoped `worker`, a `visits_consumer` fixture, the isolation guard |
| `docs/TDD.md` | §4 (`app/outbox/consumer.py`), §6.4 (unknown visit, failure policy) |
| `docs/build-spec/index.md` | Section d: `app/outbox/consumer.py` |

Not touched: the billing chain, the relay, the topology, compose, Dockerfile, `.importlinter` (`app.outbox` still imports
neither module; the modules import `app.outbox`).

Out of scope, binding: Billing emitting BillingFailed, the permanent
class, the persisted counter, parking after 5 attempts, T4 and T5 (M07);
purge, README, release (M08).

## IG-2. Dependencies, risks, assumptions, edge cases

Dependencies:

- M05 complete and merged (`755a547`). Met.
- No new package. The FastStream mechanics used by M05 (manual
  acknowledgement, raw decoder, topology queue objects) are proven by the
  M05 tests and carry over through OQ-21.

Assumptions:

| ID | Assumption | Consequence if false |
|---|---|---|
| A1 | After a broker restart, the robust connection restores the FastStream subscribers as well as the publishing channel (the M04 spike proved publishing only) | T3 would stay pending after the restart; fallback is a supervisor in the worker that restarts the broker object after a connection loss |
| A2 | The pipeline of one completion (relay poll 500 ms, two hops, two consumers) ends well inside the 10 s polling timeout of T1 (D28) | T1 would time out under load; 50 runs give the evidence |
| A3 | `SELECT ... FOR UPDATE` on the visit serialises two replies, and the conditional UPDATE of `/complete` (TDD §6.2) waits on the same row lock | A reply and a new `/complete` could interleave; 4.1.8 and T1 check it |

Risks:

| Risk | Mitigation |
|---|---|
| A live worker shares the test database: its relays publish every unpublished outbox row and its Visits consumer completes visits, so an API test asserting "pending" or "409 completion_pending" right after `/complete` could see Completed instead. A vhost would not prevent this | OQ-20: isolation by time; the `worker` fixture is module scoped (T1 module only); T3 and the worker test start their own; a guard at the start of every sensitive module fails loudly when an inbox queue has a consumer |
| Starting the T1 worker publishes and processes every leftover outbox row of earlier tests | Harmless: those tests have finished; the M04 garbage rows are already flushed and purged (DL-27); malformed leftovers are parked |
| T1 runs 50 complete flows; a slow run hits the 10 s timeout | A2; the timeout comes from D28 and is not raised; a failure would be reported, not retried |
| T3 depends on aio-pika restoring consumers (A1) and on the relay backoff (ceiling 30 s) | Timeout 60 s: 30 s backoff, 5 s reconnect interval, pipeline; recorded in the report with the measured time |
| Moving `app/billing/consumer.py` onto the shared helper (OQ-21) could change M05 behaviour | The M05 consumer tests, unchanged, must stay green; the commit carries no behaviour change |
| A reply for attempt A after a reset keeps `completion_attempt_id = A` on the visit (TDD §6.4 step 4 resets only `completion_requested_at`), so a late BillingRecordCreated for A would still match until a new `/complete` sets B | As TDD; a BillingRecordCreated for A means a record exists for that visit, so Completed is the right outcome; recorded as an edge case in 4.1.6 |

Edge cases covered by tests:

- Reply for the current attempt: Completed or reset.
- Same reply twice: duplicate, no change (idempotency test).
- Second BillingRecordCreated for a Completed visit: no-op (R3).
- Reply for an older attempt: ignored, inbox row written (T6, R1).
- BillingFailed then `/complete`: a new attempt; the old attempt's late
  reply ignored.
- Reply for a visit that does not exist: parked (OQ-18).
- Malformed body or payload, VisitCompleted on `visits.inbox`, float
  amount, unknown `error_class`: parked once (OQ-19).
- Transaction failure: requeued after 1 s, nothing written (OQ-19).
- Two replies at once for one visit: serialised.
- Broker down during `/complete` and back: Completed, no manual step (T3).

## IG-3. Execution sequence (tests first)

1. After HG-1: commit `module-06`, this report, contract §5 and §7a, TDD
   §4 and §6.4, index section d (`docs:`).
2. Isolation first (`test:` commit): module-scoped `worker`, the guard in
   the sensitive modules; suite stays at 276 collected, 226 passed, 50
   xfailed.
3. Tests (`test:` commit): 4.1.1 to 4.1.11, 4.1.13, 4.1.14; red run
   recorded; T1 still xfailed.
4. Migration `visits_0002` and the model (`feat:`): `alembic check`
   clean; T7 green.
4a. `app.contracts` BillingFailed (`feat:`).
5. `app/outbox/consumer.py` and `app/billing/consumer.py` on it
   (`feat:`): M05 tests unchanged and green.
6. `app/visits/service.py` (`feat:`): 4.1.3 to 4.1.8 green.
7. `app/visits/consumer.py` (`feat:`): 4.1.9 to 4.1.11 green.
8. `app/main_worker.py` (`feat:`): 4.1.13 and 4.1.14 green; T1 run once
   and recorded as `XPASS(strict)` failures, 50 of 50.
9. T1 marker removed (`test:`): T1 50 of 50 passed; `grep -rn xfail
   tests` empty.
10. Documentation check against the code (`docs:`).
11. Validation: clean clone; full suite in file order and with the T1
    module first; T1 module and T3 three times each; lint; both `alembic
    check`; T7; `docker compose up` smoke: `/complete` ends Completed with
    one record; branch and count after every commit.
12. `gate-report-M06-IG-7.md`, checkboxes, contract §5; stop for approval;
    merge per BS-3.

## Questions for HG-1 (contract section 7a)

Answered at HG-1; the answers are in the contract (section 7a, resolved,
and DL-29 to DL-33). The questions as asked:

| ID | Question | Agent's recommendation |
|---|---|---|
| OQ-17 | BillingFailed model and Visits handling in M06; Billing emits it from M07? | Yes |
| OQ-18 | Reply for an unknown visit: park with ERROR, or ack with WARNING? | Park |
| OQ-19 | HG-2: Visits consumer failure policy as a permanent rule: malformed → `visits.parking`; other → requeue after 1 s, no limit? | Yes |
| OQ-20 | DL-28 by time: module-scoped worker, own workers for T3 and the worker test, a guard in sensitive modules; no vhost? | Yes |
| OQ-21 | Shared consumer mechanics in `app/outbox/consumer.py`, Billing moved onto it? | Yes |
