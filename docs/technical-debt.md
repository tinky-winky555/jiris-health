# Technical debt register, Jiris Health

Technical compromises consciously accepted during construction. Open
entries are mirrored in contract section 7b.

States: Open · In progress · Blocked (Reason names the external dependency) · Paused (Reason names the priority decision) · Done.

| ID | Title | State | Reason | Owner | Source module | Notes |
|---|---|---|---|---|---|---|
| TD-1 | Local development credentials written in compose, init.sql and test fixtures | Open | | Sasha | M01 | `docker-compose.yml` (`x-app-env`, postgres service), `docker/postgres/init.sql` (role passwords) and `tests/integration/conftest.py` carry fixed local passwords (`postgres`, role name as password, `guest`). Acceptable for local run and testcontainers only; no deployment exists in this delivery. Close in M08: compose reads the values from `.env` (keys in `.env.example`), init.sql takes passwords from the environment |
| TD-2 | `.gitignore` built from a Node.js template, with entries unrelated to this repository | Open | | Sasha | M01 | Contains Next.js, Vercel and npm entries and unrelated paths (`/scripts`, `/roadmap`, `/doc`, `db/scripts/issued/`, `*.jwt`, `ca/*.crt`, `.spec-pipeline/`). `/scripts` would silently ignore a future scripts folder. Close in M08: replace with the Python entries actually used, keeping `.env*` with `!.env.example` and `.import_linter_cache/` |
