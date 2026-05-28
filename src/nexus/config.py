"""Environment-driven settings for the Nexus pipeline."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Which backend executes agents: "lyzr" (real cloud) or "mock" (offline).
    runtime: str = os.getenv("NEXUS_RUNTIME", "mock")

    # LLM the agents run on, as a Lyzr "provider/model" string.
    llm_provider: str = os.getenv("NEXUS_LLM_PROVIDER", "google/gemini-2.5-pro")

    # Name of the Gemini credential configured in the Lyzr account.
    llm_credential_id: str = os.getenv("LYZR_LLM_CREDENTIAL_ID", "lyzr_google")

    lyzr_api_key: str | None = os.getenv("LYZR_API_KEY")

    # Validator gate: below this, tests are sent back to the Test Generator.
    confidence_threshold: float = float(os.getenv("NEXUS_CONFIDENCE_THRESHOLD", "0.7"))

    # How many times the Test Generator ↔ Validator loop may retry.
    max_test_attempts: int = int(os.getenv("NEXUS_MAX_TEST_ATTEMPTS", "2"))

    github_token: str | None = os.getenv("GITHUB_TOKEN")


settings = Settings()
