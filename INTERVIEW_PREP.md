# Nexus — Lyzr Interview Prep

Everything you need to confidently discuss this repo. Structured as: (1) the
30-second pitch, (2) deep architecture walkthrough, (3) Lyzr-specific knowledge,
(4) likely questions with strong answers, (5) weaknesses to own, (6) extension ideas.

---

## 1. The 30-second pitch (memorize this)

> "Nexus is a multi-agent bug-fix pipeline. A GitHub bug report goes in; a
> reviewed, regression-tested pull request comes out. Three specialized agents
> hand each other strictly-typed Pydantic contracts: a **Bug Analyzer** triages the
> raw issue, **Patchwork** writes a regression test, and a **Validator** scores the
> test and loops back when it's not good enough. It's built on the **Lyzr ADK**
> running **Gemini 2.5 Pro**, but the whole pipeline — including the feedback loop —
> runs and unit-tests offline thanks to a swappable mock runtime."

Key phrases to drop: *typed handoffs*, *feedback loop*, *swappable runtime*,
*explicit orchestration*, *PR gate*.

---

## 2. Architecture walkthrough

### The pipeline shape
```
GitHubIssue → [1 Bug Analyzer] → BugAnalysis
            → [2 Patchwork]     → Patch  ◀─┐
            → [3 Validator]     → ValidationResult
                                          │ (feedback on reject)
                  approved ──→ open PR    │
                  rejected ───────────────┘
```

Three nodes, one feedback loop, one gate. The PR is opened **only after the
Validator approves** — so a reject→retry never spams pull requests.

### Layered design (why each layer exists)

| Layer | File | Responsibility |
|-------|------|----------------|
| **Schemas** | `schemas.py` | The typed contracts on every edge. These *are* the interface. |
| **Runtime** | `runtime/` | *How* an agent executes. `LyzrRuntime` (real) or `MockRuntime` (offline). Swappable behind a `Protocol`. |
| **Agents** | `agents/` | *What* each agent is — a declarative `AgentSpec` + a prompt builder + a mock output. |
| **Orchestrator** | `orchestrator.py` | The control flow: analyze → generate↔judge loop → gate → PR. |
| **GitHub** | `github.py` | Side-effect: draft the PR (pure) and optionally open it (PyGithub). |
| **CLI** | `cli.py` | `nexus run <issue.json>` entry point. |

### The three key abstractions

**`AgentSpec`** (`runtime/base.py`) — a *runtime-agnostic* description of an agent:
`name, role, goal, instructions, response_model, temperature`. It's just data — no
execution logic. This is what makes agents declarative.

**`AgentRuntime`** (a `Protocol`) — one method: `invoke(spec, message, *, mock) -> BaseModel`.
Two implementations, fully interchangeable:
- `LyzrRuntime`: creates the agent on the Lyzr cloud, runs it, coerces the result.
- `MockRuntime`: calls the agent's own `mock()` factory — deterministic, no network.

**`BaseAgent[TIn, TOut]`** (`agents/base.py`) — generic typed wrapper. Each concrete
agent sets a class-level `spec`, implements `build_message(payload) -> str` (renders
typed input into a prompt) and `mock_output(payload) -> TOut` (the offline stand-in).
`run()` ties it together: render → invoke → return validated output.

### Data flow through the contracts (`schemas.py`)
- `GitHubIssue` → entry contract (repo, number, title, body, labels).
- `BugAnalysis` → severity (enum), bug_type, affected_files/symbols, error_context,
  root-cause hypothesis, **search_keywords**, confidence (0–1).
- `PatchInput` = `BugAnalysis` + `feedback: list[str]` (from a prior rejection).
- `Patch` → test_file_path, test_code, framework, confidence (enum), summary.
- `ValidationInput` = analysis + patch.
- `ValidationResult` → approved, coverage_score (0–1), rationale, gaps, **suggestions**
  (the strings routed back into the next `PatchInput.feedback`).
- `PipelineResult` → the full record: issue, analysis, patch, validation, pull_request,
  attempts, status.

The feedback loop is just: `ValidationResult.suggestions` → `PatchInput.feedback`.

### The orchestrator loop (the heart — `orchestrator.py`)
```python
result.analysis = bug_analyzer.run(issue)         # node 1

feedback = []
while result.attempts < max_test_attempts:        # bounded retry
    result.attempts += 1
    result.patch = patchwork.run(PatchInput(analysis, feedback))   # node 2
    result.validation = validator.run(ValidationInput(analysis, patch))  # node 3
    if self._passes_gate(result.validation):
        break
    feedback = result.validation.suggestions       # loop with feedback

if not self._passes_gate(result.validation):
    result.status = "rejected: ..."; return result  # gate — no PR
result.pull_request = github.open_pull_request(...)  # only after approval
```

The gate: `approved OR coverage_score >= confidence_threshold` (default 0.7), bounded
by `max_test_attempts` (default 2).

---

## 3. Lyzr-specific knowledge (they WILL probe this)

**What is Lyzr?** An enterprise agent framework / Agent Development Kit (ADK). You
define server-side agents on the Lyzr Studio platform and run them; Lyzr handles the
LLM orchestration. This repo uses `lyzr.Studio`.

**How this repo uses Lyzr (`lyzr_runtime.py`):**
- `Studio(api_key=...)` — the client.
- `studio.create_agent(name, provider, role, goal, instructions, temperature,
  response_model=Model, llm_credential_id=...)` — registers a **server-side agent**.
  Crucially, passing `response_model=PydanticModel` means the agent returns a
  **validated Pydantic instance, not free text** — this is Lyzr's structured-output
  feature, and it's why the typed contracts hold end-to-end.
- `agent.run(message)` — executes it.
- `studio.list_agents()` / `studio.update_agent(id, ...)` — used for **idempotency**.

**The idempotency detail (a great thing to mention — it's the most recent commit):**
The naive implementation re-created a fresh server-side agent every process run,
piling up duplicates in the Lyzr account. `_get_or_create` now looks up the agent by
name via `list_agents()`; if it exists, it `update_agent`s it (keeping config in sync
with the current spec) instead of creating a duplicate. List failures fall back to
create — a listing error shouldn't block a run.

**`llm_credential_id`** — Lyzr stores your Google/Gemini API key as a *named credential*
in the Studio. The code references it by id (`lyzr_google`). **Your Google API key is
never in this repo** — it lives in Lyzr. Good security talking point.

**Provider string** — `google/gemini-2.5-pro`, passed as `provider`. Swapping models
is a config change (`NEXUS_LLM_PROVIDER`), not a code change.

**The `_coerce` defensive boundary** — even though `response_model` should make Lyzr
return the model directly, `_coerce()` defends against the response being wrapped
(`AgentResponse.response`), a dict, or a JSON string. "Defend the boundary you don't
own" — a maturity signal.

**Why NOT Lyzr `managed_agents`?** Lyzr offers `managed_agents` for implicit
delegation (one agent plans and calls others). Nexus deliberately keeps orchestration
**explicit** in `orchestrator.py` so the loop and the pre-PR gate are visible and
**testable**, rather than hidden inside a model's planning. Determinism + testability
over magic.

---

## 4. Likely questions & strong answers

**Q: Why exactly three agents? Why not split more (e.g. a separate code-locator)?**
A: Multi-agent value comes from clean separation of concerns and a real feedback loop,
not from maximizing node count. The defensible shape is *clean the input → do the work
→ judge the work and loop*. Patchwork is one cohesive capability (locate code + write
test); splitting code-location into its own node would be ceremony with extra handoff
cost and no clearer contract. Repo exploration is intentionally *internal* to Patchwork
and mocked.

**Q: How does the feedback loop actually work?**
A: The Validator emits `suggestions: list[str]`. On rejection the orchestrator sets
`feedback = validation.suggestions` and feeds it into the next `PatchInput`. Patchwork's
prompt builder appends "Validator feedback to address: ..." so the model revises.
Bounded by `max_test_attempts` so it can't loop forever. In the mock, the first attempt
is MEDIUM confidence → 0.62 coverage → rejected; the retry uses feedback → HIGH → 0.86
→ approved. That's exactly what the demo shows (attempts: 2, status: complete).

**Q: How do you test a system that depends on an LLM?**
A: The runtime is swappable behind a `Protocol`. `MockRuntime` calls each agent's own
`mock_output()` — deterministic, offline, no API keys. The whole pipeline including the
feedback loop unit-tests in 0.12s, 9 tests passing. The mocks use light heuristics
(regex over the issue text) so they look intelligent in a demo *and* stay deterministic.
The real `LyzrRuntime` swaps in with one env var (`NEXUS_RUNTIME=lyzr`).

**Q: Why Pydantic on every edge?**
A: The contracts ARE the interface. Each agent declares a `response_model`; Lyzr returns
a validated instance. A node literally cannot pass malformed data downstream — validation
errors surface at the boundary, not three nodes later. It also documents the system: read
`schemas.py` and you understand the whole data flow. Enums (`Severity`, `Confidence`)
constrain the value space; `Field(ge=0, le=1)` bounds the scores.

**Q: What happens if no GITHUB_TOKEN / network fails when opening the PR?**
A: `open_pull_request` always drafts first (pure, no network). Without a token it returns
the draft and logs. With a token it tries the GitHub API but wraps it in try/except —
network/permission failures log a warning and return the draft rather than crashing the
pipeline. The pipeline degrades gracefully and stays runnable offline.

**Q: How would you add a 4th agent / new step?**
A: (1) Define its input/output Pydantic contracts in `schemas.py`. (2) Subclass
`BaseAgent[TIn, TOut]` with a `spec`, `build_message`, and `mock_output`. (3) Wire it
into the orchestrator's flow. The runtime, CLI, and other agents don't change — that's
the payoff of the layering.

**Q: How does the Validator gate work / what's the threshold logic?**
A: `_passes_gate` returns true if `approved` OR `coverage_score >= confidence_threshold`
(0.7 default, env-configurable). The Validator itself approves at its own bar (0.75 in
the mock). The two-condition gate lets the orchestrator override with a configurable
threshold independent of the agent's own approval flag.

**Q: Where's the actual bug *fix*?** (honest gotcha)
A: Nexus produces a **regression test** (fails on the bug, passes once fixed) plus a PR,
not the source patch itself. That's intentional — it's the Patchwork lineage (issue →
regression test → PR). The "fix" framing is about capturing the bug in a test so a human
or downstream agent can fix with a safety net. Be precise about this; don't oversell.

**Q: Walk me through what happens for the sample issue.**
A: `examples/sample_issue.json` — checkout NoneType crash. Analyzer extracts
`src/checkout/service.py`, symbol `compute_total`, severity HIGH, type "null
dereference", confidence 0.72. Patchwork writes `tests/regression/test_...py` calling
`compute_total(None)`, MEDIUM confidence. Validator scores 0.62, rejects with two
suggestions. Patchwork retries with feedback, adds an empty-input case, HIGH confidence.
Validator scores 0.86, approves. PR drafted (no token → not opened). Status complete,
2 attempts.

---

## 5. Weaknesses to own (don't get caught off guard)

- **Mocks are heuristic, not real reasoning.** The offline path uses regex/keyword
  heuristics. Honest framing: "the mock is a deterministic stand-in for demos and tests;
  the real intelligence is Gemini via `LyzrRuntime`, which I'd flip on with credentials."
- **Code location is mocked / not implemented.** Patchwork doesn't actually grep the
  target repo; it synthesizes a module path from `affected_files`. Real version needs repo
  access (clone + search, or a code-search tool/MCP).
- **Real Lyzr run is unchecked** (`README` status: that box is unticked). The code is
  written against the Lyzr SDK API but hasn't been run end-to-end against the cloud in CI.
- **`_coerce` assumes the SDK shape.** If the Lyzr SDK returns something unexpected it
  raises a `TypeError` — defended but not proven against the live API.
- **Single issue at a time, synchronous.** No batching, no async, no retry/backoff on the
  LLM call itself.

Owning these calmly signals senior judgment far more than pretending they don't exist.

---

## 6. Extension ideas (shows product thinking)

- **Real code location**: give Patchwork repo access (clone the repo, run a code-search
  tool or an MCP server) instead of the mocked module-path synthesis.
- **Generate the fix, not just the test**: add a Fixer node that proposes the source
  patch, gated by the regression test actually going red→green.
- **Run the test for real**: execute the generated test in a sandbox to confirm it fails
  pre-fix (a stronger gate than the Validator's score).
- **Parallelize / batch**: process multiple issues; the stateless agents make this easy.
- **Observability**: structured logs/traces per node; Lyzr likely has built-in tracing.
- **Confidence-driven routing**: low-confidence analyses could request human input before
  burning LLM calls.

---

## 7. Quick facts cheat-sheet

- **Stack**: Python ≥3.10, Lyzr ADK, Gemini 2.5 Pro, Pydantic v2, PyGithub, pytest.
- **Run it**: `pip install -e .` then `nexus run examples/sample_issue.json -v`
  (mock runtime, no keys).
- **Tests**: `pytest` — 9 passing, ~0.12s, fully offline.
- **Env knobs**: `NEXUS_RUNTIME` (mock/lyzr), `NEXUS_LLM_PROVIDER`,
  `LYZR_API_KEY`, `LYZR_LLM_CREDENTIAL_ID`, `NEXUS_CONFIDENCE_THRESHOLD` (0.7),
  `NEXUS_MAX_TEST_ATTEMPTS` (2), `GITHUB_TOKEN`.
- **Lineage**: multi-agent evolution of Patchwork (single-agent issue→test→PR).
- **Design mantras**:
  1. Three nodes on purpose (separation + loop, not node-count maximizing).
  2. Strict typed handoffs (Pydantic on every edge).
  3. Agent specs decoupled from a swappable runtime.
  4. Explicit orchestration over implicit `managed_agents` delegation.
</content>
</invoke>
