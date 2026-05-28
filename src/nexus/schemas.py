"""The typed handoff contracts between Nexus nodes.

Three nodes, one chain of contracts:

    GitHubIssue → [Bug Analyzer] → BugAnalysis → [Patchwork] → Patch → [Validator] → ValidationResult
                                                     ▲                                      │
                                                     └──────────── feedback ────────────────┘

Each agent declares one of these as its Lyzr `response_model`, so the runtime
returns a validated instance rather than free text — a node cannot pass malformed
data to the next.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── Pipeline input ────────────────────────────────────────────────────────────
class GitHubIssue(BaseModel):
    """A bug report as it arrives from GitHub — the pipeline's entry contract."""

    repo_full_name: str = Field(..., description="owner/repo")
    issue_number: int
    title: str
    body: str = ""
    labels: list[str] = Field(default_factory=list)


# ── Node 1 · Bug Analyzer → ───────────────────────────────────────────────────
class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class BugAnalysis(BaseModel):
    """Structured triage of a bug report — the Bug Analyzer's cleaned output."""

    summary: str = Field(..., description="One-sentence restatement of the bug.")
    severity: Severity = Field(..., description="Impact/urgency of the bug.")
    bug_type: str = Field(
        ..., description="Category, e.g. 'null dereference', 'race condition', 'off-by-one'."
    )
    affected_files: list[str] = Field(
        default_factory=list, description="Files most likely involved in the bug."
    )
    affected_symbols: list[str] = Field(
        default_factory=list, description="Functions/classes likely involved."
    )
    error_context: str = Field(
        "", description="Stack traces or error messages extracted from the report."
    )
    reproduction_steps: list[str] = Field(
        default_factory=list, description="Ordered steps to reproduce, if derivable."
    )
    suspected_root_cause: str = Field(
        ..., description="Best hypothesis for why the bug happens."
    )
    search_keywords: list[str] = Field(
        default_factory=list,
        description="Terms Patchwork should look for when locating the relevant code.",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Analyzer's confidence in this analysis (0-1)."
    )


# ── Node 2 · Patchwork → ──────────────────────────────────────────────────────
class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PatchInput(BaseModel):
    """What Patchwork consumes: the analysis plus any Validator feedback from a prior attempt."""

    analysis: BugAnalysis
    feedback: list[str] = Field(
        default_factory=list,
        description="Validator suggestions from a previous rejected attempt, if any.",
    )


class Patch(BaseModel):
    """Patchwork's output: a regression test plus the summary used in the PR."""

    test_file_path: str
    test_code: str
    framework: str = Field(..., description="Testing framework, e.g. 'pytest', 'jest'.")
    confidence: Confidence
    summary: str = Field(..., description="What the test checks and why it targets the bug.")


# ── Node 3 · Validator → ──────────────────────────────────────────────────────
class ValidationInput(BaseModel):
    """What the Validator consumes: the patch and the original analysis it must cover."""

    analysis: BugAnalysis
    patch: Patch


class ValidationResult(BaseModel):
    """Verdict on whether the patch's test adequately covers the bug."""

    approved: bool
    coverage_score: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    gaps: list[str] = Field(
        default_factory=list, description="Aspects of the bug the test fails to cover."
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="Feedback routed back to Patchwork when the patch is rejected.",
    )


# ── PR (opened after approval) ────────────────────────────────────────────────
class PullRequest(BaseModel):
    """A drafted (and, given a token, opened) pull request."""

    branch: str
    title: str
    body: str
    url: str = Field("", description="Populated once the PR is actually opened.")
    opened: bool = False


# ── Pipeline result ───────────────────────────────────────────────────────────
class PipelineResult(BaseModel):
    """Everything the pipeline produced for one issue — what the orchestrator returns."""

    issue: GitHubIssue
    analysis: BugAnalysis | None = None
    patch: Patch | None = None
    validation: ValidationResult | None = None
    pull_request: PullRequest | None = None
    attempts: int = 0
    status: str = "pending"
