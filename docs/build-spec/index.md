# Build Spec Index, Jiris Health

Structural backbone of the Build Spec. Status, decisions and approvals
live in `contract.md`, not here. Input path B: `docs/PRD.md` and
`docs/TDD.md`.

## a. How to use this set of documents

- Strict sequential execution along section c. A module starts only
  after its prerequisites' acceptance criteria pass and the developer
  approves its document and IG-3 report (HG-1).
- One module per session. Do not open a second module in the same
  session.
- Validate against the module's acceptance criteria before advancing;
  the criteria are binary and reproducible from a clean clone.
- Out of scope is binding, both section h and each module's own list.
  Building an out of scope item is a contract violation, not initiative.
- Source of truth (Path B): `docs/TDD.md` > `docs/PRD.md` > the current
  module > this index. `docs/HANDOFF.md` explains why. On conflict,
  escalate via contract section 7a; never silently pick one.
- Routing: blocking question → contract 7a; conscious compromise →
  `docs/technical-debt.md` mirrored in contract 7b; desirable out of
  scope idea → `docs/feature-backlog.md`.

## b. Module list

| No | Name | Document | Hours |
|---|---|---|---|
| M01 | Repository foundation (built before the contract) | module-01-repository-foundation.md | 6 |
| M02 | Schemas, roles, migrations (built before the contract) | module-02-schemas-roles-migrations.md | 8 |
| M03 | Visits API, completion endpoint and outbox write | module-03-visits-api-and-outbox.md | 10 |
| M04 | Outbox relay and broker topology | module-04-outbox-relay.md (to be authored) | 8 |
| M05 | Billing consumer, happy path | module-05-billing-consumer.md (to be authored) | 10 |
| M06 | Visits consumer; T1 green | module-06-visits-consumer.md (to be authored) | 8 |
| M07 | Failure paths: errors, retries, parking | module-07-failure-paths.md (to be authored) | 10 |
| M08 | Operations and delivery: purge, reconnection, README, release | module-08-operations-delivery.md (to be authored) | 6 |

Total: 66 hours. Module documents M04 to M08 are authored by the agent
one at a time, after the previous module's IG-7 is approved.

## c. Dependency graph

```
M01 -> M02 -> M03 -> M04 -> M05 -> M06 -> M07 -> M08
```

Rationale:

- M03 writes VisitCompleted to the outbox before any relay exists; rows
  simply wait. No stub is needed: the outbox is the designed buffer.
- M04 publishes before any consumer exists; messages wait in durable
  queues. Topology is declared in M04 so that M05 and M06 only subscribe.
- M05 before M06 because Visits consumes Billing's replies.
- T1 (PRD §8) needs M03 to M06; it stays `xfail(strict=True)` until M06
  (contract DL-6) and must turn green there.
- Failure paths (M07) come after the happy path is green end to end, so
  each failure test starts from a working flow.
- M08 closes the delivery: purge job, reconnection proof, documentation,
  merge into `main` under HG-3.

## d. Canonical repository structure

```
jiris-health/
├── CLAUDE.md
├── README.md                       # M08
├── pyproject.toml · uv.lock · .python-version
├── .importlinter                   # three contracts
├── .gitignore · .env.example
├── alembic.ini                     # sections [visits] and [billing]
├── docker-compose.yml              # postgres, rabbitmq, migrate, api, worker
├── Dockerfile                      # python:3.15.2-slim
├── docker/
│   └── postgres/init.sql           # login roles and database grants (TDD §9.1); schemas and DML grants live in the Alembic chains
├── app/
│   ├── contracts/                  # envelope and event models; imports no module
│   ├── visits/
│   │   ├── api.py · service.py · models.py · consumer.py
│   │   └── migrations/             # chain "visits"
│   ├── billing/
│   │   ├── api.py · service.py · models.py · consumer.py
│   │   └── migrations/             # chain "billing"
│   ├── outbox/
│   │   ├── relay.py                # generic relay, per schema and role
│   │   └── topology.py             # exchanges, queues, bindings; declared by the worker (DL-21)
│   ├── main_api.py
│   └── main_worker.py
├── tests/
│   ├── unit/
│   └── integration/                # testcontainers PostgreSQL and RabbitMQ
└── docs/
    ├── PRD.md · TDD.md · HANDOFF.md
    ├── technical-debt.md · feature-backlog.md
    └── build-spec/
        ├── README.md · contract.md · index.md
        ├── module-NN-<slug>.md
        └── gate-report-MNN-IG-3.md / gate-report-MNN-IG-7.md
```

## e. Canonical conventions

Stack and architecture live in the contract. These are repository-level
working conventions.

**Python.**
- uv manages the interpreter and dependencies; every command runs as
  `uv run <tool>`.
- Full type hints on every signature. Async for every I/O function;
  blocking calls in async code are a defect.
- Pydantic v2 for every boundary shape (HTTP bodies, events, settings).
- Naming: modules snake_case, classes PascalCase, constants
  UPPER_SNAKE_CASE. Tests `test_<behaviour>`, arrange, act, assert; no
  test reads another test's state.
- `app.visits` and `app.billing` never import each other; `app.contracts`
  and `app.outbox` import neither (import-linter).

**API shape.** Paths under `/api`. Codes and bodies as contract
section 3. Visit body: `id`, `start_date_time`, `end_date_time`,
`description`, `rate` (decimal string), `status`,
`completion_requested_at`, `completion_attempt_id`,
`completion_failure_reason`, `completion_pending`.

**Events.** Envelope `event_id`, `event_type`, `schema_version`,
`occurred_at`, `payload`; routing keys `visits.visit_completed`,
`billing.record_created`, `billing.failed`; JSON, persistent,
`message_id` = `event_id`.

**Database.** Primary keys uuid; timestamps timestamptz; snake_case;
no cross-schema foreign keys; CHECK constraints for statuses and
invariants, named `ck_<table>_<purpose>`; indexes named
`ix_<table>_<purpose>`, unique indexes `ux_<purpose>` (as built in M02:
`ix_outbox_unpublished`, `ux_active_record`).

**Testing.** Tiers: `tests/unit` (pure logic: amount, classification,
validation), `tests/integration` (real PostgreSQL and RabbitMQ). Every
consumer has its idempotency test. T1 runs 50 times. Integration tests
wait for eventual state by polling with a 10 s timeout.

**Git.** As contract BS-3: no pull requests; after an approved IG-7,
`git merge --no-ff` of the feature branch into `build/increments` with
the message `Merge MNN <slug>: IG-7 approved`, then `git push`. Commit
messages in English, imperative mood, Conventional Commits prefix
(`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `build:` for build and
infrastructure files), no Claude attribution lines. After each commit:
`git branch --show-current` and the collected test count (CLAUDE.md,
definition of done, item 6).

**Environment.** `VISITS_DATABASE_URL`, `BILLING_DATABASE_URL`,
`MIGRATIONS_DATABASE_URL`, `RABBITMQ_URL`; relay and retry parameters as
TDD §10.

**Logging.** As contract section 3.

**Writing.** British corporate English in artefacts; Russian in chat;
no em or en dashes; concrete wording.

## f. Canonical glossary

| Term | Definition |
|---|---|
| Visit | A scheduled period during which a caregiver provides services to a patient; a `visits.visit` row |
| Billing record | A billing entry created for a completed visit; a `billing.billing_record` row |
| Active record | A billing record with status Created; at most one per visit |
| Completion attempt | One accepted `/complete`; identified by `completion_attempt_id`, equal to the VisitCompleted `event_id` |
| Pending completion | `completion_requested_at` set and status not Completed; exposed as `completion_pending` |
| Outbox | Module table holding outgoing events written in the same transaction as the state change |
| Relay | Worker loop publishing outbox rows and marking them published after a publisher confirm |
| Inbox | Module table of processed `event_id`s; in Billing also the attempt counter and last error |
| Transient error | Database connectivity, timeout or broker error; retried up to 5 times |
| Permanent error | Invalid payload for billing (for example non-positive duration); fails at once |
| Parking queue | Dead-letter queue for malformed or exhausted messages |
| Reply | BillingRecordCreated or BillingFailed sent by Billing for one completion attempt |

## g. Definition of complete

1. Every module M01 to M08 has passed its acceptance criteria from a
   clean clone, with its gate reports present (M01 and M02: IG-7 only).
2. T1 to T8 (PRD §8) pass; T1 passes 50 of 50 runs; no `xfail` remains.
3. `lint-imports`, `alembic -n visits check` and `alembic -n billing
   check` pass.
4. `docker compose up` from an empty volume starts postgres, rabbitmq,
   migrate (exit 0), api and worker; README documents run and test.
5. Contract section 7a is empty; 7b matches `docs/technical-debt.md`.
6. `build/increments` merged into `main` under HG-3.

## h. Out of scope of this release

| Item | Destination |
|---|---|
| Reversal operation and BillingRecordReversed | Next release (Handoff §12) |
| `Idempotency-Key` header on `/complete` | Next release |
| LISTEN/NOTIFY wake-up for the relay | Future release |
| Actual visit start and end times; billing on actual duration | Future release |
| Authentication and authorisation | Future release |
| Cloud hosting, CI/CD pipeline | Future release |
| Splitting Visits and Billing into separate services | Future release (schema per module keeps it a configuration change) |

## i. Document inventory

| Document | Path |
|---|---|
| Contract | docs/build-spec/contract.md |
| Index (this document) | docs/build-spec/index.md |
| Build Spec area guide | docs/build-spec/README.md |
| Technical debt register | docs/technical-debt.md |
| Feature backlog register | docs/feature-backlog.md |
| Module 01, Repository foundation | docs/build-spec/module-01-repository-foundation.md |
| Module 02, Schemas, roles, migrations | docs/build-spec/module-02-schemas-roles-migrations.md |
| Module 03, Visits API and outbox | docs/build-spec/module-03-visits-api-and-outbox.md |
| Modules 04 to 08 | to be authored, section b |
| Gate reports | docs/build-spec/gate-report-MNN-IG-3.md and gate-report-MNN-IG-7.md |
