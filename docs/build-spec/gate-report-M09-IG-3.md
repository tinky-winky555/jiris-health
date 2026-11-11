# Gate report M09, IG-3 (planning), README, definition of complete, release

Module: `module-09-release.md` · Date: 2026-11-11 · Branch:
`feature/m09-release`, created from `build/increments` at `b4e047e` (M08
merged) · Baseline: 408 collected, 408 passed. `main` is at `697fa9e`
(documents only), 72 commits behind `build/increments`.

HG-1 given by Sasha on 2026-11-11: DL-42 keeps its number; OQ-29 yes
(DL-43); OQ-30 option A (DL-44); OQ-31 yes (DL-45). Stops: IG-7, then a
separate HG-3 stop with the difference `main..build/increments` and a
clean-clone run.

## IG-1. Scope and affected surfaces

| Surface | Change |
|---|---|
| `README.md` | Rewritten from the scaffolding version (task 3.2) |
| `tests/unit/test_readme.py` (new) | Task 3.1.1 |
| `CLAUDE.md` | COMMANDS: the local run line needs a filled `.env` |
| `docs/build-spec/index.md` | Section g item 4 (OQ-29) |
| `docs/build-spec/contract.md` | §5, §6, §7a; the post-release record on `build/increments` (OQ-31) |
| `docs/build-spec/gate-report-M09-IG-7.md` | The audit of section g |
| `main` (HG-3 only) | The release merge, and the tag if OQ-30 approves it |

Not touched: application code, tests other than the README test, schema,
compose.

## IG-2. Dependencies, risks, assumptions, edge cases

Dependencies:

- M08 complete and merged (`b4e047e`). Met.
- Push rights to `origin` for `main` (HG-3).

Assumptions:

| ID | Assumption | Consequence if false |
|---|---|---|
| A1 | `main` has no commit that `build/increments` lacks (`main` at `697fa9e`, an ancestor) | The release merge would need a conflict resolution; checked before HG-3 with `git merge-base --is-ancestor main build/increments` |
| A2 | `origin` accepts a push to `main` from this account, with no protection rule requiring a pull request | If refused, the merge stays local and the developer decides how to publish it |

Risks:

| Risk | Mitigation |
|---|---|
| The README drifts from the code | 3.1.1 ties it to CLAUDE.md, `.env.example`, TDD §6.1 and §7; the audit follows the README literally from a clean clone |
| An accidental merge into `main` before HG-3 | The merge is a separate stop after the IG-7 approval; nothing is merged without the developer's explicit yes |
| The audit passes on the working copy but not from a clone | Every audit step runs in a fresh clone in the scratch directory |
| A generated `.env` with passwords lands in the repository | The audit writes it in the clone in the scratch directory, never in the working copy; `.env` is ignored and refused by `git add` (DL-38) |

## IG-3. Execution sequence (tests first)

1. After HG-1: commit `module-09`, this report, contract §5, §6, §7a,
   index section g item 4 if OQ-29 is approved (`docs:`).
2. README test (`test:` commit), red against the scaffolding README.
3. README and CLAUDE.md COMMANDS (`docs:`); the test green.
4. Audit of index section g from a fresh clone following the README;
   evidence collected.
5. `gate-report-M09-IG-7.md`, checkboxes, contract §5; stop for the IG-7
   approval; merge `feature/m09-release` into `build/increments` per BS-3
   and push.
6. **Stop for HG-3.** Present the commits and files between `main` and
   `build/increments` and the clean-clone result; wait for an explicit
   yes.
7. After the yes only: merge as OQ-30, push, post-release record as
   OQ-31.

## Questions for HG-1 (contract section 7a)

Answered at HG-1 (DL-43 to DL-45). The questions as asked:

| ID | Question | Agent's recommendation |
|---|---|---|
| OQ-29 | Amend index section g item 4 to say "with `.env` filled from `.env.example`"? | Yes |
| OQ-30 | Release by `git merge --no-ff` with `Release 1.0: Jiris Health, M01 to M09` and an annotated tag `v1.0.0`, both pushed? | Yes |
| OQ-31 | Post-release record in one `docs:` commit on `build/increments` only? | Yes |
