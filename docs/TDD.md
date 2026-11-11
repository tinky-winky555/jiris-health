# Jiris Health · Technical Design Document (TDD)

Version 1.0 · 2026-11-11 · Owner: Sasha · Status: approved, ready for build (build-time defaults D28 to D30 approved by Sasha on 2026-11-11)
Source of truth: `docs/HANDOFF.md` (D1 to D27, R1 to R9). Requirements: `docs/PRD.md`. English edition of the approved Russian SDD draft.

---

## 1. Overview

A modular monolith with two processes (API and worker) on one codebase. Visits and Billing are linked only by events through RabbitMQ. State change and event are written in one local transaction (transactional outbox); a worker publishes them; receivers de-duplicate through an inbox and a partial unique index.

## 2. Architecture

```mermaid
flowchart TB
  client[API client] --> api
  subgraph api_proc[API process: FastAPI]
    api[Visits HTTP API<br/>POST /api/visits/:id/complete]
  end
  subgraph pg[PostgreSQL: one database, two schemas]
    sv[(schema visits<br/>visit, outbox, inbox<br/>role visits_app)]
    sb[(schema billing<br/>billing_record, outbox, inbox<br/>role billing_app)]
  end
  subgraph worker[Worker process]
    rv[Relay visits]
    cv[Consumer visits]
    cb[Consumer billing]
    rb[Relay billing]
  end
  subgraph mq[RabbitMQ]
    ex{{jiris.events<br/>topic exchange}}
    qb[[billing.inbox]]
    qv[[visits.inbox]]
    dlx[[jiris.dlx parking queues]]
  end
  api -- visit + outbox, one transaction --> sv
  rv -- read outbox --> sv
  rv -- publish --> ex
  ex -- visits.* --> qb
  qb --> cb
  cb -- inbox + record + outbox --> sb
  rb -- read outbox --> sb
  rb -- publish --> ex
  ex -- billing.* --> qv
  qv --> cv
  cv -- inbox + visit status --> sv
  qb -. dead letter .-> dlx
  qv -. dead letter .-> dlx
```

| Component | Responsibility | Ref |
|---|---|---|
| API process | HTTP API of Visits; never calls Billing | D1, D5 |
| Worker process | Two relays and two consumers; separate from the API so relay failures do not affect it | D19, D20 |
| PostgreSQL | One database; schema and role per module | D13 |
| RabbitMQ | Durable topic exchange, one queue per consuming module, dead-letter exchange | D8, D20 |

## 3. Technology

| Concern | Choice | State |
|---|---|---|
| Web framework | FastAPI | decided (D1) |
| Database | PostgreSQL | decided (D1) |
| Broker | RabbitMQ, durable queues, manual ack, publisher confirms, DLX | decided (D8) |
| Consumer library | FastStream over aio-pika, with its FastAPI integration (`RabbitRouter`); Celery and FastAPI `BackgroundTasks` rejected | decided (D30) |
| Event schemas | Pydantic models in `app.contracts` | decided (D27) |
| Migrations | Alembic, two chains (one per schema) | decided (D26) |
| Boundary check | import-linter in CI | decided (D13) |
| Tests | pytest, httpx AsyncClient, testcontainers (PostgreSQL, RabbitMQ) | decided (D21) |
| Data access | SQLAlchemy 2 async + asyncpg | decided (D28) |
| Python version | 3.15.2 or later | decided (D28). Risk: 3.15 shipped in October 2026; check that asyncpg, pydantic-core and other compiled dependencies publish 3.15 wheels before pinning |
| Local run | docker-compose: postgres, rabbitmq, api, worker, plus a one-shot `migrate` service (section 9.1) | decided (D28; `migrate` approved by Sasha on 2026-11-11) |

## 4. Repository layout (D28)

```
app/
  contracts/            # event envelope and payload models; imports nothing from modules
  visits/
    api.py              # FastAPI router
    service.py          # completion logic, reply handlers
    models.py           # SQLAlchemy models, schema "visits"
    consumer.py         # handles billing.* events
    migrations/         # Alembic chain for schema "visits"
  billing/
    service.py          # amount calculation, record creation, error classification
    models.py           # schema "billing"
    consumer.py         # handles visits.* events
    migrations/         # Alembic chain for schema "billing"
  outbox/
    relay.py            # generic polling relay, parametrised by schema and role
  main_api.py           # API entry point
  main_worker.py        # worker entry point: 2 relays + 2 consumers + outbox purge
tests/
  unit/
  integration/
.importlinter
docker-compose.yml
```

import-linter contracts: `app.visits` and `app.billing` are independent; `app.contracts` imports neither; `app.outbox` imports neither module.

## 5. Data model

### 5.1 Schema `visits` (role `visits_app`)

| Table | Column | Type | Notes |
|---|---|---|---|
| `visit` | `id` | uuid PK | |
| | `start_date_time`, `end_date_time` | timestamptz | `CHECK (end_date_time > start_date_time)` |
| | `description` | text | |
| | `rate` | numeric(12,2) | `CHECK (rate > 0)` |
| | `status` | text | `CHECK (status IN ('Scheduled','In Progress','Completed','Canceled','Missed'))` |
| | `completion_requested_at` | timestamptz null | pending marker (D14); kept after Completed (D23) |
| | `completion_attempt_id` | uuid null | = VisitCompleted `event_id` (R1) |
| | `completion_failure_reason` | text null | last Billing failure (D16) |
| `outbox` | `event_id` | uuid PK | |
| | `event_type`, `schema_version`, `payload` jsonb, `occurred_at` | | |
| | `published_at` | timestamptz null | partial index `WHERE published_at IS NULL` |
| | `attempts` | int | publish attempts, diagnostic only |
| `inbox` | `event_id` | uuid PK | de-duplication of Billing replies |
| | `event_type`, `processed_at` | | |

### 5.2 Schema `billing` (role `billing_app`)

| Table | Column | Type | Notes |
|---|---|---|---|
| `billing_record` | `id` | uuid PK | |
| | `visit_id` | uuid | no foreign key across schemas |
| | `amount` | numeric(12,2) | |
| | `status` | text | `CHECK (status IN ('Created','Reversed'))` |
| | `created_at` | timestamptz | |
| | | | `CREATE UNIQUE INDEX ux_active_record ON billing.billing_record (visit_id) WHERE status = 'Created'` (D3, D12) |
| `outbox` | as in `visits` | | |
| `inbox` | `event_id` | uuid PK | |
| | `event_type` | text | |
| | `status` | text | processing, processed, failed (D22) |
| | `attempts` | int | survives restarts (D15) |
| | `last_error`, `processed_at` | | |

`completion_pending` in API responses is derived as `completion_requested_at IS NOT NULL AND status <> 'Completed'` (D28; the status clause is needed because D23 keeps the field after Completed).

## 6. Visit state machine and API

```mermaid
stateDiagram-v2
  [*] --> Scheduled
  Scheduled --> InProgress: start
  Scheduled --> Canceled: cancel
  Scheduled --> Missed: mark missed
  InProgress --> Canceled: cancel
  Scheduled --> Pending: /complete (status unchanged)
  InProgress --> Pending: /complete (status unchanged)
  Pending --> Completed: BillingRecordCreated
  Pending --> SourceStatus: BillingFailed (reset)
  note right of Pending: not a stored status; completion_requested_at set.\nCancel and Missed rejected with 409 (R2)
```

### 6.1 Endpoints

| Method and path | Purpose | State |
|---|---|---|
| `POST /api/visits/{id}/complete` | Request completion | decided (brief, D4) |
| `POST /api/visits` | Create a visit (validation per FR11, 422 on error) | decided (D28) |
| `GET /api/visits/{id}` | Read a visit with `completion_pending` | decided (D28) |
| `POST /api/visits/{id}/start` | Scheduled → In Progress | decided (D28) |
| `POST /api/visits/{id}/cancel` | → Canceled; 409 while pending | decided (D28) |
| `POST /api/visits/{id}/missed` | Scheduled → Missed; 409 while pending | decided (D28) |
| `GET /api/billing-records?visit_id=` | Read billing records (for tests and clients) | decided (D28) |

Success responses of the supporting endpoints (approved by Sasha on 2026-11-11):

| Endpoint | Code | Body |
|---|---|---|
| `POST /api/visits` | 201 | the created visit |
| `GET /api/visits/{id}` | 200 | the visit |
| `POST /api/visits/{id}/start`, `/cancel`, `/missed` | 200 | the visit after the transition |
| `GET /api/billing-records?visit_id=` | 200 | JSON array of billing records (empty when none) |

The visit body carries the columns of section 5.1 plus the derived `completion_pending`. Money fields (`rate`, `amount`) are decimal strings, as in events.

### 6.2 `/complete` algorithm (one transaction, role `visits_app`)

```sql
UPDATE visits.visit
SET completion_requested_at = now(),
    completion_attempt_id   = :event_id,
    completion_failure_reason = NULL
WHERE id = :id
  AND status IN ('Scheduled', 'In Progress')
  AND completion_requested_at IS NULL
RETURNING id, rate, start_date_time, end_date_time;
```

After BillingFailed the field is reset to NULL (D16), so a failed attempt makes the visit completable again.

1. One row returned → INSERT VisitCompleted into `visits.outbox` with `event_id = :event_id`; COMMIT; respond 202.
2. No row → read the visit: absent → 404; present → 409 with `reason` = `completion_pending` or `invalid_status`.

The conditional UPDATE is the single point that serialises concurrent requests (T1): PostgreSQL row locking lets only one transaction match the predicate.

### 6.3 Responses

| Situation | Code | Body |
|---|---|---|
| Accepted | 202 | visit with `completion_pending: true` |
| Pending or lost race | 409 | `{"reason": "completion_pending"}` |
| Completed, Canceled or Missed | 409 | `{"reason": "invalid_status"}` |
| Not found | 404 | |
| Invalid creation payload | 422 | FastAPI validation body |

### 6.4 Reply handling in Visits (consumer, one transaction)

1. INSERT into `visits.inbox` (`ON CONFLICT DO NOTHING`); no row inserted → already processed → ack.
2. Load the visit `FOR UPDATE`; if `completion_attempt_id <> payload.completion_attempt_id` → ignore (R1), commit, ack.
3. BillingRecordCreated: already Completed → no-op (R3); else `status = 'Completed'`.
4. BillingFailed: `completion_requested_at = NULL`, `completion_failure_reason = payload.reason` (D16).
5. COMMIT, then ack.

## 7. Event contract (D20, D27)

Envelope (R6), defined once in `app.contracts`:

```json
{
  "event_id": "7d1c2c4e-6f0a-4b8e-9d0a-2a6f1f3b9c11",
  "event_type": "VisitCompleted",
  "schema_version": 1,
  "occurred_at": "2026-11-11T10:15:00Z",
  "payload": { }
}
```

| Event | Routing key | Payload |
|---|---|---|
| VisitCompleted | `visits.visit_completed` | `visit_id`, `completion_attempt_id`, `rate`, `start_date_time`, `end_date_time` |
| BillingRecordCreated | `billing.record_created` | `visit_id`, `completion_attempt_id`, `billing_record_id`, `amount` |
| BillingFailed | `billing.failed` | `visit_id`, `completion_attempt_id`, `reason`, `error_class` (`transient_exhausted` or `permanent`) |

Money travels as a decimal string (for example `"42.50"`) to avoid float rounding (D28).

### 7.1 RabbitMQ topology

| Object | Type | Bindings and settings |
|---|---|---|
| `jiris.events` | topic exchange, durable | |
| `billing.inbox` | queue, durable | bound to `visits.*`; `x-dead-letter-exchange = jiris.dlx` |
| `visits.inbox` | queue, durable | bound to `billing.*`; `x-dead-letter-exchange = jiris.dlx` |
| `jiris.dlx` | exchange, durable | |
| `billing.parking`, `visits.parking` | queues, durable | bound to `jiris.dlx` |

Messages: persistent, `message_id = event_id`, `content_type = application/json`.

```mermaid
sequenceDiagram
  participant V as Visits
  participant MQ as RabbitMQ
  participant B as Billing
  V->>MQ: 1. VisitCompleted (outbox, relay)
  MQ->>B: 2. billing.inbox
  Note over B: 3. inbox + record + outbox, one transaction
  B->>MQ: 4. BillingRecordCreated or BillingFailed
  MQ->>V: 5. visits.inbox
  Note over V: 6. Completed or reset, if attempt id matches
```

## 8. Reliability

### 8.1 Outbox relay (D19, D25)

Per schema, with its own role and pool:

```
loop:
  BEGIN
  rows = SELECT * FROM <schema>.outbox
         WHERE published_at IS NULL
         ORDER BY occurred_at
         LIMIT 100
         FOR UPDATE SKIP LOCKED
  for row in rows:
      publish(row) and await publisher confirm
      UPDATE outbox SET published_at = now() WHERE event_id = row.event_id
  COMMIT
  sleep 500 ms if rows was empty
on broker error: ROLLBACK, exponential backoff up to 30 s, retry forever
```

- Several relay instances are safe (`SKIP LOCKED`).
- Crash after confirm and before COMMIT → the row is published again; receivers de-duplicate.
- Purge job in the worker: `DELETE FROM <schema>.outbox WHERE published_at < now() - interval '7 days'` (R5, D25).

### 8.2 Billing consumer (D15, R8, R9)

```
on message:
  parse envelope; parse error → reject without requeue → parking (R9)
  BEGIN
  inbox row: INSERT ... ON CONFLICT (event_id) DO NOTHING, then SELECT ... FOR UPDATE
  if status = processed → COMMIT, ack
  try:
      amount = round_half_up(rate × hours(end − start), 2)
      INSERT billing_record (status = 'Created')
        on unique violation → load the existing active record (R8)
      INSERT outbox BillingRecordCreated
      inbox.status = processed
      COMMIT, ack
  except PermanentError as e:
      ROLLBACK; in a new transaction: inbox.status = failed, last_error = e,
      INSERT outbox BillingFailed(error_class = permanent); COMMIT; ack
  except Exception as e:            # transient or unclassified
      ROLLBACK; in a new transaction: inbox.attempts += 1, last_error = e; COMMIT
      if attempts < 5: nack with requeue (after a short delay, D28)
      else: inbox.status = failed, INSERT outbox BillingFailed(error_class = transient_exhausted),
            COMMIT, reject without requeue → parking
```

Error classes: transient = database connectivity, timeouts, broker errors; permanent = validation of the payload (for example non-positive duration). Anything else counts as transient (D15).

### 8.3 Connection loss

Relays and consumers reconnect automatically with exponential backoff (R7); provided by aio-pika robust connections under FastStream (D30).

## 9. Module isolation (D5, D13)

As built (amended under contract DL-1, approved by Sasha on 2026-11-11; detail in section 9.1):

```sql
-- Cluster bootstrap: docker/postgres/init.sql, run once by the superuser
CREATE ROLE jiris_migrator LOGIN; CREATE ROLE visits_app LOGIN; CREATE ROLE billing_app LOGIN;
GRANT CONNECT, CREATE ON DATABASE jiris TO jiris_migrator;
GRANT CONNECT ON DATABASE jiris TO visits_app, billing_app;
REVOKE ALL ON SCHEMA public FROM PUBLIC;

-- Chain "visits", run by jiris_migrator; chain "billing" is symmetric
-- (billing_record, outbox, inbox; role billing_app)
CREATE SCHEMA IF NOT EXISTS visits;   -- in env.py, before Alembic creates visits.alembic_version
GRANT USAGE ON SCHEMA visits TO visits_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON visits.visit, visits.outbox, visits.inbox TO visits_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA visits
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO visits_app;
```

- Each module uses its own connection pool and role; migrations run per chain under a dedicated owner role (`MIGRATIONS_DATABASE_URL`); application roles get only DML grants (D29).
- No cross-schema foreign keys; `billing_record.visit_id` is a plain UUID from the event.

### 9.1 Roles and migration run (approved by Sasha on 2026-11-11)

- Cluster bootstrap (`docker/postgres/init.sql`, run once by the superuser) creates the login roles `jiris_migrator` (migration owner, `CONNECT, CREATE` on the database), `visits_app` and `billing_app` (`CONNECT` only), and revokes `public` from `PUBLIC`.
- The Alembic chains run under `jiris_migrator` (`MIGRATIONS_DATABASE_URL`); they create the schemas and tables, own them, and grant DML to the application roles.
- Each chain keeps its version table in its own schema (`visits.alembic_version`, `billing.alembic_version`); the chain's `env.py` runs `CREATE SCHEMA IF NOT EXISTS` before Alembic starts, because the version table needs the schema.
- DML is granted on the module's named tables, not `ON ALL TABLES`, so the application role cannot touch `alembic_version`; `ALTER DEFAULT PRIVILEGES IN SCHEMA` gives the same DML on tables created by later migrations. T7 permanently checks that neither application role can SELECT, INSERT, UPDATE or DELETE on its `alembic_version`.
- `alembic -n <chain> check` runs in the test suite and fails when the SQLAlchemy models and the migrations drift apart.
- In docker-compose, migrations run in a dedicated one-shot service `migrate` (`alembic -n visits upgrade head`, then `alembic -n billing upgrade head`). `api` and `worker` depend on it with `condition: service_completed_successfully`; the API process never runs migrations.

## 10. Configuration

| Setting | Value | Ref |
|---|---|---|
| Relay poll interval | 500 ms | D25 |
| Relay batch size | 100 | D25 |
| Relay backoff ceiling | 30 s | D25 |
| Outbox retention | 7 days | D25 |
| Billing transient retry limit | 5 | D15 |
| Database URLs | one per role: `VISITS_DATABASE_URL`, `BILLING_DATABASE_URL`; SQLAlchemy form `postgresql+asyncpg://user:password@host:port/db` | decided (D29; URL form approved 2026-11-11) |
| Broker URL | `RABBITMQ_URL` | decided (D29) |
| Migration owner URL | `MIGRATIONS_DATABASE_URL`, role `jiris_migrator`, same URL form | decided (D29; role name approved 2026-11-11) |

## 11. Testing (D21)

| # | Scenario | Expected | Technique |
|---|---|---|---|
| T1 | Two concurrent `/complete` on one visit | One 202, one 409; one outbox event; finally Completed and one record | `asyncio.gather` with two clients on separate DB connections; run 50 times (D28) |
| T2 | VisitCompleted delivered twice | One record, one reply | Publish the same message twice |
| T3 | Broker down during `/complete` | Event waits; after restart Completed with a record | Stop and start the RabbitMQ testcontainer |
| T4 | Permanent Billing error | BillingFailed; reset; `completion_failure_reason` set; retry works | Inject a permanent error |
| T5 | Transient error 5 times with worker restart | Counter persisted; BillingFailed after 5th | Fault injection + worker restart |
| T6 | Late reply with old attempt id | Ignored | Publish a crafted reply |
| T7 | `visits_app` reads `billing` schema; import-linter | Permission error; linter passes | Direct SQL with the role; CI step |
| T8 | Amount and validation | Decimal HALF_UP; 422 on invalid input | Unit tests |

Integration tests wait for eventual completion by polling `GET /api/visits/{id}` with a 10 s timeout (D28).

The integration harness runs the worker as a separate process (`python -m app.main_worker`) and treats it as ready once both `billing.inbox` and `visits.inbox` have at least one consumer (approved by Sasha on 2026-11-11). The API runs in process through `httpx.ASGITransport`.

## 12. Traceability

| Decision | Topic | Section |
|---|---|---|
| D1 to D7 | Brief: stack, model, guarantees, concurrency test | 1, 5, 11 |
| D8 | RabbitMQ; fallback NATS JetStream | 3, 7.1 |
| D9, D14, D18 | Two-phase completion; pending via field; status unchanged | 6 |
| D10 | `/complete` from Scheduled and In Progress | 6.2 |
| D11 | Billing computes amount | 8.2 |
| D12 | Reversed in model only | 5.2 |
| D13, D26 | Schema and role per module; two Alembic chains | 4, 9 |
| D15, D16 | Error classes, 5 retries; reset on failure | 6.4, 8.2 |
| D17 | 202 / 409 | 6.3 |
| D19, D25 | Polling relay in worker; parameters | 8.1, 10 |
| D20, D27 | Contract, topology; `app.contracts` | 7 |
| D21 | Tests T1 to T8 | 11 |
| D22 to D24 | Types, history field, 422 | 5, 6.3 |
| R1 to R9 | Derived requirements | 6.4, 8 |

## 13. Out of scope

Reversal operation, `Idempotency-Key`, LISTEN/NOTIFY, actual visit times, authentication (see PRD section 5).
