# Module 09, README, definition of complete, release

Effort: 4 hours (split from M08, DL-37) · Prerequisites: M01 to M08

## 1. Goal

Deliver the README a new developer needs to run and test the service,
audit the definition of complete (index section g) from a clean clone
by following that README, and, under HG-3, merge `build/increments` into
`main`. It adds no behaviour.

## 2. Prerequisites

- M08 acceptance criteria pass; M08 merged into `build/increments`
  (`b4e047e`).
- HG-1 on this document and `gate-report-M09-IG-3.md` given by Sasha on
  2026-11-11, with OQ-29 to OQ-31 answered (DL-43 to DL-45).

## 3. Tasks

3.1 Tests first (each seen failing before the README change):
- 3.1.1 Unit, README: it names every command of CLAUDE.md COMMANDS
  (`uv sync`, `uv run pytest`, `uv run lint-imports`, both `alembic
  upgrade` and both `alembic check`, `docker compose up`); every
  variable of `.env.example`; the step `cp .env.example .env`; every
  endpoint of TDD §6.1; the failure reason codes of TDD §7; the parking
  queues; and links to `docs/PRD.md`, `docs/TDD.md`, `docs/HANDOFF.md`
  and `docs/build-spec/`. It holds no em or en dash and no literal
  credential.
3.2 README.md, written in British English:
- what the service does and its guarantees (PRD §1, §7), in one screen;
- architecture in short, with a pointer to TDD §2;
- prerequisites: uv, Python 3.15.2 (installed by uv), Docker;
- setup: `uv sync`; `cp .env.example .env` and how to fill it (one
  command that generates passwords);
- run: `docker compose up` (what starts, in which order, ports), then a
  complete flow with `curl` from creation to Completed and the billing
  record;
- test: `uv run pytest` (Docker required, duration about 3 minutes), T1
  alone, `lint-imports`, the drift check;
- operations: logs and their fields, the parking queues and what lands
  there, the failure reason codes, the outbox purge, recovery from a
  broker or database outage, what needs an operator (parked messages,
  replies parked after 5 attempts);
- configuration table (TDD §10) and repository layout (index section d).
3.3 CLAUDE.md COMMANDS: the local run line states that `.env` must be
filled first (repository wins rule; reported in the IG-7 report).
3.4 Index section g audit, from a fresh clone, following the README
literally: each item of section g with its evidence in the IG-7 report,
including `alembic downgrade base` and `upgrade head` for both chains on
a throwaway database, the compose run from an empty volume and the
`curl` flow of the README.
3.5 Index section g item 4 amended if OQ-29 is approved.
3.6 Release under HG-3 (a separate stop after the IG-7 report is
approved and `feature/m09-release` is merged into `build/increments`):
the agent presents the final state (commits and files between `main`
and `build/increments`, the clean-clone result) and waits for the
developer's explicit yes; then the merge as OQ-30, the push, and the
post-release record as OQ-31.

## 4. Acceptance criteria

- [x] 3.1.1 passes.
- [x] A fresh clone, following only the README, installs, runs the full
  suite green (T1 50 of 50, no `xfail`), and brings the stack up from an
  empty volume with every service started and `migrate` exit 0; the
  README's `curl` flow ends Completed with one billing record.
- [x] Every item of index section g is met with evidence, except item 6
  (the merge into `main`), which waits for HG-3.
- [x] Contract section 7a is empty and section 7b matches
  `docs/technical-debt.md`.
- [x] Collected test count is at least 408 plus the new tests.
- [x] After HG-3 only: `main` holds the release merge (and the tag, if
  OQ-30 says so) on `origin`.

Completion report: `gate-report-M09-IG-7.md`; the criterion on `main`
ticked from the release record in that report (HG-3, `4b505cf`, `v1.0.0`).

## 5. Out of scope

| Item | Destination |
|---|---|
| CI pipeline, hosting | Future release (index section h) |
| Inbox retention | Backlog FB-5 |
| Reversal, `Idempotency-Key`, LISTEN/NOTIFY | Backlog FB-1, FB-2, FB-3 |

## 6. What comes next

Nothing in this delivery. The Evolution Envelope becomes available after
the merge into `main`, by the developer's decision (CLAUDE.md, contract
section 6).
