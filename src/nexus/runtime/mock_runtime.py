"""Deterministic, offline runtime.

Returns each agent's own mock output. This makes the whole pipeline runnable and
unit-testable with no API keys, and is what backs the (intentionally) mocked
Codebase Explorer.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel

from .base import AgentSpec, MockFactory

logger = logging.getLogger("nexus.runtime.mock")


class MockRuntime:
    def invoke(
        self,
        spec: AgentSpec,
        message: str,
        *,
        mock: MockFactory | None = None,
    ) -> BaseModel:
        if mock is None:
            raise ValueError(
                f"Agent {spec.name!r} has no mock output; cannot run under MockRuntime."
            )
        logger.info("Mock-running agent %r", spec.name)
        result = mock()
        if not isinstance(result, spec.response_model):
            raise TypeError(
                f"Agent {spec.name!r} mock returned {type(result).__name__}, "
                f"expected {spec.response_model.__name__}"
            )
        return result
