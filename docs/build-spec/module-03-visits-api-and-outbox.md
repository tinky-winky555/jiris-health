# Module 03, Visits API, completion endpoint and outbox write

Effort: 10 hours · Prerequisites: M01, M02

## 1. Goal

Deliver the Visits HTTP API of TDD §6.1 and the completion transaction
of TDD §6.2: `/complete` validates the status, sets the pending marker
and writes VisitCompleted to `visits.outbox` in one transaction, so that
of two concurrent requests exactly one wins. It does not publish
anything to RabbitMQ (M04), consume anything (M05, M06), or handle
Billing replies (M06).

## 2. Prerequisites

- M02 acceptance criteria pass; M02 committed.
- Contract HG-1 given; OQ-1 and OQ-2 answered (DL-1, DL-6).
- HG-1 on this document and `gate-report-M03-IG-3.md` given by Sasha on
  2026-11-11, with OQ-5 to OQ-8 approved (DL-13 to DL-16).

## 3. Tasks

3.1 Tests first (each seen failing before its code):
- 3.1.1 Unit: creation validation (`rate ≤ 0`, `end ≤ start`; `rate`
  with more than 2 decimal places, unknown fields, DL-12; naive
  timestamps, DL-13) → 422 (T8, validation half).
- 3.1.2 Integration: `POST /api/visits` → 201 with the visit body
  (index section e); `GET /api/visits/{id}` → 200, unknown → 404 with
  `{"detail": "Not Found"}` (DL-10).
- 3.1.3 Integration: `/start` Scheduled → In Progress; `/cancel`,
  `/missed` per TDD §6 state machine; each 200 with the body; invalid
  transition → 409 `invalid_status`.
- 3.1.4 Integration: `/complete` from Scheduled and from In Progress →
  202, `completion_pending: true`, one outbox row; from Completed,
  Canceled, Missed → 409 `invalid_status`; unknown → 404; second call
  while pending → 409 `completion_pending`.
- 3.1.5 Integration: `/cancel`, `/missed` and `/start` while pending →
  409 `completion_pending` (R2, DL-11).
- 3.1.6 Integration: two concurrent `/complete` on one visit, on two
  separate database connections → exactly one 202, one 409, exactly one
  VisitCompleted row in `visits.outbox`. This is the first half of T1;
  T1 itself stays as decided in DL-6.
- 3.1.7 Integration (DL-16): a separate `visits_app`
  connection holds the row with the conditional UPDATE in an open
  transaction; `/complete` answers only after that COMMIT, with 409
  `completion_pending`.
- 3.1.8 Integration (DL-16): after a reset done by SQL
  (`completion_requested_at` NULL, `completion_failure_reason` set),
  `/complete` → 202, reason cleared, new attempt id, second outbox row.
- 3.1.9 Integration: the API app starts with `VISITS_DATABASE_URL` only,
  and each command writes one log line (contract section 3, Logging).
3.2 `app.contracts`: envelope and VisitCompleted models (TDD §7);
money as decimal string; `schema_version = 1`. BillingRecordCreated,
BillingFailed and the exchange constants are not added here (DL-14).
3.3 `app.visits.service`: the conditional UPDATE of TDD §6.2, with an
equivalent predicate and SET (the ORM statement may return the whole
row):

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

followed in the same transaction by the outbox INSERT with
`event_id = :event_id`; zero rows → read the visit → 404 or 409 with the
reason.
3.4 `app.visits.api`: routes of TDD §6.1 for visits (not
`GET /api/billing-records`, which belongs to M05); `completion_pending`
derived as TDD §5.2.
3.5 `app.main_api`: FastAPI app, connection pool as `visits_app` only.
3.6 TDD §6, §6.1 and §6.3 and contract §3 updated for DL-10, DL-11 and
DL-12 (IG-6).
3.7 Full return annotations on every function (index section e); one
log line per command with `visit_id`, `event_id` where present, outcome.

## 4. Acceptance criteria

- [x] Every test of task 3.1 passes.
- [x] 3.1.6 passes 50 of 50 runs.
- [x] After a `/complete`, `SELECT count(*) FROM visits.outbox WHERE
  published_at IS NULL` for the visit under test equals 1 (DL-15) and the row's payload validates against the VisitCompleted model.
- [x] The API process opens no connection as `billing_app` (verified by
  configuration and by T7 still passing).
- [x] `uv run lint-imports` passes; `alembic -n visits check` and
  `alembic -n billing check` pass.
- [x] Collected test count is at least the M02 total plus the new tests.

Completion report: `gate-report-M03-IG-7.md`.

## 5. Out of scope

| Item | Destination |
|---|---|
| Publishing outbox rows | M04 |
| `GET /api/billing-records` | M05 |
| Applying BillingRecordCreated / BillingFailed | M06 |
| Authentication | Future release (index section h) |

## 6. What comes next

M04 builds the outbox relay and declares the RabbitMQ topology, so that
the rows written here reach `billing.inbox`.
