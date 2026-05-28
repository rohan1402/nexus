"""Agent 1 — Bug Analyzer.

Parses a raw GitHub issue into structured triage (`BugAnalysis`): severity,
affected files/symbols, error context, a root-cause hypothesis, and the search
keywords the Codebase Explorer will use next.
"""

from __future__ import annotations

import re

from ..runtime import AgentSpec
from ..schemas import BugAnalysis, GitHubIssue, Severity
from .base import BaseAgent

INSTRUCTIONS = """\
You are triaging a single GitHub bug report. Produce a precise, structured analysis.

For each field:
- summary: restate the bug in one clear sentence.
- severity: critical (data loss / security / outage), high (core feature broken,
  no workaround), medium (feature broken with a workaround), or low (cosmetic/minor).
- bug_type: a short category, e.g. "null dereference", "off-by-one", "race condition",
  "incorrect validation", "unhandled exception".
- affected_files: file paths the bug most likely lives in. Infer from the report,
  stack traces, and quoted code. Do not invent paths you have no evidence for.
- affected_symbols: specific functions/classes/methods implicated.
- error_context: copy the exact error messages, stack traces, or failing assertions
  present in the report. Leave empty if none are given.
- reproduction_steps: ordered steps to reproduce, only if derivable from the report.
- suspected_root_cause: your single best hypothesis for the underlying cause.
- search_keywords: 3-8 concrete terms (symbol names, error strings, domain nouns) that
  a code-search tool should grep for to locate the relevant code. These drive the next agent.
- confidence: 0.0-1.0, honest about how much the report actually tells you. A vague
  report with no stack trace should score low.

Ground every field in evidence from the report. Never fabricate file paths, symbols, or
errors that are not supported by the text.
"""

SPEC = AgentSpec(
    name="Nexus Bug Analyzer",
    role="Senior software engineer and bug-triage specialist",
    goal="Turn a raw GitHub bug report into a precise, structured analysis the rest of the pipeline can act on.",
    instructions=INSTRUCTIONS,
    response_model=BugAnalysis,
    temperature=0.2,
)


class BugAnalyzer(BaseAgent[GitHubIssue, BugAnalysis]):
    spec = SPEC

    def build_message(self, payload: GitHubIssue) -> str:
        labels = ", ".join(payload.labels) if payload.labels else "(none)"
        return (
            f"Repository: {payload.repo_full_name}\n"
            f"Issue #{payload.issue_number}: {payload.title}\n"
            f"Labels: {labels}\n\n"
            f"Description:\n{payload.body or '(no description provided)'}"
        )

    def mock_output(self, payload: GitHubIssue) -> BugAnalysis:
        return _heuristic_analysis(payload)


# ── Deterministic mock (offline) ──────────────────────────────────────────────
# Light heuristics over the issue text so the mock looks intelligent in a demo and
# stays deterministic for tests. The real agent replaces this with Gemini reasoning.

_FILE_RE = re.compile(r"[\w./-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|c|cpp|h|cs|php)")
_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_SYMBOL_RE = re.compile(r"[A-Za-z_][\w.]*(?:\(\))?$")
_ERROR_LINE_RE = re.compile(
    r"^.*\b(?:error|exception|traceback|assert|failed|panic)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_STOPWORDS = {
    "the", "a", "an", "is", "are", "to", "of", "in", "on", "and", "or", "when",
    "with", "for", "but", "not", "it", "this", "that", "if", "be", "as", "at",
    "bug", "issue", "error", "crash", "fix", "broken",
}

_SEVERITY_HINTS = {
    Severity.CRITICAL: ("data loss", "security", "outage", "corrupt", "leak", "crash on startup"),
    Severity.HIGH: ("crash", "cannot", "broken", "fails", "500", "unusable", "regression"),
    Severity.LOW: ("typo", "cosmetic", "wording", "alignment", "minor"),
}

_TYPE_HINTS = (
    (("none", "null", "nonetype", "undefined", "nullpointer"), "null dereference"),
    (("index", "out of range", "off by one", "off-by-one", "bounds"), "index/off-by-one error"),
    (("race", "concurren", "deadlock", "thread"), "race condition"),
    (("timeout", "hang", "slow", "infinite loop"), "performance/hang"),
    (("validation", "invalid input", "sanitiz"), "incorrect validation"),
    (("exception", "traceback", "unhandled"), "unhandled exception"),
)


def _heuristic_analysis(issue: GitHubIssue) -> BugAnalysis:
    text = f"{issue.title}\n{issue.body}"
    lowered = text.lower()
    label_text = " ".join(issue.labels).lower()

    # Pull fenced code blocks out so inline-code parsing doesn't span them.
    fenced = [b.strip() for b in _FENCE_RE.findall(text)]
    prose = _FENCE_RE.sub(" ", text)

    # severity
    severity = Severity.MEDIUM
    for level, hints in _SEVERITY_HINTS.items():
        if any(h in lowered or h in label_text for h in hints):
            severity = level
            break

    # bug type
    bug_type = "logic error"
    for needles, name in _TYPE_HINTS:
        if any(n in lowered for n in needles):
            bug_type = name
            break

    affected_files = _dedupe(_FILE_RE.findall(text))
    affected_symbols = _dedupe(
        s.strip()
        for s in _INLINE_CODE_RE.findall(prose)
        if _SYMBOL_RE.fullmatch(s.strip()) and not _FILE_RE.fullmatch(s.strip())
    )

    # error_context: prefer a fenced block that looks like a traceback/error.
    error_block = next((b for b in fenced if _ERROR_LINE_RE.search(b)), "")
    error_context = error_block or "\n".join(
        line.strip() for line in _ERROR_LINE_RE.findall(prose)
    ).strip()

    words = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", issue.title.lower())
    keywords = _dedupe(w for w in words if w not in _STOPWORDS)
    keywords = _dedupe([*affected_symbols[:3], *keywords])[:8]

    primary = affected_symbols[0] if affected_symbols else (
        affected_files[0] if affected_files else "the affected code path"
    )

    return BugAnalysis(
        summary=issue.title.strip().rstrip(".") + ".",
        severity=severity,
        bug_type=bug_type,
        affected_files=affected_files,
        affected_symbols=affected_symbols,
        error_context=error_context,
        reproduction_steps=[],
        suspected_root_cause=(
            f"A {bug_type} in {primary} consistent with the reported symptoms."
        ),
        search_keywords=keywords,
        confidence=0.72 if (affected_files or error_context) else 0.5,
    )


def _dedupe(items) -> list[str]:
    seen: dict[str, None] = {}
    for it in items:
        if it and it not in seen:
            seen[it] = None
    return list(seen)
