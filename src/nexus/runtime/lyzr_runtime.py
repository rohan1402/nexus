"""Real runtime: executes agents against the Lyzr cloud with Gemini 2.5 Pro."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from .base import AgentSpec, MockFactory

logger = logging.getLogger("nexus.runtime.lyzr")


class LyzrRuntime:
    """Creates each agent once on the Lyzr platform, then runs it.

    `studio.create_agent(..., response_model=Model)` registers a server-side agent
    whose `run()` returns a validated `Model` instance. We cache the created agent
    per spec name so repeated invocations (e.g. the Validator retry loop) reuse it.
    """

    def __init__(self, *, api_key: str, provider: str, credential_id: str) -> None:
        from lyzr import Studio  # imported lazily so mock-only runs need no cloud setup

        self._studio = Studio(api_key=api_key)
        self._provider = provider
        self._credential_id = credential_id
        self._agents: dict[str, Any] = {}

    def invoke(
        self,
        spec: AgentSpec,
        message: str,
        *,
        mock: MockFactory | None = None,  # ignored: the real model produces the output
    ) -> BaseModel:
        agent = self._agents.get(spec.name)
        if agent is None:
            logger.info("Creating Lyzr agent %r on %s", spec.name, self._provider)
            agent = self._studio.create_agent(
                name=spec.name,
                provider=self._provider,
                role=spec.role,
                goal=spec.goal,
                instructions=spec.instructions,
                temperature=spec.temperature,
                response_model=spec.response_model,
                llm_credential_id=self._credential_id,
            )
            self._agents[spec.name] = agent

        result = agent.run(message)
        return _coerce(result, spec.response_model)


def _coerce(result: Any, model: type[BaseModel]) -> BaseModel:
    """Normalize whatever `agent.run()` returns into a `model` instance.

    With a `response_model` set, Lyzr returns the model directly, but we defend the
    boundary against the response being wrapped (AgentResponse.response) or serialized.
    """
    if isinstance(result, model):
        return result

    # AgentResponse-style wrapper with a `.response` payload.
    payload = getattr(result, "response", result)
    if isinstance(payload, model):
        return payload
    if isinstance(payload, dict):
        return model.model_validate(payload)
    if isinstance(payload, str):
        return model.model_validate_json(payload)

    raise TypeError(
        f"Could not coerce agent output of type {type(result).__name__} into {model.__name__}"
    )
