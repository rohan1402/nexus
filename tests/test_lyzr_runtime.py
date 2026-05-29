"""LyzrRuntime contract tests — fully offline, no API keys, no network.

These pin the runtime to the *real* lyzr-adk 0.1.10 API surface (the sync methods
live on `studio.agents`: `create` / `list` / `update`) by driving the runtime with a
fake Studio. If the SDK shape the runtime expects ever drifts, these break.
"""

from __future__ import annotations

import json

import pytest

from nexus.runtime.lyzr_runtime import LyzrRuntime, _coerce
from nexus.schemas import BugAnalysis, Severity

# ── A minimal, valid response_model instance the fake agent will "return". ──────
ANALYSIS = BugAnalysis(
    summary="x.",
    severity=Severity.HIGH,
    bug_type="null dereference",
    suspected_root_cause="y",
    confidence=0.8,
)


class FakeAgent:
    def __init__(self, output):
        self._output = output
        self.runs: list[str] = []

    def run(self, message: str):
        self.runs.append(message)
        return self._output


class FakeAgentsModule:
    """Stands in for `studio.agents` — records calls to create / list / update."""

    def __init__(self, output, existing=None):
        self._output = output
        self._existing = existing or []  # list of objects/dicts with name + id
        self.create_calls: list[dict] = []
        self.update_calls: list[tuple] = []
        self.list_calls = 0

    def create(self, **kwargs):
        self.create_calls.append(kwargs)
        return FakeAgent(self._output)

    def update(self, agent_id, **kwargs):
        self.update_calls.append((agent_id, kwargs))
        return FakeAgent(self._output)

    def list(self):
        self.list_calls += 1
        return FakeAgentList(self._existing)


class FakeAgentList:
    def __init__(self, agents):
        self.agents = agents
        self.total = len(agents)


class FakeStudio:
    def __init__(self, agents_module):
        self.agents = agents_module


def make_runtime(agents_module) -> LyzrRuntime:
    return LyzrRuntime(
        api_key="unused",
        provider="google/gemini-2.5-pro",
        credential_id="lyzr_google",
        studio=FakeStudio(agents_module),
    )


# ── Tests ───────────────────────────────────────────────────────────────────────
def test_first_invoke_creates_agent_and_returns_coerced_model():
    agents = FakeAgentsModule(ANALYSIS)
    rt = make_runtime(agents)

    out = rt.invoke(_spec(), "a bug report")

    assert out is ANALYSIS
    assert len(agents.create_calls) == 1
    # The kwargs we send must match the real SDK's create() parameters.
    sent = agents.create_calls[0]
    assert sent["name"] == "Nexus Bug Analyzer"
    assert sent["provider"] == "google/gemini-2.5-pro"
    assert sent["response_model"] is BugAnalysis
    assert sent["llm_credential_id"] == "lyzr_google"


def test_second_invoke_reuses_cached_agent():
    agents = FakeAgentsModule(ANALYSIS)
    rt = make_runtime(agents)

    rt.invoke(_spec(), "first")
    rt.invoke(_spec(), "second")

    # Created once, cached in-process for the retry loop — no second create/list.
    assert len(agents.create_calls) == 1
    assert agents.list_calls == 1


def test_existing_agent_is_updated_not_recreated():
    # Idempotency path: an agent of this name already exists on the platform.
    existing = [{"name": "Nexus Bug Analyzer", "id": "agent-123"}]
    agents = FakeAgentsModule(ANALYSIS, existing=existing)
    rt = make_runtime(agents)

    rt.invoke(_spec(), "a bug report")

    assert agents.create_calls == []
    assert len(agents.update_calls) == 1
    assert agents.update_calls[0][0] == "agent-123"


def test_listing_failure_falls_back_to_create():
    agents = FakeAgentsModule(ANALYSIS)

    def boom():
        raise RuntimeError("network down")

    agents.list = boom  # a listing failure shouldn't block a fresh create
    rt = make_runtime(agents)

    out = rt.invoke(_spec(), "a bug report")
    assert out is ANALYSIS
    assert len(agents.create_calls) == 1


# ── _coerce defends the boundary against varied SDK return shapes ────────────────
def test_coerce_passes_through_model_instance():
    assert _coerce(ANALYSIS, BugAnalysis) is ANALYSIS


def test_coerce_unwraps_response_attribute():
    class Wrapper:
        response = ANALYSIS

    assert _coerce(Wrapper(), BugAnalysis) is ANALYSIS


def test_coerce_validates_dict_and_json():
    payload = ANALYSIS.model_dump()
    assert _coerce(payload, BugAnalysis) == ANALYSIS
    assert _coerce(json.dumps(payload), BugAnalysis) == ANALYSIS


def test_coerce_raises_on_unsupported_type():
    with pytest.raises(TypeError):
        _coerce(12345, BugAnalysis)


# ── helper ────────────────────────────────────────────────────────────────────
def _spec():
    from nexus.agents.bug_analyzer import SPEC

    return SPEC
