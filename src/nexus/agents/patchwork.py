"""Node 2 — Patchwork.

The original Patchwork capability, re-homed as a single Nexus agent: reason about
the analyzed bug, (internally) locate the relevant code, and write a regression
test that fails while the bug exists and passes once it's fixed. On a Validator
rejection it revises the test using the feedback.

Repo exploration is intentionally internal and mocked here — it is not a separate
pipeline node.
"""

from __future__ import annotations

import re

from ..runtime import AgentSpec
from ..schemas import Confidence, Patch, PatchInput
from .base import BaseAgent

INSTRUCTIONS = """\
You are Patchwork. Given a structured bug analysis, write ONE regression test that
fails while the bug exists and passes once it is fixed.

- Match the repository's language and framework, inferred from the affected files
  (.py → pytest, .ts/.tsx/.js/.jsx → jest).
- Target the specific failure: exercise the affected symbol with the exact input that
  triggers the bug, and assert the corrected behavior (not merely the absence of a crash).
- Keep the test self-contained and clearly named after the bug.
- If validator feedback is provided, revise the test to address every point and raise
  your confidence accordingly.
- Return the test file path, the test code, the framework, your confidence, and a one-
  line summary of what the test checks.
"""

SPEC = AgentSpec(
    name="Nexus Patchwork",
    role="Senior engineer who writes targeted regression tests (the Patchwork capability)",
    goal="Turn a bug analysis into a regression test that captures the bug.",
    instructions=INSTRUCTIONS,
    response_model=Patch,
    temperature=0.3,
)


class Patchwork(BaseAgent[PatchInput, Patch]):
    spec = SPEC

    def build_message(self, payload: PatchInput) -> str:
        a = payload.analysis
        feedback = (
            "\n\nValidator feedback to address:\n- " + "\n- ".join(payload.feedback)
            if payload.feedback
            else ""
        )
        return (
            f"Bug: {a.summary}\n"
            f"Type: {a.bug_type} · Severity: {a.severity.value}\n"
            f"Affected files: {', '.join(a.affected_files) or '(unknown)'}\n"
            f"Affected symbols: {', '.join(a.affected_symbols) or '(unknown)'}\n"
            f"Suspected root cause: {a.suspected_root_cause}\n"
            f"Error context:\n{a.error_context or '(none)'}{feedback}"
        )

    def mock_output(self, payload: PatchInput) -> Patch:
        return _mock_patch(payload)


# ── Deterministic mock (offline) ──────────────────────────────────────────────
# Generates a plausible regression test from the analysis. On a retry (feedback
# present) it adds coverage and raises confidence, so the validator loop resolves.

_JS_EXTS = (".ts", ".tsx", ".js", ".jsx")


def _framework_for(files: list[str]) -> str:
    return "jest" if any(f.endswith(_JS_EXTS) for f in files) else "pytest"


def _slug(text: str) -> str:
    words: list[str] = []
    length = 0
    for word in re.sub(r"[^a-z0-9]+", " ", text.lower()).split():
        if words and length + len(word) + 1 > 48:
            break
        words.append(word)
        length += len(word) + 1
    return "_".join(words) or "bug"


def _module_and_symbol(analysis) -> tuple[str, str]:
    symbol = next(
        (s for s in analysis.affected_symbols if re.fullmatch(r"[A-Za-z_]\w*", s) and s != "None"),
        "target",
    )
    module = "module_under_test"
    if analysis.affected_files:
        path = re.sub(r"\.(py|ts|tsx|js|jsx)$", "", analysis.affected_files[0])
        path = re.sub(r"^(src|app|lib)/", "", path)
        module = path.replace("/", ".")
    return module, symbol


def _mock_patch(payload: PatchInput) -> Patch:
    a = payload.analysis
    improved = bool(payload.feedback)
    framework = _framework_for(a.affected_files)
    module, symbol = _module_and_symbol(a)
    slug = _slug(a.summary)

    if framework == "pytest":
        path = f"tests/regression/test_{slug}.py"
        extra = (
            f"\n\ndef test_{slug}_empty_input():\n"
            f"    # Added per validator feedback: cover the empty (non-None) input too.\n"
            f"    assert {symbol}([]) == 0\n"
            if improved
            else ""
        )
        code = (
            "import pytest\n\n"
            f"from {module} import {symbol}\n\n\n"
            f"def test_{slug}():\n"
            f"    # Regression for: {a.summary}\n"
            f"    # Before the fix, this raised due to a {a.bug_type}.\n"
            f"    result = {symbol}(None)\n"
            "    assert result == 0\n"
            f"{extra}"
        )
    else:  # jest
        path = f"__tests__/regression/{slug}.test.ts"
        extra = (
            f"\n  it('handles the empty input case', () => {{\n"
            f"    expect({symbol}([])).toBe(0);\n"
            f"  }});\n"
            if improved
            else ""
        )
        code = (
            f"import {{ {symbol} }} from '{module}';\n\n"
            f"describe('{a.summary}', () => {{\n"
            f"  it('does not crash on the reported input', () => {{\n"
            f"    // Regression for a {a.bug_type}.\n"
            f"    expect(() => {symbol}(null)).not.toThrow();\n"
            f"  }});\n"
            f"{extra}}});\n"
        )

    confidence = Confidence.HIGH if improved else Confidence.MEDIUM
    summary = (
        f"Exercises {symbol}() with the failing input and asserts corrected behavior"
        + ("; revised to also cover the empty-input case." if improved else ".")
    )
    return Patch(
        test_file_path=path,
        test_code=code,
        framework=framework,
        confidence=confidence,
        summary=summary,
    )
