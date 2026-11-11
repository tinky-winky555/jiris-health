# Jiris Health · Product Requirements Document (PRD)

Version 1.0 · 2026-11-11 · Owner: Sasha · Status: approved
Source of truth: `docs/HANDOFF.md` (decisions D1 to D27, requirements R1 to R9). Companion: `docs/TDD.md`.

---

## 1. Summary

Jiris Health is a small back-end service, built as a modular monolith with two modules (Visits and Billing), that records caregiver visits and bills every completed visit exactly once. It must keep this guarantee when the message broker is unavailable, when events are delivered twice and when two completion requests arrive at the same time.

## 2. Problem and outcome

- **Problem:** greenfield. A completed visit must always produce one, and only one, active billing record, while the two modules stay strictly separated and communicate only through events.
- **Outcome:** a FastAPI + PostgreSQL + RabbitMQ application whose guarantees are demonstrated by an automated test suite, including a test of two concurrent completion requests on the same visit.

## 3. Users

| Profile | Need |
|---|---|
| API client (caregiver application or scheduler) | Create visits and complete them; see whether completion is pending, done or failed |
| Operator | No manual action needed to recover from broker outages or duplicate deliveries |

## 4. Domain

| Entity | Attributes | States |
|---|---|---|
| Visit: a scheduled period during which a caregiver provides services to a patient | `start_date_time`, `end_date_time`, `description`, `rate` (per hour) | Scheduled, In Progress, Completed, Canceled, Missed |
| BillingRecord: a billing entry created for a completed visit | `visit_id`, `amount` | Created, Reversed |

Rule: only one active (Created) billing record may exist for a visit (D3).

## 5. Scope

**In scope**

- Visits module: visit creation with validation, completion endpoint, status changes driven by Billing replies.
- Billing module: billing record creation from events, amount calculation, failure reporting.
- Event processing through RabbitMQ with transactional outbox, inbox de-duplication, retries and dead-lettering.
- Automated tests T1 to T8 (section 8).
- Supporting endpoints needed to exercise the flow (create, read, start, cancel, mark missed): defined in the TDD (D28), since the brief names only `/complete`.

**Out of scope (parked for a later release)**

- Reversal operation and BillingRecordReversed event (D12); `Reversed` exists in the model only.
- `Idempotency-Key` header on `/complete` (D17).
- Actual start and end times of a visit and billing on actual duration.
- LISTEN/NOTIFY optimisation of the outbox relay (D19).
- Authentication and authorisation.

## 6. Functional requirements

| # | Requirement | Ref |
|---|---|---|
| FR1 | `POST /api/visits/{id}/complete` validates the current status and, in one transaction, marks the visit as pending completion and records a VisitCompleted event | D4, D9, D14 |
| FR2 | Completion is allowed from Scheduled and In Progress only | D10 |
| FR3 | While pending, the visit keeps its status; pending is expressed by `completion_requested_at`; the API exposes a derived `completion_pending` flag | D14, D18 |
| FR4 | Responses: 202 when accepted; 409 when the visit is pending, lost a concurrent race, or is Completed, Canceled or Missed; 404 when the visit does not exist | D17, R4 |
| FR5 | Billing computes `amount = rate × (end_date_time − start_date_time)` in hours, in Decimal, rounded to 2 places with ROUND_HALF_UP | D11 |
| FR6 | Billing creates the record and replies BillingRecordCreated; on receipt Visits sets the visit to Completed | D9 |
| FR7 | Billing retries transient errors up to 5 times; permanent errors fail at once; unclassified errors count as transient; on failure Billing replies BillingFailed | D15 |
| FR8 | On BillingFailed, Visits clears `completion_requested_at`, stores the cause in `completion_failure_reason`, and `/complete` can be called again | D16 |
| FR9 | Visits applies a reply only when its `completion_attempt_id` matches the current attempt; other replies are ignored | R1 |
| FR10 | Cancel or Missed on a pending visit is rejected with 409 | R2 |
| FR11 | Visit creation rejects `rate ≤ 0` and `end_date_time ≤ start_date_time` with 422 | D11, D24 |
| FR12 | `completion_requested_at` is kept after Completed as history | D23 |

## 7. Non-functional requirements (guarantees)

| # | Requirement | Ref |
|---|---|---|
| NFR1 | A completed visit always gets a billing record, even if the broker is unavailable | D6 |
| NFR2 | A visit never gets two active billing records, even under duplicate delivery or concurrent requests | D6 |
| NFR3 | Visits and Billing never read or write each other's tables; they communicate only through events; enforced by database roles and import-linter | D5, D13 |
| NFR4 | Events that could not be published are published later without manual intervention | D6, D19 |
| NFR5 | Relays and consumers reconnect to the broker automatically with backoff | R7 |
| NFR6 | Malformed messages go to a parking queue without retries | R9 |
| NFR7 | Published outbox rows are purged after 7 days | R5, D25 |
| NFR8 | Every event carries `event_id`, `event_type`, `schema_version`, `occurred_at` | R6 |

## 8. Acceptance criteria

| # | Given / When | Then | Covers |
|---|---|---|---|
| T1 | A visit In Progress; two `/complete` requests sent concurrently | One 202 and one 409; one VisitCompleted in the outbox; after processing the visit is Completed with exactly one billing record | NFR2, FR4 |
| T2 | The same VisitCompleted is delivered twice | One billing record and one reply | NFR2 |
| T3 | Broker stopped; `/complete` called; broker restarted | 202; the event waits in the outbox; after restart the visit is Completed with a record, with no manual step | NFR1, NFR4, NFR5 |
| T4 | Billing hits a permanent error | BillingFailed; visit back to its source status, `completion_failure_reason` set; `/complete` works again | FR7, FR8 |
| T5 | Billing hits a transient error 5 times, with a worker restart between attempts | Counter survives the restart; BillingFailed after the 5th attempt | FR7 |
| T6 | A reply arrives with an old `completion_attempt_id` | Ignored | FR9 |
| T7 | The Visits database role queries the Billing schema; import-linter runs | Permission error; linter passes | NFR3 |
| T8 | Amount calculation and creation validation | Decimal, 2 places, HALF_UP; invalid `rate` and times rejected with 422 | FR5, FR11 |

## 9. Success and stop conditions

- **Success:** T1 to T8 green in CI; zero duplicate records; no manual step in the outage scenario.
- **Stop:** T1, T2 or T3 cannot pass with this design; that would reopen D8, D19 or D20.

## 10. Assumptions and constraints

- Stack fixed: FastAPI, PostgreSQL, RabbitMQ (D1, D8).
- Only planned times exist; completing a visit before `start_date_time` bills the planned duration (D10, D11).
- No start operation is required by the brief; how a visit reaches In Progress is defined in the TDD: `POST /api/visits/{id}/start` (D28).

## 11. Glossary

| Term | Meaning |
|---|---|
| Outbox | Table where a module writes outgoing events in the same transaction as its state change |
| Relay | Worker loop that publishes outbox rows to RabbitMQ and marks them published |
| Inbox | Table where a module records processed event ids, used for de-duplication and retry counting |
| Completion attempt | One accepted `/complete` call, identified by `completion_attempt_id` (equal to the VisitCompleted `event_id`) |
| Parking queue | Dead-letter queue for messages that cannot or must not be retried |
