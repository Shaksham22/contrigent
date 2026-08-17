from __future__ import annotations

import re

from contrigent_api.agents.issue_analyzer.output_schema import (
    Feasibility,
)
from contrigent_api.models.repository_test_result import (
    RepositoryTestResult,
)
from contrigent_api.models.run_record import (
    Run,
)

from contrigent_api.services.run_progress import (
    RunProgressEvent,
)

def show_header() -> None:
    print()
    print("CONTRIGENT")
    print()
    print(
        "A multi-AI open-source "
        "contribution agent."
    )
    print()
    print(
        "Paste an open-source project's "
        "GitHub repository URL and issue "
        "URL below."
    )
    print()
    print(
        "Contrigent will investigate the "
        "issue using multiple AI agents, "
        "develop and independently review "
        "a solution, ask for your approval, "
        "and create a draft pull request "
        "from your fork."
    )
    print()


def show_starting_analysis() -> None:
    print(
        "Preparing repository and "
        "analyzing issue..."
    )
    print()


def show_plan(
    run: Run,
) -> None:
    analysis = run.analysis

    if analysis is None:
        return

    print("Analysis complete.")
    print()

    print("Problem:")
    print(analysis.summary)
    print()

    print("Proposed solution:")

    for step in sorted(
        analysis.implementation_plan,
        key=lambda item: item.order,
    ):
        print(
            f"{step.order}. "
            f"{step.description}"
        )

    if analysis.likely_files:
        print()
        print("Likely files:")

        for file_path in (
            analysis.likely_files
        ):
            print(
                f"- {file_path}"
            )


def show_plan_details(
    run: Run,
) -> None:
    analysis = run.analysis

    if analysis is None:
        print(
            "No analysis is available."
        )
        return

    print("Analysis details")
    print("----------------")
    print()

    print(
        "Feasibility: "
        f"{analysis.feasibility.value}"
    )

    if analysis.acceptance_criteria:
        print()
        print("Acceptance criteria:")

        for item in (
            analysis.acceptance_criteria
        ):
            print(
                f"- {item}"
            )

    if analysis.ambiguities:
        print()
        print("Ambiguities:")

        for item in analysis.ambiguities:
            print(
                f"- {item}"
            )

    if analysis.risks:
        print()
        print("Risks:")

        for risk in analysis.risks:
            print(
                f"- [{risk.severity.value}] "
                f"{risk.category}: "
                f"{risk.description}"
            )

    if analysis.worker_assignments:
        print()
        print("Worker assignments:")

        for assignment in sorted(
            analysis.worker_assignments,
            key=lambda item: item.order,
        ):
            print(
                f"- {assignment.worker_id}: "
                f"{assignment.task}"
            )


def show_no_changes_needed(
    run: Run,
) -> None:
    print("Analysis complete.")
    print()
    print("No changes needed.")
    print()

    if run.analysis is not None:
        print("Reason:")
        print(
            _remove_summary_prefix(
                run.analysis.summary,
                "No changes needed:",
            )
        )
        print()

    print(
        "No source files were changed."
    )
    print(
        "No commit was created."
    )
    print(
        "No branch was pushed."
    )
    print(
        "No pull request was created."
    )


def show_solution_not_found(
    run: Run,
) -> None:
    print("Analysis stopped.")
    print()

    if (
        run.analysis is not None
        and run.analysis.feasibility
        == Feasibility.UNSAFE
    ):
        print(
            "Contrigent determined that "
            "this issue should not be "
            "executed safely."
        )
    else:
        print(
            "Contrigent could not identify "
            "a sufficiently reliable "
            "solution for this issue."
        )

    if run.analysis is not None:
        print()
        print("Reason:")
        print(
            _remove_summary_prefix(
                run.analysis.summary,
                "Solution not found:",
            )
        )

        if run.analysis.ambiguities:
            print()
            print("Unresolved details:")

            for ambiguity in (
                run.analysis.ambiguities
            ):
                print(
                    f"- {ambiguity}"
                )

    print()
    print(
        "No source files were changed."
    )
    print(
        "No commit was created."
    )
    print(
        "No branch was pushed."
    )
    print(
        "No pull request was created."
    )

def show_implementation_started() -> None:
    print()
    print(
        "Implementation and review"
    )
    print(
        "-------------------------"
    )
    print()


def show_run_progress(
    event: RunProgressEvent,
) -> None:
    if event.kind == "testing_progress":
        print(
            f"  {event.message}"
        )
        return

    symbols = {
        "preflight_started": "→",
        "preflight_detecting": "→",
        "preflight_verifying": "→",
        "preflight_discovery": "→",
        "preflight_passed": "✓",
        "preflight_failed": "✗",
        "analysis_started": "→",
        "worker_started": "→",
        "worker_completed": "✓",
        "testing_started": "→",
        "testing_passed": "✓",
        "testing_failed": "✗",
        "manager_revision_started": "→",
        "manager_revision_completed": "✓",
        "review_started": "→",
        "review_approved": "✓",
        "review_changes_required": "✗",
        "stopped": "✗",
    }

    symbol = symbols.get(
        event.kind,
        "→",
    )

    print(
        f"{symbol} {event.message}"
    )

    for detail in event.details:
        print(
            f"  {detail}"
        )

    print()


def show_solution(
    run: Run,
) -> None:
    print("Solution ready.")
    print()

    if run.worker_results:
        print("Changes:")

        for worker_id, result in (
            run.worker_results.items()
        ):
            print(
                f"- {worker_id}: "
                f"{result.summary}"
            )

        print()

    reviewer = run.reviewer_result

    if reviewer is not None:
        print("Independent review:")
        print(
            reviewer.recommendation.upper()
        )
        print()

    if run.candidate_test_result is not None:
        print("Candidate testing:")
        print(
            _test_result_summary(
                run.candidate_test_result
            )
        )
        print()

    if run.proposed_files:
        print("Files to change:")

        for replacement in (
            run.proposed_files
        ):
            print(
                f"- {replacement.file_path}"
            )


def show_solution_details(
    run: Run,
) -> None:
    print("Solution details")
    print("----------------")
    print()

    for worker_id, result in (
        run.worker_results.items()
    ):
        print(
            f"{worker_id}:"
        )
        print(
            result.summary
        )

        for finding in result.findings:
            print(
                f"- {finding}"
            )

        print()

    if run.proposed_files:
        print("Proposed files:")

        for replacement in (
            run.proposed_files
        ):
            print(
                f"- {replacement.file_path}"
            )
            print(
                f"  Reason: "
                f"{replacement.reason}"
            )

        print()

    reviewer = run.reviewer_result

    if reviewer is not None:
        print("Independent Reviewer:")
        print(
            reviewer.summary
        )

        if reviewer.findings:
            print()

            for finding in (
                reviewer.findings
            ):
                print(
                    f"- [{finding.severity}] "
                    f"{finding.category}: "
                    f"{finding.description}"
                )

        print()

    if run.candidate_test_result is not None:
        print("Candidate tests:")
        print(
            _test_result_summary(
                run.candidate_test_result
            )
        )


def show_unapproved_solution(
    run: Run,
) -> None:
    print()
    print(
        "Solution could not be approved."
    )

    reviewer = run.reviewer_result

    if reviewer is not None:
        print()
        print(
            "Independent Reviewer:"
        )
        print(
            reviewer.summary
        )

        if reviewer.findings:
            print()
            print(
                "Unresolved findings:"
            )

            for finding in (
                reviewer.findings
            ):
                print(
                    f"- [{finding.severity}] "
                    f"{finding.description}"
                )

    print()
    print(
        "Contrigent will not execute "
        "this solution."
    )
    print()
    print(
        "No project files were changed."
    )
    print(
        "No commit was created."
    )
    print(
        "No pull request was created."
    )


def show_worker_failure(
    run: Run,
) -> None:
    print()
    print("Solution stopped.")
    print()

    if (
        run.candidate_test_result
        is not None
    ):
        print(
            _test_result_summary(
                run.candidate_test_result
            )
        )

    print()
    print(
        "Contrigent could not produce "
        "an acceptable solution within "
        "the configured limits."
    )
    print()
    print(
        "No pull request was created."
    )


def show_execution_started() -> None:
    print()
    print(
        "Executing approved solution..."
    )
    print()


def show_execution_result(
    run: Run,
    *,
    include_draft_pr_confirmation: bool = True,
) -> None:
    if (
        run.repository_tests_completed
        and not run.repository_tests_passed
    ):
        print()
        print("Execution stopped.")
        print()
        print("✗ Tests failed")

        if (
            run.repository_test_result
            is not None
        ):
            print()
            print(
                _test_result_summary(
                    run.repository_test_result
                )
            )

        print()
        print(
            "No pull request was created."
        )

        return

    if not run.draft_pr_created:
        print()
        print(
            "Execution did not complete."
        )
        return

    print()
    print(
        "Contrigent completed the issue."
    )
    print()

    if run.changes_applied:
        print(
            "✓ Changes applied"
        )

    if (
        run.repository_tests_passed
        and run.repository_test_result
        is not None
    ):
        print(
            "✓ Tests passed — "
            + _test_result_summary(
                run.repository_test_result
            )
        )

    if run.commit_created:
        print(
            "✓ Commit created"
        )

    if run.branch_pushed:
        print(
            "✓ Branch pushed"
        )

    if (
        run.draft_pr_created
        and include_draft_pr_confirmation
    ):
        print(
            "✓ Draft pull request created"
        )

    if run.run_branch:
        print()
        print("Branch:")
        print(
            run.run_branch
        )

    if run.commit_sha:
        print()
        print("Commit:")
        print(
            run.commit_sha[:7]
        )

    if run.draft_pr_url:
        print()
        print("Draft PR:")
        print(
            run.draft_pr_url
        )


def show_draft_pull_request_created() -> None:
    print()
    print(
        "✓ Draft pull request created"
    )


def show_issue_comment_preview(
    issue_number: int,
    comment: str,
) -> None:
    print()
    print(
        "Issue comment"
    )
    print(
        "-------------"
    )
    print()
    print(
        "Contrigent will post this comment "
        f"to issue #{issue_number} in 5 seconds:"
    )
    print()
    print(
        comment
    )
    print()


def show_issue_comment_details(
    *,
    issue_url: str,
    issue_number: int,
    pull_request_url: str,
    pull_request_number: int,
    comment: str,
) -> None:
    print(
        "Issue comment details"
    )
    print(
        "---------------------"
    )
    print()
    print(
        f"Issue URL: {issue_url}"
    )
    print(
        f"Issue number: {issue_number}"
    )
    print(
        f"Draft PR URL: {pull_request_url}"
    )
    print(
        f"PR number: {pull_request_number}"
    )
    print()
    print(
        "Complete issue comment:"
    )
    print()
    print(
        comment
    )


def show_issue_comment_posted() -> None:
    print()
    print(
        "✓ Issue comment posted"
    )


def show_issue_comment_skipped() -> None:
    print()
    print(
        "○ Issue comment skipped"
    )


def show_issue_comment_failure(
    pull_request_url: str,
    error_message: str,
) -> None:
    print()
    print(
        "⚠ Draft pull request was created, but "
        "the issue comment could not be posted."
    )
    print()
    print(
        "PR:"
    )
    print(
        pull_request_url
    )
    print()
    print(
        "GitHub error:"
    )
    print(
        error_message
    )


def show_cancelled() -> None:
    print()
    print("Contrigent cancelled the run.")
    print()
    print(
        "No source files were changed."
    )
    print(
        "No commit was created."
    )
    print(
        "No pull request was created."
    )


def show_error(
    message: str,
) -> None:
    print()
    print("Contrigent stopped.")
    print()
    print(
        f"Error: {message}"
    )


def _test_result_summary(
    result: RepositoryTestResult,
) -> str:
    output = (
        result.stdout
        + "\n"
        + result.stderr
    )

    matches = re.findall(
        r"(\d+\s+passed"
        r"(?:,\s*\d+\s+failed)?"
        r"(?:,\s*\d+\s+skipped)?)",
        output,
    )

    if matches:
        return matches[-1]

    if result.passed:
        return "Tests passed"

    if result.timed_out:
        return "Tests timed out"

    if result.exit_code is not None:
        return (
            "Tests failed "
            f"(exit code "
            f"{result.exit_code})"
        )

    return "Tests failed"


def _remove_summary_prefix(
    summary: str,
    prefix: str,
) -> str:
    if summary.lower().startswith(
        prefix.lower()
    ):
        return summary[
            len(prefix):
        ].strip()

    return summary
