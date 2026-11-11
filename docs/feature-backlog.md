# Feature backlog register, Jiris Health

Features identified as desirable but out of scope of the current
release. No contract update is needed for a new entry.

States: Open · In progress · Blocked (Reason names the external dependency) · Paused (Reason names the priority decision) · Done.

| ID | Title | State | Reason | Owner | Source module | Notes |
|---|---|---|---|---|---|---|
| FB-1 | Reversal operation `POST /api/billing-records/{id}/reverse` and BillingRecordReversed, with the visit state rule | Open | | Sasha | Handoff D12 | Next release |
| FB-2 | `Idempotency-Key` header on `/complete` | Open | | Sasha | Handoff D17 | Next release |
| FB-3 | LISTEN/NOTIFY wake-up for the outbox relay | Open | | Sasha | Handoff D19 | Future release; only if relay latency matters |
| FB-4 | Actual visit start and end times; billing on actual duration | Open | | Sasha | Handoff D10, D11 | Future release; needs `schema_version` 2 of VisitCompleted |
| FB-5 | Retention for `visits.inbox` and `billing.inbox` | Open | | Sasha | M08 planning (next release) | R5 purges published outbox rows only; inbox rows grow with every consumed event. A retention for processed inbox rows needs a de-duplication window longer than any redelivery; not in this release |
