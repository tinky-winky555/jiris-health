# Gate report M09, IG-7 (completion), README, definition of complete, release

Module: `module-09-release.md` · Date: 2026-11-11 · Branch:
`feature/m09-release` (from `build/increments` at `b4e047e`) · Planning
report: `gate-report-M09-IG-3.md`, approved with HG-1 on 2026-11-11
(DL-43 to DL-45). The merge into `main` (index section g item 6) is not
part of this report: it waits for HG-3 at a separate stop.

## Commits on the branch

| Commit | Content |
|---|---|
| `e308a25` | docs: HG-1 record; index section g item 4 (DL-43); contract DL-43 to DL-45 |
| `c7fa742` | test: `tests/unit/test_readme.py`, committed red |
| `1e9218e` | docs: README; CLAUDE.md COMMANDS local run line |
| `5c2011f` | docs: README after the audit: host port conflict, Alembic in the `migrate` image, `curl -w '\n'` |

## Red run (tests first)

| After | Result |
|---|---|
| `c7fa742`, README test | First run: 30 failed, 2 passed, 1 skipped. The skip was a defect of the test: the COMMANDS section of CLAUDE.md was parsed between the wrong `====` lines, so the command list was empty and those cases would have checked nothing; fixed before the commit; then 34 failed, 7 passed against the scaffolding README, with 9 commands, 10 variables, 7 endpoints and 5 reason codes extracted |
| `1e9218e`, README | 41 passed |

## IG-4. Implementation consistent with the approved scope

- `README.md`: purpose and guarantees, architecture in short, prerequisites,
  setup (`uv sync`, `cp .env.example .env`, a script that fills the
  passwords), run (`docker compose up`, order, ports, a `curl` flow to
  Completed and the billing record), endpoints, test, operations (logs,
  failure behaviour, reason codes, parking queues, what needs an operator,
  purge), configuration, repository layout; links to the PRD, the TDD, the
  Handoff and the Build Spec.
- `CLAUDE.md` COMMANDS: the local run line says `.env` must be filled
  first (repository wins rule, reported here).
- Index section g item 4: "with `.env` filled from `.env.example`"
  (DL-43).
- No application code, schema or compose change.

## IG-5. Validation: audit of index section g

From a fresh clone of the branch (`git clone` into the scratch directory),
following the README literally: its setup script, its `curl` block and
its Alembic block were extracted from `README.md` and executed as they
stand.

| Item of section g | State | Evidence |
|---|---|---|
| 1. Every module M01 to M09 passed its criteria from a clean clone, gate reports present (M01, M02: IG-7 only) | Met for M01 to M08; M09 by this report | `gate-report-M01-IG-7.md`, `M02-IG-7`, and the IG-3 and IG-7 pair of M03 to M08, all approved; M09 IG-3 approved, this IG-7 pending review; no unticked criterion in module-01 to module-08; the fresh-clone suite below covers every module's tests |
| 2. T1 to T8 pass; T1 50 of 50; no `xfail` | Met | Fresh clone at `1e9218e`: `uv run pytest` 449 passed in 196.3 s, 0 xfailed, 0 xpassed, 0 skipped; `grep -rn xfail tests` empty; `uv run pytest tests/integration/test_t1_concurrent_complete.py` 50 passed; T2 2, T3 1, T4 1, T5 1, T6 2, T7 21, T8 26 tests passed |
| 3. `lint-imports`, `alembic -n visits check`, `alembic -n billing check` | Met | `uv run lint-imports`: 3 kept; in the suite `test_models_match_migrations` 2 passed; against the stack, `docker compose run --rm migrate alembic -n visits check` and `-n billing check`: "No new upgrade operations detected", exit 0 |
| 4. `docker compose up` from an empty volume with `.env` filled starts every service; README documents run and test | Met | Fresh clone at `5c2011f`: `cp .env.example .env` and the README script set the six credentials (passwords 32 characters) and left the four URLs empty, as the README says; `.env` ignored, `git status` clean; `docker compose up -d --build` on a new volume: postgres, rabbitmq, api, worker running, migrate exited 0; the README `curl` flow: In Progress, then pending, then Completed, then one record `Created`, `50.00`; the README Alembic block: both checks clean, `visits` downgrade base and upgrade head exit 0; `billing` downgrade base and upgrade head exit 0; `visits_0002 (head)`, `billing_0001 (head)`; `stop worker` exit 0; `down -v`; `.env` deleted. README test 41 passed |
| 5. Contract §7a empty; §7b matches `docs/technical-debt.md` | Met | §7a open rows: none; §7b and the register: TD-1 to TD-7 all Done, compared by script |
| 6. `build/increments` merged into `main` under HG-3 | Pending | Separate HG-3 stop after this report is approved and `feature/m09-release` is merged into `build/increments` (DL-44) |

Module criteria (module-09 section 4): 3.1.1 passes (41); fresh clone
following only the README: met (items 2 and 4); items 1 to 5 of section g
met, item 6 pending; §7a empty and §7b matching; collected count 449 (408
plus 41); the criterion on `main` waits for HG-3.

Verdict tally for this gate: 5 met, 0 not met, 1 pending HG-3 by design.

Audit finding, fixed in `5c2011f`: on this machine a local PostgreSQL
(PID 894) listens on `127.0.0.1:5432` and `[::1]:5432`, so the README's
first Alembic commands, run from the host against `localhost:5432` with
`MIGRATIONS_DATABASE_URL` for the stack, reached that server and failed
with `role "jiris_migrator" does not exist`. The stack itself was
unaffected (its services talk inside the compose network). The README now
says so and runs the commands against the stack inside the `migrate`
image; the local server was not touched. A second, cosmetic finding: the
`curl` responses ran together on one line; `-w '\n'` added.

Branch and count after each commit: `git branch --show-current` returned
`feature/m09-release` after every commit; collected totals 408 after
`e308a25`, 449 after `1e9218e` and `5c2011f`.

## IG-6. Documentation

- `README.md` written; `CLAUDE.md` COMMANDS corrected (local run needs
  `.env`).
- `docs/build-spec/index.md` section g item 4.
- `docs/build-spec/contract.md`: §5, §6 DL-43 to DL-45, §7a resolved
  OQ-29 to OQ-31.
- `module-09-release.md`: criteria ticked from this report, except the
  one on `main`.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| A host PostgreSQL on port 5432 shadows the stack's published port | Host-side database tools reach the wrong server | Documented in the README; the stack is unaffected; a configurable host port would need a default in compose, which the TD-1 rule refuses, so it is not added |
| No CI in this release | The suite runs only where a developer runs it | Index section h (future release) |
| Parked messages have no replay tool | An operator republishes by hand | README, Operations; not in this release |
| Inbox retention | Inbox tables grow | FB-5, next release |

Registers: no new technical debt; no new backlog entry.

## Next: HG-3

After this report is approved, `feature/m09-release` is merged into
`build/increments` (BS-3) and pushed. Then the agent stops again, shows
the commits and files between `main` and `build/increments` and a
fresh-clone run of `build/increments`, and merges into `main` (DL-44)
only after the developer's explicit yes.
