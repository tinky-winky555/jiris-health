# Jiris Health

A small back-end service that records caregiver visits and bills every completed visit
exactly once. It is a modular monolith with two modules, Visits and Billing, that never
read each other's tables and talk only through events over RabbitMQ.

Guarantees, each proven by the automated tests T1 to T8 ([PRD §8](docs/PRD.md)):

- a completed visit always gets a billing record, even when the broker is down (T3);
- a visit never gets two active billing records, under duplicate delivery (T2) or two
  concurrent `/complete` requests (T1);
- an event that could not be published is published later with no manual step;
- a Billing failure is reported back and the visit can be completed again (T4, T5);
- a reply for an older completion attempt is ignored (T6);
- each module's database role sees only its own schema (T7).

Design: [PRD](docs/PRD.md) (what), [TDD](docs/TDD.md) (how), [Handoff](docs/HANDOFF.md)
(why each decision), [Build Spec](docs/build-spec/) (how it was built, module by module).

## Architecture in short

Two processes on one codebase ([TDD §2](docs/TDD.md)):

- **API** (FastAPI): the Visits HTTP API. `POST /api/visits/{id}/complete` marks the visit
  pending and writes a VisitCompleted event to the `visits.outbox` table in the same
  transaction, then answers 202. It never calls Billing and never touches the broker.
- **Worker**: two outbox relays (they publish outbox rows to RabbitMQ with publisher
  confirms), the Billing consumer (creates the billing record and replies), the Visits
  consumer (sets the visit Completed, or resets it after a failure), and the outbox purge.

Flow: VisitCompleted → Billing creates the record and replies BillingRecordCreated or
BillingFailed → Visits sets the visit Completed or resets it. Delivery is at least once;
every consumer de-duplicates by `event_id` through its inbox table.

PostgreSQL holds one database with the schemas `visits` and `billing`, one role per module
(`visits_app`, `billing_app`) and a migration owner (`jiris_migrator`). RabbitMQ holds the
topic exchange `jiris.events`, the queues `billing.inbox` and `visits.inbox`, and the parking
queues `billing.parking` and `visits.parking` behind the dead-letter exchange `jiris.dlx`.

## Prerequisites

- [uv](https://docs.astral.sh/uv/); it installs Python 3.15.2 from `.python-version`.
- Docker with Docker Compose (the stack and the integration tests run in containers).

## Setup

```sh
uv sync                      # create .venv with every dependency
cp .env.example .env         # .env is ignored by git and never committed
```

Fill every empty value of the compose block in `.env` (database superuser and role
passwords, broker user and password). This fills them with random values:

```sh
uv run python - <<'PY'
import secrets
from pathlib import Path

env = Path(".env")
lines = []
for line in env.read_text().splitlines():
    key, sep, value = line.partition("=")
    if sep and not value and key.endswith("PASSWORD"):
        value = secrets.token_urlsafe(24)
    elif sep and not value and key.endswith("USER"):
        value = "jiris"
    lines.append(key + sep + value)
env.write_text("\n".join(lines) + "\n")
PY
```

The four URLs at the end of `.env` (`VISITS_DATABASE_URL`, `BILLING_DATABASE_URL`,
`MIGRATIONS_DATABASE_URL`, `RABBITMQ_URL`) are needed only to run the API, the worker or
Alembic outside compose; compose builds them from the passwords.

Without a value, compose stops with an error that names the missing variable.

## Run

```sh
docker compose up
```

Compose starts `postgres` and `rabbitmq`, then the one-shot `migrate` service (both Alembic
chains as `jiris_migrator`), then, once `migrate` has exited 0, `api` and `worker`. The API
listens on `localhost:8000`; PostgreSQL on 5432; RabbitMQ on 5672, with its management UI
on `localhost:15672` (log in with `RABBITMQ_USER` and `RABBITMQ_PASSWORD` from `.env`).

A complete flow, from creation to a billing record:

```sh
VISIT=$(curl -s -X POST localhost:8000/api/visits -H 'content-type: application/json' \
  -d '{"start_date_time": "2026-11-11T09:00:00Z", "end_date_time": "2026-11-11T11:00:00Z",
       "description": "Morning care visit", "rate": "25.00"}' \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["id"])')
curl -s -X POST localhost:8000/api/visits/$VISIT/start      # Scheduled → In Progress
curl -s -X POST localhost:8000/api/visits/$VISIT/complete   # 202, completion_pending: true
sleep 3
curl -s localhost:8000/api/visits/$VISIT                    # status Completed
curl -s "localhost:8000/api/billing-records?visit_id=$VISIT"  # one record, amount "50.00"
```

### Endpoints

| Method and path | Purpose | Success |
|---|---|---|
| `POST /api/visits` | Create a visit; 422 for `rate ≤ 0`, `end ≤ start`, more than 2 decimal places, a time without a zone, an unknown field | 201, the visit |
| `GET /api/visits/{id}` | Read a visit, with the derived `completion_pending` | 200 |
| `POST /api/visits/{id}/start` | Scheduled → In Progress | 200 |
| `POST /api/visits/{id}/cancel` | → Canceled | 200 |
| `POST /api/visits/{id}/missed` | Scheduled → Missed | 200 |
| `POST /api/visits/{id}/complete` | Request completion (Scheduled or In Progress) | 202 |
| `GET /api/billing-records?visit_id=` | Billing records of a visit | 200, a JSON array |

Conflicts answer 409 with `{"reason": "completion_pending"}` (a completion is pending, or a
concurrent `/complete` won) or `{"reason": "invalid_status"}`; an unknown visit answers 404.
Money is a decimal string, times are UTC with a `Z`. Full contract: [TDD §6](docs/TDD.md).

## Test

Docker must be running: the integration tests start PostgreSQL and RabbitMQ in
testcontainers, with random passwords per session.

```sh
uv run pytest                                                   # whole suite, about 3 minutes
uv run pytest tests/integration/test_t1_concurrent_complete.py  # T1 only, 50 runs
uv run lint-imports                                             # module boundaries, 3 contracts
```

The suite includes the drift check between the SQLAlchemy models and the migrations
(`tests/integration/test_migrations.py`). Against a database of your own, with
`MIGRATIONS_DATABASE_URL` set and both chains at head:

```sh
uv run alembic -n visits upgrade head
uv run alembic -n billing upgrade head
uv run alembic -n visits check
uv run alembic -n billing check
```

## Operations

**Logs.** One line per command in the API (`command`, `visit_id`, `event_id`,
`event_type`, `outcome`, and `path` for a 422) and one line per consumed event in the worker
(`module`, `event_id`, `event_type`, `visit_id`, `message_id`, `redelivered`, `outcome`);
never a payload body. The relays log each published event, the purge each pass.

**Failures and what happens.**

| Situation | Behaviour |
|---|---|
| Broker down or connections lost | The API keeps answering; events wait in the outbox; relays back off up to 30 s and consumers reconnect; everything resumes by itself |
| Database unavailable for a consumer | The message is requeued with backoff up to 30 s, without a limit and without counting |
| Billing permanent error | BillingFailed at once; the visit returns to its source status with a reason code |
| Billing transient error | Retried up to 5 times, counted in `billing.inbox`; then BillingFailed and the message is parked |
| Malformed message | Parked at once, never retried |
| Reply for an unknown visit, or a Visits failure 5 times | Parked; the visit stays pending |

**Failure reason codes** (`completion_failure_reason` of the visit, `reason` of
BillingFailed): `invalid_payload`, `amount_out_of_range`, `invalid_data`,
`constraint_violation`, `transient_errors_exhausted`. The raw error text stays in
`billing.inbox.last_error`; it never reaches an API client.

**Parking queues.** `billing.parking` receives malformed VisitCompleted messages and those
exhausted after 5 transient failures; `visits.parking` receives malformed replies, replies
for unknown visits and replies that failed 5 times. Each parked message keeps its original
routing key in the `x-death` header. There is no replay tool in this release: an operator
inspects the message (management UI or `rabbitmqctl list_queues`), fixes the cause and, if
needed, republishes it to `jiris.events` with that routing key. A visit whose reply was
parked stays pending until then.

**Outbox purge.** The worker deletes published outbox rows older than 7 days, at start and
then hourly, in batches of 1000; unpublished rows are never deleted.

## Configuration

| Setting | Value | Where |
|---|---|---|
| `VISITS_DATABASE_URL`, `BILLING_DATABASE_URL` | One pool per module role | API and worker |
| `MIGRATIONS_DATABASE_URL` | Role `jiris_migrator` | `migrate`, Alembic |
| `RABBITMQ_URL` | Broker | Worker |
| `POSTGRES_PASSWORD`, `JIRIS_MIGRATOR_PASSWORD`, `VISITS_APP_PASSWORD`, `BILLING_APP_PASSWORD`, `RABBITMQ_USER`, `RABBITMQ_PASSWORD` | Credentials, from `.env` | Compose |
| Relay poll interval, batch, backoff ceiling | 500 ms, 100 rows, 30 s | Code ([TDD §10](docs/TDD.md)) |
| Billing transient retry limit | 5 | Code |
| Outbox retention, purge interval, batch | 7 days, 1 hour, 1000 rows | Code |

## Repository layout

```
app/
  contracts/     event envelope and payload models; imports no module
  visits/        api, service, models, consumer, migrations (chain "visits")
  billing/       api, service, models, consumer, migrations (chain "billing")
  outbox/        relay, topology, shared consumer mechanics, purge
  main_api.py    API entry point (uvicorn --factory app.main_api:create_app)
  main_worker.py worker entry point (python -m app.main_worker)
tests/
  unit/          pure logic
  integration/   real PostgreSQL and RabbitMQ in testcontainers; T1 to T8
docker/postgres/ init.sql (role bootstrap template) and init.sh
docs/            PRD, TDD, Handoff, registers, build-spec/
```
