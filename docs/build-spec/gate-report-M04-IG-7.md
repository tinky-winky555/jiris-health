# Gate report M04, IG-7 (completion), Outbox relay and broker topology

Module: `module-04-outbox-relay.md` · Date: 2026-11-11 · Branch:
`feature/m04-outbox-relay` (from `build/increments` at `65bb3f7`) ·
Planning report: `gate-report-M04-IG-3.md`, approved with HG-1 on
2026-11-11 (DL-18 to DL-22).

## Commits on the branch

| Commit | Content |
|---|---|
| `14349e4` | test: rate precision for JSON strings and numbers (developer request after M03 IG-7, before the module) |
| `c7cded5` | docs: HG-1 record; TDD §7.1 and §8.1, index section d, module-04, IG-3, contract DL-18 to DL-22 |
| `af581c1` | test: M03 outbox checks by row presence (DL-22) |
| `dc00d55` | test: M04 tests, committed red |
| `2c13824` | feat: exchange names, routing key registry, `format_timestamp` in `app.contracts` |
| `67d6cc5` | feat: `app/outbox/topology.py` |
| `435267d` | test: unique module name for the relay unit tests; explicit fixtures in the unknown type test (two test defects) |
| `e7425b7` | feat: `app/outbox/relay.py` |
| `b8c96ad` | test: the worker test waits for the topology (test defect) |
| `f46f791` | feat: `app/main_worker.py` |
| `d1fea72` | chore: `PublishError` taken from `aio_pika.exceptions` |

## Red runs (tests first)

| After | Result |
|---|---|
| `af581c1`, M03 adjustment | 187 collected; `test_visits_api.py` 85 passed |
| `dc00d55`, M04 tests | 137 passed, 50 xfailed, 1 failed, 9 errors: `tests/unit/test_outbox_relay.py` and `tests/integration/test_outbox_relay.py` not collectable (`ImportError` on `DEAD_LETTER_EXCHANGE` and `format_timestamp` in `app.contracts`); 7 topology tests at setup (`ModuleNotFoundError: app.outbox.topology`); the worker test failed, no message reached `billing.inbox` from the M01 stub |
| `67d6cc5`, topology | `test_topology.py` 7 passed |
| `e7425b7`, relay | First run: a collection clash between `tests/unit/test_outbox_relay.py` and `tests/integration/test_outbox_relay.py` (same base name, no package), fixed by renaming the unit file to `test_relay_helpers.py`; then 20 passed, 2 failed in the unknown type test (`request.getfixturevalue` of an async fixture inside the running loop), fixed with explicit fixtures; then 22 passed |
| `f46f791`, worker | Full suite 167 passed, 50 xfailed; the worker test run alone failed with `NOT_FOUND - no queue 'billing.inbox'`, because it read the queue before the worker declared it; fixed in `b8c96ad` by waiting for the `topology declared` line; then passed alone and in the suite |

## IG-4. Implementation consistent with the approved scope

- `app.contracts`: `EXCHANGE`, `DEAD_LETTER_EXCHANGE`, `EVENTS` (VisitCompleted
  only, DL-14), `routing_key_for()`, `format_timestamp()` (now also used by
  `Timestamp`).
- `app/outbox/topology.py`: `jiris.events` topic and `jiris.dlx` direct,
  both durable; `billing.inbox` bound to `visits.*` and `visits.inbox`
  bound to `billing.*`, each with `x-dead-letter-exchange = jiris.dlx` and
  `x-dead-letter-routing-key` = its parking queue (DL-18); parking queues
  bound by their own name; `declare_topology()` idempotent; queue objects
  exported for the M05 and M06 consumers (DL-21).
- `app/outbox/relay.py`: the loop of TDD §8.1 as amended: `WHERE
  published_at IS NULL AND attempts < 5 ORDER BY occurred_at LIMIT 100
  FOR UPDATE SKIP LOCKED`; per row a `mandatory` persistent publish with
  `message_id = event_id` and `content_type = application/json`, the
  confirm awaited with a timeout, then `published_at = now()`; COMMIT;
  500 ms sleep after an empty pass. Error classes as DL-19 and DL-20:
  `BrokerUnavailable` (connection lost, broker down, negative confirm,
  timeout) and `Unroutable` (`PublishError`, ERROR line) roll back and
  back off without touching `attempts`; unknown event types are counted
  after the pass in a short transaction, with one ERROR line each, and
  leave the selection at 5. One INFO line per published event, written
  after COMMIT.
- `app/main_worker.py`: one FastStream broker (robust connection,
  confirms on, `on_return_raises=True`); connection retried with backoff;
  topology at start; relays for `visits` as `visits_app` and `billing` as
  `billing_app`, one pool each (D13); SIGTERM and SIGINT end the running
  passes, then exit 0.
- M03 tests: outbox row presence instead of `published_at IS NULL`
  (DL-22).
- Out of scope respected: no consumer, no Billing reply model, no purge
  job, no schema or migration change; `app/visits` and `app/billing`
  untouched (`git diff --stat build/increments..HEAD` lists only
  `app/contracts`, `app/outbox`, `app/main_worker.py`, `tests/` and
  `docs/`).

## IG-5. Validation

Runs from a clean clone of the branch at `f46f791` (`git clone`, `uv
sync`), and the full suite again in the working copy at `d1fea72` after
the last code commit.

| Criterion | State | Evidence |
|---|---|---|
| Every test of task 3.1 passes | Met | `test_relay_helpers.py` 14 passed (3.1.1); `test_topology.py` 7 passed (3.1.2); `test_outbox_relay.py` 8 passed (3.1.3 to 3.1.8, 3.1.10); `test_worker.py` 1 passed (3.1.9) |
| After a `/complete` and one relay pass, the message is in `billing.inbox` with the 3.1.3 properties, `published_at` is set, a second pass publishes nothing | Met | `test_relay_publishes_a_completion_with_the_tdd_message_properties`: routing key `visits.visit_completed`, `delivery_mode = 2`, `message_id = event_id`, `content_type = application/json`, body equal to the row and valid as `Envelope[VisitCompleted]`; next pass selected 0 and no second message within 1 s |
| 3.1.6: published after the broker restart with no manual step; the relay task never exited | Met | `test_relay_recovers_after_a_broker_outage`: row unpublished with `attempts = 0` during the outage, task alive; after restart published, message in the isolated broker's `billing.inbox`, `attempts = 0`. Three further runs in a row: 3 of 3 passed |
| 3.1.5: no `event_id` delivered twice by two concurrent relays | Met | `test_two_relays_never_publish_a_row_twice`: 40 rows, both relays published a share, 40 distinct messages, none more within 1 s. Three further runs: 3 of 3 passed |
| A message rejected from either inbox reaches its parking queue | Met | `test_rejected_message_reaches_its_parking_queue[billing]` and `[visits]`: routing key = parking queue name, `x-death` with the inbox, `rejected` and the original key |
| 3.1.7, 3.1.8, 3.1.10: failures never change `attempts`; unknown types excluded after five passes and do not block good events | Met | Unroutable: two passes, `Unroutable` raised, two ERROR lines with the event id, `attempts = 0`, row still selected. Unknown type, both schemas: `attempts` 1 to 5, five ERROR lines, the last `outcome=excluded`, sixth pass selects nothing; the `billing` case ran as `billing_app`. 100 unknown rows: passes `(100, 0, 100)` five times, then `(3, 3, 0)`; the 3 good messages delivered |
| `lint-imports` 3 kept; both `alembic check`; T7 | Met | `Contracts: 3 kept, 0 broken.`; `test_models_match_migrations` 2 passed; T7 21 passed |
| T1 collected 50 times, xfailed with `WorkerNotReady` | Met | 50 xfailed with reason `needs relay and consumers; removed in M06` |
| Collected count at least 187 plus the new tests | Met | 217 collected (187 plus 30): 167 passed, 50 xfailed |

Verdict tally: 9 met, 0 not met, 0 not verified.

Smoke run on an isolated compose project (`jiris-m04-check`, removed with
`down -v`): `rabbitmqctl list_queues` showed the four queues durable,
`billing.inbox` and `visits.inbox` with `x-dead-letter-exchange =
jiris.dlx` and their parking routing keys; after a `/complete`,
`billing.inbox` held 1 message and the outbox row was published with
`attempts = 0`; the `worker` log showed `topology declared`, `relay
started` for both schemas and `event published ... outcome=published`;
`docker compose stop worker` gave exit code 0 after `relay stopped` for
both schemas and `worker stopped`.

Branch and count after each commit: `git branch --show-current` returned
`feature/m04-outbox-relay` after every commit. Collected totals: 187
after `14349e4`, `c7cded5` and `af581c1`; not collectable in full after
`dc00d55` and `2c13824` (red, by design); 217 from `e7425b7` onwards.

## IG-6. Documentation

- `docs/TDD.md` §7.1 (DL-18, topology file) and §8.1 (DL-19, DL-20;
  negative confirm named with the broker failures at completion).
- `docs/build-spec/index.md` section d: `app/outbox/topology.py`.
- `docs/build-spec/contract.md`: §5; §6 DL-18 to DL-22; §7a resolved
  OQ-9 to OQ-13; §7b TD-5.
- `module-04-outbox-relay.md`: amended at HG-1; criteria ticked from this
  report.
- `docs/technical-debt.md`: TD-5.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| FastStream adds `x-queue-type = classic` to every queue it declares | A consumer that declares an inbox queue with other arguments fails with `PRECONDITION_FAILED` | M05 and M06 subscribe with the queue objects of `app/outbox/topology.py` (DL-21) |
| The relay imports `aio-pika` and `pamqp`, present only through `faststream[rabbit]` | A transport change in FastStream would break the relay without a lock conflict | TD-5, close in M08 (dependency change, developer decision) |
| A row excluded at `attempts = 5` stays unpublished for ever; no tool lists or replays it | An operator must find it in the table; the ERROR line with `outcome=excluded` is the only signal | Accepted (DL-19); in M05 the Billing reply types are registered, so no current producer writes an unknown type |
| A broker failure in the middle of a pass rolls back rows already confirmed in it, which are published again | Duplicate messages | By design (TDD §8.1); consumers de-duplicate by `event_id` from M05 |
| A long-running worker in the integration session (from M05, when consumers make `worker` ready) publishes rows while other tests run | Assertions on `published_at` would race | M03 checks now use row presence (DL-22); M05 and M06 tests must filter by their own ids |
| The worker declares the topology once at start; a failure there ends the process with an error, and compose has no restart policy for `worker` | The worker stays down until restarted | Review with operations in M08 (restart policy) |
| `declare_topology()` binds queues but never removes stale bindings | A renamed routing key would leave the old binding | No rename planned; noted for future changes |

Registers: TD-5 opened and mirrored in contract section 7b. No backlog
entry.
