# Nexus

**A multi-agent bug-fix pipeline.** A GitHub bug report goes in; a reviewed, regression-tested pull request comes out — produced by three specialized agents that hand strictly-typed contracts to one another, with a validation feedback loop in the middle.

Nexus is the multi-agent evolution of [Patchwork](https://github.com/rohan1402/patchwork) (single-agent: issue → regression test → PR). It wraps Patchwork's capability in two specialists: a **Bug Analyzer** that cleans the input, and a **Validator** that judges the output and loops back when it isn't good enough.

Built on the [Lyzr ADK](https://docs.lyzr.ai) with Gemini 2.5 Pro.

---

## The pipeline

```
                 GitHubIssue
                      │
                      ▼
            ┌────────────────────┐
            │  1 · Bug Analyzer  │   issue → cleaned, structured triage
            └────────────────────┘
                      │ BugAnalysis
                      ▼
            ┌────────────────────┐ ◀──────────────────────────┐
            │  2 · Patchwork     │   locates code (mocked) +   │  feedback
            │                    │   writes the regression test│  (rejected)
            └────────────────────┘                             │
                      │ Patch                                   │
                      ▼                                         │
            ┌────────────────────┐ ────────────────────────────┘
            │  3 · Validator     │   scores test coverage;
            │                    │   approve, or send back
            └────────────────────┘
                      │ approved
                      ▼
              open PR via GitHub API
```

| # | Node | Input → Output | Responsibility |
|---|------|----------------|----------------|
| 1 | **Bug Analyzer** | `GitHubIssue` → `BugAnalysis` | Clean the report into structured triage: severity, affected files, error context, search keywords. |
| 2 | **Patchwork** | `BugAnalysis` (+ feedback) → `Patch` | The Patchwork capability as one node: locate the relevant code *(mocked)* and write a regression test that fails on the bug and passes once fixed. |
| 3 | **Validator** | `Patch` → `ValidationResult` | Score how well the test covers the bug; reject back to Patchwork below the threshold. |

The PR is opened **only after the Validator approves**, so a reject→retry never spams pull requests.

---

## Design decisions

The orchestration matters as much as the output.

1. **Three nodes, on purpose.** Multi-agent value comes from clean separation of concerns
   and a real feedback loop — not from maximizing the node count. Patchwork is one cohesive
   capability; splitting it further would be ceremony. The defensible shape is: *clean the
   input → do the work → judge the work and loop.*

2. **Strict typed handoffs (Pydantic on every edge).** Each agent declares a Pydantic
   `response_model`; Lyzr returns a validated instance, not free text. The contracts in
   [`schemas.py`](src/nexus/schemas.py) *are* the interface — a node cannot pass malformed
   data downstream.

3. **Agent definitions decoupled from a swappable runtime.** An agent is a declarative spec
   (role, goal, instructions, response_model); a `runtime` executes it. `LyzrRuntime` is real
   (Lyzr cloud + Gemini 2.5 Pro); `MockRuntime` is deterministic and offline — so the whole
   pipeline, **including the feedback loop, runs and unit-tests with zero API keys.**

4. **Explicit orchestration over implicit delegation.** Lyzr offers `managed_agents`, but
   [`orchestrator.py`](src/nexus/orchestrator.py) keeps the control flow — the loop and the
   pre-PR gate — visible and testable rather than hidden inside a model's planning.

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env          # NEXUS_RUNTIME=mock works with no keys
nexus run examples/sample_issue.json -v
```

A mock run shows the loop firing: Patchwork's first attempt is rejected by the Validator, its
feedback drives a revised test, and the second attempt is approved.

To run against the real Lyzr cloud, set in `.env`: `LYZR_API_KEY`, a Gemini
`LYZR_LLM_CREDENTIAL_ID` (the name of your Gemini credential in the Lyzr studio — your Google
API key lives there, not in this repo), and `NEXUS_RUNTIME=lyzr`. Set `GITHUB_TOKEN` to open
real PRs.

---

## Project structure

```
src/nexus/
├── config.py            # env-driven settings (runtime, provider, threshold, attempts)
├── schemas.py           # the typed handoff contracts: GitHubIssue → BugAnalysis → Patch → ValidationResult
├── github.py            # draft / open the PR (PyGithub; opens only with a token)
├── runtime/
│   ├── base.py          # AgentRuntime protocol + AgentSpec
│   ├── lyzr_runtime.py  # real, Lyzr Studio–backed
│   └── mock_runtime.py  # deterministic, offline
├── agents/
│   ├── base.py          # BaseAgent: spec + run(payload) -> response_model
│   ├── bug_analyzer.py  # node 1
│   ├── patchwork.py     # node 2
│   └── validator.py     # node 3
├── orchestrator.py      # the three-node flow + validator feedback loop
└── cli.py               # `nexus run <issue.json>`
```

## Status

- [x] Three-node pipeline runs end-to-end on the mock runtime (`pytest`: 17 passing)
- [x] Validator feedback loop (reject → revise → approve)
- [x] PR drafting; opening wired via PyGithub (needs `GITHUB_TOKEN`)
- [x] `LyzrRuntime` wired to the real `lyzr-adk` 0.1.10 sync API (`studio.agents.create/
      list/update`, `agent.run`), with an offline contract test that pins the SDK surface
- [ ] Live Gemini round-trip executed (set `LYZR_API_KEY` + `LYZR_LLM_CREDENTIAL_ID`
      locally and flip `NEXUS_RUNTIME=lyzr` — the one step that needs real credentials)
