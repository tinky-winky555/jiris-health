# Gate report M05, IG-7 (completion), Billing consumer, happy path

Module: `module-05-billing-consumer.md` · Date: 2026-11-11 · Branch:
`feature/m05-billing-consumer` (from `build/increments` at `fa5dec6`) ·
Planning report: `gate-report-M05-IG-3.md`, approved with HG-1 on
2026-11-11 (DL-24 to DL-28).

## Commits on the branch

| Commit | Content |
|---|---|
| `5b91b75` | docs: HG-1 record; TDD §4 and §8.2, index section d, module-05, IG-3, contract DL-24 to DL-28 |
| `fad1157` | test: M05 tests, the M04 queue cleanup (DL-27), the reworked worker test, the M03 configuration test change; committed red |
| `1af9f5e` | feat: BillingRecordCreated in `app.contracts` |
| `66d7b6e` | feat: `app/billing/service.py` |
| `a5efa5a` | feat: `app/billing/consumer.py` |
| `481b6e6` | feat: `app/billing/api.py`, billing pool in `app/main_api.py` |
| `54715e6` | feat: Billing consumer in `app/main_worker.py` |
| `58ef57c` | docs: raw decoder and literal index predicate in TDD §8.2 |

## Red runs (tests first)

| After | Result |
|---|---|
| `fad1157`, tests | 180 passed, 50 xfailed, 7 failed, 5 errors: `test_billing_amount.py`, `test_billing_parse.py`, `test_billing_service.py`, `test_billing_consumer.py`, `test_billing_api.py` not collectable (`ImportError` on `compute_amount`, `process_visit_completed`, `MalformedMessage`, `BillingRecordCreated`, `BILLING_RECORD_CREATED`); failed: three contract tests, the two API configuration tests, the rule test that looks for the topology import in `app/billing/consumer.py`, and the worker test (no billing record). The 180 passed are the 167 of the baseline, with the M04 tests now purging their queues, plus 13 new tests that hold already: the rule test over the existing module files and "BillingFailed not registered" |
| `1af9f5e`, contract | Contract and relay helper tests: 27 passed |
| `66d7b6e`, service | First run: `test_r8_second_attempt_replies_with_the_existing_record[concurrent]` failed with `there is no unique or exclusion constraint matching the ON CONFLICT specification`. Cause: `ON CONFLICT (visit_id) WHERE status = $5` with a bound parameter; PostgreSQL matched the partial index while it planned the prepared statement for the value, and failed once it switched to a generic plan. Fixed with the literal predicate `status = 'Created'`, as in `ux_active_record`; then amount and service tests 17 passed, three runs in a row |
| `a5efa5a`, consumer | First run: the `not-json` case of 4.1.8 failed; the message was received but never reached the handler. Cause: FastStream decodes a body with `content_type = application/json` before the handler runs; the decoder raised, and under `AckPolicy.MANUAL` the message stayed unsettled. Fixed with a raw body decoder on the subscriber, so all parsing happens in `parse_visit_completed`; then 30 passed |
| `481b6e6`, API | API and configuration tests: 8 passed |
| `54715e6`, worker | Worker test passed; full suite 224 passed, 50 xfailed |

## IG-4. Implementation consistent with the approved scope

- `app.contracts`: BillingRecordCreated and `BILLING_RECORD_CREATED`
  (`billing.record_created`) in `EVENTS`; BillingFailed not added (DL-26).
- `app/billing/service.py`: `compute_amount()` in Decimal from the exact
  duration in microseconds, `to_money()` (2 places, ROUND_HALF_UP);
  `process_visit_completed()` in the caller's transaction: inbox `INSERT
  ... ON CONFLICT (event_id) DO NOTHING`, `SELECT status ... FOR UPDATE`,
  not `processing` means duplicate; record `INSERT ... ON CONFLICT
  (visit_id) WHERE status = 'Created' DO NOTHING RETURNING id`, else the
  existing active record and its amount (R8); BillingRecordCreated in
  `billing.outbox`; inbox `processed`, `processed_at = now()`.
- `app/billing/consumer.py`: subscriber on `INBOX_QUEUES[BILLING_INBOX]`
  with `AckPolicy.MANUAL`, `prefetch_count = 10`, a raw body decoder, no
  exchange; malformed envelope, other type or version, or invalid payload:
  `reject(requeue=False)` to `billing.parking`; success or duplicate: ack
  after COMMIT; any other exception: ERROR line, 1 s, `nack(requeue=True)`
  (DL-25). One log line per consumed message with `event_id`,
  `event_type`, `visit_id`, `message_id`, `redelivered`, outcome.
- `app/billing/api.py` and `app/main_api.py`: `GET /api/billing-records`
  with a `billing_app` pool; the API reads both module URLs and neither
  the migration nor the broker setting (DL-24).
- `app/main_worker.py`: the Billing subscriber is registered with a
  `billing_app` session factory; the broker starts after the topology.
- Tests: M04 tests purge the session queues after each test; worker
  fixtures purge both inboxes before start (DL-27); the M04 unknown type
  test uses `NoSuchBillingEvent`; the M04 worker test asserts the billing
  record and the reply instead of reading `billing.inbox`.
- Out of scope respected: no Visits consumer, no BillingFailed, no
  counter, no permanent class, no purge; `app/visits` and `app/outbox`
  unchanged; no migration (`git diff --name-only build/increments..HEAD`
  under `app/`: `app/billing/api.py`, `app/billing/consumer.py`,
  `app/billing/service.py`, `app/contracts/__init__.py`,
  `app/main_api.py`, `app/main_worker.py`).

## IG-5. Validation

From a clean clone of the branch at `58ef57c` (`git clone`, `uv sync`).

| Criterion | State | Evidence |
|---|---|---|
| Every test of task 4.1 passes | Met | `test_billing_amount.py` 11, `test_contracts.py` 13 (4 new), `test_billing_service.py` 6, `test_billing_consumer.py` 7, `test_billing_parse.py` 8, `test_billing_api.py` 4, `test_consumer_rule.py` 16, `test_main_api.py` 4, `test_worker.py` 1: all passed |
| T2: one VisitCompleted delivered twice gives one record and one reply | Met | `test_t2_same_event_twice_gives_one_record_and_one_reply` and `test_t2_same_event_at_the_same_time_gives_one_record_and_one_reply`; the concurrent case and both R8 cases three further runs in a row: 3 of 3 |
| T8 amount half passes | Met | 8 cases including 0.01 for 30 min = 0.01 (half up), 33.33 for 30 min = 16.67, half a second at 36.00 = 0.01; a float rate raises `TypeError` |
| Ack only after COMMIT | Met | 4.1.9 on a dedicated broker: the overflow fails the transaction, two ERROR lines `outcome=requeued`, the second with `redelivered=True` at least 1 s after the first, no inbox row, record or reply (three further runs: 3 of 3); 4.1.7: exactly one `outcome=processed` line, `redelivered=False`, nothing more within 2 s |
| No source under `app/billing` or `app/visits` declares or binds a queue | Met | `test_module_code_declares_and_binds_no_queue` over every module file; `test_billing_consumer_takes_its_queue_from_the_topology` |
| `lint-imports` 3 kept; both `alembic check`; T7 | Met | `Contracts: 3 kept, 0 broken.`; `test_models_match_migrations` 2 passed; T7 21 passed |
| T1 collected 50 times, xfailed with `WorkerNotReady` | Met | 50 xfailed; the worker has a consumer on `billing.inbox` only |
| Collected count at least 217 plus the new tests | Met | 274 collected (217 plus 57): 224 passed, 50 xfailed |

Verdict tally: 8 met, 0 not met, 0 not verified.

Malformed messages (4.1.8): `not-json`, `no-envelope-fields`,
`payload-n-1` (VisitCompleted with payload `{"n": 1}`), `other-type`,
`other-version` each reached `billing.parking` once (`x-death` queue
`billing.inbox`, reason `rejected`, count 1), with one `outcome=parked`
line, were not in `billing.inbox` afterwards, and the next good message
was processed.

Smoke run on an isolated compose project (`jiris-m05-check`, removed with
`down -v`): `/complete` 202; `GET /api/billing-records` returned one
record, amount `29.99` (19.99 for 1 h 30 min); `billing.inbox` empty with
1 consumer; `visits.inbox` 1 message (BillingRecordCreated, no consumer
before M06); `visits.outbox` VisitCompleted and `billing.outbox`
BillingRecordCreated both published; `billing.inbox` row `processed`;
`docker compose stop worker` exit code 0.

Branch and count after each commit: `git branch --show-current` returned
`feature/m05-billing-consumer` after every commit. Collected totals: 217
after `5b91b75`; not collectable in full after `fad1157` to `66d7b6e`
(red modules importing code still to come); 274 from `54715e6` onwards
(checked after `54715e6` and `58ef57c`).

## IG-6. Documentation

- `docs/TDD.md`: §4 `app/billing/api.py` (DL-24); §8.2 interim behaviour
  (DL-25), manual acknowledgement, raw decoder, literal index predicate.
- `docs/build-spec/index.md` section d: `app/billing/api.py`.
- `docs/build-spec/contract.md`: §5; §6 DL-24 to DL-28; §7a resolved
  OQ-14 to OQ-16.
- `module-05-billing-consumer.md`: amended at HG-1; criteria ticked from
  this report.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| Until M07, a message that fails for any reason other than parsing is requeued every second for ever | A poison message loops and blocks nothing else only because prefetch lets other messages through; logs grow | Interim by decision (DL-25); M07 adds the counter, the permanent class, BillingFailed and parking after 5 attempts |
| From M06 the session `worker` fixture becomes ready and lives to the end of the session | Tests that read queues directly race the worker | DL-28: the M06 plan isolates them |
| FastStream writes its own log lines (`Received`, `Processed`, coloured) next to ours | Two formats in the worker log | Review with logging in M08 |
| A malformed message is parked with its body only; the reason is in our ERROR line, not on the message | An operator reading `billing.parking` must correlate with the log by `message_id` | Accepted; M07 may add a header with the reason |
| `INSERT ... ON CONFLICT ... WHERE` depends on the literal predicate matching `ux_active_record` | Changing the index predicate without the code breaks billing | The literal is built from `RECORD_CREATED`, the same constant as the model's index |
| R8 replies with the existing record's amount, not the amount of the new attempt | A second attempt with another rate (not possible through the API, since D17 and R1) gets the first amount | As TDD §8.2 and R8 |

Added before the merge at the developer's request (IG-7 approval
condition): `test_on_conflict_survives_the_generic_plan[auto]` and
`[force_generic_plan]`, 12 attempts for one visit on one connection
(`pg_backend_pid()` checked after each), every attempt after the first
conflicting on `ux_active_record`: no exception, one active record, 12
replies. Shown on a scratch copy with the bound predicate restored: both
cases fail with `there is no unique or exclusion constraint matching the
ON CONFLICT specification`. The code comment next to the literal predicate
names the cause and TDD §8.2.

Registers: no new technical debt or backlog entry.
