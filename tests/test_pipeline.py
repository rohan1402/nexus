"""End-to-end pipeline tests on the MockRuntime — no API keys, no network."""

from __future__ import annotations

import json
import pathlib

from nexus.config import Settings
from nexus.orchestrator import Pipeline
from nexus.runtime import MockRuntime
from nexus.schemas import Confidence, GitHubIssue

SAMPLE = pathlib.Path(__file__).resolve().parents[1] / "examples" / "sample_issue.json"


def load_sample() -> GitHubIssue:
    return GitHubIssue(**json.loads(SAMPLE.read_text()))


def make_settings(**overrides) -> Settings:
    base = dict(
        runtime="mock",
        confidence_threshold=0.7,
        max_test_attempts=2,
        github_token=None,
    )
    base.update(overrides)
    return Settings(**base)


def test_pipeline_completes_and_feedback_loop_fires():
    # First patch is MEDIUM (rejected); the retry, using feedback, is HIGH (approved).
    result = Pipeline(runtime=MockRuntime(), settings=make_settings()).run(load_sample())

    assert result.status == "complete"
    assert result.attempts == 2  # the loop ran twice: reject → retry → approve
    assert result.analysis is not None
    assert result.patch is not None and result.patch.confidence == Confidence.HIGH
    assert result.validation is not None and result.validation.approved


def test_pr_is_drafted_not_opened_without_token():
    result = Pipeline(runtime=MockRuntime(), settings=make_settings()).run(load_sample())

    assert result.pull_request is not None
    assert result.pull_request.opened is False
    assert result.pull_request.branch == "nexus/issue-142"
    assert "#142" in result.pull_request.title


def test_pipeline_rejects_when_attempts_exhausted():
    # With a single allowed attempt, the MEDIUM patch never clears the gate.
    result = Pipeline(runtime=MockRuntime(), settings=make_settings(max_test_attempts=1)).run(
        load_sample()
    )

    assert result.attempts == 1
    assert "rejected" in result.status
    assert result.pull_request is None


def test_python_repo_yields_pytest_patch():
    result = Pipeline(runtime=MockRuntime(), settings=make_settings()).run(load_sample())

    assert result.patch.framework == "pytest"
    assert "def test_" in result.patch.test_code
