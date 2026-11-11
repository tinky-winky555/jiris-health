# CLAUDE.md, Jiris Health (repository root)

This file is read by the coding agent (Claude Code) before any task in this repository. It defines the Execution Safety Envelope, the system in short, the invariants, the stack and the definition of done. Detailed procedures live in the documents it references; this file stays operational.

================================================================
EXECUTION SAFETY ENVELOPE, PROJECT OPERATING DEFAULT
================================================================
Jiris Health is a greenfield build. All non-trivial work runs under the
FULL ENVELOPE, executed under the Build Spec in `docs/build-spec/`. The
Build Spec is the roadmap, checklist, sequence and instruction set; do
not create parallel roadmap, checklist, contract, index or gate
artefacts.

THE THREE MODES
Every task is classified before implementation starts.

Fast Path: only small, low-risk, localised changes with no meaningful
functional impact: documentation-only updates; wording, comments or
naming corrections; localised refactors with no behaviour change;
narrow bug fixes with low blast radius and no architectural impact.
Fast Path is NOT allowed for: new features, module work, API, schema,
role, migration, queue, topology, compose or dependency changes, any
change with unclear scope.

Full Envelope: the default here. Module by module under the approved
Build Spec, each module with its gate-report pair
(`gate-report-MNN-IG-3.md` before code, `gate-report-MNN-IG-7.md` at
completion).

Evolution Envelope: not active. It becomes available only after the
delivery is complete (index section g) and only by the developer's
decision, recorded in contract section 6.

If the mode is unclear: Full Envelope.

INTERNAL GATES (owned by the agent; reported in the gate-report pair)
IG-1 scope and affected surfaces identified · IG-2 dependencies, risks,
assumptions identified · IG-3 execution sequence is clear · IG-4
implementation consistent with approved scope · IG-5 validation
completed for the affected area · IG-6 documentation updated where
materially required · IG-7 residual risks and follow-ups reported.

HUMAN GATES (owned by the developer; the agent stops and waits)
HG-1 approval of the contract, then of each module document and its
IG-3 report before code · HG-2 architecture or trade-off decisions with
lasting impact, any deviation from TDD · HG-3 merge into `main`, history
rewrite, destructive database action outside a test container · HG-4
material scope expansion during implementation.
Do not stop only for ceremony.

ESCALATION RULE
If a Fast Path task reveals hidden scope, cross-module impact, contract
changes or non-trivial risk: pause, summarise what was discovered,
escalate to the Full Envelope. Silent escalation is not permitted.

ROUTING RULES DURING EXECUTION
- Need an answer from the developer to proceed: add it to contract
  section 7a (Open questions) and pause.
- Took a conscious decision that leaves something suboptimal: entry in
  `docs/technical-debt.md`, mirrored in contract section 7b.
- Identified something desirable but out of scope: entry in
  `docs/feature-backlog.md`, no contract update.

================================================================
SOURCE OF TRUTH HIERARCHY (Path B)
================================================================
docs/TDD.md > docs/PRD.md > the current Build Spec module > the Build
Spec index. `docs/HANDOFF.md` holds the rationale of every decision
(D1 to D30, R1 to R9); read it when a decision looks wrong before
proposing to change it. Escalate on conflict (contract section 7a); do
not silently pick one.

================================================================
THE SYSTEM (condensed; full design in docs/TDD.md)
================================================================
A modular monolith, two processes on one codebase:
- API process (FastAPI): Visits HTTP API. `POST /api/visits/{id}/complete`
  validates the status, sets `completion_requested_at` and writes
  VisitCompleted to `visits.outbox` in ONE transaction, answers 202.
  Never calls Billing.
- Worker process: two outbox relays (visits, billing), two consumers
  (Billing on `billing.inbox`, Visits on `visits.inbox`), the outbox
  purge job.
- PostgreSQL: one database, schemas `visits` and `billing`, one role per
  module (`visits_app`, `billing_app`), migrations by `jiris_migrator`.
- RabbitMQ: topic exchange `jiris.events`, queues `billing.inbox` and
  `visits.inbox`, dead-letter exchange `jiris.dlx` with parking queues.
Flow: VisitCompleted → Billing creates the record and replies
BillingRecordCreated or BillingFailed → Visits sets Completed or resets.
Delivery is at-least-once: every consumer is idempotent.

================================================================
ARCHITECTURE INVARIANTS (do not break)
================================================================
- Build in modules: implement only the current module; never close a
  seam a later module needs.
- Events, not calls: Visits and Billing never read or write each other's
  tables and never import each other; they share only `app.contracts`.
  Enforced by database grants and import-linter.
- Outbox: a state change and its event are written in one local
  transaction. Nothing publishes to RabbitMQ except the relay.
- Inbox: consumers de-duplicate by `event_id` and ack only after COMMIT.
- One active billing record per visit: partial unique index
  `(visit_id) WHERE status = 'Created'`.
- `/complete` serialises through the conditional UPDATE of TDD §6.2;
  the winner gets 202, everyone else 409.
- Visits applies a Billing reply only when `completion_attempt_id`
  matches the current attempt.
- Money is Decimal, 2 places, ROUND_HALF_UP; in events a decimal string.

================================================================
REPOSITORY LAYOUT
================================================================
See TDD §4 and index section d. In short: `app/{contracts,visits,
billing,outbox}`, `app/main_api.py`, `app/main_worker.py`, `tests/`,
`docker/`, `docs/` (PRD, TDD, HANDOFF, registers, build-spec/).

================================================================
STACK AND CONVENTIONS
================================================================
Python 3.15.2 or later, managed by uv. FastAPI, SQLAlchemy 2 async +
asyncpg, Alembic (two chains), FastStream over aio-pika, Pydantic v2.
pytest, httpx, testcontainers. import-linter. docker-compose (postgres,
rabbitmq, migrate, api, worker). Conventions: index section e.

================================================================
COMMANDS
================================================================
Package manager: uv (`pyproject.toml`, `uv.lock`, Python pinned in `.python-version`).

- Install: `uv sync`
- Tests: `uv run pytest` (T1 only: `uv run pytest tests/integration/test_t1_concurrent_complete.py`)
- Boundaries: `uv run lint-imports`
- Migrations: `uv run alembic -n visits upgrade head`, `uv run alembic -n billing upgrade head`
- Drift check: `uv run alembic -n visits check`, `uv run alembic -n billing check`
  (needs `MIGRATIONS_DATABASE_URL` pointing at a database migrated to head;
  the suite runs both checks in `tests/integration/test_migrations.py`
  against testcontainers)
- Local run: `docker compose up` (migrate runs first, then api and worker);
  `.env` must be filled from `.env.example` first (README, Setup)
If a command here differs from what the repository actually uses, the
repository wins: correct this section and say so in the next gate report.

================================================================
DATABASE AND MIGRATIONS (never bend)
================================================================
- Migrations run only as `jiris_migrator` (`MIGRATIONS_DATABASE_URL`),
  via the `migrate` compose service or a test fixture; never from the
  application roles.
- Application roles hold DML on their own module's tables only; no DDL,
  no access to `alembic_version` (contract section 6, DL-1).
- `alembic -n <chain> check` must stay clean: models and migrations
  never diverge.

================================================================
TESTING (test-driven)
================================================================
Test first: write the failing test from PRD §8 or the module's
acceptance criteria, then the code. Integration tests use real
PostgreSQL and RabbitMQ in testcontainers, never mocks of them. Every
consumer has the idempotency test: a repeated message changes nothing.
A test that cannot pass until a later module is marked
`xfail(strict=True)` with the module that will close it (contract 7a,
OQ-2).

================================================================
SECRETS AND CONFIG
================================================================
No hardcoded secrets. Env vars: `VISITS_DATABASE_URL`,
`BILLING_DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, `RABBITMQ_URL`.
Never commit `.env`; `.env.example` holds keys only.

================================================================
GIT
================================================================
See index section e (Git) and contract BS-3. Commits authored as
`gunsareloaded@proton.me`; check `git config user.email` before the
first commit of a session. Commit messages in English, imperative mood,
no Claude attribution lines. Never push to `main` without HG-3; never
force-push; never rewrite published history.

================================================================
DEFINITION OF DONE (for any module)
================================================================
1. The module's binary acceptance criteria pass from a clean clone.
2. The full test suite passes (xfail entries only as listed in the
   module); `lint-imports` passes; `alembic -n visits check` and
   `alembic -n billing check` pass.
3. No invariant above is violated; out of scope items were not built.
4. Documentation materially affected is updated (IG-6).
5. Contract section 5 is updated; the IG-7 report exists.
6. After every commit, verify the branch and the test count, not only
   that the run is green: `git branch --show-current` must be the
   module's branch, and the collected total must be at least the
   previous total. A suite that shrinks passes silently.

================================================================
WRITING
================================================================
- Chat with the developer (Sasha) in Russian.
- Every artefact (code, comments, commits, docs, gate reports, register
  entries) in British corporate English.
- No em dashes or en dashes anywhere; use commas, semicolons,
  parentheses or full stops. Be concrete; never "appropriate", "as
  needed", "standard", "best practice".
