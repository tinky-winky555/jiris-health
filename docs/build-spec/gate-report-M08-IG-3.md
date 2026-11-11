# Gate report M08, IG-3 (planning), Technical debt and operations

Module: `module-08-operations-delivery.md` · Date: 2026-11-11 · Branch:
`feature/m08-operations-delivery`, created from `build/increments` at
`64ef30c` (M07 merged) · Baseline: 353 collected, 353 passed.

HG-1 given by Sasha on 2026-11-11: OQ-24 yes, M08 11 hours and M09 4
hours (DL-37); OQ-25 yes, `.env` checked as ignored and refused by `git
add` (DL-38); OQ-26 yes with the accepted risk below (DL-39); OQ-27 and
OQ-28 yes (DL-40, DL-41); FB-5 stays in the backlog for the next release.

## Effort

The requested scope, estimated item by item:

| Item | Hours |
|---|---|
| R5 outbox purge, tests, worker loop | 2.0 |
| R7 reconnection proof (broker down at start, closed connections) | 1.5 |
| TD-1 credentials from `.env`, init template, random test passwords | 2.0 |
| TD-3 amd64 build and import check | 1.0 |
| TD-4 422 logging | 0.5 |
| TD-6 SQLSTATE narrowing | 1.0 |
| TD-7 stable reason codes | 1.0 |
| README | 1.5 |
| Index section g audit from a clean clone | 1.0 |
| Merge into `main` under HG-3 | 0.5 |
| Reports, registers, documentation | 1.0 |
| TD-2 and the OQ-28 follow-ups, if approved | 1.0 |
| Total | 14.0 to 15.0 |

Above the 12-hour limit of BS-2, hence OQ-24: M08 (all rows except the
README, the audit and the merge) at 11 hours, and M09 at 4 hours (README
1.5, audit 1.0, merge 0.5, reports 1.0). This report plans M08 as split;
if OQ-24 is refused, the M09 rows are appended as tasks 3.11 to 3.13.

## IG-1. Scope and affected surfaces

| Surface | Change |
|---|---|
| `app/outbox/purge.py` (new) | Batched purge of published outbox rows older than 7 days |
| `app/main_worker.py` | Purge loop for both schemas; FastStream log level |
| `app/outbox/consumer.py` | `is_database_unavailable()` narrowed (TD-6) |
| `app/billing/service.py`, `app/billing/consumer.py` | Stable reason codes (TD-7); classification follows TD-6 |
| `app/main_api.py` | `RequestValidationError` handler with the command log line (TD-4) |
| `docker-compose.yml`, `docker/postgres/init.sql`, `docker/postgres/init.sh` (new), `.env.example` | Credentials from `.env` only; `migrate` environment reduced; restart policy (TD-1, OQ-28) |
| `.gitignore` | Rewritten (TD-2) |
| `tests/` | Purge, R7, TD-1, TD-2, TD-4, TD-6, TD-7, OQ-28 tests; `conftest.py` random session passwords; T4 and T5 assert the reason codes; M07 classification cases for 40001 and 40P01 change if OQ-26 is approved |
| `docs/` | TDD §7, §8.1, §8.2; technical debt register; contract §5, §6, §7b; index section b if OQ-24 is approved |

Not touched: the schema and migrations, the topology, the relay loop, the
Visits service.

## IG-2. Dependencies, risks, assumptions, edge cases

Dependencies:

- M07 complete and merged (`64ef30c`). Met.
- Docker Desktop with buildx and QEMU for the amd64 build (TD-3).

Assumptions:

| ID | Assumption | Consequence if false |
|---|---|---|
| A1 | `rabbitmqctl close_all_connections` drops the worker's AMQP connections without stopping the broker, and aio-pika's robust connection reopens them and restores the consumers | R7 needs another fault; T3 already proves recovery after a restart |
| A2 | The postgres image runs `*.sh` scripts in `docker-entrypoint-initdb.d` with the container environment, so `init.sh` can pass passwords to `psql -v` | The template would be rendered by a compose one-shot service instead |
| A3 | A `DELETE ... WHERE event_id IN (SELECT ... LIMIT n)` as `visits_app` or `billing_app` deletes only published old rows and does not block the relay's `FOR UPDATE SKIP LOCKED` longer than one batch | Smaller batches; the relay skips locked rows anyway |
| A4 | Docker Desktop on this arm64 host can build `linux/amd64` with QEMU in reasonable time | TD-3 stays open with the attempt recorded |

Risks:

| Risk | Mitigation |
|---|---|
| TD-1 changes how every developer starts the stack (`.env` required) | README in M09; a clear compose error when a variable is missing (`${VAR:?}`) |
| Random test passwords must reach the worker subprocesses and every fixture | One session `Stack` carries them; no test builds a URL by hand |
| TD-6 changes classification in both consumers | Unit cases for each SQLSTATE; T4, T5 and the M06 consumer tests rerun |
| The purge deletes rows that a slow relay pass still holds | It deletes only `published_at < now() - 7 days`; the relay never selects published rows |
| Reason codes change the text that API clients see after a failure | Codes are stable and documented in TDD §7; no client depends on the old text |
| Accepted risk (DL-39): with 40001 and 40P01 not counted, a deterministic deadlock caused by a bug repeats for ever | Visible only in the logs, as WARNING lines with `cause=database_unavailable`; accepted by the developer |

Edge cases covered by tests:

- Purge: exactly 7 days, 7 days and 1 second, unpublished 30 days old,
  excluded rows, more than one batch, empty outbox.
- R7: broker down at start; connections closed while idle and while a
  completion is in flight.
- TD-7: each code; raw text present in `last_error`, absent from the
  reply and from the API body.
- TD-4: 422 on creation and on the billing records query, body unchanged.

## IG-3. Execution sequence (tests first)

1. After HG-1: commit `module-08`, this report, contract §5, §6, §7a,
   index section b (`docs:`).
2. Tests (`test:` commit): 3.1.1 to 3.1.10 and the T4, T5 code
   assertions; red run recorded.
3. `app/outbox/purge.py` and the worker loop (`feat:`).
4. TD-1 and OQ-28 compose changes, init template, fixtures (`build:` and
   `test:`).
5. TD-4 (`feat:`), TD-6 (`fix:`), TD-7 (`feat:`), TD-2 (`chore:`).
6. TD-3 amd64 build and import check; evidence recorded.
7. Registers and documentation (`docs:`).
8. Validation: clean clone; full suite in file order and with the T1
   module first; R7 and purge tests three times; `docker compose up` from
   an empty volume with a filled `.env`; branch and count after every
   commit.
9. `gate-report-M08-IG-7.md`, checkboxes, contract §5; stop for approval;
   merge per BS-3.

## Questions for HG-1 (contract section 7a)

Answered at HG-1; the answers are in the contract (section 7a, resolved,
and DL-37 to DL-41). The questions as asked:

| ID | Question | Agent's recommendation |
|---|---|---|
| OQ-24 | Split into M08 (11 h) and M09 (4 h); total 73 h? | Yes |
| OQ-25 | TD-1: credentials only from `.env`, keys only in `.env.example`, init template, random test passwords; a clean clone needs `.env` filled? | Yes |
| OQ-26 | HG-2, TD-6: 08, 57P*, 40001, 40P01 not counted; other `OperationalError` counted; M07 cases for 40001 and 40P01 change? | Yes |
| OQ-27 | Include TD-2? | Yes |
| OQ-28 | Include restart policy, FastStream log level, reduced `migrate` environment? | Yes |
