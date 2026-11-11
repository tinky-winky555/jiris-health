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

## 3. Tasks

3.1 Tests first (each seen failing before its code):
- 3.1.1 Unit: creation validation (`rate ≤ 0`, `end ≤ start`) → 422
  (T8, validation half).
- 3.1.2 Integration: `POST /api/visits` → 201 with the visit body
  (index section e); `GET /api/visits/{id}` → 200, unknown → 404.
- 3.1.3 Integration: `/start` Scheduled → In Progress; `/cancel`,
  `/missed` per TDD §6 state machine; each 200 with the body; invalid
  transition → 409 `invalid_status`.
- 3.1.4 Integration: `/complete` from Scheduled and from In Progress →
  202, `completion_pending: true`, one outbox row; from Completed,
  Canceled, Missed → 409 `invalid_status`; unknown → 404; second call
  while pending → 409 `completion_pending`.
- 3.1.5 Integration: `/cancel` and `/missed` while pending → 409
  `completion_pending` (R2).
- 3.1.6 Integration: two concurrent `/complete` on one visit, on two
  separate database connections → exactly one 202, one 409, exactly one
  VisitCompleted row in `visits.outbox`. This is the first half of T1;
  T1 itself stays as decided in OQ-2.
3.2 `app.contracts`: envelope and VisitCompleted models (TDD §7);
money as decimal string; `schema_version = 1`.
3.3 `app.visits.service`: the conditional UPDATE of TDD §6.2, exactly:

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
3.6 TDD §6.1 updated if any response detail differs (IG-6).

## 4. Acceptance criteria

- [ ] Every test of task 3.1 passes.
- [ ] 3.1.6 passes 50 of 50 runs.
- [ ] After a `/complete`, `SELECT count(*) FROM visits.outbox WHERE
  published_at IS NULL` equals 1 and the row's payload validates against
  the VisitCompleted model.
- [ ] The API process opens no connection as `billing_app` (verified by
  configuration and by T7 still passing).
- [ ] `uv run lint-imports` passes; `alembic -n visits check` and
  `alembic -n billing check` pass.
- [ ] Collected test count is at least the M02 total plus the new tests.

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
