# Gate report M01, IG-7 (completion), Repository foundation

Module: `module-01-repository-foundation.md` · Date: 2026-11-11 ·
Retrospective: M01 was built before the contract and committed as
`6c707c0` on `build/increments`. No planning report exists (contract
section 4). Evidence was collected from the repository as it stands at
adoption.

## IG-4. Implementation consistent with the approved scope

- Tasks 3.1 to 3.7 are present at `6c707c0`: `pyproject.toml`, `uv.lock`
  and `.python-version` (3.15.2); the TDD §4 package layout with
  docstring-only modules; `.importlinter` with three contracts;
  `docker-compose.yml` (postgres, rabbitmq, migrate, api, worker);
  `Dockerfile` on `python:3.15.2-slim`; `docker/postgres/init.sql`;
  `tests/integration/test_t1_concurrent_complete.py` parametrised 50
  times; `.gitignore` with `/tests` removed and `.import_linter_cache/`
  added.
- Out of scope respected: at `6c707c0`, `models.py`, `service.py`,
  `api.py`, `consumer.py` and `relay.py` hold a docstring only; there are
  no migrations.
- Deviations from the module text, corrected at adoption (contract DL-9):
  `.gitignore` is a Node.js template with a Python block, not the GitHub
  Python template (task 3.7 reworded, cleanup in TD-2); the T1 criterion
  is worded for the `xfail(strict=True)` marker (DL-6).
- Not as BS-3: M01 was committed directly on `build/increments`, before
  BS-3 existed. History is kept as it is (DL-7).

## IG-5. Validation

| Criterion | State | Evidence |
|---|---|---|
| `uv sync` succeeds on a clean clone with Python 3.15.2 | Met | `git clone --branch build/increments` into a scratch folder, `uv sync` exit 0, `uv run python --version` gives `Python 3.15.2` |
| `uv run lint-imports` reports 3 contracts kept | Met | `Contracts: 3 kept, 0 broken.` in the working tree and in the clean clone |
| `docker compose config` validates | Met | `docker compose config -q`, exit 0 |
| T1 exists, is collected 50 times, and is reported xfailed because the worker is not built; no collection or syntax error | Met | `uv run pytest -rx`: 50 lines `XFAIL at setup of ...test_t1_concurrent_complete_yields_one_winner_and_one_billing_record[0..49] - needs relay and consumers; removed in M06` |
| `git check-ignore tests/integration/test_t1_concurrent_complete.py` returns nothing | Met | No output, exit 1 |

Verdict tally: 5 met, 0 not met, 0 not verified.

Task 3.1 (compiled wheels): verified on macOS arm64 (`uv sync` from the
clean clone) and on manylinux aarch64 (`docker compose build` with
`uv sync --frozen --no-dev`, image architecture `arm64`). Not verified on
manylinux x86_64; see residual risks.

Suite at adoption: 73 collected, 23 passed, 50 xfailed (T1). At
`aed4672`, before the adoption changes: 71 collected, 21 passed, 50
xfailed.

## IG-6. Documentation

- `docs/build-spec/index.md` section d: `init.sql` described as login
  roles and database grants.
- `module-01-repository-foundation.md`: task 3.7 and the T1 criterion
  reworded; criteria ticked from this report.
- `CLAUDE.md` COMMANDS: the package manager line restored from the
  previous version; the drift check line now states that it needs
  `MIGRATIONS_DATABASE_URL` and a migrated database, and that the suite
  runs it in `tests/integration/test_migrations.py` (repository wins
  rule).
- `.env.example` added with the four keys only (contract section 3).
- `README.md` is still the scaffolding version; it is completed in M08.

## IG-7. Residual risks and follow-ups

| Risk or follow-up | Impact | Handling |
|---|---|---|
| Compiled wheels not verified on manylinux x86_64 | A build on an x86_64 host could fail on a missing cp315 wheel | Verify when an x86_64 host or CI is available; no host in this delivery |
| Local credentials written in compose, init.sql and fixtures | Not suitable outside local run and tests | TD-1, close in M08 |
| `.gitignore` carries unrelated entries; `/scripts` would hide a future scripts folder | A new file could be silently left out of a commit | TD-2, close in M08 |
| T1 xfails at fixture setup, not at an assertion | Until M06, any other setup failure of the worker fixture is also reported as xfailed; `strict=True` only catches an unexpected pass | Accepted until M06 (DL-6); M06 removes the marker |
| README does not yet name the `migrate` service | Run instructions incomplete | M08 |

Registers: TD-1 and TD-2 opened in `docs/technical-debt.md` and mirrored
in contract section 7b. No backlog entry.
