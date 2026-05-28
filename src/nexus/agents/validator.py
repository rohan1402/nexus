"""Node 3 — Validator.

Judges how well Patchwork's regression test covers the reported bug. If the score
is below the configured threshold, the orchestrator routes the feedback back to
Patchwork for another attempt.
"""

from __future__ import annotations

from ..runtime import AgentSpec
from ..schemas import Confidence, ValidationInput, ValidationResult
from .base import BaseAgent

INSTRUCTIONS = """\
You are the quality gate. Compare the generated regression test against the bug analysis.

- Score coverage from 0 to 1: does the test exercise the exact failing path, assert the
  corrected behavior, and guard the adjacent cases a real fix must handle?
- Approve only if the test genuinely captures the bug.
- When you reject, list concrete gaps and give actionable suggestions Patchwork can apply
  on its next attempt — these are fed straight back to it.
"""

SPEC = AgentSpec(
    name="Nexus Validator",
    role="Quality gate that judges regression-test coverage",
    goal="Decide whether the generated test adequately covers the reported bug.",
    instructions=INSTRUCTIONS,
    response_model=ValidationResult,
    temperature=0.2,
)

# Mock maps Patchwork's self-reported confidence to a coverage score.
_SCORE_BY_CONFIDENCE = {
    Confidence.HIGH: 0.86,
    Confidence.MEDIUM: 0.62,
    Confidence.LOW: 0.40,
}
_APPROVAL_BAR = 0.75


class Validator(BaseAgent[ValidationInput, ValidationResult]):
    spec = SPEC

    def build_message(self, payload: ValidationInput) -> str:
        return (
            f"Bug: {payload.analysis.summary}\n"
            f"Bug type: {payload.analysis.bug_type}\n"
            f"Generated test ({payload.patch.framework}):\n{payload.patch.test_code}"
        )

    def mock_output(self, payload: ValidationInput) -> ValidationResult:
        score = _SCORE_BY_CONFIDENCE[payload.patch.confidence]
        approved = score >= _APPROVAL_BAR
        if approved:
            return ValidationResult(
                approved=True,
                coverage_score=score,
                rationale="Test targets the reported failure path and asserts the corrected behavior.",
            )
        return ValidationResult(
            approved=False,
            coverage_score=score,
            rationale="Test covers the crash but misses adjacent cases; coverage is thin.",
            gaps=[
                "No assertion for the empty-but-not-None input case.",
                "Only checks that no exception is raised, not the corrected return value.",
            ],
            suggestions=[
                "Add a case for an empty (non-None) input.",
                "Assert the corrected return value, not just the absence of an exception.",
            ],
        )
