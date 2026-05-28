"""The pipeline orchestrator.

Explicit control flow over three nodes, with one feedback loop:

    analyze → (Patchwork generates ↔ Validator judges, bounded retries) → gate → open PR

The PR is opened only after the Validator approves, so a reject→retry never spams PRs.
"""

from __future__ import annotations

import logging

from . import github
from .agents.bug_analyzer import BugAnalyzer
from .agents.patchwork import Patchwork
from .agents.validator import Validator
from .config import Settings
from .config import settings as default_settings
from .runtime import AgentRuntime, build_runtime
from .schemas import (
    GitHubIssue,
    PatchInput,
    PipelineResult,
    ValidationInput,
    ValidationResult,
)

logger = logging.getLogger("nexus.orchestrator")


class Pipeline:
    def __init__(
        self,
        runtime: AgentRuntime | None = None,
        settings: Settings = default_settings,
    ) -> None:
        self.settings = settings
        self.runtime = runtime or build_runtime(settings)
        self.bug_analyzer = BugAnalyzer(self.runtime)
        self.patchwork = Patchwork(self.runtime)
        self.validator = Validator(self.runtime)

    def run(self, issue: GitHubIssue) -> PipelineResult:
        result = PipelineResult(issue=issue, status="running")
        try:
            # 1 · Bug Analyzer cleans the report.
            result.analysis = self.bug_analyzer.run(issue)
            logger.info(
                "Analyzed #%s: severity=%s type=%s",
                issue.issue_number,
                result.analysis.severity.value,
                result.analysis.bug_type,
            )

            # 2 + 3 · Patchwork generates, Validator judges, loop on rejection.
            feedback: list[str] = []
            while result.attempts < self.settings.max_test_attempts:
                result.attempts += 1
                result.patch = self.patchwork.run(
                    PatchInput(analysis=result.analysis, feedback=feedback)
                )
                result.validation = self.validator.run(
                    ValidationInput(analysis=result.analysis, patch=result.patch)
                )
                if self._passes_gate(result.validation):
                    break
                feedback = result.validation.suggestions
                logger.info(
                    "Validator rejected (score=%.2f); retry %d with feedback",
                    result.validation.coverage_score,
                    result.attempts,
                )

            # Gate: don't open a PR for a patch that never cleared the threshold.
            if not self._passes_gate(result.validation):
                result.status = "rejected: patch did not clear the validator after max attempts"
                return result

            # Open (or draft) the PR now that the patch is approved.
            result.pull_request = github.open_pull_request(
                issue,
                result.patch,
                result.validation,
                token=self.settings.github_token,
            )
            result.status = "complete"
        except NotImplementedError as exc:
            result.status = f"stopped (stub): {exc}"
            logger.warning("Pipeline stopped at an unimplemented stage: %s", exc)
        return result

    def _passes_gate(self, validation: ValidationResult | None) -> bool:
        return bool(
            validation
            and (validation.approved or validation.coverage_score >= self.settings.confidence_threshold)
        )
