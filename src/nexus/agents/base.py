"""BaseAgent: a typed wrapper that turns a payload into a validated output.

A concrete agent supplies a class-level `spec` (its role/goal/instructions and
`response_model`), renders its typed input into a prompt via `build_message`, and
optionally provides a deterministic `mock_output` for offline runs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel

from ..runtime import AgentRuntime, AgentSpec

TIn = TypeVar("TIn", bound=BaseModel)
TOut = TypeVar("TOut", bound=BaseModel)


class BaseAgent(ABC, Generic[TIn, TOut]):
    #: Set by each concrete agent. `spec.response_model` must be the agent's `TOut`.
    spec: ClassVar[AgentSpec]

    def __init__(self, runtime: AgentRuntime) -> None:
        self.runtime = runtime

    @abstractmethod
    def build_message(self, payload: TIn) -> str:
        """Render the typed input into the prompt the agent receives."""

    def mock_output(self, payload: TIn) -> TOut:
        """Deterministic stand-in output for the MockRuntime. Override per agent."""
        raise NotImplementedError(f"{type(self).__name__} provides no mock_output().")

    def run(self, payload: TIn) -> TOut:
        result = self.runtime.invoke(
            self.spec,
            self.build_message(payload),
            mock=lambda: self.mock_output(payload),
        )
        return cast(TOut, result)
