"""Runtime selection: build the backend the settings ask for."""

from __future__ import annotations

from ..config import Settings, settings as default_settings
from .base import AgentRuntime, AgentSpec, MockFactory
from .mock_runtime import MockRuntime

__all__ = ["AgentRuntime", "AgentSpec", "MockFactory", "build_runtime", "MockRuntime"]


def build_runtime(settings: Settings = default_settings) -> AgentRuntime:
    if settings.runtime == "mock":
        return MockRuntime()
    if settings.runtime == "lyzr":
        if not settings.lyzr_api_key:
            raise RuntimeError("NEXUS_RUNTIME=lyzr requires LYZR_API_KEY to be set.")
        from .lyzr_runtime import LyzrRuntime

        return LyzrRuntime(
            api_key=settings.lyzr_api_key,
            provider=settings.llm_provider,
            credential_id=settings.llm_credential_id,
        )
    raise ValueError(f"Unknown NEXUS_RUNTIME {settings.runtime!r} (expected 'mock' or 'lyzr').")
