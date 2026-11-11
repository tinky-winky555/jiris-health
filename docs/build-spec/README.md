# Build Spec area

This folder holds the Build Spec: the execution plan the coding agent
follows module by module under the Full Envelope.

| File | What it is |
|---|---|
| `contract.md` | The developer's operating panel and the first gate (HG-1). Seven sections; 1 to 4 locked after approval, 5 to 7 live. |
| `index.md` | Structural backbone: module list, dependency graph, repository tree, conventions, glossary, definition of complete, out of scope. |
| `module-NN-<slug>.md` | One execution session each: goal, prerequisites, numbered tasks, binary acceptance criteria, binding out of scope, handoff. |
| `gate-report-MNN-IG-3.md` | Planning report (IG-1 to IG-3), before code. |
| `gate-report-MNN-IG-7.md` | Completion report (IG-4 to IG-7), when the criteria pass. |
| `adoption-prompt.md` | Paste into Claude Code once to adopt this Build Spec in the repository. |

The control registers live one level up (`../technical-debt.md`,
`../feature-backlog.md`).

Execution rules (short form; the index restates them): strict
sequential order, one module per session, validate acceptance criteria
before advancing, out of scope is binding, source of truth
TDD > PRD > module > index.
