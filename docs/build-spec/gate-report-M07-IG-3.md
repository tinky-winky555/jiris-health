# Gate report M07, IG-3 (planning), Failure paths in Billing

Module: `module-07-failure-paths.md` · Date: 2026-11-11 · Branch:
`feature/m07-failure-paths`, created from `build/increments` at `0459df5`
(M06 merged) · Baseline: 325 collected, 325 passed.

HG-1 given by Sasha on 2026-11-11: OQ-22 yes (DL-35); OQ-23 yes except
SQLSTATE 23505 `unique_violation`, which stays transient, with a test of
two concurrent deliveries of one VisitCompleted (DL-36); replacement of
M05 test 4.1.9 approved.

## IG-1. Scope and affected surfaces

In scope:

| Surface | Change |
|---|---|
| `app/billing/service.py` | `PermanentError`; validation of duration and rate before any write; `record_permanent_failure()`, `count_transient_failure()` (short transactions writing `billing.inbox` and BillingFailed to `billing.outbox`) |
| `app/billing/consumer.py` | `classify()`; the failure path replacing DL-25 (b); backoff for an unavailable database |
| `tests/unit/` | `test_billing_classify.py`; permanent validation cases in `test_billing_amount.py` |
| `tests/integration/` | Failure tests in `test_billing_service.py` and `test_billing_consumer.py`; `test_t4_permanent_failure.py`, `test_t5_transient_exhausted.py` (new); M05 test 4.1.9 replaced |
| `docs/TDD.md` | §8.2 (OQ-22, OQ-23; interim note replaced) |
| `docs/build-spec/contract.md` | §3 Retries; §5; §6 |

Not touched: `app/visits` (its BillingFailed handling is M06), `app/outbox`
(the relay already routes `billing.failed`; the shared consumer mechanics
already carry what Billing needs), schema and migrations (`billing.inbox`
has `status`, `attempts`, `last_error` since M02), compose, Dockerfile.

Out of scope, binding: purge, README, release, remaining technical debt
(M08); replay tooling.

## IG-2. Dependencies, risks, assumptions, edge cases

Dependencies:

- M06 complete and merged (`0459df5`): the Visits consumer applies
  BillingFailed, so T4 and T5 can run end to end. Met.
- No new package. asyncpg exposes `sqlstate` on every server error, which
  `classify()` reads through the cause chain of the SQLAlchemy error.

Assumptions:

| ID | Assumption | Consequence if false |
|---|---|---|
| A1 | A rate of 9999999999.99 for 2 hours is accepted at visit creation (numeric(12,2), DL-12) and makes the amount insert fail with SQLSTATE 22003 | T4 would need a crafted message; 4.1.5 already covers the crafted path |
| A2 | A `RAISE EXCEPTION` in a trigger arrives as SQLSTATE P0001 and is therefore transient | T5 would need another injection; checked by 4.1.2 |
| A3 | On SIGTERM, a message in its 1 s requeue delay is either nacked or returned unacknowledged when the channel closes, so the new worker receives it with the counter at its persisted value | The counter could jump or the message stall; 4.1.9 checks both |
| A4 | `billing.inbox` status `failed` makes any later delivery a duplicate (M05 rule: anything not `processing`) | A redelivery after BillingFailed would bill again; 4.1.3 checks it |

Risks:

| Risk | Mitigation |
|---|---|
| Crash after the BillingFailed COMMIT and before the reject: the redelivery finds `failed`, is acknowledged as a duplicate and is not parked | Acceptable: the reply is already in the outbox; recorded as an edge case |
| A permanent error is acknowledged, not parked (TDD §8.2) | The inbox row keeps `last_error`; the visit carries `completion_failure_reason` |
| T5 timing: four requeue delays of 1 s plus a worker restart (about 3 s) | Timeout 60 s; the restart waits for the counter to reach 2, read from the database |
| The trigger of 4.1.6 and T5 must not leak into other tests | Named per test, limited to one `visit_id`, dropped in `finally` |
| TD-6: an `OperationalError` that is not about the connection is treated as unavailable in Billing too | Accepted until M08 (TD-6) |

Edge cases covered by tests:

- Permanent: duration zero or negative, rate zero or negative (crafted),
  numeric overflow (through the API).
- 23505 stays transient; two concurrent deliveries of one VisitCompleted
  give one record and no BillingFailed (4.1.11).
- Transient: counted 1 to 5, persisted across a worker restart; fifth
  attempt emits BillingFailed and parks.
- Database unavailable: never counted, never parked.
- Delivery after `failed`: duplicate, no second BillingFailed.
- No failure path ever writes a billing record.
- After a failure, `/complete` starts a new attempt and succeeds once the
  cause is gone.

## IG-3. Execution sequence (tests first)

1. After HG-1: commit `module-07`, this report, contract §5, §6, §7a,
   TDD §8.2, index section b (`docs:`).
2. Tests (`test:` commit): 4.1.1 to 4.1.9, the M05 test replaced; red run
   recorded.
3. `app/billing/service.py` (`feat:`): 4.1.1, 4.1.3, 4.1.4 green.
4. `app/billing/consumer.py` (`feat:`): 4.1.2, 4.1.5 to 4.1.9 green.
5. Documentation check against the code (`docs:`).
6. Validation: clean clone; full suite in file order and with the T1
   module first; T4 and T5 three times; lint; both `alembic check`; T7;
   `docker compose up` smoke of T4 (overflow visit reset, `/complete`
   accepted again); branch and count after every commit.
7. `gate-report-M07-IG-7.md`, checkboxes, contract §5; stop for approval;
   merge per BS-3.

## Questions for HG-1 (contract section 7a)

Answered at HG-1; the answers are in the contract (section 7a, resolved,
and DL-35, DL-36). The questions as asked:

| ID | Question | Agent's recommendation |
|---|---|---|
| OQ-22 | HG-2: database unavailable in Billing retried with backoff, unlimited, never counted, as in the relay and the Visits consumer; D15's 5 attempts for the other transient errors? | Yes |
| OQ-23 | HG-2: permanent class extended with SQLSTATE classes 22 and 23, so T4 runs end to end through the API; M05 interim test 4.1.9 replaced? | Yes |
