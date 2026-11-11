# Build Spec Contract, Jiris Health

The developer's operating panel and the first gate of the Build Spec.
Input path B: `docs/PRD.md` and `docs/TDD.md`; rationale in
`docs/HANDOFF.md`. Release boundary: the delivery defined in PRD §5 and
index section g. Executor: the Claude Code agent in this repository, one
module per session, Full Envelope.

Sections 1 to 4 are LOCKED after developer approval; changes require
explicit approval and a decision log entry (section 6). Sections 5 to 7
are LIVE and are maintained by the agent.

## 1. Architecture decisions

Inherited decisions cite their Handoff IDs (D-nn, R-n). Decisions
ratified with this contract carry BS-nn IDs.

| ID | Decision | Affected |
|---|---|---|
| D1 | Modular monolith on FastAPI + PostgreSQL; modules Visits and Billing | all |
| D5, D13 | No cross-module table access; schema and role per module (`visits_app`, `billing_app`); import-linter | all, db |
| D6 | Completed visit always gets a record; never two; unpublished events published later without manual action | all |
| D8 | RabbitMQ: durable queues, manual ack, publisher confirms, DLX | outbox, consumers |
| D9, D14, D18 | Two-phase completion: `/complete` sets `completion_requested_at`, status unchanged; Completed only after BillingRecordCreated | visits |
| D10 | `/complete` allowed from Scheduled and In Progress | visits |
| D11 | Billing computes `amount = rate × hours(end − start)`, Decimal, 2 places, ROUND_HALF_UP | billing |
| D12 | `Reversed` in the model only; no reversal operation | billing |
| D15 | Transient errors retried up to 5 times (counter in `billing.inbox`); permanent errors fail at once; unclassified count as transient. Refined by DL-35 (database unavailable: backoff, unlimited, not counted) and DL-36 (SQLSTATE classes 22 and 23 permanent, except 23505) | billing |
| D16 | On BillingFailed: reset `completion_requested_at`, store `completion_failure_reason` | visits |
| D17 | `/complete`: 202 winner; 409 pending, lost race or invalid status; 404 unknown | visits |
| D19, D25 | Polling relay with `FOR UPDATE SKIP LOCKED` in a separate worker; 500 ms, 100 rows, backoff ceiling 30 s; retention 7 days | outbox, worker |
| D20, D27 | Event envelope and topology as TDD §7; schemas in `app.contracts` | contracts, all |
| D23 | `completion_requested_at` kept after Completed | visits |
| D26, D29 | Two Alembic chains run by `jiris_migrator`; app roles DML only | db |
| D28 | Supporting endpoints, layout, stack defaults as TDD §3, §4, §6.1 | all |
| D30 | FastStream over aio-pika with its FastAPI integration | consumers, worker |
| R1 to R9 | Derived requirements as Handoff §10a, §10b | all |
| BS-1 | Governance: Full Envelope under this Build Spec; gate-report pair per module | delivery |
| BS-2 | Module size for this delivery: 4 to 12 hours (the generic 12 to 24 does not fit a two-module service) | delivery |
| BS-3 | Git: `main` holds released work only; `build/increments` is the integration branch; one branch `feature/mNN-<slug>` per module, created from `build/increments`. No pull requests in this delivery. After the developer approves the module's IG-7 report, the agent merges the feature branch locally into `build/increments` with `git merge --no-ff` and the message `Merge MNN <slug>: IG-7 approved`, then runs `git push`. `build/increments` into `main` under HG-3 at delivery. M01 and M02 were committed directly on `build/increments` before this contract; their history is kept as it is (DL-7) | delivery |
| BS-4 | `migrate` is a one-shot compose service; `api` and `worker` depend on it with `condition: service_completed_successfully` | compose |

## 2. Stack

No deviation without developer approval and a decision log entry in
section 6.

| Concern | Choice |
|---|---|
| Language | Python 3.15.2 or later, async everywhere, full type hints |
| Package manager | uv (`pyproject.toml`, `uv.lock`, `.python-version`) |
| API framework | FastAPI with uvicorn, uvloop and httptools (not `uvicorn[standard]`: pyyaml has no cp315 wheel) |
| Validation | Pydantic v2 |
| Database | PostgreSQL in Docker (compose and testcontainers) |
| ORM | SQLAlchemy 2 async with asyncpg; URLs `postgresql+asyncpg://` |
| Migrations | Alembic, one `alembic.ini` with sections `[visits]` and `[billing]`, version tables in their own schemas |
| Messaging | RabbitMQ; FastStream over aio-pika |
| Boundaries | import-linter (`.importlinter`, three contracts) |
| Tests | pytest with pytest-asyncio (`asyncio_mode = auto`, session event loop), httpx AsyncClient, testcontainers |
| Local run | docker-compose: postgres, rabbitmq, migrate, api, worker |
| Containers | One Dockerfile, image `python:3.15.2-slim`, no `CMD` or `ENTRYPOINT` in the image; compose sets three commands on it: `migrate` (both Alembic chains), `api` (`uvicorn --factory app.main_api:create_app`), `worker` (`python -m app.main_worker`) |
| Hosting, CI/CD | None in this delivery (local only); see index section h |

## 3. Cross-cutting patterns

| Pattern | Rule |
|---|---|
| Error shape | 409 body `{"reason": "completion_pending" \| "invalid_status"}`; 404 body `{"detail": "Not Found"}` (DL-10); 422 FastAPI validation body |
| Response codes | Create 201 with the visit; `/start`, `/cancel`, `/missed` 200 with the visit; `/complete` 202 with the visit; list endpoints return a JSON array; no pagination |
| Transactions | One transaction per HTTP command and per consumed message; state change and outbox row in the same transaction |
| Idempotency | Inbox insert `ON CONFLICT (event_id) DO NOTHING` first, then the row `FOR UPDATE`; processed (`billing.inbox.status`, `visits.inbox.processed_at`) → ack without effect; `message_id` = `event_id` |
| Concurrency | Conditional UPDATE for `/complete`; `SELECT ... FOR UPDATE` on the visit in the Visits consumer; `SKIP LOCKED` in relays |
| Retries | Relay: unlimited, exponential backoff to 30 s. Billing (DL-35, DL-36): database unavailable, unlimited with backoff to 30 s, not counted; 5 attempts for other transient or unclassified errors, counted in `billing.inbox`; permanent errors none. Visits consumer (DL-31): database unavailable, unlimited with backoff to 30 s; other errors 5 attempts counted in `visits.inbox`, then parking |
| Dead letters | Malformed messages and exhausted retries go to the module's parking queue through `jiris.dlx`; never requeued automatically |
| Reconnection | aio-pika robust connections under FastStream (R7) |
| Money | Decimal, numeric(12,2), ROUND_HALF_UP; decimal string in events |
| Time | timestamptz everywhere; UTC in events (`occurred_at`) |
| Secret management | Env vars only; `.env` never committed; `.env.example` keys only. Local development credentials in `docker-compose.yml`, `docker/postgres/init.sql` and the test fixtures are a recorded compromise (TD-1) |
| Logging | One line per command and per consumed event with `visit_id`, `event_id`, `event_type`, outcome; no payload bodies |
| Writing | British corporate English in artefacts; Russian in chat; no em or en dashes |

## 4. Gate map

Internal gate reports live in `docs/build-spec/`. Consecutive internal
gates of one module are combined into two files: the planning report
`gate-report-MNN-IG-3.md` (IG-1, IG-2, IG-3, before implementation) and
the completion report `gate-report-MNN-IG-7.md` (IG-4 to IG-7, when the
acceptance criteria pass). Human gates produce no file; their outcome is
recorded in section 5 and, where the entry rule applies, in section 6.

The acceptance checkboxes of a module document are a reading of its
completion report, not a second record. A box is ticked when the IG-7
report records the criterion as met.

| Gate | Trigger | Expected report |
|---|---|---|
| IG-1 | Start of every module: scope and affected surfaces | gate-report-MNN-IG-3.md |
| IG-2 | Start of every module: dependencies, risks, assumptions, edge cases | gate-report-MNN-IG-3.md |
| IG-3 | Start of every module: execution sequence, tests written first | gate-report-MNN-IG-3.md |
| IG-4 | End of every module: implementation consistent with approved scope | gate-report-MNN-IG-7.md |
| IG-5 | End of every module: acceptance criteria, full suite, lint-imports, alembic check | gate-report-MNN-IG-7.md |
| IG-6 | End of every module: affected documentation updated | gate-report-MNN-IG-7.md |
| IG-7 | End of every module: residual risks, follow-ups, registers | gate-report-MNN-IG-7.md |
| HG-1 | This contract; the index; each module document with its IG-3 report, before code | none (section 5) |
| HG-2 | Any change to sections 1 to 4; any deviation from TDD; any design choice with lasting impact | none (section 6) |
| HG-3 | Merge of `build/increments` into `main`; any history rewrite; any destructive action on a database outside a test container | none (section 5) |
| HG-4 | Material scope expansion mid-module (new table, endpoint, event, dependency, cross-module impact) | none (section 6 when it changes the contract) |

M01 and M02 were built before this contract. They receive a completion
report only (`gate-report-M01-IG-7.md`, `gate-report-M02-IG-7.md`), written
from the repository as it stands; no planning report is written
retrospectively.


## 5. Current status

| Field | Value |
|---|---|
| Contract | **Approved (HG-1) by Sasha on 2026-11-11**, with the adoption corrections of DL-9. Sections 1 to 4 are locked. |
| Index | Approved (HG-1) by Sasha on 2026-11-11, with the adoption corrections of DL-9. |
| M01, repository foundation | Complete. Committed as `6c707c0` on `build/increments` before the contract. Completion report `gate-report-M01-IG-7.md`: 5 of 5 criteria met. IG-7 approved by Sasha on 2026-11-11. |
| M02, schemas, roles, migrations | Complete. Committed as `aed4672` on `build/increments` before the contract; T7 write case added in the adoption commit (DL-9, item 15). Completion report `gate-report-M02-IG-7.md`: 6 of 6 criteria met. IG-7 approved by Sasha on 2026-11-11. |
| T1 | Green: 50 of 50 passed; the `xfail` marker was removed in M06 (`e2a1d54`) after a recorded `XPASS(strict)` 50 of 50. No `xfail` remains in the suite. |
| Test count | 449 collected on `feature/m09-release`, 449 passed (fresh clone), M09 completion. Baseline before M09: 408. |
| M03, Visits API and outbox | Complete. IG-7 approved by Sasha on 2026-11-11; merged into `build/increments` as `65bb3f7` (`Merge M03 visits-api-and-outbox: IG-7 approved`) and pushed. Completion report `gate-report-M03-IG-7.md`: 6 of 6 criteria met. The pre-contract draft is kept in `~/Code/jiris/m03-draft/` (DL-8). |
| Rate precision (developer request after M03) | `tests/integration/test_rate_precision.py`, committed as `14349e4` on `feature/m04-outbox-relay`: `0.10` and `19.99`, sent as a JSON string or number, are stored, returned and carried in VisitCompleted to the cent; `1.005` is rejected with 422 in both forms (DL-12). No precision loss found; no open question raised. |
| M04, outbox relay and topology | Complete. IG-7 approved by Sasha on 2026-11-11 with the condition to close TD-5 first (done, DL-23, `0bf2246`); merged into `build/increments` as `fa5dec6` (`Merge M04 outbox-relay: IG-7 approved`) and pushed. Completion report `gate-report-M04-IG-7.md`: 9 of 9 criteria met. |
| M05, Billing consumer, happy path | Complete. IG-7 approved by Sasha on 2026-11-11 with the condition of a generic plan regression test (done, `ab215ad`); merged into `build/increments` as `755a547` (`Merge M05 billing-consumer: IG-7 approved`) and pushed. Completion report `gate-report-M05-IG-7.md`: 8 of 8 criteria met. |
| M06, Visits consumer; T1 green | Complete. IG-7 approved by Sasha on 2026-11-11 with TD-6 recorded (`0087141`); merged into `build/increments` as `0459df5` (`Merge M06 visits-consumer: IG-7 approved`) and pushed. Completion report `gate-report-M06-IG-7.md`: 10 of 10 criteria met; T1, T3, T6 green. |
| M07, failure paths in Billing | Complete. IG-7 approved by Sasha on 2026-11-11; merged into `build/increments` as `64ef30c` (`Merge M07 failure-paths: IG-7 approved`) and pushed. Completion report `gate-report-M07-IG-7.md`: 8 of 8 criteria met; T4, T5 green. T1 to T8 all green. |
| M08, technical debt and operations | Complete. IG-7 approved by Sasha on 2026-11-11 with 53300 decided (DL-42, `8cc4036`); merged into `build/increments` as `b4e047e` (`Merge M08 operations-delivery: IG-7 approved`) and pushed. Completion report `gate-report-M08-IG-7.md`: 9 of 9 criteria met; no technical debt open. |
| M09, README, definition of complete, release | Complete on `feature/m09-release` except the merge into `main` (from `build/increments` at `b4e047e`; not merged, not pushed). Completion report `gate-report-M09-IG-7.md`: index section g items 1 to 5 met, item 6 waits for HG-3. |
| Current module | None open. Delivery complete pending HG-3. |
| Last approved gate | HG-1 on module-09 and `gate-report-M09-IG-3.md`, 2026-11-11. |
| Next pending gate | Developer review of `gate-report-M09-IG-7.md`; then HG-3 for the merge into `main`. |
| Blockers | None. |

## 6. Decision log

Decisions taken during build before this contract, and decisions taken at
its adoption, recorded so the contract starts consistent with the
repository.

| ID | Date | Decision | State |
|---|---|---|---|
| DL-1 | 2026-11-11 | TDD §9 amended: grants on the module's named tables plus `ALTER DEFAULT PRIVILEGES` instead of `ON ALL TABLES`, so application roles have no access to `alembic_version` (D29). Held permanently by T7. Detail in TDD §9 and §9.1 | approved by the developer (HG-2, OQ-1) |
| DL-2 | 2026-11-11 | API contract details in TDD §6.1: 201 on create, 200 with body on `/start`, `/cancel`, `/missed`, arrays on lists | approved by the developer |
| DL-3 | 2026-11-11 | `migrate` one-shot compose service (BS-4); `jiris_migrator`; `postgresql+asyncpg://`; worker readiness = a consumer on both `*.inbox` queues | approved by the developer |
| DL-4 | 2026-11-11 | `uvicorn` without `[standard]`, with `uvloop` and `httptools` (pyyaml has no cp315 wheel) | approved by the developer |
| DL-5 | 2026-11-11 | `/tests` removed from `.gitignore`; `.import_linter_cache/` added | approved by the developer |
| DL-6 | 2026-11-11 | T1 is marked `xfail(strict=True)` with reason "needs relay and consumers; removed in M06"; the marker is removed in M06, where T1 must pass 50 of 50 runs (OQ-2) | approved by the developer |
| DL-7 | 2026-11-11 | BS-3 without pull requests: after an approved IG-7, local `git merge --no-ff` of the feature branch into `build/increments` with the message `Merge MNN <slug>: IG-7 approved`, then `git push`. M01 and M02 history on `build/increments` is kept as it is (OQ-3) | approved by the developer |
| DL-8 | 2026-11-11 | The M03 draft written before the contract is removed from the working tree and kept as a patch outside the repository. After HG-1 on module-03, the tests are committed first and their red run is recorded, then the code, aligned with the IG-3 report (OQ-4) | approved by the developer |
| DL-9 | 2026-11-11 | Adoption corrections 1 to 20 of the reconciliation: contract §2 Containers and Tests rows, §3 Secret management and Writing rows, BS-3; index sections c, d and e (init.sql description, index naming as built, `build:` commit prefix, `completion_attempt_id` in the visit body); module-01 task 3.7 and the T1 criterion; module-02 T7 write case; TDD §9 block replaced by the as-built grants; CLAUDE.md commands; `.env.example`; TD-1 and TD-2 | approved by the developer (HG-1) |
| DL-10 | 2026-11-11 | 404 responses keep the FastAPI body `{"detail": "Not Found"}`; TDD §6.3 and contract §3 are updated in M03 (IG-6) | approved by the developer (HG-2); applied in M03 |
| DL-11 | 2026-11-11 | `/start` on a visit with a pending completion returns 409 `completion_pending`, like `/cancel` and `/missed` (extends R2); TDD §6 updated in M03 | approved by the developer (HG-2); applied in M03 |
| DL-12 | 2026-11-11 | Visit creation also returns 422 for a `rate` with more than 2 decimal places and for unknown fields (extends FR11); TDD §6.1 updated in M03 | approved by the developer (HG-2); applied in M03 |
| DL-13 | 2026-11-11 | Visit creation returns 422 for timestamps without a time zone (extends FR11); TDD §6.1 updated in M03 | approved by the developer (HG-2, OQ-5); applied in M03 |
| DL-14 | 2026-11-11 | M03 adds only the envelope and VisitCompleted to `app.contracts`; BillingRecordCreated, BillingFailed and the exchange constants come with M04 to M06 | approved by the developer (OQ-6) |
| DL-15 | 2026-11-11 | M03 criterion on the outbox count is evaluated for the visit under test, because integration tests share one database | approved by the developer (OQ-7) |
| DL-16 | 2026-11-11 | M03 task 3.1 gains a deterministic row-lock test (3.1.7) and a re-completion after reset test (3.1.8) | approved by the developer (OQ-8) |
| DL-17 | 2026-11-11 | The T1 marker is narrowed to `xfail(strict=True, raises=WorkerNotReady)`: the worker fixture raises `WorkerNotReady` when no consumer appears on both inbox queues, and any other error fails T1. Refines DL-6 | approved by the developer |
| DL-18 | 2026-11-11 | TDD §7.1 amended: `jiris.dlx` is a direct exchange; `billing.inbox` and `visits.inbox` set `x-dead-letter-routing-key` to `billing.parking` and `visits.parking`; each parking queue is bound by its own name (OQ-9, option A) | approved by the developer (HG-2) |
| DL-19 | 2026-11-11 | TDD §8.1 amended: an outbox row whose event type has no routing key gets `attempts + 1` in a short transaction after the pass and an ERROR log line; the relay selects only `attempts < 5`, so at most five passes are spent on such a row (OQ-10, OQ-11) | approved by the developer (HG-2) |
| DL-20 | 2026-11-11 | TDD §8.1 amended: broker unavailable, connection lost or publish timeout means ROLLBACK, exponential backoff to 30 s, retry forever, `attempts` unchanged (D6); a message returned as unroutable (`mandatory=True`, `on_return_raises=True`) is handled the same way plus an ERROR log line, and the row is never excluded (OQ-11, OQ-12) | approved by the developer (HG-2) |
| DL-21 | 2026-11-11 | Topology declared by the worker through `app/outbox/topology.py`; exchange names and the routing key registry live in `app.contracts`; index section d updated (OQ-13) | approved by the developer |
| DL-22 | 2026-11-11 | M03 tests check that the visit's outbox row exists, not that it is unpublished, because from M04 a running relay may publish it between the write and the assertion. Refines DL-15 | approved by the developer |
| DL-23 | 2026-11-11 | `aio-pika>=10.2.3` and `pamqp>=5.0.0` declared as direct dependencies at their locked versions; no locked version changed. Closes TD-5 | approved by the developer (HG-2) |
| DL-24 | 2026-11-11 | `GET /api/billing-records?visit_id=` is served by the API process through `app/billing/api.py` with a pool as `billing_app` from `BILLING_DATABASE_URL` (D13). The API reads the two module URLs and never `MIGRATIONS_DATABASE_URL` or `RABBITMQ_URL`; the M03 configuration test changes accordingly. TDD §4 and index section d updated (OQ-14) | approved by the developer (HG-2) |
| DL-25 | 2026-11-11 | TDD §8.2, interim until M07: a body that is not a valid envelope, an envelope of another event type or schema version, and an envelope whose payload fails the validation of its event type are rejected without requeue to `billing.parking` at once (R9); any other exception means ROLLBACK, an ERROR line and `nack` with requeue after 1 s, without a counter. M07 replaces the second rule (OQ-15) | approved by the developer (HG-2) |
| DL-26 | 2026-11-11 | M05 adds only BillingRecordCreated to `app.contracts`; BillingFailed comes with M06 or M07 (OQ-16) | approved by the developer |
| DL-27 | 2026-11-11 | Clean test state: the M04 tests that publish or read messages purge `billing.inbox`, `visits.inbox` and both parking queues of the session broker after each test; every fixture that starts a worker purges `billing.inbox` and `visits.inbox` first | approved by the developer |
| DL-28 | 2026-11-11 | Carried into the M06 plan: tests that read queues directly run isolated from the long-lived worker, on a dedicated vhost or broker or with the worker stopped for the test | approved by the developer |
| DL-29 | 2026-11-11 | BillingFailed is added to `app.contracts` and handled by the Visits consumer in M06 (TDD §6.4 step 4), tested with crafted replies. This part of the failure path moves from M07 to M06; M07 keeps Billing's emission of BillingFailed, the error classes, the counter and T4, T5 (OQ-17). Reverses DL-26 for BillingFailed | approved by the developer |
| DL-30 | 2026-11-11 | A reply whose `visit_id` matches no visit is parked in `visits.parking` with an ERROR line (OQ-18) | approved by the developer |
| DL-31 | 2026-11-11 | TDD §5.1 and §6.4 amended: the Visits consumer classifies failures as the relay does. Database unavailable or connection lost: requeue with exponential backoff to 30 s, unlimited (D6). Malformed message: `visits.parking` at once. Any other exception: `attempts + 1` and `last_error` in `visits.inbox` in a short transaction after ROLLBACK; at 5 attempts, `visits.parking` and an ERROR line. Migration `visits_0002` adds `attempts` (int, default 0) and `last_error` (text, null) to `visits.inbox`, and makes `processed_at` nullable without a default: with a counter in the row, a row can exist before the reply is processed, so `processed_at IS NOT NULL` is the processed marker (OQ-19) | approved by the developer (HG-2); the `processed_at` change approved with DL-34 |
| DL-32 | 2026-11-11 | DL-28 is implemented by time, not by vhost: the `worker` fixture is module scoped; T3 and the worker test start their own worker; sensitive modules start with a guard that fails when an inbox queue has a foreign consumer (OQ-20) | approved by the developer |
| DL-33 | 2026-11-11 | The consumer mechanics shared by Billing and Visits (manual acknowledgement, raw decoder, prefetch, settling, log line) live in `app/outbox/consumer.py`; `app/billing/consumer.py` uses them with no change of behaviour; the M05 tests pass unchanged, except the M05 assertion that BillingFailed is not registered, which DL-29 reverses (OQ-21) | approved by the developer |
| DL-34 | 2026-11-11 | Approved before M06 IG-7: `visits.inbox.processed_at` nullable, with `processed_at IS NOT NULL` as the processed marker (DL-31); a BillingFailed for a Completed visit is a no-op with a WARNING line naming `visit_id` and `completion_attempt_id`; TDD §6.4 updated and tested | approved by the developer (HG-2) |
| DL-35 | 2026-11-11 | TDD §8.2 and D15 refined: in Billing, database unavailable or connection lost is retried with a backoff of 0.5 s doubling to 30 s, without a limit and without counting, as in the relay and the Visits consumer (D6); the 5 attempts of D15 cover every other transient or unclassified error (OQ-22) | approved by the developer (HG-2) |
| DL-36 | 2026-11-11 | TDD §8.2 amended: the permanent class covers payload validation and database errors of SQLSTATE class 22 and class 23, except `23505` `unique_violation`, which stays transient so that a concurrent duplicate delivery is resolved on retry through the inbox and never emits BillingFailed; held by a test with two concurrent deliveries of one VisitCompleted. M05 test 4.1.9 (overflow requeued, interim) replaced by the permanent path (OQ-23) | approved by the developer (HG-2) |
| DL-37 | 2026-11-11 | The closing scope (about 15 hours) is split: M08, technical debt and operations, 11 hours; M09, README, definition of complete and release, 4 hours. Index sections b, c, d and g updated; total 73 hours (OQ-24) | approved by the developer |
| DL-38 | 2026-11-11 | TD-1 closed by credentials taken only from `.env`: no default in `docker-compose.yml`, keys only in `.env.example`, `docker/postgres/init.sql` as a psql variable template run by `docker/postgres/init.sh`, random passwords per test session. `.env` stays ignored by `.gitignore` and is refused by `git add` (checked at HG-1 and held by the TD-2 test). A clean clone needs `.env` filled before `docker compose up`; the README (M09) says how (OQ-25) | approved by the developer |
| DL-39 | 2026-11-11 | TDD §8.2 and §6.4 amended (TD-6): `is_database_unavailable()` covers connection errors, SQLSTATE class 08, 57P01 to 57P03, 40001 and 40P01; any other `OperationalError` is counted. In Billing, 40001 and 40P01 move from counted (DL-36) to not counted. Accepted risk: a deterministic deadlock caused by a bug repeats for ever and is visible only in the logs (WARNING lines with `cause=database_unavailable`) (OQ-26) | approved by the developer (HG-2), risk accepted |
| DL-40 | 2026-11-11 | TD-2 is part of M08 (OQ-27) | approved by the developer |
| DL-41 | 2026-11-11 | M08 also delivers a restart policy for `api` and `worker`, FastStream's own log lines at WARNING in the application format, and a `migrate` service that receives only `MIGRATIONS_DATABASE_URL` (OQ-28) | approved by the developer |
| DL-42 | 2026-11-11 | SQLSTATE 53300 `too_many_connections` is a temporary condition (database unavailable: backoff, not counted), with 08, 57P, 40001 and 40P01; TD-6 and TDD §8.2 list it; held by tests in `test_consumer_mechanics.py` and `test_billing_classify.py`. Recorded as DL-42 because DL-40 was already taken (TD-2) | approved by the developer (HG-2) |
| DL-43 | 2026-11-11 | Index section g item 4 reads: `docker compose up` from an empty volume, with `.env` filled from `.env.example`, starts every service (OQ-29). DL-42 keeps its number (developer's decision) | approved by the developer |
| DL-44 | 2026-11-11 | Release under HG-3: `git merge --no-ff build/increments` into `main` with the message `Release 1.0: Jiris Health, M01 to M09`, an annotated tag `v1.0.0` on that merge, then `git push origin main` and `git push origin v1.0.0`; only after the developer's explicit yes at a separate stop (OQ-30) | approved by the developer; execution waits for HG-3 |
| DL-45 | 2026-11-11 | After the release merge, the record (merge hash, tag, final status) goes into one `docs:` commit on `build/increments` only; `main` keeps the released snapshot (OQ-31) | approved by the developer |

## 7. Open questions and technical debt

### 7a. Open questions (blocking)

| ID | Question | Agent's recommendation |
|---|---|---|
| (none) | | |

Resolved questions, kept for traceability:

| ID | Question | Answer | Recorded as |
|---|---|---|---|
| OQ-1 | Approve DL-1 (per-table grants and default privileges instead of `ON ALL TABLES`)? | Approved; the `alembic_version` check in T7 stays permanently | DL-1 |
| OQ-2 | Red T1 until M06, or `xfail(strict=True)`? | `xfail(strict=True)`, reason names M06 | DL-6 |
| OQ-3 | Approve BS-3? | Approved without pull requests: local `git merge --no-ff` with `Merge MNN <slug>: IG-7 approved`, then `git push` | DL-7, BS-3 |
| OQ-4 | What to do with the M03 draft written before the contract? | Patch outside the repository (`~/Code/jiris/m03-draft/`), clean working tree, tests first after HG-1 on module-03 | DL-8 |
| OQ-5 | M03: reject naive timestamps at creation with 422? | Yes | DL-13 |
| OQ-6 | M03: limit `app.contracts` to the envelope and VisitCompleted? | Yes | DL-14 |
| OQ-7 | M03: outbox count criterion "for the visit under test"? | Yes | DL-15 |
| OQ-8 | M03: add the row-lock test and the reset test? | Yes | DL-16 |
| OQ-9 | M04: parking routing through `jiris.dlx` | Option A: direct exchange, `x-dead-letter-routing-key` per inbox queue | DL-18 |
| OQ-10 | M04: outbox row with an unknown event type | `attempts` + 1 in a short transaction; rows with `attempts >= 5` leave the selection; ERROR log | DL-19 |
| OQ-11 | M04: when to increment `attempts` | Only for an unknown event type; never for broker unavailability or an unroutable message | DL-19, DL-20 |
| OQ-12 | M04: `mandatory=True` with `on_return_raises=True` | Yes; an unroutable message is handled as a temporary failure with an ERROR log, the row is not excluded | DL-20 |
| OQ-13 | M04: `app/outbox/topology.py`; exchange names and routing keys in `app.contracts` | Yes | DL-21 |
| OQ-14 | M05: `GET /api/billing-records` in the API process with a `billing_app` pool | Yes | DL-24 |
| OQ-15 | M05: interim failure behaviour until M07 | (a) extended: a malformed envelope and a payload that fails its event type's validation go to `billing.parking` at once (R9); (b) yes, until M07 | DL-25 |
| OQ-16 | M05: only BillingRecordCreated in `app.contracts` | Yes | DL-26 |
| OQ-17 | M06: BillingFailed and its Visits handling now | Yes; the Visits side moves from M07 to M06 | DL-29 |
| OQ-18 | M06: reply for an unknown visit | Park in `visits.parking` with ERROR | DL-30 |
| OQ-19 | M06, HG-2: Visits consumer failure policy | Not unlimited requeue: classes as in the relay (database unavailable: backoff, unlimited; malformed: parking; other: counted in `visits.inbox`, parking at 5) | DL-31 |
| OQ-20 | M06: DL-28 by time, not by vhost | Yes | DL-32 |
| OQ-21 | M06: shared consumer mechanics in `app/outbox/consumer.py` | Yes; M05 tests pass unchanged | DL-33 |
| OQ-22 | M07, HG-2: database unavailable in Billing | Yes: backoff to 30 s, unlimited, not counted (D6); D15's 5 attempts for the other transient and unclassified errors | DL-35 |
| OQ-23 | M07, HG-2: SQLSTATE classes 22 and 23 permanent | Yes, except 23505 `unique_violation`, which stays transient; M05 test 4.1.9 replaced | DL-36 |
| OQ-24 | M08: split into M08 and M09 | Yes: M08 11 hours, M09 4 hours; total 73 | DL-37 |
| OQ-25 | M08, TD-1: credentials only from `.env` | Yes; `.env` stays ignored and cannot be committed | DL-38 |
| OQ-26 | M08, HG-2, TD-6: 08, 57P*, 40001, 40P01 not counted | Yes, with the accepted risk recorded | DL-39 |
| OQ-27 | M08: include TD-2 | Yes | DL-40 |
| OQ-28 | M08: restart policy, FastStream log level, reduced `migrate` environment | Yes | DL-41 |
| OQ-29 | M09: index section g item 4 with a filled `.env` | Yes | DL-43 |
| OQ-30 | M09: release mechanics under HG-3 | Option A: `git merge --no-ff build/increments` into `main` with `Release 1.0: Jiris Health, M01 to M09`, annotated tag `v1.0.0`, push of `main` and the tag | DL-44 |
| OQ-31 | M09: post-release record | One `docs:` commit on `build/increments` only | DL-45 |

### 7b. Technical debt summary

Mirrors open entries in `docs/technical-debt.md`.

| ID | Title | State |
|---|---|---|
| TD-1 | Local development credentials written in compose, init.sql and test fixtures | Done (M08, DL-38) |
| TD-2 | `.gitignore` built from a Node.js template, with entries unrelated to this repository | Done (M08, DL-40) |
| TD-3 | Compiled cp315 wheels not verified on manylinux x86_64 | Done (M08) |
| TD-4 | Rejected creation requests (422) leave no command log line | Done (M08) |
| TD-5 | The relay imports aio-pika and pamqp, which reach the lock only through `faststream[rabbit]` | Done (DL-23) |
| TD-6 | Classifier treats every OperationalError as database unavailable | Done (M08, DL-39) |
| TD-7 | BillingFailed reason carries the raw exception text | Done (M08) |

No technical debt is open.
