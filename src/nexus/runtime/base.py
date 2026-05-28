"""Runtime contract: what it means to *execute* an agent.

An agent is a declarative `AgentSpec`. A runtime turns that spec plus a message
into a validated `response_model` instance. Two implementations exist — a real
Lyzr-cloud runtime and a deterministic mock — and they're interchangeable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol, runtime_checkable

from pydantic import BaseModel

# A zero-arg factory that produces a deterministic stand-in output.
# Passed in by the agent so the MockRuntime can answer without knowing about
# specific agents. Real runtimes ignore it.
MockFactory = Callable[[], BaseModel]


@dataclass(frozen=True)
class AgentSpec:
    """A runtime-agnostic description of an agent."""

    name: str
    role: str
    goal: str
    instructions: str
    response_model: type[BaseModel]
    temperature: float = 0.3


@runtime_checkable
class AgentRuntime(Protocol):
    """Executes an `AgentSpec` and returns a validated `response_model` instance."""

    def invoke(
        self,
        spec: AgentSpec,
        message: str,
        *,
        mock: MockFactory | None = None,
    ) -> BaseModel:
        ...
