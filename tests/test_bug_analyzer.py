"""Bug Analyzer tests — run entirely on the MockRuntime, no API keys needed."""

from __future__ import annotations

from nexus.agents import BugAnalyzer
from nexus.runtime import MockRuntime
from nexus.schemas import BugAnalysis, GitHubIssue, Severity


def make_issue(**overrides) -> GitHubIssue:
    base = dict(
        repo_full_name="acme/widgets",
        issue_number=1,
        title="App crashes",
        body="",
        labels=[],
    )
    base.update(overrides)
    return GitHubIssue(**base)


def analyze(issue: GitHubIssue) -> BugAnalysis:
    return BugAnalyzer(MockRuntime()).run(issue)


def test_returns_validated_bug_analysis():
    issue = make_issue(
        title="Checkout crashes with NoneType error when cart is empty",
        body=(
            "Crash in `compute_total` in `src/checkout/service.py`.\n"
            "```\nAttributeError: 'NoneType' object has no attribute 'items'\n```"
        ),
        labels=["bug", "high-priority"],
    )
    out = analyze(issue)

    assert isinstance(out, BugAnalysis)
    assert out.severity == Severity.HIGH
    assert out.bug_type == "null dereference"
    assert "src/checkout/service.py" in out.affected_files
    assert "compute_total" in out.affected_symbols
    assert "NoneType" in out.error_context
    assert 0.0 <= out.confidence <= 1.0


def test_inline_code_does_not_leak_the_fenced_block():
    # The fenced code block must not bleed into affected_symbols.
    issue = make_issue(
        title="bad parse",
        body="See `handler`.\n```\nthis is a long traceback line\n```",
    )
    out = analyze(issue)
    assert out.affected_symbols == ["handler"]


def test_vague_report_is_lower_severity_and_confidence():
    out = analyze(make_issue(title="Button label has a typo", body="minor wording issue"))
    assert out.severity == Severity.LOW
    assert out.confidence < 0.72  # no files or error context to go on


def test_search_keywords_are_populated():
    out = analyze(make_issue(title="Login throttling rejects valid users"))
    assert out.search_keywords  # non-empty; drives the Codebase Explorer


def test_build_message_includes_issue_fields():
    msg = BugAnalyzer(MockRuntime()).build_message(
        make_issue(title="T", body="B", labels=["x"])
    )
    assert "acme/widgets" in msg
    assert "T" in msg
    assert "B" in msg
