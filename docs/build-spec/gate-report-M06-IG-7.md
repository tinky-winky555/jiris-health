# Gate report M06, IG-7 (completion), Visits consumer; T1 green

Module: `module-06-visits-consumer.md` · Date: 2026-11-11 · Branch:
`feature/m06-visits-consumer` (from `build/increments` at `755a547`) ·
Planning report: `gate-report-M06-IG-3.md`, approved with HG-1 on
2026-11-11 (DL-29 to DL-33).

## Commits on the branch

| Commit | Content |
|---|---|
| `e82e78d` | docs: HG-1 record; TDD §4, §5.1, §6.4; contract §3, DL-29 to DL-33; index section d; module-06; IG-3 |
| `e01b3f1` | test: isolation by time (DL-32): module-scoped `worker`, guard `no_foreign_consumers` |
| `7303873` | test: M06 tests, committed red |
| `33e367b` | feat: migration `visits_0002` and the Inbox model (DL-31) |
| `d74efff` | feat: BillingFailed in `app.contracts` (DL-29) |
| `5457132` | feat: `app/outbox/consumer.py`; Billing consumer moved onto it (DL-33) |
| `7ec92ed` | feat: `apply_billing_reply()` in `app/visits/service.py` |
| `1c63ae2` | feat: `app/visits/consumer.py` |
| `3a73fd5` | test: WARNING for BillingFailed on a Completed visit, committed red (approved before IG-7) |
| `79717ec` | feat: that WARNING and no-op; TDD §6.4 |
| `5b15416` | feat: Visits consumer in `app/main_worker.py` |
| `e2a1d54` | test: T1 `xfail` marker removed |

## Red runs and the T1 proof

| After | Result |
|---|---|
| `e01b3f1`, isolation | 276 collected, 226 passed, 50 xfailed: unchanged |
| `7303873`, tests | 224 passed, 50 xfailed, 6 failed, 4 errors: `test_visits_parse.py`, `test_consumer_mechanics.py` (`app.outbox.consumer` missing), `test_visits_reply_service.py` (`UnknownVisit` missing), `test_visits_consumer.py` (`BILLING_FAILED` missing) not collectable; failed: four BillingFailed contract tests, T3, the reworked worker test. 224 = 226 minus the replaced M05 test and minus the worker test |
| `5457132`, shared mechanics | M05 tests: 55 passed, test bodies unchanged |
| `7ec92ed`, reply service | 9 passed |
| `1c63ae2`, Visits consumer | Parsing, rule and consumer tests: 35 passed |
| `3a73fd5`, WARNING test | 1 failed: no WARNING record; green after `79717ec` |
| `5b15416`, worker | T1 run with the marker still in place: **50 failed, each `[XPASS(strict)] needs relay and consumers; removed in M06`**: the recorded proof that the full flow passes and the marker is obsolete |
| `e2a1d54`, marker removed | T1: 50 passed; `grep -rn xfail tests` finds nothing |

Incident during the module: after `5457132`, the working copy of
`app/outbox/consumer.py` gained a stray `1` before its docstring from an
accidental keystroke in the IDE (not by the agent). The agent reported it
instead of reverting it; the developer confirmed it was unintended; it was
restored with `git checkout -- app/outbox/consumer.py`, and the consumer
tests ran again: 75 passed. No commit contains the stray edit.

## IG-4. Implementation consistent with the approved scope

- `app.contracts`: BillingFailed (`visit_id`, `completion_attempt_id`,
  `reason`, `error_class` in `transient_exhausted`, `permanent`) and
  `BILLING_FAILED` (`billing.failed`) in `EVENTS` (DL-29).
- Migration `visits_0002`: `visits.inbox.attempts` int not null default
  0, `last_error` text null, `processed_at` nullable without a default
  (DL-31, DL-34); downgrade restores the M02 shape.
- `app/outbox/consumer.py` (DL-33): subscription with
  `AckPolicy.MANUAL`, prefetch 10, raw body decoder, `title` = queue name;
  `MalformedMessage`; `is_database_unavailable()` over the cause chain
  (OSError, TimeoutError, asyncpg connection errors, SQLAlchemy
  `OperationalError`, `InterfaceError`, invalidated connections); one log
  line per consumed message. Imports neither module.
- `app/billing/consumer.py`: same behaviour on the shared mechanics; same
  log line; `MalformedMessage` and `parse_visit_completed` still exported.
- `app/visits/service.py`: `apply_billing_reply()` per TDD §6.4 as
  amended: inbox insert, `processed_at` `FOR UPDATE` as the processed
  marker; visit `FOR UPDATE`; unknown visit → `UnknownVisit`; attempt
  mismatch → ignored (R1); Completed → no-op (R3), with a WARNING for a
  BillingFailed (DL-34); BillingRecordCreated → Completed; BillingFailed →
  reset (D16); `processed_at = now()`.
- `app/visits/consumer.py`: `parse_billing_reply()` accepts only the two
  reply types, version 1, valid payload; failure classes of DL-31:
  malformed or unknown visit → `visits.parking` with ERROR; database
  unavailable → requeue after backoff 0.5 s doubling to 30 s, unlimited,
  never counted; other → `attempts + 1` and `last_error` by `INSERT ... ON
  CONFLICT DO UPDATE` in a short transaction, requeue after 1 s, parked at
  5 with ERROR.
- `app/main_worker.py`: both consumers registered; the worker meets the
  readiness rule of TDD §11.
- Tests: module-scoped `worker`; guard in `test_topology.py`,
  `test_outbox_relay.py`, `test_billing_consumer.py`,
  `test_visits_consumer.py`, `test_visits_reply_service.py`,
  `test_visits_api.py`, `test_rate_precision.py`, `test_worker.py`,
  `test_t3_broker_outage.py`; the M05 test that BillingFailed is not
  registered replaced by its opposite (DL-29).
- Out of scope respected: Billing does not emit BillingFailed; no error
  classes or counter in Billing; no purge. Files changed under `app/`:
  `app/billing/consumer.py`, `app/contracts/__init__.py`,
  `app/main_worker.py`, `app/outbox/consumer.py`,
  `app/visits/consumer.py`, the migration, `app/visits/models.py`,
  `app/visits/service.py`.

## IG-5. Validation

From a clean clone of the branch at `e2a1d54` (`git clone`, `uv sync`):
325 collected, 325 passed, no `xfail` in `tests/`; `lint-imports` 3
kept.

| Criterion | State | Evidence |
|---|---|---|
| Every test of task 4.1 passes | Met | `test_visits_parse.py` 10, `test_consumer_mechanics.py` 16, `test_contracts.py` 16, `test_visits_reply_service.py` 10, `test_visits_consumer.py` 8, `test_t3_broker_outage.py` 1, `test_worker.py` 1, `test_t1_concurrent_complete.py` 50: all passed |
| T1 passes 50 of 50 with no `xfail` left | Met | 50 passed in every run below; `XPASS(strict)` 50 of 50 recorded before the removal; `grep -rn xfail tests` empty |
| T3: Completed with one record after the broker restart, no manual step, no worker restart | Met | Visit `Scheduled` and pending, outbox row unpublished with `attempts = 0` during the outage; after the restart Completed, one record `50.00`, worker process alive, then SIGTERM exit 0. Recovery 13.0 s in the file-order run, 13.3, 13.0 and 13.1 s in three further runs |
| T6: a reply with an old attempt id is ignored | Met | `test_t6_reply_with_an_old_attempt_id_is_ignored[record_created]` and `[failed]`: visit stays pending on attempt B, inbox row processed, a second delivery is a duplicate, the reply for B completes the visit |
| Idempotency test of the Visits consumer | Met | `test_the_same_reply_twice_changes_nothing`; through the broker, one `outcome=completed` line and no redelivery within 2 s |
| Database outage never parks; stable failure parks after 5 counted attempts | Met | 4.1.11 on a dedicated broker with a closed database port: three deliveries, `cause=database_unavailable`, gaps at least 0.5 s then 1.0 s and growing, nothing parked, the reply still in `visits.inbox`, no inbox row. 4.1.16: trigger raising on the test visit, outcomes `requeued` four times then `parked`, `attempts=5`, inbox row `attempts = 5`, `processed_at` NULL, `last_error` with the trigger message; the next reply completed its visit |
| `visits_0002` downgrade then upgrade | Met | Isolated compose project `jiris-m06-check`: `downgrade visits_0002 -> visits_0001`, `upgrade visits_0001 -> visits_0002`, `visits_0002 (head)`; columns `processed_at` nullable, `attempts` not null, `last_error` nullable; project removed with `down -v` |
| Suite in file order and with the T1 module first; guard never fires | Met | File order: 325 passed (153.8 s). T1 module first, then every other integration file, then `tests/unit`: 325 passed (151.9 s). No guard failure in either |
| `lint-imports`; both `alembic check`; T7 | Met | `Contracts: 3 kept, 0 broken.`; `test_models_match_migrations` 2 passed; T7 21 passed |
| Collected count at least 276 plus the new tests | Met | 325 collected (276 minus 1 replaced, plus 50 new; T1's 50 now count as passed, not xfailed) |

Verdict tally: 10 met, 0 not met, 0 not verified.

Smoke run on an isolated compose project (`jiris-m06-check`): `/complete`
202; after 4 s the visit is Completed, `completion_pending` false,
`completion_requested_at` kept; one billing record `50.00`; both inbox
queues empty with 1 consumer each, parking queues empty; the
`visits.inbox` row processed with `attempts = 0`; `docker compose stop
worker` exit 0.

Branch and count after each commit: `git branch --show-current` returned
`feature/m06-visits-consumer` after every commit. Collected totals: 276
after `e82e78d` and `e01b3f1`; not collectable in full after `7303873` to
`7ec92ed` (red modules importing code still to come); 325 after
`e2a1d54`, and in every full run.

## IG-6. Documentation

- `docs/TDD.md`: §4 (`app/outbox/consumer.py`, `topology.py`); §5.1
  `visits.inbox` columns; §6.4 steps and failure classes (DL-30, DL-31),
  BillingFailed for a Completed visit (DL-34).
- `docs/build-spec/contract.md`: §3 Idempotency and Retries; §5; §6
  DL-29 to DL-34; §7a resolved OQ-17 to OQ-21.
- `docs/build-spec/index.md` section d: `app/outbox/consumer.py`.
- `module-06-visits-consumer.md`: amended at HG-1; criteria ticked from
  this report.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| The Billing consumer still requeues every non-parse failure every second for ever (DL-25, interim) | A poison VisitCompleted loops until M07 | M07 replaces it with the Billing failure path |
| A reply parked after 5 attempts leaves its visit pending; no tool replays it | The visit stays pending until an operator acts | Accepted (DL-31); `visits.inbox.last_error` and the ERROR line name the cause; replay tooling is not in this release |
| Backoff for an unavailable database is per consumer process and blocks that consumer while it waits | Other replies wait too | Intended: nothing can be processed without the database |
| `is_database_unavailable()` treats every SQLAlchemy `OperationalError` as an outage | A non-connection operational error would retry for ever instead of being counted | TD-6, target M08: narrow by SQLSTATE (`08`, `57P`, `40001`, `40P01` temporary; the rest counted) |
| The worker logs FastStream's own lines next to ours | Two log formats | M08 logging review |
| T3 relies on aio-pika restoring consumers after a restart (A1 of IG-3) | Proven by T3 at 13 s; a library change could break it | T3 runs in every suite |

Registers: TD-6 opened at the developer's request on IG-7 approval and mirrored in contract section 7b. No backlog entry.
