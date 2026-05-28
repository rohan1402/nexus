"""`nexus run <issue.json>` — run the three-node pipeline on a single GitHub issue."""

from __future__ import annotations

import argparse
import json
import logging

from .config import settings
from .orchestrator import Pipeline
from .schemas import PipelineResult, GitHubIssue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexus", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run", help="Run the pipeline on a GitHub issue JSON file.")
    run_p.add_argument("issue", help="Path to a JSON file describing the issue.")
    run_p.add_argument("-v", "--verbose", action="store_true", help="Show agent/runtime logs.")
    args = parser.parse_args(argv)

    if args.command == "run":
        if args.verbose:
            logging.basicConfig(level=logging.INFO, format="  · %(name)s: %(message)s")
        with open(args.issue) as fh:
            issue = GitHubIssue(**json.load(fh))
        print(f"Nexus · runtime={settings.runtime} · provider={settings.llm_provider}\n")
        _print_result(Pipeline().run(issue))
        return 0
    return 1


def _indent(text: str, pad: str) -> str:
    return text.replace("\n", "\n" + pad)


def _print_result(result: PipelineResult) -> None:
    a = result.analysis
    if a:
        print("── 1 · Bug Analysis ──────────────────────────────────────────")
        print(f"  summary    : {a.summary}")
        print(f"  severity   : {a.severity.value}   bug_type: {a.bug_type}")
        print(f"  files      : {', '.join(a.affected_files) or '-'}")
        print(f"  symbols    : {', '.join(a.affected_symbols) or '-'}")
        print(f"  keywords   : {', '.join(a.search_keywords) or '-'}")
        print(f"  confidence : {a.confidence:.2f}")

    p = result.patch
    if p:
        print("\n── 2 · Patchwork ─────────────────────────────────────────────")
        print(f"  file       : {p.test_file_path}  ({p.framework})")
        print(f"  confidence : {p.confidence.value}")
        print(f"  summary    : {p.summary}")
        print(f"  test       : {_indent(p.test_code.rstrip(), '               ')}")

    v = result.validation
    if v:
        verdict = "APPROVED" if v.approved else "REJECTED"
        print("\n── 3 · Validator ─────────────────────────────────────────────")
        print(f"  verdict    : {verdict}  (coverage {v.coverage_score:.0%})")
        print(f"  rationale  : {v.rationale}")
        if v.suggestions:
            print("  suggestions: " + "; ".join(v.suggestions))

    pr = result.pull_request
    if pr:
        print("\n── Pull Request ──────────────────────────────────────────────")
        print(f"  {pr.title}")
        print(f"  branch     : {pr.branch}")
        print(f"  {'opened: ' + pr.url if pr.opened else 'drafted (not opened — no token / mock run)'}")

    print(f"\nstatus: {result.status}  (attempts: {result.attempts})")


if __name__ == "__main__":
    raise SystemExit(main())
