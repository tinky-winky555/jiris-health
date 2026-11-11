# Technical debt register, Jiris Health

Technical compromises consciously accepted during construction. Open
entries are mirrored in contract section 7b.

States: Open · In progress · Blocked (Reason names the external dependency) · Paused (Reason names the priority decision) · Done.

| ID | Title | State | Reason | Owner | Source module | Notes |
|---|---|---|---|---|---|---|
| TD-1 | Local development credentials written in compose, init.sql and test fixtures | Open | | Sasha | M01 | `docker-compose.yml` (`x-app-env`, postgres service), `docker/postgres/init.sql` (role passwords) and `tests/integration/conftest.py` carry fixed local passwords (`postgres`, role name as password, `guest`). Acceptable for local run and testcontainers only; no deployment exists in this delivery. Close in M08: compose reads the values from `.env` (keys in `.env.example`), init.sql takes passwords from the environment |
| TD-2 | `.gitignore` built from a Node.js template, with entries unrelated to this repository | Open | | Sasha | M01 | Contains Next.js, Vercel and npm entries and unrelated paths (`/scripts`, `/roadmap`, `/doc`, `db/scripts/issued/`, `*.jwt`, `ca/*.crt`, `.spec-pipeline/`). `/scripts` would silently ignore a future scripts folder. Close in M08: replace with the Python entries actually used, keeping `.env*` with `!.env.example` and `.import_linter_cache/` |
| TD-3 | Compiled cp315 wheels not verified on manylinux x86_64 | Open | | Sasha | M01 | Verified on macOS arm64 (`uv sync`) and manylinux aarch64 (Docker image build, `uv sync --frozen --no-dev`). An x86_64 host could fail on a missing wheel for asyncpg, pydantic-core, greenlet, uvloop, httptools, multidict or yarl. Close in M08: build the image with `docker build --platform linux/amd64` and record the result |
| TD-4 | Rejected creation requests (422) leave no command log line | Open | | Sasha | M03 | FastAPI validates the body before the handler runs, so `POST /api/visits` with an invalid body is answered 422 without the line that contract section 3 asks for each command. Close in M08: a `RequestValidationError` handler that writes the line and returns the FastAPI default body |
| TD-5 | The relay imports aio-pika and pamqp, which reach the lock only through `faststream[rabbit]` | Open | | Sasha | M04 | `app/outbox/relay.py` uses `aio_pika.exceptions.PublishError` (unroutable) and `pamqp.commands.Basic.Ack` (confirm type); the tests use `aio_pika` directly. A FastStream release that changes its transport would break them without a lock conflict. Close in M08: declare `aio-pika` and `pamqp` in `pyproject.toml` with lower bounds (a dependency change, developer decision) |
