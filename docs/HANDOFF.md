# Jiris Health · Handoff (memory between windows)

Updated on 2026-11-11 · chat: Russian, final material: British English · working document

What it is for: this is the project's handoff, the memory that travels between Cowork windows. It holds what the product is and the whole body of decisions and knowledge gathered in discovery: the agenda, the rationale of each decision, the findings. Anyone opening a new window reads this first. The next steps and the sequence live in `jiris-health_Roadmap.md` (the checklist).

Rule 1 (resume): keep this document alive at every step. Every closed decision, every new material and every piece of acquired knowledge enters here, until the user signals it is safe to drive by the Roadmap alone. The Roadmap mirrors the state and guides the sequence; this holds the content and the why.

Division of roles:
- **Handoff (this):** the product, the decisions and the body of knowledge. The memory.
- **Roadmap:** status panel and next-step checklist. The sequence guide, resilient to window switching.

**Project settings:** chat language: Russian · form of address: Sasha. (Recorded here, not in CLAUDE.md.)

**Update log:** (append a short entry each session, newest at the top)
- 2026-11-11 (y): `MIGRATIONS_DATABASE_URL` approved (D29 extended). PRD and TDD have no open items; ready for build in Claude Code.
- 2026-11-11 (x): D30 closed (FastStream over aio-pika with FastAPI integration). FastAPI BackgroundTasks and in-process domain events rejected (not durable, no broker; break D5, D6). TDD has one remaining [PROPOSAL]: name `MIGRATIONS_DATABASE_URL`.
- 2026-11-11 (w): D29 closed (env var names; dedicated migration owner role, application roles DML only). Sasha asked why not Celery; analysis recorded in §11. Reconnect/consumer library (FastStream over aio-pika) awaiting confirmation.
- 2026-11-11 (v): D28 closed: TDD build-time defaults approved (docker-compose, supporting endpoints, repo layout and stack with Python 3.15.2 or later, small rules, `completion_pending` clause). Still [PROPOSAL] in TDD: env var names, migration owner role, reconnect via FastStream/aio-pika robust connections. Python 3.15.2 confirmed on python.org (released 2026-10-25); wheel availability of compiled dependencies is a build risk.
- 2026-11-11 (u): Sasha approved the whole SDD and asked for English deliverables for the build in Claude Code. Created `PRD_jiris-health.md` and `TDD_jiris-health.md` (British English, Markdown, Mermaid diagrams) in the project folder. TDD is the English edition of the SDD plus build-time defaults tagged [PROPOSAL] (supporting endpoints, repo layout, SQLAlchemy/asyncpg, Python 3.12, docker-compose, money as decimal string, retry delay, test polling timeout, `completion_pending` clause). The Russian Claude Doc stays as the review record.
- 2026-11-11 (t): D27 closed (shared `app.contracts`). All SDD review questions closed; Russian draft ready for translation.
- 2026-11-11 (s): SDD open questions 1 to 5 closed by Sasha (D22 to D26); SDD updated and items ticked. Question 6 (`app.contracts`) open with a recommendation.
- 2026-11-11 (r): SDD draft in Russian created as a Claude Doc for Sasha's review: https://claude.ai/artifact/Vw7M9A4M8yuzb7tD3XxrWN. Six open questions listed in its section 10 (column types, keeping `completion_requested_at`, 422 code, relay parameters, Alembic layout, `app.contracts` package).
- 2026-11-11 (q): R7 to R9 and D21 confirmed. Discovery closed: all decisions D1 to D21 and requirements R1 to R9 closed. Next stage (spec or build) is a boundary in the Roadmap.
- 2026-11-11 (p): D20 closed (contract and topology). Architecture passes run (§10b), R7 to R9 proposed. Test strategy proposed as D21. All awaiting confirmation.
- 2026-11-11 (o): D19 closed (polling relay in a separate worker). Event contract and RabbitMQ topology proposed as D20, awaiting confirmation.
- 2026-11-11 (n): D13 closed (schema and role per module; import-linter). Next: D19 (outbox relay mechanism).
- 2026-11-11 (m): D8 closed (RabbitMQ). Next: D13 (module data isolation).
- 2026-11-11 (l): R1 to R6 confirmed; domain semantics piece closed. Architecture piece opened with D8 (broker).
- 2026-11-11 (k): D12 closed (Reversed in model only; reversal operation parked). Domain semantics piece: analyst passes run (§10a); derived requirements R1 to R6 proposed, awaiting confirmation. Next piece: architecture (D8, D13).
- 2026-11-11 (j): D11 closed (Billing computes amount from event payload; Decimal, 2 places, ROUND_HALF_UP; validation at visit creation). Next: D12.
- 2026-11-11 (i): D18 closed (status unchanged while pending; derived `completion_pending` in API). D14 generalised. Next: D11.
- 2026-11-11 (h): D10 closed (complete allowed from Scheduled and In Progress). D17 condition updated. Consequence on D14 raised as D18.
- 2026-11-11 (g): D17 closed (409 for the losing or invalid-state request). Idempotency-Key vs JWT `jti` clarified (§11). Next: D10.
- 2026-11-11 (f): D15 unknown-error default confirmed (transient). D16 closed (option 1 plus `completion_failure_reason`). Next: D17.
- 2026-11-11 (e): D15 refined (transient vs permanent errors; persisted attempt counter). D16 discussed: Canceled/Missed rejected as failure outcome; recommendation option 1 awaiting Sasha's confirmation.
- 2026-11-11 (d): D14 closed (status stays In Progress plus `completion_requested_at`). D15 closed (BillingFailed after 5 failed processing attempts). Next: D16, the Visits reaction to BillingFailed.
- 2026-11-11 (c): assignment hypothesis removed at Sasha's request. D9 closed: two-phase completion (visit becomes Completed only after Billing confirms). New open decision D14 (how to represent the pending state).
- 2026-11-11 (b): brief received from Sasha. Scope, data model, guarantees and the completion endpoint captured. Requirements from the brief recorded as closed decisions D1 to D7. Open decisions D8 to D13 identified. Candidate architectures recorded in parallel (§6).
- 2026-11-11 (a): study bootstrapped. Subfolder, Handoff and Roadmap created; chat language (Russian) and form of address (Sasha) set. Working name: Jiris Health. Discovery starts.

---

## 1. The product, in one page

- **Working name:** Jiris Health (provisional)
- **Problem (one sentence):** greenfield; no legacy pain. Need a small service that records caregiver visits and bills completed visits reliably, with no lost and no duplicate billing.
- **Desired outcome:** a FastAPI + PostgreSQL modular monolith (modules: Visits, Billing) where every completed visit has exactly one active billing record, proven by an automated concurrency test, and robust to broker outage and duplicate delivery.
- **Why now:** not stated.

## 2. Audience and usage modes

| Profile | Role | Frequency | Notes |
|---|---|---|---|
| API client (caregiver app / scheduler) | Creates and completes visits | Per visit | Not described in the brief |

## 3. Closed decisions

Distilled: rewrite as understanding matures. Each decision carries its rationale. D1 to D7 come directly from Sasha's brief (evidence).

| # | Decision | Rationale | Date | State |
|---|---|---|---|---|
| D1 | Stack: FastAPI + PostgreSQL; modular monolith with two modules, Visits and Billing | Brief | 2026-11-11 | closed |
| D2 | Visit: start_date_time, end_date_time, description, rate (per hour), status ∈ {Scheduled, In Progress, Completed, Canceled, Missed} | Brief | 2026-11-11 | closed |
| D3 | BillingRecord: visit_id, amount, status ∈ {Created, Reversed}; at most one active record per visit | Brief | 2026-11-11 | closed |
| D4 | `POST /api/visits/{id}/complete` validates current status and atomically creates a VisitCompleted event | Brief | 2026-11-11 | closed |
| D5 | Module isolation: neither module reads or writes the other's tables; communication only through events via a message broker (Visits publishes, Billing consumes) | Brief | 2026-11-11 | closed |
| D6 | Guarantees: completed visit always gets a billing record even if broker is down; never two records under duplicate delivery or concurrent requests; unpublished events are republished automatically | Brief | 2026-11-11 | closed |
| D7 | Automated test: two concurrent complete requests on the same visit | Brief | 2026-11-11 | closed |
| D9 | Two-phase completion: `/complete` validates status, moves the visit to a pending state and writes VisitCompleted to the outbox in one transaction; Billing creates the record and emits a confirmation event (e.g. BillingRecordCreated); Visits consumes it and sets Completed | Literal reading of the brief: "After event processing, the visit is completed and has a BillingRecord". Chosen by Sasha | 2026-11-11 | closed |

| D14 | Pending state: status is not changed by `/complete`; new field `completion_requested_at` (null = not requested). Status contract keeps the five statuses of the brief (generalised by D18) | Preserves the brief's status list. Chosen by Sasha | 2026-11-11 | closed |
| D11 | Billing computes `amount = rate × (end_date_time − start_date_time)` in hours (planned duration). VisitCompleted payload carries `visit_id`, `rate`, `start_date_time`, `end_date_time` (plus event metadata). Decimal arithmetic, 2 decimal places, ROUND_HALF_UP. Visits rejects `rate ≤ 0` and `end ≤ start` at creation | Money rules live in the money module; Visits unaffected if pricing changes; D5 forces data to travel in the event; only planned times exist in the model. Chosen by Sasha | 2026-11-11 | closed |
| D8 | Message broker: RabbitMQ (durable queues, manual ack, publisher confirms, dead-letter exchange for parked messages). Fallback candidate recorded: NATS JetStream | Queue/ack/DLQ model matches the two-way flow; dedup and retry counting already in our tables; light in docker-compose; easy outage simulation in tests; mature Python clients. Kafka rejected as excessive (no need for replay or partitions); Redis Streams weaker durability. Claude's recommendation accepted by Sasha | 2026-11-11 | closed |
| D13 | One PostgreSQL database; schema per module (`visits`, `billing`), each with its own outbox and inbox; a database role per module granted only on its own schema; separate connection pools. Code boundary enforced by import-linter | Isolation (D5) enforced by the database, not by convention; outbox stays in the same local transaction; low complexity; easy later extraction into services. Claude's recommendation accepted by Sasha | 2026-11-11 | closed |
| D19 | Outbox relay: polling with `SELECT ... FOR UPDATE SKIP LOCKED`, batches, exponential backoff while the broker is down, rows marked published only after publisher confirm; runs in a separate worker process, not inside FastAPI. LISTEN/NOTIFY kept as a later optimisation | Simplest design meeting all guarantees; safe with several relay instances; API isolated from relay failures; relay can be stopped independently in tests. Claude's recommendation accepted by Sasha | 2026-11-11 | closed |
| D20 | Event contract and RabbitMQ topology as recorded in §11 (2026-11-11, D20 entry): envelope per R6; events VisitCompleted, BillingRecordCreated, BillingFailed; topic exchange `jiris.events`; queues `billing.inbox`, `visits.inbox`; DLX `jiris.dlx`; `message_id` = `event_id`; one worker process (two relays, two consumers); FastStream over aio-pika to confirm at build | Consolidates D9 to D19 and R1, R6 into one contract. Claude's proposal accepted by Sasha | 2026-11-11 | closed |
| D21 | Test strategy T1 to T8 as recorded in §9: unit (pytest) plus integration on real PostgreSQL and RabbitMQ (testcontainers); T1 is the mandatory concurrency test | Each brief guarantee (D6, D7) and each requirement R1 to R9 has a test that demonstrates it. Claude's proposal accepted by Sasha | 2026-11-11 | closed |
| D22 | Column types (numeric(12,2) for money, timestamptz for times) and `billing.inbox` statuses (processing, processed, failed) as in SDD section 4 | Approved by Sasha in SDD review | 2026-11-11 | closed |
| D23 | `completion_requested_at` is kept after Completed as history | Approved by Sasha in SDD review | 2026-11-11 | closed |
| D24 | Validation errors at visit creation return 422 | FastAPI convention for invalid payloads. Approved by Sasha | 2026-11-11 | closed |
| D25 | Relay parameters: poll 500 ms, batch 100 rows, backoff ceiling 30 s; outbox retention 7 days | Approved by Sasha in SDD review | 2026-11-11 | closed |
| D26 | Two Alembic chains, one per schema | Matches D13 isolation; each module migrates independently. Chosen by Sasha | 2026-11-11 | closed |
| D27 | Shared package `app.contracts` with versioned Pydantic event schemas; both modules import it, it imports nothing from them (import-linter) | One source of truth, no schema drift; standard published language for a modular monolith; becomes a small library or JSON Schema on extraction. Claude's recommendation accepted by Sasha | 2026-11-11 | closed |
| D28 | Build defaults (TDD): docker-compose (postgres, rabbitmq, api, worker); supporting endpoints `POST /api/visits`, `GET /api/visits/{id}`, `/start`, `/cancel`, `/missed`, `GET /api/billing-records?visit_id=`; repo layout per TDD §4; SQLAlchemy 2 async + asyncpg; Python 3.15.2 or later; money as decimal string in events; short delay before Billing requeue; T1 run 50 times; integration polling timeout 10 s; `completion_pending = completion_requested_at IS NOT NULL AND status <> 'Completed'` | Needed to build and test the flow; brief names only `/complete`. Approved by Sasha | 2026-11-11 | closed |
| D29 | Env vars `VISITS_DATABASE_URL`, `BILLING_DATABASE_URL`, `RABBITMQ_URL`, `MIGRATIONS_DATABASE_URL`; migrations run under a dedicated owner role, application roles hold DML grants only | Least privilege; app roles cannot alter schema. Approved by Sasha | 2026-11-11 | closed |
| D30 | Messaging library: FastStream over aio-pika, using its FastAPI integration (`RabbitRouter`); reconnection via aio-pika robust connections (R7) | Celery is a task queue (named tasks, own protocol, retries in message, not asyncio-native), against D5 and D15; FastAPI BackgroundTasks and in-process domain events are not durable and bypass the broker, against D6. Approved by Sasha | 2026-11-11 | closed |
| D12 | `Reversed` exists in the model only; no reversal operation in this release. Partial unique index `billing_record(visit_id) WHERE status='Created'` enforces one active record and allows Reversed history | No brief guarantee depends on reversal; avoids an undefined visit state machine after reversal. Chosen by Sasha | 2026-11-11 | closed |
| D18 | While pending, the visit keeps its source status (Scheduled or In Progress); pending is expressed only by `completion_requested_at`. API responses expose a derived read field `completion_pending` (no extra column) | One source of truth; rollback on BillingFailed is a single field reset; no fake transitions. Claude's recommendation accepted by Sasha | 2026-11-11 | closed |
| D15 | Billing failure: transient errors (database, network) are retried up to 5 times; permanent errors (validation, e.g. invalid amount) emit BillingFailed immediately. After the 5th transient failure, BillingFailed is emitted (via Billing's outbox) and the message is parked. The attempt counter and last error are persisted in Billing's tables (inbox extended). Unclassified errors default to transient | Prevents a visit staying pending forever; no wasted retries on errors that cannot recover; counter survives restarts; unknown errors stay bounded by the limit. Claude's proposal accepted by Sasha | 2026-11-11 | closed |
| D17 | `/complete` responses: winner gets `202 Accepted` (completion is asynchronous); a concurrent loser, a pending visit or a visit in a non-completable status gets `409 Conflict` with the reason in the body. Winner chosen by conditional UPDATE `WHERE status IN ('Scheduled','In Progress') AND completion_requested_at IS NULL` (updated after D10) | Server cannot tell a retry from a competing request without a client key; 409 is the HTTP semantics for state conflict; stricter concurrency test. Chosen by Sasha | 2026-11-11 | closed |
| D10 | `/complete` allowed from Scheduled and In Progress; Completed, Canceled and Missed get 409 | Caregiver can close a visit without a separate start operation (none in the brief). Trade-off accepted: actual start moment is not captured. Chosen by Sasha | 2026-11-11 | closed |
| D16 | On BillingFailed, Visits resets `completion_requested_at` to null and stores the cause in `completion_failure_reason` (nullable); the visit is a plain In Progress again and `/complete` may be retried. The field is cleared on the next successful completion request [PROPOSAL on clearing] | Canceled/Missed are business outcomes and terminal, wrong for a technical failure; no new states or manual unlock operation. Chosen by Sasha | 2026-11-11 | closed |

Note on D15 scope: the 5-retry limit applies to the Billing consumer only. The outbox relay towards the broker retries without limit (brief: unpublished events must be published later automatically).

Consequences of D9: Billing also publishes events, so it needs its own outbox; Visits also consumes, so it needs its own idempotent consumer. The flow is symmetric.

Open: none. R7 to R9 (§10b) confirmed by Sasha on 2026-11-11 and are binding requirements. R1 to R6 (§10a) confirmed by Sasha on 2026-11-11 and are binding requirements.

## 4. Assumptions

Framed so they would need to be proven false. Riskiest first.

| Assumption (framed to be falsified) | Risk (H/M/L) | How it could be tested | State |
|---|---|---|---|
| A2: (superseded by D9: visit becomes Completed only after Billing confirms) | | | closed |
| A3: (confirmed by D11) | | | closed |
| A4: (superseded by D10: Scheduled and In Progress) | | | closed |

## 5. Foundations

- **Data:** PostgreSQL. Visits and Billing data owned separately (D5, D13).
- **External systems:** one message broker (D8).
- **Auth / identity:** not in scope of the brief.
- **Persistence:** event storage strategy is ours to decide (brief).
- **Depends on an existing mechanism?** Well-known patterns cover the guarantees: transactional outbox (no lost events), idempotent consumer / inbox (no duplicate processing), database uniqueness constraint (no duplicate record). See §8.

## 6. Candidate solutions (held in parallel)

Outcome: approach A (RabbitMQ) chosen in D8; C (NATS JetStream) kept as fallback. Table kept for traceability.

Core pattern common to all (evidence-based on the guarantees): outbox row written in the same transaction as the status change; relay publishes and retries; Billing de-duplicates by event id and a partial unique index on `billing_record(visit_id) WHERE status = 'Created'`. The candidates differ in transport.

| Approach | Core idea | Optimises for | Trades off |
|---|---|---|---|
| A · RabbitMQ | Outbox + polling relay → RabbitMQ (publisher confirms, DLQ); Billing consumer with inbox table | Familiar, simple ops, mature Python clients | No built-in dedup; relies on our inbox |
| B · Kafka / Redpanda | Outbox + relay (or Debezium CDC) → topic; consumer group | Replay, ordering per key, scale | Heavy for a small app; more infra in docker-compose |
| C · NATS JetStream | Outbox + relay → JetStream with Msg-Id dedup window | Light, built-in publish-side dedup | Less common; dedup window is time-bounded, inbox still needed |
| D · Redis Streams | Outbox + relay → stream; consumer groups with ack | Minimal footprint | Weaker durability guarantees; less "broker-like" for reviewers |

## 7. Market references / inspiration (append-only)

| Reference | What it does that is interesting | Where to look | Insight it sparked |
|---|---|---|---|
| Transactional Outbox pattern | Atomic state change + event | microservices.io/patterns/data/transactional-outbox | Basis for D6 |
| Idempotent Consumer pattern | Dedup by message id | microservices.io/patterns/communication-style/idempotent-consumer | Basis for D6 |

## 8. Reuse and dependencies

| Need | Already exists? | Source | Build or reuse |
|---|---|---|---|
| Broker client and consumer framework | Yes | FastStream (RabbitMQ/Kafka/NATS/Redis), aio-pika | [PROPOSAL] reuse; to evaluate |
| Outbox relay | Partly (Debezium for CDC; no dominant Python lib) | Debezium, custom polling with `FOR UPDATE SKIP LOCKED` | [PROPOSAL] build small polling relay |
| Module boundary enforcement in code | Yes | import-linter | Reuse (D13) |
| Concurrency test harness | Yes | pytest + httpx AsyncClient + asyncio.gather, testcontainers | Reuse |

## 9. Success conditions

- **This is a success if:** all D6 guarantees hold and are demonstrated by tests (concurrency, duplicate delivery, broker down then recovery).
- **Metrics / targets:** test suite T1 to T8 green; zero duplicate records; no manual step in the broker outage scenario.
- **D21 test strategy (closed).** Levels: unit (pytest) and integration with real PostgreSQL and RabbitMQ (testcontainers).

| # | Scenario | Expected |
|---|---|---|
| T1 (D7, mandatory) | Two concurrent `POST /complete` on the same visit (httpx AsyncClient + asyncio.gather) | One 202, one 409; one outbox event; after processing: visit Completed, exactly one billing record |
| T2 | Same VisitCompleted delivered twice | One billing record, one reply event |
| T3 | Broker stopped, `/complete` called, broker restarted | 202; event waits in outbox; after restart visit Completed with a record, no manual action |
| T4 | Permanent Billing error | BillingFailed; visit back to plain state, `completion_failure_reason` set; `/complete` works again |
| T5 | Transient error 5 times, worker restarted in between | Counter persisted; BillingFailed after the 5th attempt |
| T6 | Late reply with an old `completion_attempt_id` | Ignored (R1) |
| T7 | Visits role queries `billing` schema; import-linter in CI | Permission error; linter passes |
| T8 | Amount calculation and creation validation | Decimal, 2 places, HALF_UP; `rate ≤ 0` and `end ≤ start` rejected |
- **What would tell us to stop:** T1, T2 or T3 cannot be made to pass with this design (would reopen D8, D19 or D20).

## 10. Risks and open tensions

- D14: every status check must now combine status and `completion_requested_at` (e.g. Cancel on an In Progress visit that is pending must be rejected or defined).
- D15: error classification (transient vs permanent) must be explicit in code; unknown exceptions default to transient (confirmed).
- D16: a late or duplicate BillingFailed arriving after a later successful retry must not reset the new request; Visits must match the event to the completion attempt (e.g. by event or attempt id).
- D16: Canceled/Missed are business outcomes (the visit did not happen), and terminal. Using them for a technical billing failure would mark delivered work as not delivered and block billing permanently. Rejected as the failure outcome.
- D9 naming: the event is called VisitCompleted while the visit is not yet Completed; name kept as in the brief.
- Second concurrent `/complete` while pending: response contract to define (409 vs idempotent 202).
- Relay crash after publish but before marking sent → duplicate delivery (covered by consumer idempotency, must be tested).
- Several relay instances → double publish unless rows are claimed (`SKIP LOCKED`).
- Poison message in Billing → needs retry limit and dead-letter handling.
- Data validation edge cases: end before start, zero or negative rate, complete on Canceled/Missed.

## 10a. Analyst passes · domain semantics (2026-11-11)

State: R1 to R6 confirmed by Sasha (2026-11-11); the [PROPOSAL] tags below are resolved as accepted.

| Pass | Finding | Derived requirement |
|---|---|---|
| Edge case | Late or duplicate BillingFailed / BillingRecordCreated after a newer completion attempt | R1 [PROPOSAL]: visit stores `completion_attempt_id` (= VisitCompleted event id); Visits ignores reply events whose attempt id does not match |
| Edge case | Cancel or Missed requested while completion is pending | R2 [PROPOSAL]: reject with 409 while `completion_requested_at` is set |
| Edge case | Duplicate BillingRecordCreated when visit is already Completed | R3 [PROPOSAL]: no-op (idempotent), covered by inbox and R1 |
| Edge case | Visit id not found on `/complete` | R4 [PROPOSAL]: 404 |
| Risk | Outbox tables grow without bound | R5 [PROPOSAL]: periodic clean-up of published rows after a retention period (architecture piece) |
| Future state | Actual times not captured (D10 trade-off); pricing on actual duration later would change the payload | R6 [PROPOSAL]: events carry `event_type`, `event_id`, `schema_version`, `occurred_at` |
| Future state | Reversal (D12) and Idempotency-Key (D17) parked; current model does not block either | none |
| Profile alignment | Domain model consistent with analyst/architect reasoning; gap: formal event contract not yet written | Covered in architecture piece; not blocking |

## 10b. Analyst passes · architecture (2026-11-11)

State: R7 to R9 confirmed by Sasha (2026-11-11); the [PROPOSAL] tags below are resolved as accepted.

| Pass | Finding | Derived requirement |
|---|---|---|
| Edge case | Relay crashes after publisher confirm, before marking the row published → duplicate publish | Covered by inbox dedup on `message_id` |
| Edge case | Consumer commits, crashes before ack → redelivery | Covered by inbox dedup; Billing writes inbox row, billing record and outbox reply in one transaction |
| Edge case | Broker lost while consumers are connected | R7 [PROPOSAL]: consumers and relays reconnect automatically with backoff |
| Edge case | VisitCompleted for a visit that already has an active record (defence in depth; should not happen after D17) | R8 [PROPOSAL]: on unique-index conflict, Billing replies BillingRecordCreated with the existing record (no second record, visit still gets completed) |
| Edge case | Malformed or unparseable message | R9 [PROPOSAL]: sent straight to the module's parking queue via DLX, no retries |
| Risk | Outbox growth | Covered by R5 (clean-up job in the worker) |
| Future state | Extracting a module into its own service: schema per module and event-only contract make this a configuration change, not a redesign | none |
| Profile alignment | Design reflects standard analyst/architect reasoning (outbox, inbox, idempotent consumer, DB-enforced boundaries) | none; not blocking |

## 11. Findings log (append-only)

### 2026-11-11 · Session 1
- Brief received: greenfield; two entities (Visit, BillingRecord); modular monolith; event-only communication; outbox-like guarantees; broker choice delegated to us; concurrency test required.
- D9 closed: two-phase completion chosen (option 2).
- D14 closed: In Progress plus `completion_requested_at`.
- D15 closed: BillingFailed after 5 retries (Sasha's proposal).
- D15 refined: transient retried, permanent fail fast; counter persisted.
- D16: Sasha asked whether Canceled/Missed suffice; analysis says no (business vs technical outcome). Recommendation: option 1 plus a `completion_failure_reason` field.
- D16 closed as recommended; D15 unknown-error default confirmed.
- D17: Sasha asked for best practice. Recommendation: 409 for the loser. Rationale: without a client idempotency key the server cannot tell a retry from a competing request, so returning 202 to both hides a real conflict; HTTP semantics put state conflicts on 409. True idempotent retries belong to the `Idempotency-Key` header pattern (IETF httpapi draft), parked for vNext. Awaiting confirmation.
- D17 closed: 409.
- D10 closed: Scheduled and In Progress. Raises D18 (pending status for Scheduled source). Edge case noted: complete on a Scheduled visit before its start_date_time.
- D18: Sasha asked for a recommendation. Recommended option 1 (status unchanged; pending expressed only by `completion_requested_at`), with a derived read field `completion_pending` in API responses [PROPOSAL]. Rationale: one source of truth for pending; rollback on BillingFailed is a single field reset; no fake Scheduled → In Progress transition; consistent with D14 (pending is a flag, not a status). Awaiting confirmation.
- D18 closed as recommended.
- D11 evidence: the Visit model has only planned times (start_date_time, end_date_time); no actual start/end fields exist, so the only available duration is the planned one. Because of D5, Billing cannot read Visits' tables: whatever it needs must travel in the VisitCompleted payload.
- D11 closed: Billing computes; Decimal, 2 places, ROUND_HALF_UP; creation-time validation accepted.
- D12 evidence: the brief says "only one active billing record", which implies Reversed records may coexist with a new Created one; the brief defines no operation that reverses.
- D12 closed: model only. Domain semantics passes run; R1 to R6 proposed (§10a).
- R1 to R6 accepted. Domain semantics closed.
- D8 re-assessment after domain decisions: dedup (inbox), retry counting (D15) and parking are implemented in our tables, so broker-native dedup and retry features weigh less. Remaining criteria: at-least-once with ack and redelivery, durable queues, two-way flow, light docker-compose footprint, Python client maturity (FastStream supports RabbitMQ, Kafka, NATS, Redis), ease of simulating outage in tests.
- D8 closed: RabbitMQ.
- D13 options: (1) one database, schema per module (`visits`, `billing`) with a database role per module granted only on its own schema; (2) one schema, isolation by convention; (3) separate databases. Constraint: each module's outbox must sit in the same database as its business tables so the state change and the event are one local transaction (holds for all three). Recommendation: option 1. Reuse candidate for code-level isolation: import-linter (forbids Visits importing Billing internals and vice versa).
- D13 closed: option 1 with import-linter.
- D28 closed (build defaults). Python 3.15.2 verified: python.org latest release, 2026-10-25 (https://www.python.org/downloads/latest/); 3.15.0 final on 2026-10-09 (https://blog.python.org/2026/10/python-3150-final-is-here/).
- D19 options: (1) polling relay with `SELECT ... FOR UPDATE SKIP LOCKED`, batches, exponential backoff when the broker is down; (2) LISTEN/NOTIFY to wake the relay, polling kept as fallback; (3) CDC with Debezium. Placement: inside the FastAPI process (lifespan task) or a separate worker process. Recommendation: option 1 in a separate worker process.
- D19 closed: polling relay in a separate worker.
- D20 [PROPOSAL] event contract and topology:
  - Envelope (R6): `event_id` (UUID), `event_type`, `schema_version`, `occurred_at`, `payload`.
  - VisitCompleted (Visits → Billing): `visit_id`, `completion_attempt_id` (= event_id, R1), `rate`, `start_date_time`, `end_date_time`.
  - BillingRecordCreated (Billing → Visits): `visit_id`, `completion_attempt_id`, `billing_record_id`, `amount`.
  - BillingFailed (Billing → Visits): `visit_id`, `completion_attempt_id`, `reason`, `error_class` (transient_exhausted | permanent).
  - Topology: one durable topic exchange `jiris.events`; routing keys `visits.visit_completed`, `billing.record_created`, `billing.failed`; one queue per consuming module (`billing.inbox` bound to `visits.*`, `visits.inbox` bound to `billing.*`); a dead-letter exchange `jiris.dlx` with one parking queue per module.
  - Messages persistent; `message_id` = `event_id` (inbox dedup key).
  - Worker: one process running two relay loops, each with its own module role and pool (D13), plus the two consumers.
  - Consumer library: FastStream over aio-pika (reuse), to confirm at build time.
- D20 confirmed by Sasha. Architecture passes run (§10b); R7 to R9 proposed. Test strategy D21 proposed (§9).
- R7 to R9 and D21 confirmed. Discovery closed.
- SDD review: questions 1 to 5 closed (D22 to D26). D27 options: (1) shared `app.contracts` package with versioned Pydantic schemas, importable by both modules, importing nothing from them (import-linter enforces); (2) each module keeps its own copy of the schema plus contract tests against JSON samples. Recommendation: option 1 (one source of truth, no drift, standard "published language" in a modular monolith; on extraction to services it becomes a small library or a JSON Schema).
- Knowledge: `Idempotency-Key` vs JWT `jti`. `jti` identifies a token (credential), reused across many requests; used against token replay and for revocation. `Idempotency-Key` identifies one business operation, generated by the client per operation and resent unchanged on retries. Same mechanism (unique id stored server-side), different scope; `jti` cannot replace it.
- Description of the domain deliberately not provided by Sasha for now.

- Celery considered and rejected for the event flow (Sasha's question): Celery is a task queue (a producer calls a named task on a worker), not a publish/subscribe event bus. It would make Visits address a Billing task by name (coupling against D5), imposes its own message protocol (hard to carry our envelope, `message_id` = `event_id`, publisher confirms from the outbox relay), keeps retry counts in the message rather than in our inbox (conflicts with D15), and is not asyncio-native (stack is FastAPI + asyncpg). Fits background jobs, not inter-module events. FastStream is a thin asyncio framework on top of aio-pika (one stack, not two libraries).

## 12. Parking lot / future releases (append-only)

| Idea | Target release | Trigger | Origin | State |
|---|---|---|---|---|
| Reversal flow (Cancel after Completed → Reversed) | vNext / someday | D12 | Brief mentions Reversed status only | parked |
| Reversal operation `POST /api/billing-records/{id}/reverse` + BillingRecordReversed, with visit state rule | vNext | Business need for corrections | D12 discussion | parked |
| `Idempotency-Key` header on `/complete` (replay same response for same key) | vNext | Clients need safe automatic retries | D17 discussion | parked |
