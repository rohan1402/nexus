"""Real runtime: executes agents against the Lyzr cloud with Gemini 2.5 Pro."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel

from .base import AgentSpec, MockFactory

logger = logging.getLogger("nexus.runtime.lyzr")


class LyzrRuntime:
    """Creates each agent once on the Lyzr platform, then runs it.

    `studio.agents.create(..., response_model=Model)` registers a server-side agent
    whose `run()` returns a validated `Model` instance. We cache the created agent
    per spec name so repeated invocations (e.g. the Validator retry loop) reuse it.
    """

    def __init__(
        self,
        *,
        api_key: str,
        provider: str,
        credential_id: str,
        studio: Any | None = None,
    ) -> None:
        # `studio` is injectable so the runtime can be unit-tested with a fake client
        # and no network; by default we build the real Lyzr Studio.
        if studio is None:
            from lyzr import Studio  # imported lazily so mock-only runs need no cloud setup

            studio = Studio(api_key=api_key)
        self._studio = studio
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
            agent = self._get_or_create(spec)
            self._agents[spec.name] = agent
        result = agent.run(message)
        return _coerce(result, spec.response_model)

    def _get_or_create(self, spec: AgentSpec):
        """Reuse the platform agent of this name (syncing its config), else create it.

        Without this, each process re-created a fresh server-side agent, piling up
        duplicates in the Lyzr account. Looking up by name makes runs idempotent; the
        update keeps the reused agent in sync with the current spec.
        """
        existing_id = self._find_agent_id(spec.name)
        if existing_id is not None:
            logger.info("Reusing Lyzr agent %r (id=%s)", spec.name, existing_id)
            return self._studio.agents.update(
                existing_id,
                role=spec.role,
                goal=spec.goal,
                instructions=spec.instructions,
                temperature=spec.temperature,
                response_model=spec.response_model,
                llm_credential_id=self._credential_id,
            )
        logger.info("Creating Lyzr agent %r on %s", spec.name, self._provider)
        return self._studio.agents.create(
            name=spec.name,
            provider=self._provider,
            role=spec.role,
            goal=spec.goal,
            instructions=spec.instructions,
            temperature=spec.temperature,
            response_model=spec.response_model,
            llm_credential_id=self._credential_id,
        )

    def _find_agent_id(self, name: str) -> str | None:
        try:
            listing = self._studio.agents.list()
        except Exception as exc:  # a listing failure shouldn't block a fresh create
            logger.warning("Could not list existing agents (%s); creating a new one.", exc)
            return None
        for agent in getattr(listing, "agents", listing):
            if _attr(agent, "name") == name:
                return _attr(agent, "id")
        return None


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


def _attr(obj: Any, key: str):
    """Read a field whether the listing yields pydantic objects or plain dicts."""
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
